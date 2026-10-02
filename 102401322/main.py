"""程序入口。

用法（在项目根目录下执行）：

    python main.py crawl          # 爬弹幕
    python main.py clean          # 清洗
    python main.py analyze        # 统计 + 导出 Excel
    python main.py visualize      # 出图
    python main.py media          # 附加题：媒体趋势
    python main.py all            # 上面几步一次跑完

调试的时候可以加参数，比如只抓 20 个视频：
    python main.py crawl --per-keyword 20 --limit 5
"""

import argparse
import sys

from src.config import PROJECT_NAME, STUDENT_ID, ensure_directories, setup_console_encoding
from src.utils import get_logger

log = get_logger("main")


def build_parser():
    """定义命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=f"{PROJECT_NAME}（学号 {STUDENT_ID}）",
    )
    sub = parser.add_subparsers(dest="command")

    crawl = sub.add_parser("crawl", help="爬取 B站弹幕")
    crawl.add_argument("--per-keyword", type=int, default=300, help="每个关键词抓多少视频")
    crawl.add_argument("--limit", type=int, default=None, help="只抓前 N 个视频（调试用）")
    crawl.add_argument("--force", action="store_true", help="忽略缓存重新抓")

    clean = sub.add_parser("clean", help="清洗弹幕、过滤噪声")
    clean.add_argument("--force", action="store_true", help="忽略已有结果重新清洗")

    sub.add_parser("analyze", help="统计分析并导出 Excel")
    sub.add_parser("visualize", help="生成词云图和可视化大屏")

    media = sub.add_parser("media", help="附加题：爬科技媒体并做趋势分析")
    media.add_argument("--per-feed", type=int, default=40, help="每个源留多少篇文章")
    media.add_argument("--force", action="store_true", help="忽略缓存重新抓")

    all_cmd = sub.add_parser("all", help="一键跑完 爬取->清洗->统计->可视化")
    all_cmd.add_argument("--per-keyword", type=int, default=300)
    all_cmd.add_argument("--limit", type=int, default=None)

    return parser


def cmd_crawl(args):
    """爬弹幕。"""
    from src.crawler.danmaku_fetcher import DanmakuCrawler

    crawler = DanmakuCrawler()
    try:
        videos = crawler.run(per_keyword=args.per_keyword,
                             video_limit=args.limit,
                             force=args.force)
    finally:
        crawler.close()

    ok = 0
    for video in videos:
        if video.status == "ok":
            ok += 1
    log.info("抓取结束：视频 %d 个（有弹幕的 %d 个），弹幕合计 %d 条",
             len(videos), ok, sum(v.fetched for v in videos))
    return 0


def cmd_clean(args):
    """清洗。"""
    from src.pipeline import run_clean

    stats = run_clean(force=args.force)
    if not stats:
        return 1
    for key, value in stats.items():
        log.info("  %s：%s", key, value)
    return 0


def cmd_analyze(_args):
    """统计并导出 Excel。"""
    from src.pipeline import run_analyze

    result = run_analyze()
    log.info("Top%d 具体应用案例：", result.meta.get("top_n", 8))
    for item in result.case_ranking:
        log.info("  %d. %s（%d 条）", item["rank"], item["name"], item["count"])
    return 0


def cmd_visualize(_args):
    """生成图表。"""
    from src.pipeline import run_visualize

    for path in run_visualize():
        log.info("  已生成 %s", path)
    return 0


def cmd_media(args):
    """附加题。"""
    from src.pipeline import run_media

    trend = run_media(per_feed=args.per_feed, force=args.force)
    meta = trend.get("meta", {})
    log.info("媒体文章 %d 篇，来源 %d 个",
             meta.get("article_count", 0), meta.get("source_count", 0))
    if trend.get("video_forecast_note"):
        log.info("趋势判断：%s", trend["video_forecast_note"])
    return 0


def cmd_all(args):
    """一键跑完。"""
    from src.crawler.danmaku_fetcher import DanmakuCrawler
    from src.pipeline import run_analyze, run_clean, run_visualize

    crawler = DanmakuCrawler()
    try:
        crawler.run(per_keyword=args.per_keyword, video_limit=args.limit)
    finally:
        crawler.close()

    run_clean()
    run_analyze()
    run_visualize()
    log.info("全流程完成")
    return 0


COMMANDS = {
    "crawl": cmd_crawl,
    "clean": cmd_clean,
    "analyze": cmd_analyze,
    "visualize": cmd_visualize,
    "media": cmd_media,
    "all": cmd_all,
}


def main(argv=None):
    """解析参数并执行对应的命令。"""
    ensure_directories()
    setup_console_encoding()

    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    handler = COMMANDS.get(args.command)
    if handler is None:
        log.error("未知命令：%s", args.command)
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
