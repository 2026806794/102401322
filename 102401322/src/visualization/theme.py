"""图表主题：配色、字体、通用样式。

把"长什么样"集中在这里，其他画图的文件只管"画什么"。
"""

import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager

from src.config import CHINESE_FONT, DEFAULT_ANALYSIS_CONFIG

# 没有界面也要能出图（服务器上跑的时候）
matplotlib.use("Agg")

# 配色：蓝色系为主，配几个对比色
PALETTE = ["#4C8DFF", "#38D9C0", "#FFB84C", "#FF6B81", "#9B7BFF",
           "#3DDC97", "#F7A072", "#5BC0EB", "#E8C547", "#C084FC"]

BACKGROUND_DARK = "#0F1B2D"     # 深色底（词云、大屏用）
BACKGROUND_LIGHT = "#F7F9FC"    # 浅色底（统计图用）
TEXT_COLOR = "#1F2937"

FIGURE_SIZE = (12, 7)
DPI = DEFAULT_ANALYSIS_CONFIG.figure_dpi


def apply_matplotlib_theme():
    """设置全局样式，最重要的是中文字体。

    这里踩过一个坑：直接把字体文件路径写进 font.sans-serif 是没用的，
    matplotlib 不认路径，会默默退回默认字体，然后中文全变成方框。
    正确做法是先用 font_manager.addfont 把字体注册进去，
    再按字体族名引用。
    """
    if CHINESE_FONT:
        try:
            font_manager.fontManager.addfont(CHINESE_FONT)
            family = font_manager.FontProperties(fname=CHINESE_FONT).get_name()
            matplotlib.rcParams["font.sans-serif"] = [family, "Microsoft YaHei",
                                                      "SimHei", "DejaVu Sans"]
        except (RuntimeError, ValueError, OSError):
            matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei",
                                                      "DejaVu Sans"]

    matplotlib.rcParams["axes.unicode_minus"] = False     # 负号显示成方框的问题
    matplotlib.rcParams["figure.facecolor"] = BACKGROUND_LIGHT
    matplotlib.rcParams["axes.facecolor"] = BACKGROUND_LIGHT
    matplotlib.rcParams["axes.edgecolor"] = "#D8DEE9"
    matplotlib.rcParams["axes.labelcolor"] = TEXT_COLOR
    matplotlib.rcParams["text.color"] = TEXT_COLOR
    matplotlib.rcParams["xtick.color"] = TEXT_COLOR
    matplotlib.rcParams["ytick.color"] = TEXT_COLOR
    matplotlib.rcParams["axes.titleweight"] = "bold"
    matplotlib.rcParams["figure.autolayout"] = True


def new_figure(figsize=FIGURE_SIZE):
    """新建一张画布，顺便把主题应用上。"""
    apply_matplotlib_theme()
    return plt.subplots(figsize=figsize, dpi=DPI)


def style_axes(axes, title="", xlabel="", ylabel=""):
    """统一的坐标轴样式：加标题、加浅色网格、去掉上面和右边的框。"""
    axes.set_title(title, fontsize=15, pad=14)
    axes.set_xlabel(xlabel, fontsize=11)
    axes.set_ylabel(ylabel, fontsize=11)
    axes.grid(axis="y", linestyle="--", alpha=0.35)
    axes.set_axisbelow(True)
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
