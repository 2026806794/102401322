"""附加题的可视化：媒体趋势报告。

四张图 + 一个 HTML 报告：
    1. B站视频发布量的月度趋势与外推（这条序列比 RSS 可靠，是趋势判断的主证据）
    2. 媒体报道热度的月度趋势
    3. 媒体 vs 用户的话题关注度对比（双向条形图）
    4. 各媒体源的报道量与 LLM 相关占比
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from src.config import DEFAULT_ANALYSIS_CONFIG, FIGURE_DIR, HTML_DIR, STUDENT_ID
from src.utils import get_logger
from src.visualization.html_common import (
    ECHARTS_INIT_SCRIPT, ECHARTS_SCRIPT_TAG)
from src.visualization.theme import PALETTE, new_figure, style_axes

log = get_logger(__name__)

DPI = DEFAULT_ANALYSIS_CONFIG.figure_dpi

# 大屏用的配色
AXIS_LABEL = {"color": "#9FB3D1"}
SPLIT_LINE = {"lineStyle": {"color": "#1E3350"}}
TOOLTIP_STYLE = {"backgroundColor": "rgba(16,30,51,.94)", "borderColor": "#4C8DFF",
                 "textStyle": {"color": "#E8F1FF"}}


def save_figure(figure, path):
    """保存并关闭。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=figure.get_facecolor())
    plt.close(figure)
    log.info("已生成趋势图：%s", path.name)
    return path


def build_video_trend_chart(trend):
    """B站视频发布量趋势 + 外推。"""
    monthly = trend.get("video_monthly_trend", [])
    forecast = trend.get("video_forecast", [])
    figure, axes = new_figure((13, 6.2))

    if not monthly:
        axes.text(0.5, 0.5, "暂无视频时间数据", ha="center", va="center", fontsize=16)
        return save_figure(figure, FIGURE_DIR / "媒体趋势_视频发布趋势.png")

    months = [item["month"] for item in monthly]
    counts = [item["llm_related"] for item in monthly]

    axes.plot(months, counts, marker="o", linewidth=2.6, color=PALETTE[0],
              label="每月新增大模型相关视频数")
    axes.fill_between(months, counts, color=PALETTE[0], alpha=0.14)

    if forecast:
        f_months = [item["month"] for item in forecast]
        f_values = [item["predicted"] for item in forecast]
        f_lower = [item["lower"] for item in forecast]
        f_upper = [item["upper"] for item in forecast]

        # 从最后一个真实点连出去，虚线表示这是预测
        axes.plot([months[-1]] + f_months, [counts[-1]] + f_values,
                  linestyle="--", marker="^", linewidth=2.2, color=PALETTE[3],
                  label="线性外推（未来 3 个月）")
        axes.fill_between(f_months, f_lower, f_upper, color=PALETTE[3], alpha=0.18,
                          label="约 95% 预测区间")
        axes.axvspan(months[-1], f_months[-1], color=PALETTE[3], alpha=0.06)

    axes.set_xticks(months + [item["month"] for item in forecast])
    axes.tick_params(axis="x", rotation=45)
    style_axes(axes, "B站大模型相关视频发布量的月度趋势与外推", "发布月份", "视频数")
    axes.legend(fontsize=10, loc="upper left")
    return save_figure(figure, FIGURE_DIR / "媒体趋势_视频发布趋势.png")


