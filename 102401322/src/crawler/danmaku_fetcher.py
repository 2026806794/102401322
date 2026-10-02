"""弹幕抓取流程。

客户端（bilibili_client）负责"怎么把数据拿下来"，这个文件负责
"按什么顺序拿、拿哪些视频、拿完存哪里"，另外还管缓存和断点续爬。

抓取流程大致是：
    搜索关键词 -> 汇总视频清单（按 bvid 去重）-> 逐个视频拿 cid -> 抓弹幕 -> 存 json
"""

import math
import random
import time
from collections import Counter
from pathlib import Path

from src.config import (
    DANMAKU_RAW_DIR,
    DEFAULT_CRAWLER_CONFIG,
    VIDEO_INDEX_FILE,
)
from src.crawler.bilibili_client import BilibiliAPIError, BilibiliClient, make_progress_logger
from src.utils import get_logger, read_json, write_json

log = get_logger(__name__)


class VideoMeta:
    """一个视频的基本信息 + 抓取状态。

    抓完之后 status 有三种：
        ok    —— 拿到了弹幕
        empty —— 视频本身就没有弹幕（新视频很常见）
        failed—— 抓取出错了
    """

    def __init__(self, bvid, title="", author="", keyword="", search_rank=0,
                 cid=None, duration=0, pubdate=0, tname="", view=0,
                 danmaku_total=0, fetched=0, source="", status="pending", error=""):
        self.bvid = bvid
        self.title = title
        self.author = author
        self.keyword = keyword
        self.search_rank = search_rank
        self.cid = cid
        self.duration = duration
        self.pubdate = pubdate
        self.tname = tname
        self.view = view
        self.danmaku_total = danmaku_total   # 视频总共多少弹幕（接口给的）
        self.fetched = fetched               # 实际抓到多少条
        self.source = source                 # 用哪个通道抓到的
        self.status = status
        self.error = error

    def to_dict(self):
        """转成字典，方便写 json。"""
        return dict(self.__dict__)


def _video_meta_from_dict(data):
    """从字典还原 VideoMeta（读缓存用）。

    只挑类里已有的字段，这样以后加字段了旧缓存也还能用。
    """
    valid_keys = set(VideoMeta(bvid="").__dict__.keys())
    kwargs = {}
    for key, value in data.items():
        if key in valid_keys:
            kwargs[key] = value
    return VideoMeta(**kwargs)


