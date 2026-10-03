"""把统计数据自动填进博客正文。

博客里用 <!--DATA:xxx--> 做占位符，这个脚本读统计结果，
生成对应的 Markdown 表格替换进去。

这样做是为了避免"博客里写的数字和程序跑出来的对不上"。
每次重新跑完分析，执行一下这个脚本，博客里的数据就同步更新了。

运行：
    python scripts/render_blog_data.py
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.trend_analyzer import TrendAnalyzer
from src.config import PROCESSED_DIR, VIDEO_INDEX_FILE
from src.utils import get_logger, read_json

log = get_logger("blog")

BLOG_PATH = PROJECT_ROOT / "docs" / "博客.md"
ANALYSIS_FILE = PROCESSED_DIR / "analysis_result.json"
TREND_FILE = PROCESSED_DIR / "trend_result.json"


def make_table(headers, rows):
    """生成 Markdown 表格。"""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def fmt_int(value):
    """整数加千分位。"""
    try:
        return format(int(value), ",")
    except (TypeError, ValueError):
        return str(value)


def fmt_pct(value):
    """小数转百分比。"""
    try:
        return "%.1f%%" % (float(value) * 100)
    except (TypeError, ValueError):
        return "-"


def render_category(analysis, trend):
    """结论一：每类弹幕的总数量。"""
    rows = []
    for item in analysis.get("category_stats", []):
        rows.append([item["rank"], item["name"], fmt_int(item["count"]),
                     fmt_pct(item["ratio"])])

    words = []
    for item in analysis.get("top_words", []):
        words.append("`%s`(%d)" % (item["word"], item["count"]))

    text = make_table(["排名", "应用领域", "命中弹幕数", "占话题总量比例"], rows)
    text += "\n\n**整体词频 Top-8**：" + "、".join(words) + "\n"
    text += ("\n> 统计基数：清洗后有效弹幕 %s 条，覆盖视频 %s 个，有效词 %s 个。\n"
             % (fmt_int(analysis.get("total_danmaku")),
                fmt_int(analysis.get("total_videos")),
                fmt_int(analysis.get("total_words"))))
    return text


def render_cases(analysis, trend):
    """结论二：Top-8 具体应用案例。"""
    rows = []
    for item in analysis.get("case_ranking", []):
        rows.append([item["rank"], item["name"], fmt_int(item["count"]),
                     fmt_pct(item["ratio"])])
    return make_table(["排名", "应用案例", "提及弹幕数", "占案例提及总量比例"], rows)


def render_sentiment(analysis, trend):
    """结论三：用户态度分布。"""
    rows = []
    for item in analysis.get("sentiment", []):
        rows.append([item["name"], fmt_int(item["count"]), fmt_pct(item["ratio"])])
    return make_table(["态度类别", "命中弹幕数", "占比"], rows)


def render_cost_risk(analysis, trend):
    """结论四：成本与风险关注点。"""
    cost_rows = []
    for item in analysis.get("cost", []):
        cost_rows.append([item["name"], fmt_int(item["count"])])

    risk_rows = []
    for item in analysis.get("risk", []):
        risk_rows.append([item["name"], fmt_int(item["count"])])

    return ("**应用成本关注度**\n\n"
            + make_table(["成本维度", "命中弹幕数"], cost_rows)
            + "\n\n**不利影响关注度**\n\n"
            + make_table(["风险维度", "命中弹幕数"], risk_rows))


def render_media(analysis, trend):
    """附加题：媒体来源统计与趋势外推。"""
    source_rows = []
    for item in trend.get("source_stats", []):
        source_rows.append([item["name"], item["region"], fmt_int(item["count"]),
                            fmt_pct(item["llm_ratio"])])

    forecast_rows = []
    for item in trend.get("video_forecast", []):
        forecast_rows.append([item["month"], fmt_int(item["predicted"]),
                              "%s ~ %s" % (fmt_int(item["lower"]), fmt_int(item["upper"]))])

    words = []
    for item in trend.get("top_keywords", [])[:12]:
        words.append("`%s`" % item["word"])

    text = ("共采集 %s 篇文章，来源 %s 个。\n\n"
            % (fmt_int(trend.get("meta", {}).get("article_count")),
               trend.get("meta", {}).get("source_count")))
    text += make_table(["媒体来源", "地区", "文章数", "大模型相关占比"], source_rows)
    text += "\n\n**媒体报道高频词**：" + "、".join(words) + "\n"

    if forecast_rows:
        text += "\n**B站视频发布量趋势外推（未来 3 个月）**\n\n"
        text += make_table(["预测月份", "预测视频数", "约 95% 预测区间"], forecast_rows)
        text += "\n\n> %s\n" % trend.get("video_forecast_note", "")
    return text


def render_media_gap(analysis, trend):
    """附加题：媒体和用户的话题差异。"""
    rows = []
    for item in trend.get("media_vs_danmaku", [])[:8]:
        rows.append([item["name"], fmt_pct(item["media_ratio"]),
                     fmt_pct(item["danmaku_ratio"]), "%+.1f%%" % (item["gap"] * 100)])

    if not rows:
        return "> 需要同时有弹幕分析和媒体分析的结果才能做这个对比。\n"
    return make_table(["应用领域", "媒体关注度", "弹幕关注度", "差值（媒体−用户）"], rows)


RENDERERS = {
    "CATEGORY": render_category,
    "CASES": render_cases,
    "SENTIMENT": render_sentiment,
    "COST_RISK": render_cost_risk,
    "MEDIA": render_media,
    "MEDIA_GAP": render_media_gap,
}


def main():
    analysis = read_json(ANALYSIS_FILE, {})
    if not analysis:
        log.error("没找到分析结果，请先运行 python main.py analyze")
        return 1

    trend = read_json(TREND_FILE, {})
    if not trend:
        # 趋势结果没有的话，用缓存里的文章现场算一遍
        from src.crawler.media_spider import iter_cached_articles

        articles = list(iter_cached_articles())
        if articles:
            trend = TrendAnalyzer(articles, analysis).analyze().to_dict()
            log.info("用缓存的文章现场重算趋势：%d 篇", len(articles))

    videos = read_json(VIDEO_INDEX_FILE, [])
    if videos:
        count_by_keyword = {}
        for video in videos:
            key = video.get("keyword", "未标注")
            count_by_keyword[key] = count_by_keyword.get(key, 0) + 1
        log.info("视频清单：%s",
                 "、".join("%s %d 个" % (k, v) for k, v in count_by_keyword.items()))

    text = BLOG_PATH.read_text(encoding="utf-8")
    missing = []

    for key, renderer in RENDERERS.items():
        # 用一对注释把内容包起来，这样脚本可以重复执行（每次只替换中间的内容）
        pattern = re.compile(r"<!--DATA:%s-->.*?<!--/DATA:%s-->|<!--DATA:%s-->"
                             % (key, key, key), re.DOTALL)
        if not pattern.search(text):
            missing.append(key)
            continue

        content = renderer(analysis, trend).strip()
        replacement = "<!--DATA:%s-->\n%s\n<!--/DATA:%s-->" % (key, content, key)
        text = pattern.sub(lambda m, r=replacement: r, text, count=1)
        log.info("已注入 %s", key)

    BLOG_PATH.write_text(text, encoding="utf-8", newline="\n")
    log.info("博客数据注入完成：%s", BLOG_PATH)
    if missing:
        log.info("博客里没找到这些占位符（可以忽略）：%s", "、".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
