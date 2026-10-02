"""统计图表（matplotlib）。

六张图：
    1. 每类弹幕数量（横向条形图）
    2. Top-8 应用案例（横向条形图）
    3. 用户态度（环形图）
    4. 成本与风险（左右两个面板）
    5. 弹幕随视频进度的分布（折线 + 面积）
    6. 各关键词的弹幕量（柱状图）

横向条形图用得比较多，因为领域名是中文，横着放才看得清。
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from src.config import DEFAULT_ANALYSIS_CONFIG, FIGURE_DIR
from src.visualization.theme import PALETTE, new_figure, style_axes
from src.utils import get_logger

log = get_logger(__name__)

DPI = DEFAULT_ANALYSIS_CONFIG.figure_dpi


def save_figure(figure, path):
    """保存并关闭。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=DPI, bbox_inches="tight", facecolor=figure.get_facecolor())
    plt.close(figure)
    log.info("已生成统计图：%s", path.name)
    return path


def build_category_chart(payload):
    """每类弹幕的总数量。"""
    stats = payload.get("category_stats", [])
    figure, axes = new_figure((11, 6.5))

    if not stats:
        axes.text(0.5, 0.5, "暂无数据", ha="center", va="center", fontsize=16)
        return save_figure(figure, FIGURE_DIR / "统计图_每类弹幕数量.png")

    # 反过来排，这样数值最大的在上面
    names = [item["name"] for item in stats][::-1]
    counts = [item["count"] for item in stats][::-1]
    colors = []
    for index in range(len(names)):
        colors.append(PALETTE[index % len(PALETTE)])

    bars = axes.barh(names, counts, color=colors, height=0.62)
    # 在每根柱子右边标上数值
    for rect, count in zip(bars, counts):
        axes.text(rect.get_width() + max(counts) * 0.012,
                  rect.get_y() + rect.get_height() / 2,
                  format(count, ","), va="center", fontsize=10)

    axes.set_xlim(0, max(counts) * 1.16)
    style_axes(axes, "各类应用领域的弹幕数量分布", "弹幕条数")
    axes.grid(axis="x", linestyle="--", alpha=0.35)
    axes.grid(axis="y", visible=False)
    return save_figure(figure, FIGURE_DIR / "统计图_每类弹幕数量.png")


def build_case_chart(payload):
    """Top-8 具体应用案例排名。"""
    cases = payload.get("case_ranking", [])
    top_n = payload.get("meta", {}).get("top_n", 8)
    figure, axes = new_figure((11, 6.5))

    if not cases:
        axes.text(0.5, 0.5, "暂无数据", ha="center", va="center", fontsize=16)
        return save_figure(figure, FIGURE_DIR / "统计图_Top8应用案例.png")

    names = [item["name"] for item in cases][::-1]
    counts = [item["count"] for item in cases][::-1]

    bars = axes.barh(names, counts, color=PALETTE[0], height=0.6)
    for rect, count in zip(bars, counts):
        axes.text(rect.get_width() + max(counts) * 0.012,
                  rect.get_y() + rect.get_height() / 2,
                  format(count, ","), va="center", fontsize=10)

    axes.set_xlim(0, max(counts) * 1.16)
    style_axes(axes, f"弹幕提及数量排名前 {top_n} 的大语言模型应用案例", "被提及弹幕条数")
    axes.grid(axis="x", linestyle="--", alpha=0.35)
    axes.grid(axis="y", visible=False)
    return save_figure(figure, FIGURE_DIR / "统计图_Top8应用案例.png")


def build_sentiment_chart(payload):
    """用户态度分布，画成环形图。"""
    sentiment = payload.get("sentiment", [])
    figure, axes = new_figure((9, 7))

    if not sentiment:
        axes.text(0.5, 0.5, "暂无数据", ha="center", va="center", fontsize=16)
        return save_figure(figure, FIGURE_DIR / "统计图_用户态度.png")

    labels = []
    for item in sentiment:
        labels.append(f"{item['name']}\n{item['count']:,} 条")
    sizes = [item["count"] for item in sentiment]
    colors = [PALETTE[0], PALETTE[3], PALETTE[2], PALETTE[1]]

    _, _, autotexts = axes.pie(
        sizes, labels=labels, colors=colors[:len(sizes)], autopct="%1.1f%%",
        startangle=110, pctdistance=0.76,
        wedgeprops={"width": 0.42, "edgecolor": "white", "linewidth": 2},
        textprops={"fontsize": 12})
    for autotext in autotexts:
        autotext.set_color("white")
        autotext.set_fontweight("bold")

    # 中间写上样本量，免得读者只看到比例不知道基数
    axes.text(0, 0, f"态度\n样本\n{sum(sizes):,}",
              ha="center", va="center", fontsize=13, fontweight="bold", color="#1F2937")
    axes.set_title("弹幕用户态度分布", fontsize=16, fontweight="bold", pad=18)
    return save_figure(figure, FIGURE_DIR / "统计图_用户态度.png")