def build_media_trend_chart(trend):
    """媒体报道热度趋势。"""
    monthly = trend.get("monthly_trend", [])
    forecast = trend.get("forecast", [])
    figure, axes = new_figure((13, 6.2))

    if not monthly:
        axes.text(0.5, 0.5, "暂无媒体数据", ha="center", va="center", fontsize=16)
        return save_figure(figure, FIGURE_DIR / "媒体趋势_报道热度.png")

    months = [item["month"] for item in monthly]
    totals = [item["total"] for item in monthly]
    llm = [item["llm_related"] for item in monthly]

    axes.plot(months, totals, marker="o", linewidth=2.2, color=PALETTE[2],
              label="全部科技报道")
    axes.plot(months, llm, marker="s", linewidth=2.6, color=PALETTE[0],
              label="大模型相关报道")

    if forecast:
        f_months = [item["month"] for item in forecast]
        f_values = [item["predicted"] for item in forecast]
        f_lower = [item["lower"] for item in forecast]
        f_upper = [item["upper"] for item in forecast]

        axes.plot([months[-1]] + f_months, [llm[-1]] + f_values,
                  linestyle="--", marker="^", linewidth=2.2, color=PALETTE[3],
                  label="趋势外推（未来 3 个月）")
        axes.fill_between(f_months, f_lower, f_upper, color=PALETTE[3], alpha=0.18,
                          label="约 95% 预测区间")
        axes.axvspan(months[-1], f_months[-1], color=PALETTE[3], alpha=0.06)

    axes.set_xticks(months + [item["month"] for item in forecast])
    axes.tick_params(axis="x", rotation=45)
    style_axes(axes, "科技媒体大模型报道热度与趋势外推", "月份", "文章数")
    axes.legend(fontsize=10, loc="upper left")
    return save_figure(figure, FIGURE_DIR / "媒体趋势_报道热度.png")


def build_topic_compare_chart(trend):
    """媒体话题 vs 用户话题的双向条形图。

    左边画弹幕（取负值），右边画媒体，中间一条竖线是 0。
    这样"哪边关注得多"一眼就能看出来。
    """
    rows = trend.get("media_vs_danmaku", [])[:10]
    figure, axes = new_figure((12, 6.5))

    if not rows:
        axes.text(0.5, 0.5, "暂无对比数据", ha="center", va="center", fontsize=16)
        return save_figure(figure, FIGURE_DIR / "媒体趋势_话题对比.png")

    names = [row["name"] for row in rows][::-1]
    media = np.array([row["media_ratio"] for row in rows][::-1]) * 100
    danmaku = -np.array([row["danmaku_ratio"] for row in rows][::-1]) * 100
    positions = np.arange(len(names))

    axes.barh(positions, media, color=PALETTE[0], height=0.55, label="科技媒体关注度")
    axes.barh(positions, danmaku, color=PALETTE[1], height=0.55, label="B站弹幕关注度")
    axes.set_yticks(positions)
    axes.set_yticklabels(names)
    axes.axvline(0, color="#94A3B8", linewidth=1)

    limit = max(abs(media).max(), abs(danmaku).max()) * 1.28
    axes.set_xlim(-limit, limit)
    ticks = np.linspace(-limit, limit, 9)
    axes.set_xticks(ticks)
    # 左边显示绝对值，不然负号看着别扭
    axes.set_xticklabels([f"{abs(tick):.0f}%" for tick in ticks])

    for index in range(len(names)):
        axes.text(media[index] + limit * 0.02, index, f"{media[index]:.1f}%",
                  va="center", fontsize=9)
        axes.text(danmaku[index] - limit * 0.02, index, f"{abs(danmaku[index]):.1f}%",
                  va="center", ha="right", fontsize=9)

    axes.set_title("话题关注度对比：媒体 vs 用户（左侧=弹幕，右侧=媒体）",
                   fontsize=15, pad=14)
    axes.set_xlabel("该领域占各自话题总量的比例")
    axes.legend(fontsize=10, loc="lower right")
    axes.grid(axis="x", linestyle="--", alpha=0.3)
    axes.set_axisbelow(True)
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.spines["left"].set_visible(False)
    return save_figure(figure, FIGURE_DIR / "媒体趋势_话题对比.png")


