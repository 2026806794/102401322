"""附加题：爬主流科技媒体的文章。

科技媒体网站大多是前端渲染的（打开网页看源码发现没有正文），
想抓内容就得用 Selenium 模拟浏览器，而且网站改版就失效了。
所以这里选了更省事的办法：用网站自己提供的 RSS/Atom 订阅源。
好处是字段固定、不用登录、对服务器也友好。

这个文件只负责把文章抓下来存好，趋势分析在 analysis/trend_analyzer.py 里。
"""

import random
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from src.config import DEFAULT_MEDIA_CONFIG, MEDIA_RAW_DIR
from src.utils import get_logger, normalize_text, read_json, write_json

log = get_logger(__name__)

# Atom 格式的标签带命名空间
ATOM_NS = "{http://www.w3.org/2005/Atom}"

_tag_re = re.compile(r"<[^>]+>")     # 匹配 HTML 标签
_space_re = re.compile(r"\s+")


@dataclass
class MediaArticle:
    """一篇文章。"""

    source: str          # 媒体名
    region: str          # 国内 / 国际
    title: str
    link: str = ""
    published: str = ""  # 统一成 ISO 格式的字符串，方便排序和按月分组
    summary: str = ""
    fetched_at: str = ""

    def to_dict(self):
        return asdict(self)


def strip_html(text):
    """去掉 HTML 标签，把常用的转义字符换回来，得到纯文本。"""
    if not text:
        return ""
    text = _tag_re.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return _space_re.sub(" ", text).strip()


def parse_feed(xml_text, source, region):
    """解析 RSS 或 Atom，返回文章列表。

    两种格式的标签名不一样，这里统一映射成一样的字段：
        RSS 用 item / title / link / pubDate / description
        Atom 用 entry / title / link(href 属性) / updated / summary
    """
    if not xml_text.strip():
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log.warning("%s 解析失败：%s", source, e)
        return []

    # RSS 是 item，Atom 是 entry，两种都找一下
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//" + ATOM_NS + "entry")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    articles = []

    for item in items:
        title = _get_text(item, "title") or _get_text(item, ATOM_NS + "title")
        if not title:
            continue

        link = _get_text(item, "link") or _get_atom_link(item)
        pub_date = (_get_text(item, "pubDate") or _get_text(item, "published")
                    or _get_text(item, ATOM_NS + "updated")
                    or _get_text(item, ATOM_NS + "published"))
        summary = (_get_text(item, "description") or _get_text(item, "summary")
                   or _get_text(item, ATOM_NS + "summary")
                   or _get_text(item, ATOM_NS + "content"))

        articles.append(MediaArticle(
            source=source,
            region=region,
            title=normalize_text(title),
            link=link.strip(),
            published=_normalize_date(pub_date),
            summary=strip_html(summary)[:600],
            fetched_at=now,
        ))

    return articles


def _get_text(node, tag):
    """取子标签的文本，没有就返回空字符串。"""
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text


def _get_atom_link(node):
    """Atom 的链接在 link 标签的 href 属性里，得单独取。"""
    for link in node.findall(ATOM_NS + "link"):
        href = link.get("href")
        if href:
            return href
    return ""


def _normalize_date(raw):
    """把各种格式的时间统一成 ISO 字符串。

    RSS 用 "Tue, 30 Sep 2026 10:00:00 +0800" 这种（RFC822），
    Atom 用 "2026-09-28T12:00:00Z" 这种（ISO8601），两种都要能处理。
    """
    raw = (raw or "").strip()
    if not raw:
        return ""

    try:
        return parsedate_to_datetime(raw).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        pass

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat(timespec="seconds")
    except ValueError:
        return raw    # 实在认不出来就原样返回


class MediaSpider:
    """媒体 RSS 爬虫，带缓存。"""

    def __init__(self, config=None, raw_dir=MEDIA_RAW_DIR):
        self.config = config or DEFAULT_MEDIA_CONFIG
        self.raw_dir = Path(raw_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        })

    def _cache_path(self, source):
        """每个源一个缓存文件。源名里有空格和斜杠，要换成合法文件名。"""
        safe_name = re.sub(r"[^\w\u4e00-\u9fff-]", "_", source)
        return self.raw_dir / (safe_name + ".json")

    def fetch_feed(self, feed, force=False):
        """抓一个源。已经有缓存就不重复请求。"""
        cache_file = self._cache_path(feed["name"])

        if not force:
            cached = read_json(cache_file)
            if cached:
                log.info("%s：用缓存 %d 篇", feed["name"], len(cached.get("articles", [])))
                return [MediaArticle(**item) for item in cached.get("articles", [])]

        articles = []
        try:
            response = self.session.get(feed["url"], timeout=self.config.timeout)
            response.raise_for_status()
            articles = parse_feed(response.text, feed["name"], feed.get("region", "未知"))
        except (requests.RequestException, ValueError) as e:
            log.warning("%s 抓取失败：%s", feed["name"], e)

        articles = articles[:self.config.per_feed]
        write_json(cache_file, {
            "source": feed["name"],
            "url": feed["url"],
            "region": feed.get("region", "未知"),
            "count": len(articles),
            "articles": [a.to_dict() for a in articles],
        })
        log.info("%s：抓到 %d 篇", feed["name"], len(articles))

        time.sleep(random.uniform(*self.config.request_interval))
        return articles

    def run(self, per_feed=None, force=False):
        """把所有源抓一遍，按链接去重后返回。"""
        limit = per_feed or self.config.per_feed
        collected = {}

        for feed in self.config.feeds:
            for article in self.fetch_feed(feed, force=force)[:limit]:
                key = article.link or (article.source + "|" + article.title)
                if key not in collected:
                    collected[key] = article

        articles = list(collected.values())
        write_json(self.raw_dir / "all_articles.json", {
            "count": len(articles),
            "sources": [f["name"] for f in self.config.feeds],
            "articles": [a.to_dict() for a in articles],
        })
        log.info("媒体文章采集完成：%d 篇（去重后），共 %d 个来源",
                 len(articles), len(self.config.feeds))
        return articles

    def close(self):
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def iter_cached_articles(raw_dir=MEDIA_RAW_DIR):
    """读缓存里的文章，用来离线重新分析。"""
    data = read_json(Path(raw_dir) / "all_articles.json", {})
    return data.get("articles", [])