class DanmakuCrawler:
    """弹幕爬虫。

    参数：
        client  —— 可以传一个自己的客户端进去（测试时会用假的替身）
        config  —— 爬虫参数
        raw_dir —— 弹幕缓存目录
    """

    def __init__(self, client=None, config=None, raw_dir=DANMAKU_RAW_DIR):
        self.config = config or DEFAULT_CRAWLER_CONFIG
        self.client = client or BilibiliClient(self.config)
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        # 记录每个通道连续失败了几次，失败太多就不要再试它了
        self.channel_failures = {"comment": 0, "list": 0}

    # ---------- 第一步：收集视频清单 ----------

    def collect_videos(self, keywords=None, per_keyword=None, refresh=False):
        """按关键词搜索，汇总出一个视频清单（跨关键词按 bvid 去重）。

        这里有两个地方是踩过坑之后改的：

        1. 清单是"合并"而不是"覆盖"。中途被限流打断后重新运行，
           之前搜到的视频要保留下来，不然白搜了。
        2. 搜索返回空页不能直接当成"没有更多结果"。被限流时接口会返回
           code=0 但结果是空的，我一开始直接 break，结果有个关键词只抓到
           36 个视频就停了。现在的做法是等一会儿重试一次，还空就跳过这页继续翻。
        """
        keywords = tuple(keywords or self.config.keywords)
        per_keyword = per_keyword or self.config.videos_per_keyword

        # 先把已有的清单读进来
        seen = {}
        if not refresh:
            for item in read_json(VIDEO_INDEX_FILE, []) or []:
                video = _video_meta_from_dict(item)
                seen[video.bvid] = video

        # 看看哪些关键词还没抓够
        count_by_keyword = Counter(v.keyword for v in seen.values())
        todo = []
        for keyword in keywords:
            if count_by_keyword.get(keyword, 0) < per_keyword:
                todo.append(keyword)

        if not todo:
            log.info("视频清单已经够了（%d 个），跳过搜索", len(seen))
            return list(seen.values())

        log.info("需要补搜的关键词：%s（现有 %d 个视频）",
                 "、".join(f"{k}({count_by_keyword.get(k, 0)})" for k in todo),
                 len(seen))

        for keyword in todo:
            pages = math.ceil(per_keyword / self.config.page_size)
            collected = count_by_keyword.get(keyword, 0)
            empty_pages = 0

            for page in range(1, pages + 1):
                items = self._search_one_page(keyword, page)

                if not items:
                    empty_pages += 1
                    if empty_pages >= 2:
                        log.warning("关键词「%s」连续 %d 页为空，停止翻页", keyword, empty_pages)
                        break
                    continue
                empty_pages = 0

                for item in items:
                    bvid = item["bvid"]
                    collected += 1
                    if bvid in seen:
                        continue
                    seen[bvid] = VideoMeta(
                        bvid=bvid,
                        title=item["title"],
                        author=item["author"],
                        keyword=keyword,
                        search_rank=item["search_rank"],
                        duration=_parse_duration(item.get("duration", 0)),
                        pubdate=item.get("pubdate", 0),
                        danmaku_total=item.get("danmaku_count", 0),
                        view=item.get("play", 0),
                    )

                log.info("关键词「%s」已抓取 %d/%d 个视频（第 %d/%d 页）",
                         keyword, collected, per_keyword, page, pages)

                if collected >= per_keyword:
                    break

            # 每搜完一个关键词就存一次盘，中断了也不至于全丢
            write_json(VIDEO_INDEX_FILE, [v.to_dict() for v in seen.values()])

        videos = list(seen.values())
        write_json(VIDEO_INDEX_FILE, [v.to_dict() for v in videos])
        log.info("视频清单汇总完成：%d 个去重后的视频", len(videos))
        return videos

    def _search_one_page(self, keyword, page):
        """搜一页。返回空的话等几秒再试一次（区分"真的没有"和"被限流"）。"""
        try:
            items = self.client.search_videos(keyword, page)
        except BilibiliAPIError as e:
            log.error("搜索「%s」第 %d 页失败：%s", keyword, page, e)
            return []

        if items:
            return items

        wait = random.uniform(8.0, 16.0)
        log.info("搜索「%s」第 %d 页返回空，%.0f 秒后重试一次", keyword, page, wait)
        time.sleep(wait)
        try:
            return self.client.search_videos(keyword, page)
        except BilibiliAPIError as e:
            log.error("搜索「%s」第 %d 页重试也失败：%s", keyword, page, e)
            return []

    def sync_index_with_cache(self):
        """把"缓存里有弹幕、但清单里没有"的视频补进清单。

        为什么会出现这种情况：搜索结果会随时间变化，早期抓到的视频
        在后面的搜索结果里可能已经不在了，于是它留在缓存里但掉出了清单，
        统计的时候就没有标题、播放量这些信息。这里做一次对齐。
        """
        videos = {}
        for item in read_json(VIDEO_INDEX_FILE, []) or []:
            video = _video_meta_from_dict(item)
            videos[video.bvid] = video

        added = 0
        for path in sorted(self.raw_dir.glob("*.json")):
            bvid = path.stem
            if bvid in videos:
                continue

            cached = read_json(path, {})
            if not cached.get("danmaku"):
                continue      # 没有弹幕数据的不用进清单

            video = VideoMeta(
                bvid=bvid,
                title=cached.get("title", ""),
                author=cached.get("author", ""),
                keyword=cached.get("keyword", ""),
                duration=cached.get("duration", 0),
                cid=cached.get("cid"),
                fetched=cached.get("fetched", 0),
                status=cached.get("status", "ok"),
            )
            # 尽量从接口补全信息，补不到就用缓存里的
            try:
                detail = self.client.get_video_detail(bvid)
                video.title = detail.get("title") or video.title
                video.author = detail.get("owner") or video.author
                video.duration = detail.get("duration", video.duration)
                video.pubdate = detail.get("pubdate", 0)
                video.tname = detail.get("tname", "")
                video.view = detail.get("view", 0)
                video.danmaku_total = detail.get("danmaku", 0)
            except (BilibiliAPIError, ValueError) as e:
                log.info("补全 %s 的信息失败，用缓存里的：%s", bvid, e)

            videos[bvid] = video
            added += 1

        if added:
            write_json(VIDEO_INDEX_FILE, [v.to_dict() for v in videos.values()])
            log.info("清单与缓存对齐：补入 %d 个视频，现在共 %d 个", added, len(videos))
        else:
            log.info("清单与缓存一致，不需要对齐")
        return added

    # ---------- 第二步：抓弹幕 ----------

    def _cache_path(self, bvid):
        return self.raw_dir / (bvid + ".json")

    def fetch_video_danmaku(self, video, force=False):
        """抓一个视频的弹幕，带缓存。

        如果缓存里状态是 ok，就直接用缓存，不再请求。
        状态是 empty/failed 的会重新抓一次（这些多半是当时被限流了）。
        """
        cache_file = self._cache_path(video.bvid)
        cached = None
        if self.config.use_cache and not force:
            cached = read_json(cache_file)

        if cached and cached.get("status") == "ok":
            video.cid = cached.get("cid")
            video.fetched = cached.get("fetched", 0)
            video.source = cached.get("source", "cache")
            video.status = "ok"
            return cached.get("danmaku", [])

        records = []
        source = ""
        try:
            detail = self.client.get_video_detail(video.bvid)
            video.cid = detail.get("cid")
            video.title = detail.get("title") or video.title
            video.author = detail.get("owner") or video.author
            video.duration = detail.get("duration", video.duration)
            video.pubdate = detail.get("pubdate", video.pubdate)
            video.tname = detail.get("tname", "")
            video.view = detail.get("view", video.view)
            video.danmaku_total = detail.get("danmaku", video.danmaku_total)

            if not video.cid:
                raise BilibiliAPIError(-1, "视频详情里没有 cid", video.bvid)

            records, source = self._fetch_danmaku_by_cid(
                video.cid, video.duration, video.danmaku_total)

            video.fetched = len(records)
            video.source = source
            if records:
                video.status = "ok"
            else:
                video.status = "empty"

        except (BilibiliAPIError, ValueError, KeyError) as e:
            log.warning("视频 %s 抓取失败：%s", video.bvid, e)
            video.status = "failed"
            video.error = str(e)

        # 失败的结果也写缓存，方便事后查；下次运行会自动重试
        danmaku_list = []
        for record in records:
            item = dict(record)
            item["bvid"] = video.bvid
            item["keyword"] = video.keyword
            item["video_title"] = video.title
            item["author"] = video.author
            danmaku_list.append(item)

        write_json(cache_file, {
            "bvid": video.bvid,
            "cid": video.cid,
            "title": video.title,
            "author": video.author,
            "keyword": video.keyword,
            "duration": video.duration,
            "source": source,
            "status": video.status,
            "fetched": video.fetched,
            "danmaku": danmaku_list,
        })
        return records

    def _fetch_danmaku_by_cid(self, cid, duration=0, expected_total=-1):
        """抓弹幕，三个通道依次尝试，哪个先拿到数据就用哪个。

        为什么要搞三个通道：我一开始只用 api 的 list.so，被限流之后
        所有视频都返回 412，一晚上几乎没抓到东西。后来一个个接口试，
        发现它们的限流策略不一样：

            1. comment.bilibili.com/{cid}.xml  —— 一次请求拿全部，限流最松（主力）
            2. api 的 list.so                   —— 格式一样但限流很严，经常 412
            3. api 的 seg.so                    —— protobuf 分段（6分钟一段），
                                                   属于另一个限流桶，当兜底

        每个通道还加了"熔断"：连续失败 3 次就认为这个通道暂时不能用了，
        后面的视频直接跳过它。不这么做的话，每个视频都要为一次注定失败的
        请求等 2 分钟退避，486 个视频就是十几个小时。

        expected_total 是视频总共多少条弹幕。如果是 0 就直接返回——
        新上传的视频经常一条弹幕都没有，不加这个判断的话每个空视频
        都会白跑最多 12 次分段请求。
        """
        if expected_total == 0:
            return [], ""

        limit = self.config.channel_failure_limit
        records = []
        source = ""

        # 前两个通道都是"一次拿全部"，拿到 100 条以上就不用再试了
        channels = [
            ("comment", self.client.fetch_danmaku_comment_xml, "comment.xml"),
            ("list", self.client.fetch_danmaku_xml, "list.so"),
        ]
        for name, fetch_func, label in channels:
            if len(records) >= 100:
                break
            if self.channel_failures[name] >= limit:
                continue

            try:
                got = fetch_func(cid)
                self.channel_failures[name] = 0
                if got:
                    records = got
                    source = label
            except (BilibiliAPIError, ValueError) as e:
                self.channel_failures[name] += 1
                log.info("%s 抓取失败(cid=%s，累计 %d 次)：%s",
                         label, cid, self.channel_failures[name], e)
                if self.channel_failures[name] == limit:
                    log.warning("%s 连续失败 %d 次，判定为通道级限流，后面跳过它",
                                label, limit)

        # 前面都没拿到（或者拿到的太少），用分段接口兜底
        if self._need_segment_fallback(records, expected_total):
            if duration and duration > 0:
                need_segments = math.ceil(duration / 360)
            else:
                need_segments = 1
            need_segments = min(need_segments, self.config.max_segments)

            for index in range(1, need_segments + 1):
                try:
                    records.extend(self.client.fetch_danmaku_segment(cid, index))
                except (BilibiliAPIError, ValueError) as e:
                    log.debug("分段 %d 抓取失败(cid=%s)：%s", index, cid, e)
                    break

            # 两条通道的数据可能有重复，按 (时间, 内容) 去个重
            unique = {}
            for record in records:
                key = (record.get("time", 0.0), record.get("text", ""))
                unique[key] = record
            records = list(unique.values())

            if records:
                source = "seg.so"

        records.sort(key=lambda r: r.get("time", 0.0))
        return records[:self.config.max_danmaku_per_video], source

    @staticmethod
    def _need_segment_fallback(records, expected_total):
        """判断要不要动用分段兜底通道。

        前面两个通道返回的是**完整的弹幕池**，所以"拿到了但数量不多"
        通常说明这个视频本来就没多少弹幕，再去逐段抓就是白跑十几次请求。
        只有两种情况值得补抓：
            1. 前面全都失败了，一条没拿到；
            2. 拿到了，但相对视频标注的总数明显偏少（不到一半，而且总数上百），
               可能是接口那边截断了。
        """
        if not records:
            return True
        if expected_total >= 100 and len(records) < expected_total * 0.5:
            return True
        return False

    # ---------- 主流程 ----------

    def run(self, keywords=None, per_keyword=None, video_limit=None,
            force=False, refresh_index=False):
        """完整流程：收集视频 -> 同步清单 -> 逐个抓弹幕 -> 回写清单。

        video_limit 是只抓前 N 个视频，调试的时候用。
        """
        start_time = time.perf_counter()
        self.client.bootstrap()

        self.collect_videos(keywords, per_keyword, refresh=refresh_index)
        self.sync_index_with_cache()

        # 重新读一次清单：上面两步都可能往里加过东西
        videos = [_video_meta_from_dict(item)
                  for item in read_json(VIDEO_INDEX_FILE, []) or []]
        if video_limit:
            videos = videos[:video_limit]

        report = make_progress_logger(len(videos), step=10)
        ok = empty = failed = 0

        for index, video in enumerate(videos, start=1):
            self.fetch_video_danmaku(video, force=force)
            if video.status == "ok":
                ok += 1
            elif video.status == "empty":
                empty += 1
            else:
                failed += 1
            report(index)

        write_json(VIDEO_INDEX_FILE, [v.to_dict() for v in videos])
        total_danmaku = sum(v.fetched for v in videos)
        log.info("弹幕抓取完成：视频 %d 个（成功 %d / 空 %d / 失败 %d），"
                 "累计弹幕 %d 条，耗时 %.1f 分钟",
                 len(videos), ok, empty, failed, total_danmaku,
                 (time.perf_counter() - start_time) / 60)
        return videos

    def close(self):
        self.client.close()


def _parse_duration(value):
    """把 "12:34" 或 "1:02:03" 这样的时长转成秒数。

    搜索接口给的时长是字符串，视频详情接口给的是秒数，统一成秒。
    """
    if isinstance(value, (int, float)):
        return int(value)
    if not value:
        return 0

    parts = str(value).split(":")
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return 0

    seconds = 0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def iter_cached_danmaku(raw_dir=DANMAKU_RAW_DIR):
    """遍历所有缓存文件里的弹幕，用来离线重新统计。

    缓存文件名就是 bvid，所以即使文件里的记录没写 bvid 也能从文件名补上。
    """
    for path in sorted(Path(raw_dir).glob("*.json")):
        data = read_json(path)
        if not data:
            continue

        bvid = data.get("bvid") or path.stem
        keyword = data.get("keyword", "")
        source = data.get("source", "")

        for record in data.get("danmaku", []):
            item = dict(record)
            item["bvid"] = record.get("bvid") or bvid
            item["keyword"] = record.get("keyword") or keyword
            # 记录抓取通道，做"弹幕随进度分布"时要区分（分段通道只覆盖开头一段）
            item["source"] = source
            yield item