def build_source_chart(trend):
    """各媒体源的文章数和大模型相关占比。"""
    stats = trend.get("source_stats", [])
    figure, axes = new_figure((11, 5.8))

    if not stats:
        axes.text(0.5, 0.5, "暂无媒体数据", ha="center", va="center", fontsize=16)
        return save_figure(figure, FIGURE_DIR / "媒体趋势_来源分布.png")

    names = [item["name"] for item in stats]
    counts = [item["count"] for item in stats]
    positions = np.arange(len(names))

    bars = axes.bar(positions, counts, color=PALETTE[4], width=0.55, label="文章总数")
    for index in range(len(names)):
        ratio = stats[index]["llm_ratio"] * 100
        axes.text(bars[index].get_x() + bars[index].get_width() / 2,
                  counts[index] + max(counts) * 0.02,
                  f"{counts[index]}篇\n大模型占{ratio:.0f}%",
                  ha="center", fontsize=9)

    axes.set_xticks(positions)
    axes.set_xticklabels(names, rotation=18)
    axes.set_ylim(0, max(counts) * 1.26)
    style_axes(axes, "各科技媒体源的报道量与 LLM 相关占比", "媒体来源", "文章数")
    return save_figure(figure, FIGURE_DIR / "媒体趋势_来源分布.png")


# ---------------- HTML 报告 ----------------

def media_trend_option(trend):
    """媒体报道趋势的 ECharts 配置。

    这里不设 smooth，因为月份数据点很少，平滑会画出夸张的过冲
    （实测真实峰值 35 会被画成 80），反而误导人。
    """
    monthly = trend.get("monthly_trend", [])
    forecast = trend.get("forecast", [])

    months = [item["month"] for item in monthly] + [item["month"] for item in forecast]
    totals = [item["total"] for item in monthly] + [None] * len(forecast)

    llm_actual = [item["llm_related"] for item in monthly] + [None] * len(forecast)
    llm_forecast = []
    if forecast:
        llm_forecast = [None] * (len(monthly) - 1) + [monthly[-1]["llm_related"]]
        llm_forecast += [item["predicted"] for item in forecast]

    series = [
        {"name": "全部科技报道", "type": "line", "smooth": False, "data": totals,
         "lineStyle": {"width": 2, "color": "#FFB84C"}, "itemStyle": {"color": "#FFB84C"}},
        {"name": "大模型相关报道", "type": "line", "smooth": False, "data": llm_actual,
         "lineStyle": {"width": 3, "color": "#4C8DFF"}, "itemStyle": {"color": "#4C8DFF"},
         "areaStyle": {"color": "#4C8DFF", "opacity": 0.16}},
    ]
    if llm_forecast:
        series.append({"name": "趋势外推", "type": "line", "smooth": False,
                       "data": llm_forecast,
                       "lineStyle": {"width": 2, "type": "dashed", "color": "#FF6B81"},
                       "itemStyle": {"color": "#FF6B81"}})

    return {
        "backgroundColor": "transparent",
        "title": {"text": "科技媒体大模型报道热度与趋势外推", "left": 14, "top": 10,
                  "textStyle": {"color": "#E8F1FF", "fontSize": 16}},
        "tooltip": dict(TOOLTIP_STYLE, trigger="axis"),
        "legend": {"data": [item["name"] for item in series], "right": 16, "top": 12,
                   "textStyle": {"color": "#9FB3D1"}},
        "grid": {"left": "3%", "right": "4%", "top": 64, "bottom": 46, "containLabel": True},
        "xAxis": {"type": "category", "data": months,
                  "axisLabel": {"color": "#9FB3D1", "rotate": 45}},
        "yAxis": {"type": "value", "axisLabel": AXIS_LABEL, "splitLine": SPLIT_LINE},
        "series": series,
    }