def build_cost_risk_chart(payload):
    """应用成本和不利影响，左右并排两个面板。"""
    cost = payload.get("cost", [])
    risk = payload.get("risk", [])
    figure, (axes_left, axes_right) = plt.subplots(1, 2, figsize=(15, 6.2), dpi=DPI)

    panels = [
        (axes_left, cost, "用户关注的应用成本维度", PALETTE[2]),
        (axes_right, risk, "用户担忧的不利影响维度", PALETTE[3]),
    ]

    for axes, data, title, color in panels:
        if not data:
            axes.text(0.5, 0.5, "暂无数据", ha="center", va="center", fontsize=14)
            axes.axis("off")
            continue

        names = [item["name"] for item in data][::-1]
        counts = [item["count"] for item in data][::-1]
        axes.barh(names, counts, color=color, height=0.55)
        for index, count in enumerate(counts):
            axes.text(count + max(counts) * 0.02, index, format(count, ","),
                      va="center", fontsize=10)
        axes.set_xlim(0, max(counts) * 1.2)
        style_axes(axes, title, "相关弹幕条数")
        axes.grid(axis="x", linestyle="--", alpha=0.35)
        axes.grid(axis="y", visible=False)

    figure.suptitle("成本与风险：B站用户的两大关切", fontsize=17, fontweight="bold")
    return save_figure(figure, FIGURE_DIR / "统计图_成本与风险.png")


def build_progress_chart(payload):
    """弹幕随视频进度的分布。"""
    distribution = payload.get("progress_distribution", [])
    figure, axes = new_figure((11.5, 5.6))

    if not distribution:
        axes.text(0.5, 0.5, "暂无数据", ha="center", va="center", fontsize=16)
        return save_figure(figure, FIGURE_DIR / "统计图_弹幕进度分布.png")

    buckets = [item["bucket"] for item in distribution]
    counts = np.array([item["count"] for item in distribution], dtype=float)

    axes.plot(buckets, counts, marker="o", linewidth=2.6, color=PALETTE[0], markersize=7)
    axes.fill_between(buckets, counts, color=PALETTE[0], alpha=0.18)

    for index, count in enumerate(counts):
        axes.annotate(format(int(count), ","), (index, count), textcoords="offset points",
                      xytext=(0, 9), ha="center", fontsize=9)

    axes.set_ylim(0, counts.max() * 1.18)
    style_axes(axes, "弹幕数量随视频进度的分布", "视频进度", "弹幕条数")
    # 标一下统计口径，不然读者会以为"用户只看开头"
    axes.text(0.99, 0.94,
              "注：只统计弹幕池覆盖整段视频的数据\n（分段抓取的视频不计入，否则会集中在开头）",
              transform=axes.transAxes, ha="right", va="top",
              fontsize=9, color="#6B7280")
    return save_figure(figure, FIGURE_DIR / "统计图_弹幕进度分布.png")


def build_keyword_chart(payload):
    """不同搜索关键词带来的弹幕量对比。"""
    stats = payload.get("keyword_stats", [])
    figure, axes = new_figure((9, 5.4))

    if not stats:
        axes.text(0.5, 0.5, "暂无数据", ha="center", va="center", fontsize=16)
        return save_figure(figure, FIGURE_DIR / "统计图_关键词对比.png")

    names = [item["name"] for item in stats]
    counts = [item["count"] for item in stats]

    bars = axes.bar(names, counts, color=PALETTE[:len(names)], width=0.5)
    for rect, count in zip(bars, counts):
        axes.text(rect.get_x() + rect.get_width() / 2, rect.get_height() + max(counts) * 0.02,
                  format(count, ","), ha="center", fontsize=11, fontweight="bold")

    axes.set_ylim(0, max(counts) * 1.16)
    style_axes(axes, "各搜索关键词的弹幕数量对比", "搜索关键词", "弹幕条数")
    return save_figure(figure, FIGURE_DIR / "统计图_关键词对比.png")


def build_stat_charts(payload):
    """生成全部六张统计图。"""
    return [
        build_category_chart(payload),
        build_case_chart(payload),
        build_sentiment_chart(payload),
        build_cost_risk_chart(payload),
        build_progress_chart(payload),
        build_keyword_chart(payload),
    ]
