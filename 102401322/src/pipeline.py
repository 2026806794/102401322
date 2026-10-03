"""把各个阶段串起来。

整个流程分几步，每一步都把结果写到文件里，下一步从文件读：

    爬取 -> data/raw/danmaku/*.json
    清洗 -> data/processed/danmaku_clean.jsonl + clean_stats.json
    统计 -> data/processed/analysis_result.json + output/xlsx/*.xlsx
    可视化 -> output/figures/*.png + output/html/*.html
    附加题 -> data/processed/trend_result.json + 媒体趋势报告

这样设计的好处是每个阶段都能单独重跑。比如后来我改了停用词，
只要重跑"清洗 + 统计"就行，不用重新爬一遍数据（爬一次要 40 分钟）。
"""

import json

from src.analysis.analyzer import DanmakuAnalyzer
from src.analysis.exporter import ExcelExporter
from src.config import (
    DANMAKU_CLEAN_FILE,
    DEFAULT_ANALYSIS_CONFIG,
    PROCESSED_DIR,
    VIDEO_INDEX_FILE,
    ensure_directories,
)
from src.crawler.danmaku_fetcher import iter_cached_danmaku
from src.processing.cleaner import DanmakuCleaner
from src.utils import get_logger, read_json, read_jsonl, write_json

log = get_logger(__name__)

CLEAN_STATS_FILE = PROCESSED_DIR / "clean_stats.json"
ANALYSIS_RESULT_FILE = PROCESSED_DIR / "analysis_result.json"
TREND_RESULT_FILE = PROCESSED_DIR / "trend_result.json"


def run_clean(force=False):
    """清洗弹幕，写出 danmaku_clean.jsonl。

    force=False 时如果已经有结果就直接返回，不重复算。
    """
    ensure_directories()

    if DANMAKU_CLEAN_FILE.exists() and not force:
        stats = read_json(CLEAN_STATS_FILE, {})
        if stats:
            log.info("清洗结果已存在，跳过（想重跑加 --force）")
            return stats

    raw_records = list(iter_cached_danmaku())
    log.info("从缓存读取原始弹幕 %d 条", len(raw_records))
    if not raw_records:
        log.warning("没找到弹幕缓存，请先执行 python main.py crawl")
        return {}

    cleaner = DanmakuCleaner(min_length=DEFAULT_ANALYSIS_CONFIG.min_word_length)
    kept, stats = cleaner.clean_batch(raw_records)

    with open(DANMAKU_CLEAN_FILE, "w", encoding="utf-8", newline="\n") as f:
        for record in kept:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    write_json(CLEAN_STATS_FILE, stats.as_dict())
    write_json(PROCESSED_DIR / "noise_samples.json", stats.samples)

    log.info("清洗完成：保留 %d 条（噪声占比 %s）",
             len(kept), stats.as_dict()["噪声占比"])
    return stats.as_dict()


def run_analyze():
    """统计并导出 Excel。"""
    ensure_directories()

    records = read_jsonl(DANMAKU_CLEAN_FILE)
    if not records:
        raise FileNotFoundError("没找到清洗后的弹幕，请先执行 python main.py clean")

    videos = read_json(VIDEO_INDEX_FILE, [])
    clean_stats = read_json(CLEAN_STATS_FILE, {})

    analyzer = DanmakuAnalyzer(records, videos, DEFAULT_ANALYSIS_CONFIG)
    result = analyzer.analyze(clean_stats)

    write_json(ANALYSIS_RESULT_FILE, result.to_dict(), indent=None)
    ExcelExporter().export(result)
    log.info("分析结果已写入 %s", ANALYSIS_RESULT_FILE.name)
    return result


def load_analysis_result():
    """读已经存下来的分析结果，可视化那边要用。"""
    payload = read_json(ANALYSIS_RESULT_FILE)
    if not payload:
        raise FileNotFoundError("没找到分析结果，请先执行 python main.py analyze")
    return payload


def run_visualize():
    """生成词云、统计图和可视化大屏。"""
    from src.visualization import build_all_charts

    payload = load_analysis_result()
    figures = build_all_charts(payload)
    log.info("可视化产物 %d 个", len(figures))
    return figures


def run_media(per_feed=40, force=False):
    """附加题：爬科技媒体 -> 分析趋势 -> 出报告。"""
    from src.analysis.trend_analyzer import TrendAnalyzer
    from src.crawler.media_spider import MediaSpider
    from src.visualization.trend_report import build_trend_visuals

    ensure_directories()

    spider = MediaSpider()
    try:
        articles = [a.to_dict() for a in spider.run(per_feed=per_feed, force=force)]
    finally:
        spider.close()

    # 弹幕分析的结果用来做"媒体 vs 用户"的话题对比
    danmaku_result = read_json(ANALYSIS_RESULT_FILE, {})

    trend = TrendAnalyzer(articles, danmaku_result).analyze()
    write_json(TREND_RESULT_FILE, trend.to_dict(), indent=None)
    build_trend_visuals(trend.to_dict())
    return trend.to_dict()