def video_trend_option(trend):
    """B站视频趋势的 ECharts 配置。"""
    monthly = trend.get("video_monthly_trend", [])
    forecast = trend.get("video_forecast", [])

    months = [item["month"] for item in monthly] + [item["month"] for item in forecast]
    counts = [item["llm_related"] for item in monthly] + [None] * len(forecast)

    forecast_series = []
    if forecast:
        forecast_series = [None] * (len(monthly) - 1) + [monthly[-1]["llm_related"]]
        forecast_series += [item["predicted"] for item in forecast]

    series = [
        {"name": "每月新增相关视频", "type": "line", "smooth": False, "data": counts,
         "lineStyle": {"width": 3, "color": "#4C8DFF"}, "itemStyle": {"color": "#4C8DFF"},
         "areaStyle": {"color": "#4C8DFF", "opacity": 0.16}},
    ]
    if forecast_series:
        series.append({"name": "趋势外推", "type": "line", "smooth": False,
                       "data": forecast_series,
                       "lineStyle": {"width": 2, "type": "dashed", "color": "#FF6B81"},
                       "itemStyle": {"color": "#FF6B81"}})

    return {
        "backgroundColor": "transparent",
        "title": {"text": "B站大模型相关视频发布量的月度趋势与外推", "left": 14, "top": 10,
                  "textStyle": {"color": "#E8F1FF", "fontSize": 16}},
        "tooltip": dict(TOOLTIP_STYLE, trigger="axis"),
        "legend": {"data": [item["name"] for item in series], "right": 16, "top": 12,
                   "textStyle": {"color": "#9FB3D1"}},
        "grid": {"left": "3%", "right": "4%", "top": 64, "bottom": 46, "containLabel": True},
        "xAxis": {"type": "category", "data": months,
                  "axisLabel": {"color": "#9FB3D1", "rotate": 45}},
        "yAxis": {"type": "value", "axisLabel": AXIS_LABEL, "splitLine": SPLIT_LINE},
        "series": series,
    }


def topic_compare_option(trend):
    """话题对比的 ECharts 配置。"""
    rows = trend.get("media_vs_danmaku", [])[:10]
    names = [row["name"] for row in rows]
    media = [round(row["media_ratio"] * 100, 2) for row in rows]
    danmaku = [round(row["danmaku_ratio"] * 100, 2) for row in rows]

    return {
        "backgroundColor": "transparent",
        "title": {"text": "话题关注度对比：媒体 vs B站用户", "left": 14, "top": 10,
                  "textStyle": {"color": "#E8F1FF", "fontSize": 16}},
        "tooltip": dict(TOOLTIP_STYLE, trigger="axis", axisPointer={"type": "shadow"}),
        "legend": {"data": ["科技媒体", "B站弹幕"], "right": 16, "top": 12,
                   "textStyle": {"color": "#9FB3D1"}},
        "grid": {"left": "3%", "right": "6%", "top": 64, "bottom": 26, "containLabel": True},
        "xAxis": {"type": "value", "axisLabel": {"color": "#9FB3D1", "formatter": "{value}%"},
                  "splitLine": SPLIT_LINE},
        "yAxis": {"type": "category", "data": names, "axisLabel": {"color": "#D6E4FF"}},
        "series": [
            {"name": "科技媒体", "type": "bar", "data": media,
             "itemStyle": {"color": "#4C8DFF", "borderRadius": [0, 5, 5, 0]}},
            {"name": "B站弹幕", "type": "bar", "data": danmaku,
             "itemStyle": {"color": "#38D9C0", "borderRadius": [0, 5, 5, 0]}},
        ],
    }


REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>科技媒体大模型趋势报告 · {student_id}</title>
{echarts_tag}
<style>
  body {{ margin:0; padding:24px 30px 44px; background:#0b1524; color:#E8F1FF;
         font-family:"Microsoft YaHei","PingFang SC",sans-serif; }}
  h1 {{ font-size:26px; margin:0 0 6px;
        background:linear-gradient(90deg,#4C8DFF,#38D9C0,#FFB84C);
        -webkit-background-clip:text; background-clip:text; color:transparent; }}
  p.sub {{ color:#7C93B5; font-size:13px; margin:0 0 20px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:20px; }}
  .kpi {{ background:linear-gradient(160deg,rgba(76,141,255,.16),rgba(56,217,192,.06));
          border:1px solid rgba(76,141,255,.32); border-radius:12px;
          padding:14px; text-align:center; }}
  .kpi .v {{ font-size:24px; font-weight:700; color:#7FE3FF; }}
  .kpi .l {{ font-size:12px; color:#8FA7C7; margin-top:4px; }}
  .card {{ background:rgba(16,30,51,.72); border:1px solid rgba(76,141,255,.20);
           border-radius:14px; padding:12px; margin-bottom:18px; }}
  .chart {{ width:100%; height:380px; }}
  .note {{ color:#9FB3D1; font-size:13px; line-height:1.7; padding:4px 10px 10px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ padding:7px 10px; border-bottom:1px solid #1E3350; text-align:left; }}
  th {{ background:#12233c; color:#9FB3D1; }}
  a {{ color:#7FE3FF; text-decoration:none; }}
  tr:hover td {{ background:#12233c; }}
</style>
</head>
<body>
  <h1>科技媒体大模型观点与趋势报告</h1>
  <p class="sub">附加题 · 学号 {student_id} · 数据来源：主流科技媒体 RSS 订阅源</p>

  <section class="kpis">
    <div class="kpi"><div class="v">{article_count}</div><div class="l">采集文章总数</div></div>
    <div class="kpi"><div class="v">{source_count}</div><div class="l">媒体来源数</div></div>
    <div class="kpi"><div class="v">{llm_ratio}</div><div class="l">大模型相关占比</div></div>
    <div class="kpi"><div class="v">{month_count}</div><div class="l">覆盖月份数</div></div>
  </section>

  <div class="card"><div class="chart" id="trend"></div>
    <div class="note">{forecast_note}</div></div>
  <div class="card"><div class="chart" id="videotrend"></div>
    <div class="note">{video_forecast_note}</div></div>
  <div class="card"><div class="chart" id="topic"></div>
    <div class="note">对比说明：两侧比例的分母不一样（各自话题命中的总量），
    所以比的是<b>相对关注度</b>。差值越大，说明媒体的议程和用户的关切越不同步。</div></div>
  <div class="card">
    <h3 style="margin:6px 10px 12px;font-size:16px;">部分代表性文章</h3>
    <table><thead><tr><th>来源</th><th>标题</th></tr></thead><tbody>{rows}</tbody></table>
  </div>

  {init_script}
</body>
</html>
"""


def build_trend_report(trend):
    """生成趋势报告 HTML。"""
    source_stats = trend.get("source_stats", [])
    total = sum(item["count"] for item in source_stats)
    llm_total = sum(item["llm_related"] for item in source_stats)
    if total == 0:
        total = 1

    rows = ""
    for item in trend.get("sample_titles", []):
        rows += (f'<tr><td>{item.get("source", "")}</td>'
                 f'<td><a href="{item.get("link", "#")}" target="_blank" '
                 f'rel="noopener">{item.get("title", "")}</a></td></tr>')
    if not rows:
        rows = "<tr><td colspan='2'>暂无数据</td></tr>"

    charts = {
        "trend": media_trend_option(trend),
        "videotrend": video_trend_option(trend),
        "topic": topic_compare_option(trend),
    }

    html = REPORT_TEMPLATE.format(
        student_id=STUDENT_ID,
        article_count=trend.get("meta", {}).get("article_count", 0),
        source_count=trend.get("meta", {}).get("source_count", 0),
        llm_ratio=f"{llm_total * 100.0 / total:.0f}%",
        month_count=len(trend.get("monthly_trend", [])),
        forecast_note=trend.get("forecast_note", ""),
        video_forecast_note=trend.get("video_forecast_note", ""),
        rows=rows,
        echarts_tag=ECHARTS_SCRIPT_TAG,
        init_script=ECHARTS_INIT_SCRIPT.format(
            charts_json=json.dumps(charts, ensure_ascii=False)),
    )

    path = HTML_DIR / "媒体趋势报告.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8", newline="\n")
    log.info("已生成媒体趋势报告：%s", path.name)
    return path


def build_trend_visuals(trend):
    """生成附加题的全部可视化产物。"""
    return [
        build_video_trend_chart(trend),
        build_media_trend_chart(trend),
        build_topic_compare_chart(trend),
        build_source_chart(trend),
        build_trend_report(trend),
    ]
