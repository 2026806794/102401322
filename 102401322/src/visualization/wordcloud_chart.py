"""词云图。

一共画四张：
    1. 总体词云（深色背景）
    2. Top-8 应用案例词云
    3. 风险担忧词云（暖色，表达"警示"）
    4. 分领域组合词云（2x2）

中文词云必须指定字体文件，否则画出来全是方框。
"""

from pathlib import Path

import matplotlib.pyplot as plt
from wordcloud import WordCloud

from src.config import CHINESE_FONT, DEFAULT_ANALYSIS_CONFIG, FIGURE_DIR
from src.visualization.theme import (
    BACKGROUND_DARK,
    BACKGROUND_LIGHT,
    PALETTE,
    apply_matplotlib_theme,
)
from src.utils import get_logger

log = get_logger(__name__)


def make_wordcloud(frequencies, colormap, background, max_words=220,
                   prefer_horizontal=0.88):
    """按统一参数生成一个 WordCloud 对象。

    frequencies 是 {词: 权重} 的字典，权重决定字号大小。
    """
    return WordCloud(
        font_path=CHINESE_FONT,          # 不指定就会画成方框
        width=1600,
        height=900,
        background_color=background,
        colormap=colormap,
        max_words=max_words,
        prefer_horizontal=prefer_horizontal,
        relative_scaling=0.45,
        min_font_size=12,
        max_font_size=170,
        margin=6,
        random_state=DEFAULT_ANALYSIS_CONFIG.random_seed,   # 固定随机种子，每次结果一样
        collocations=False,              # 不要自动组合词组
    ).generate_from_frequencies(frequencies)


def save_figure(figure, path):
    """保存图片并关掉画布。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=DEFAULT_ANALYSIS_CONFIG.figure_dpi,
                   facecolor=figure.get_facecolor(), bbox_inches="tight")
    plt.close(figure)
    log.info("已生成词云：%s", path.name)
    return path


def build_overall_wordcloud(payload):
    """总体弹幕词云，深色科技风。"""
    frequencies = {}
    for item in payload.get("word_freq", []):
        frequencies[item["word"]] = item["count"]

    apply_matplotlib_theme()
    cloud = make_wordcloud(
        frequencies,
        colormap="plasma",
        background=BACKGROUND_DARK,
        max_words=DEFAULT_ANALYSIS_CONFIG.wordcloud_max_words,
    )

    figure, axes = plt.subplots(figsize=(13, 7.5), dpi=DEFAULT_ANALYSIS_CONFIG.figure_dpi)
    figure.patch.set_facecolor(BACKGROUND_DARK)
    axes.imshow(cloud, interpolation="bilinear")
    axes.axis("off")
    axes.set_title(
        f"B站大语言模型相关视频弹幕词云（有效弹幕 {payload.get('total_danmaku', 0):,} 条）",
        fontsize=17, color="#E8F1FF", pad=16, fontweight="bold")
    return save_figure(figure, FIGURE_DIR / "词云_总体弹幕.png")


def build_case_wordcloud(payload):
    """Top-8 应用案例词云，字号就是被提及的弹幕条数。"""
    cases = payload.get("case_ranking", [])
    if not cases:
        return FIGURE_DIR / "词云_应用案例.png"

    frequencies = {}
    for item in cases:
        frequencies[item["name"]] = item["count"]

    cloud = make_wordcloud(frequencies, colormap="winter",
                           background=BACKGROUND_LIGHT, max_words=60,
                           prefer_horizontal=0.95)

    figure, axes = plt.subplots(figsize=(12, 6.5), dpi=DEFAULT_ANALYSIS_CONFIG.figure_dpi)
    axes.imshow(cloud, interpolation="bilinear")
    axes.axis("off")
    axes.set_title("弹幕提及最多的 LLM 应用案例（字号 = 提及弹幕数）",
                   fontsize=16, pad=14, fontweight="bold")
    return save_figure(figure, FIGURE_DIR / "词云_应用案例.png")


def build_risk_wordcloud(payload):
    """风险担忧词云。把"不利影响"各个子类下的词频合起来画。"""
    aspects = payload.get("top_words_by_aspect", {})
    merged = {}
    for aspect, words in aspects.items():
        if not aspect.startswith("风险-"):
            continue
        for item in words:
            merged[item["word"]] = merged.get(item["word"], 0) + item["count"]

    if not merged:
        merged = {"暂无数据": 1}

    cloud = make_wordcloud(merged, colormap="YlOrRd",
                           background="#1B1B1F", max_words=120)

    figure, axes = plt.subplots(figsize=(12, 6.5), dpi=DEFAULT_ANALYSIS_CONFIG.figure_dpi)
    figure.patch.set_facecolor("#1B1B1F")
    axes.imshow(cloud, interpolation="bilinear")
    axes.axis("off")
    axes.set_title("用户担忧什么？—— 不利影响相关弹幕词云",
                   fontsize=16, color="#FFE9D6", pad=14, fontweight="bold")
    return save_figure(figure, FIGURE_DIR / "词云_风险担忧.png")


def build_domain_wordclouds(payload):
    """分领域组合词云：取弹幕量前 4 的领域，2x2 排列。"""
    by_category = payload.get("top_words_by_category", {})
    domains = list(by_category.keys())[:4]
    if not domains:
        return FIGURE_DIR / "词云_分领域组合.png"

    apply_matplotlib_theme()
    figure, axes_grid = plt.subplots(2, 2, figsize=(15, 9),
                                     dpi=DEFAULT_ANALYSIS_CONFIG.figure_dpi)
    cells = list(axes_grid.ravel())

    for index, domain in enumerate(domains):
        axes = cells[index]
        frequencies = {}
        for item in by_category[domain]:
            frequencies[item["word"]] = item["count"]

        cloud = make_wordcloud(frequencies, colormap="viridis",
                               background=BACKGROUND_LIGHT, max_words=90,
                               prefer_horizontal=0.9)
        axes.imshow(cloud, interpolation="bilinear")
        axes.axis("off")
        axes.set_title(f"应用领域：{domain}", fontsize=14, fontweight="bold",
                       color=PALETTE[index % len(PALETTE)])

    # 领域不到 4 个的话，多出来的子图要隐藏掉，
    # 不然会露出空坐标轴和 0.0~1.0 的刻度线，很难看
    for axes in cells[len(domains):]:
        axes.set_visible(False)

    figure.suptitle("分领域弹幕词云（按领域弹幕量排序）", fontsize=17,
                    fontweight="bold", y=0.98)
    return save_figure(figure, FIGURE_DIR / "词云_分领域组合.png")


def build_wordclouds(payload):
    """生成全部四张词云。"""
    if not CHINESE_FONT:
        log.warning("没找到中文字体，词云可能显示成方块")

    return [
        build_overall_wordcloud(payload),
        build_case_wordcloud(payload),
        build_risk_wordcloud(payload),
        build_domain_wordclouds(payload),
    ]
