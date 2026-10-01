"""B站接口客户端。

这个文件只管一件事：怎么把数据从 B站 拿下来。包括维持 cookie、加签名、
控制请求频率、失败了重试、以及把返回的二进制数据解析成 Python 列表。
至于"抓哪些视频、存到哪"是 danmaku_fetcher.py 的事。

里面几个解析函数（parse_danmaku_xml / parse_danmaku_proto）是纯函数，
不联网也能测，所以单独拆出来了。
"""

import html
import random
import re
import time
import zlib

import requests

from src.config import DEFAULT_CRAWLER_CONFIG
from src.crawler import wbi
from src.utils import get_logger

log = get_logger(__name__)

# 用到的几个接口地址
SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
DANMAKU_XML_URL = "https://api.bilibili.com/x/v1/dm/list.so"
DANMAKU_COMMENT_XML = "https://comment.bilibili.com/{cid}.xml"
DANMAKU_SEG_URL = "https://api.bilibili.com/x/v2/dm/web/seg.so"
FINGER_SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"

# 搜索结果标题里会带 <em class="keyword"> 高亮标签，要去掉
_em_tag = re.compile(r"</?em[^>]*>")
# 弹幕 XML 里一条弹幕长这样：<d p="属性">内容</d>
_danmaku_item = re.compile(r'<d p="([^"]*)">(.*?)</d>', re.DOTALL)


class BilibiliAPIError(Exception):
    """B站接口返回了非 0 的 code，或者请求一直失败。"""

    def __init__(self, code, message, url=""):
        super().__init__(f"B站接口错误 code={code} message={message} url={url}")
        self.code = code
        self.message = message
        self.url = url


# ==================== 解析函数 ====================

def parse_danmaku_xml(content):
    """解析弹幕 XML，返回弹幕列表。

    接口返回的是 deflate 压缩过的 XML（没有 zlib 头），格式大致是：
        <i><d p="出现时间,模式,字号,颜色,时间戳,弹幕池,用户哈希,行号">弹幕内容</d></i>

    返回的每条是 {'time': 秒, 'mode': 模式, 'color': 颜色, 'uid_hash': ..., 'text': 内容}
    """
    if not content:
        return []

    # 先试着按 deflate 解压，失败就说明没压缩，直接用原文
    raw = content
    try:
        raw = zlib.decompress(content, -zlib.MAX_WBITS)
    except zlib.error:
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS | 32):
            try:
                raw = zlib.decompress(content, wbits)
                break
            except zlib.error:
                continue

    text = raw.decode("utf-8", errors="ignore")

    records = []
    for attr, body in _danmaku_item.findall(text):
        fields = attr.split(",")
        # p 属性正常有 8 段，少说明这条数据坏了，跳过
        if len(fields) < 8:
            continue
        try:
            records.append({
                "time": round(float(fields[0]), 1),
                "mode": int(fields[1]),
                "color": int(fields[3]),
                "uid_hash": fields[6],
                "text": html.unescape(body).strip(),
            })
        except ValueError:
            continue
    return records


def _read_varint(data, pos):
    """读一个 protobuf 的 varint，返回 (值, 新的位置)。"""
    result = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:      # 最高位是 0 表示这个数读完了
            return result, pos
        shift += 7
        if shift > 63:
            break
    raise ValueError("varint 编码不对")


def _parse_danmaku_elem(chunk):
    """解析 protobuf 里的一条弹幕（DanmakuElem）。

    字段编号对应关系（从前端的 .proto 文件看来的）：
        1=id  2=progress(毫秒)  3=mode  4=字号  5=color  6=用户哈希  7=内容
    """
    elem = {"time": 0.0, "mode": 0, "color": 16777215, "uid_hash": "", "text": ""}
    pos = 0
    while pos < len(chunk):
        tag, pos = _read_varint(chunk, pos)
        field_no = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 0:            # varint
            value, pos = _read_varint(chunk, pos)
            if field_no == 2:
                elem["time"] = round(value / 1000.0, 1)   # 毫秒转秒
            elif field_no == 3:
                elem["mode"] = value
            elif field_no == 5:
                elem["color"] = value
        elif wire_type == 2:          # 长度分隔（字符串或嵌套消息）
            length, pos = _read_varint(chunk, pos)
            payload = chunk[pos:pos + length]
            pos += length
            if field_no == 7:
                elem["text"] = payload.decode("utf-8", errors="ignore").strip()
            elif field_no == 6:
                elem["uid_hash"] = payload.decode("utf-8", errors="ignore")
        elif wire_type == 5:          # 32 位定长
            pos += 4
        elif wire_type == 1:          # 64 位定长
            pos += 8
        else:
            break                     # 不认识的类型，直接停，免得死循环
    return elem


