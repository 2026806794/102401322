"""全局配置。

把路径、爬虫参数、关键词这些到处都要用的东西集中放在这里，
其他文件统一从这里 import，避免同一个常量在好几个地方各写一遍。
"""

import os
import sys
from pathlib import Path

# 学号与项目名，写报告和导出 Excel 时要用
STUDENT_ID = "102401322"
PROJECT_NAME = "大语言模型应用相关视频弹幕分析挖掘"

# ---------------- 路径 ----------------
# __file__ 是 src/config.py，取两次 parent 就是项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DANMAKU_RAW_DIR = RAW_DIR / "danmaku"      # 每个视频的弹幕原始缓存（一个视频一个 json）
MEDIA_RAW_DIR = RAW_DIR / "media"          # 附加题：科技媒体文章缓存
PROCESSED_DIR = DATA_DIR / "processed"     # 清洗、统计后的中间结果

VIDEO_INDEX_FILE = PROCESSED_DIR / "videos.json"          # 视频清单
DANMAKU_CLEAN_FILE = PROCESSED_DIR / "danmaku_clean.jsonl"  # 清洗后的弹幕

OUTPUT_DIR = PROJECT_ROOT / "output"
FIGURE_DIR = OUTPUT_DIR / "figures"        # 词云、统计图
XLSX_DIR = OUTPUT_DIR / "xlsx"             # Excel 统计表
HTML_DIR = OUTPUT_DIR / "html"             # 可视化大屏、报告
ASSET_DIR = OUTPUT_DIR / "assets"          # echarts 的 js 文件（放本地，断网也能看大屏）
LOG_DIR = PROJECT_ROOT / "logs"

ALL_DIRS = (DANMAKU_RAW_DIR, MEDIA_RAW_DIR, PROCESSED_DIR,
            FIGURE_DIR, XLSX_DIR, HTML_DIR, ASSET_DIR, LOG_DIR)


def ensure_directories():
    """把所有需要的目录建出来，重复调用也没关系。"""
    for directory in ALL_DIRS:
        directory.mkdir(parents=True, exist_ok=True)


# ---------------- 中文字体 ----------------
# 词云和图表要显示中文，必须指定字体文件，否则会画成一堆方框。
# 这里按优先级找本机装了的字体，找不到就返回 None。
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",       # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",     # 黑体
    r"C:\Windows\Fonts\simsun.ttc",     # 宋体
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def detect_chinese_font():
    """返回本机第一个能用的中文字体路径，没有就返回 None。"""
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


CHINESE_FONT = detect_chinese_font()


# ---------------- 爬虫参数 ----------------
class CrawlerConfig:
    """爬虫用到的参数。

    之所以做成一个类而不是一堆全局变量，是为了方便临时改参数：
    比如调试时只抓 10 个视频，就 CrawlerConfig(videos_per_keyword=10)。
    """

    def __init__(self,
                 keywords=("大语言模型", "大模型", "LLM"),
                 videos_per_keyword=300,
                 page_size=20,
                 request_interval=(1.2, 2.8),
                 max_retries=4,
                 timeout=20,
                 backoff_base=2.0,
                 block_cooldown=(25.0, 45.0),
                 max_segments=12,
                 channel_failure_limit=3,
                 max_danmaku_per_video=4000,
                 use_cache=True):
        self.keywords = tuple(keywords)          # 搜索关键词
        self.videos_per_keyword = videos_per_keyword   # 每个关键词抓多少个视频
        self.page_size = page_size               # B站搜索一页返回多少条
        self.request_interval = request_interval  # 每次请求之间随机 sleep 的区间（秒）
        self.max_retries = max_retries           # 单个请求最多重试几次
        self.timeout = timeout                   # 请求超时（秒）
        self.backoff_base = backoff_base         # 重试等待时间按这个底数指数增长
        self.block_cooldown = block_cooldown     # 连续被 412 限流后的冷却时间
        self.max_segments = max_segments         # 一个视频最多抓几个弹幕分段
        self.channel_failure_limit = channel_failure_limit  # 某个通道连续失败几次就放弃它
        self.max_danmaku_per_video = max_danmaku_per_video  # 单视频弹幕上限
        self.use_cache = use_cache               # 命中缓存就不再请求

        self.user_agent = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        self.referer = "https://www.bilibili.com/"


class AnalysisConfig:
    """统计分析的参数。"""

    def __init__(self,
                 top_n=8,
                 category_word_pool=60,
                 min_word_length=2,
                 wordcloud_max_words=220,
                 figure_dpi=200,
                 random_seed=42):
        self.top_n = top_n                       # 作业要求排名前 8
        self.category_word_pool = category_word_pool  # 每个领域留多少个词（给分领域词云用）
        self.min_word_length = min_word_length   # 小于这个长度的词不统计
        self.wordcloud_max_words = wordcloud_max_words
        self.figure_dpi = figure_dpi
        self.random_seed = random_seed


class MediaConfig:
    """附加题：科技媒体爬取参数。

    这里用 RSS/Atom 而不是直接解析网页，因为媒体站点大多是前端渲染的，
    抓 HTML 要上 Selenium 而且页面一改就失效；RSS 是站点自己提供的结构化数据，
    字段稳定也不用登录。下面这些源都实测能访问（2025-10 测过）。
    """

    def __init__(self, feeds=None, per_feed=40, article_max_chars=3000,
                 request_interval=(0.8, 1.8), timeout=20):
        self.feeds = feeds if feeds is not None else [
            {"name": "量子位", "url": "https://www.qbitai.com/feed", "region": "国内"},
            {"name": "InfoQ 中国", "url": "https://www.infoq.cn/feed", "region": "国内"},
            {"name": "少数派", "url": "https://sspai.com/feed", "region": "国内"},
            {"name": "Solidot", "url": "https://www.solidot.org/index.rss", "region": "国内"},
            {"name": "开源中国", "url": "https://www.oschina.net/news/rss", "region": "国内"},
            {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/",
             "region": "国际"},
            {"name": "TechCrunch AI",
             "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
             "region": "国际"},
        ]
        self.per_feed = per_feed                 # 每个源最多留多少篇
        self.article_max_chars = article_max_chars
        self.request_interval = request_interval
        self.timeout = timeout
        self.user_agent = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


# 默认参数对象，其他模块直接用这个
DEFAULT_CRAWLER_CONFIG = CrawlerConfig()
DEFAULT_ANALYSIS_CONFIG = AnalysisConfig()
DEFAULT_MEDIA_CONFIG = MediaConfig()


def setup_console_encoding():
    """Windows 控制台默认是 GBK，中文日志会乱码，这里统一改成 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