def parse_danmaku_proto(data):
    """解析 seg.so 接口返回的 protobuf 数据。

    外层是 DmSegMobileReply，里面 repeated DanmakuElem elems = 1，
    也就是一堆 field_no=1、wire_type=2 的嵌套消息。

    这里没有用 protobuf 库，而是自己按 varint 规则读的——
    因为只用到几个字段，自己写反而更简单，也少装一个依赖。
    """
    records = []
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        field_no = tag >> 3
        wire_type = tag & 0x07

        if wire_type == 2:
            length, pos = _read_varint(data, pos)
            chunk = data[pos:pos + length]
            pos += length
            if field_no == 1:
                elem = _parse_danmaku_elem(chunk)
                if elem["text"]:
                    records.append(elem)
        elif wire_type == 0:
            _, pos = _read_varint(data, pos)
        elif wire_type == 5:
            pos += 4
        elif wire_type == 1:
            pos += 8
        else:
            break
    return records


def strip_search_highlight(title):
    """去掉搜索结果标题里的 <em> 标签。"""
    return html.unescape(_em_tag.sub("", title or "")).strip()


# ==================== 客户端 ====================

class BilibiliClient:
    """带限流和重试的 B站请求客户端。

    用法：
        client = BilibiliClient()
        client.bootstrap()          # 先拿 cookie 和签名密钥
        videos = client.search_videos("大模型")
    """

    def __init__(self, config=None):
        self.config = config or DEFAULT_CRAWLER_CONFIG
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.user_agent,
            "Referer": self.config.referer,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://www.bilibili.com",
        })
        self.img_key = None
        self.sub_key = None
        self.block_count = 0     # 连续被 412 的次数，用来决定要不要长冷却

    def _sleep(self):
        """随机等一会儿再发下一个请求，别把人家服务器打崩。"""
        low, high = self.config.request_interval
        time.sleep(random.uniform(low, high))

    def _request(self, url, params=None, raw=False, need_sign=False,
                 accept_codes=(), retries=None):
        """发 GET 请求，失败自动重试。

        参数说明：
            raw          —— True 表示返回原始 bytes（弹幕是压缩过的二进制），
                            否则解析 json 并检查 code 是不是 0
            need_sign    —— 要不要做 wbi 签名
            accept_codes —— 额外的"可以接受"的业务码。比如 nav 接口没登录时返回 -101，
                            但密钥照样会给，所以要放行
            retries      —— 覆盖默认重试次数。弹幕接口有兜底通道，不用重试太多次
        """
        last_error = None
        max_attempts = retries if retries else self.config.max_retries

        for attempt in range(1, max_attempts + 1):
            try:
                query = params or {}
                if need_sign:
                    query = self.sign(query)

                response = self.session.get(url, params=query, timeout=self.config.timeout)
                response.raise_for_status()

                if raw:
                    self._sleep()
                    return response.content

                data = response.json()
                code = data.get("code", -1)

                if code == 0 or code in accept_codes:
                    self._sleep()
                    return data.get("data")

                # 这几个 code 是风控/限流，等一会儿重试
                if code in (-403, -412, -509):
                    wait = self.config.backoff_base ** attempt + random.random()
                    log.warning("触发风控 code=%s，%.1f 秒后重试 (%d/%d)",
                                code, wait, attempt, max_attempts)
                    time.sleep(wait)
                    if code in (-403, -412):
                        self._refresh_keys()
                    continue

                # 其他业务错误（比如稿件不可见），重试也没用，直接抛
                raise BilibiliAPIError(code, data.get("message", ""), url)

            except (requests.RequestException, ValueError) as e:
                last_error = e
                wait = self.config.backoff_base ** attempt + random.random()

                # 412 是限流。偶尔一次退避就够了，但如果连续好几次都是 412，
                # 说明这个 IP 已经被盯上了，得等久一点
                status = None
                if getattr(e, "response", None) is not None:
                    status = e.response.status_code

                if status == 412:
                    self.block_count += 1
                    if self.block_count >= 3:
                        cooldown = random.uniform(*self.config.block_cooldown)
                        log.warning("连续 %d 次 412 限流，冷却 %.0f 秒后继续",
                                    self.block_count, cooldown)
                        time.sleep(cooldown)
                        self.block_count = 0
                else:
                    self.block_count = 0

                log.warning("请求失败(%s)：%s，%.1f 秒后重试 (%d/%d)",
                            url.split("?")[0], e, wait, attempt, max_attempts)
                time.sleep(wait)

        raise BilibiliAPIError(-1, f"重试 {max_attempts} 次后还是失败: {last_error}", url)

    def bootstrap(self):
        """准备工作：访问一次首页拿 cookie，再取签名密钥。"""
        try:
            self.session.get("https://www.bilibili.com/", timeout=self.config.timeout)
        except requests.RequestException as e:
            log.warning("访问首页拿 cookie 失败：%s", e)

        # 没有 buvid3 的话搜索接口可能会被拒，用 finger/spi 兜一下
        if "buvid3" not in self.session.cookies:
            self._request(FINGER_SPI_URL)

        self._refresh_keys()

    def _refresh_keys(self):
        """从 nav 接口刷新 wbi 密钥。

        nav 在没登录时返回 -101，但 wbi_img 字段还是会给的，所以要把 -101 放行。
        """
        data = self._request(NAV_URL, accept_codes=(-101,)) or {}
        wbi_img = data.get("wbi_img") or {}
        img_url = wbi_img.get("img_url", "")
        sub_url = wbi_img.get("sub_url", "")

        if img_url and sub_url:
            self.img_key = wbi.extract_key_from_url(img_url)
            self.sub_key = wbi.extract_key_from_url(sub_url)
        else:
            # 实在拿不到就用网上流传的兜底密钥，至少还能试一次
            log.warning("nav 接口没返回 wbi 密钥，使用兜底密钥")
            if not self.img_key:
                self.img_key = "7cd084941338484aae1ad9425b84077c"
            if not self.sub_key:
                self.sub_key = "4932caff0ff746eab6f01bf08b70ac45"

    def sign(self, params):
        """给参数做签名，密钥还没有就先刷一下。"""
        if not self.img_key or not self.sub_key:
            self._refresh_keys()
        return wbi.sign_params(params, self.img_key, self.sub_key)

    # ---------- 具体接口 ----------

    def search_videos(self, keyword, page=1):
        """按关键词搜索视频，返回整理好的列表。

        用 order=totalrank 就是"综合排序"，和网页上默认的一致。
        """
        params = {
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "order": "totalrank",
            "page_size": self.config.page_size,
        }
        data = self._request(SEARCH_URL, params, need_sign=True) or {}
        results = data.get("result") or []

        videos = []
        for item in results:
            bvid = item.get("bvid")
            # 搜索结果里会混进广告、番剧之类，只保留 BV 号开头的
            if not bvid or not bvid.startswith("BV"):
                continue
            videos.append({
                "bvid": bvid,
                "title": strip_search_highlight(item.get("title", "")),
                "author": item.get("author", ""),
                "duration": item.get("duration", ""),
                "play": item.get("play", 0),
                "danmaku_count": item.get("video_review", 0),
                "pubdate": item.get("pubdate", 0),
                "keyword": keyword,
                "search_rank": len(videos) + 1,
            })
        return videos

    def get_video_detail(self, bvid):
        """拿视频详情，主要目的是里面的 cid（拉弹幕要用）。"""
        data = self._request(VIEW_URL, {"bvid": bvid}) or {}
        stat = data.get("stat") or {}
        owner = data.get("owner") or {}

        return {
            "bvid": bvid,
            "aid": data.get("aid"),
            "cid": data.get("cid"),
            "title": data.get("title", ""),
            "desc": (data.get("desc") or "")[:200],
            "duration": data.get("duration", 0),
            "pubdate": data.get("pubdate", 0),
            "tname": data.get("tname", ""),
            "owner": owner.get("name", ""),
            "view": stat.get("view", 0),
            "danmaku": stat.get("danmaku", 0),
            "reply": stat.get("reply", 0),
            "like": stat.get("like", 0),
        }

    def fetch_danmaku_comment_xml(self, cid, retries=None):
        """通道一：comment.bilibili.com/{cid}.xml，一次请求拿全部弹幕。

        这个地址和 api 的 list.so 返回一样的 XML，但限流松得多。
        实测 api 那边一直返回 412 的时候，这个还能正常用。
        """
        url = DANMAKU_COMMENT_XML.format(cid=cid)
        content = self._request(url, None, raw=True, retries=retries or 2)
        return parse_danmaku_xml(content)

    def fetch_danmaku_xml(self, cid, retries=None):
        """通道二：api 的 list.so，同样是一次拿全部弹幕。

        这个接口被限流时会一直 412，所以默认只重试 2 次，别把时间耗在退避上。
        """
        content = self._request(DANMAKU_XML_URL, {"oid": cid}, raw=True,
                                retries=retries or 2)
        return parse_danmaku_xml(content)

    def fetch_danmaku_segment(self, cid, segment_index=1):
        """通道三（兜底）：seg.so，按 6 分钟一段返回 protobuf 数据。"""
        params = {"type": 1, "oid": cid, "segment_index": segment_index}
        content = self._request(DANMAKU_SEG_URL, params, raw=True)
        return parse_danmaku_proto(content)

    def close(self):
        """关掉连接池。"""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def make_progress_logger(total, step=20):
    """返回一个回调，用来每隔几条打印一次进度。"""

    def report(done):
        if done % step == 0 or done == total:
            log.info("进度 %d/%d (%.1f%%)", done, total, done * 100.0 / max(total, 1))

    return report
