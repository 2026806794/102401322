"""可视化大屏（HTML）。

思路：不用 pyecharts 的模板，而是自己写 ECharts 的配置字典，
再用 json 塞进一个自己写的 HTML 页面里，页面加载时统一
echarts.init + setOption 渲染出来。

为什么不直接用 pyecharts：试过它的 dump_options()，
饼图和词云的数据会被序列化成 {"name": "name", "value": "value"} 这种占位符，
图表出来是空白的。与其去研究它内部怎么处理的，不如自己拼配置，
反正 ECharts 的配置本来就是普通字典。

另外 echarts 的 js 文件放在 output/assets/ 下本地引用，
这样断网也能打开大屏。
"""

import json

from src.config import FIGURE_DIR, HTML_DIR, STUDENT_ID
from src.utils import get_logger
from src.visualization.html_common import (
    ECHARTS_INIT_SCRIPT, ECHARTS_SCRIPT_TAG)

log = get_logger(__name__)

PALETTE = ["#4C8DFF", "#38D9C0", "#FFB84C", "#FF6B81", "#9B7BFF",
           "#3DDC97", "#F7A072", "#5BC0EB", "#E8C547", "#C084FC"]

# 坐标轴文字的颜色，好几个图都要用
AXIS_LABEL = {"color": "#9FB3D1", "fontSize": 11}
CATEGORY_LABEL = {"color": "#D6E4FF", "fontSize": 11}
SPLIT_LINE = {"lineStyle": {"color": "#1E3350"}}
TOOLTIP_STYLE = {"backgroundColor": "rgba(16,30,51,.94)", "borderColor": "#4C8DFF",
                 "textStyle": {"color": "#E8F1FF"}}


def base_option(title):
    """所有图表的公共配置。"""
    return {
        "backgroundColor": "transparent",
        "title": {
            "text": title,
            "left": 14,
            "top": 10,
            "textStyle": {"color": "#E8F1FF", "fontSize": 16, "fontWeight": "bold"},
        },
        "tooltip": dict(TOOLTIP_STYLE, trigger="item"),
        "color": PALETTE,
    }


def wordcloud_card():
    """词云卡片。这里直接嵌一张 matplotlib 画好的高清图。

    本来想用 echarts-wordcloud 插件做交互式词云的，结果发现那个插件
    是按 ECharts 4 写的（内部调用了已经废弃的 extendSeriesModel），
    在 ECharts 5 上根本注册不上系列类型，图是空白的。
    与其把整个图表库降级到 4，不如直接用自己的词云图，
    反正效果也不差，还不用担心兼容性。
    """
    image = FIGURE_DIR / "词云_总体弹幕.png"
    if not image.exists():
        return ('<div class="card span-3 tall"><div class="card-title">弹幕高频词云</div>'
                '<div class="card-note">请先运行 python main.py visualize 生成词云图</div></div>')

    return ('<div class="card span-3 tall">'
            '<div class="card-title">弹幕高频词云</div>'
            f'<img class="cloud" src="../figures/{image.name}" alt="弹幕高频词云">'
            '</div>')


def rose_option(payload):
    """应用领域玫瑰图。"""
    data = []
    for item in payload.get("category_stats", []):
        data.append({"name": item["name"], "value": item["count"]})

    option = base_option("每类弹幕的总数量（应用领域）")
    option["tooltip"] = dict(TOOLTIP_STYLE, trigger="item",
                             formatter="{b}<br/>{c} 条 ({d}%)")
    option["series"] = [{
        "type": "pie",
        "radius": ["20%", "70%"],
        "center": ["50%", "58%"],
        "roseType": "radius",           # 半径大小也跟着数值变
        "itemStyle": {"borderRadius": 6, "borderColor": "#0F1B2D", "borderWidth": 2},
        "label": {"color": "#D6E4FF", "fontSize": 11, "formatter": "{b} {c}"},
        "labelLine": {"lineStyle": {"color": "#5C7398"}},
        "data": data,
    }]
    return option


def sentiment_option(payload):
    """用户态度环形图。"""
    data = []
    for item in payload.get("sentiment", []):
        data.append({"name": item["name"], "value": item["count"]})

    option = base_option("用户态度分布")
    option["tooltip"] = dict(TOOLTIP_STYLE, trigger="item",
                             formatter="{b}<br/>{c} 条 ({d}%)")
    option["series"] = [{
        "type": "pie",
        "radius": ["42%", "70%"],
        "center": ["50%", "58%"],
        "itemStyle": {"borderRadius": 6, "borderColor": "#0F1B2D", "borderWidth": 2},
        "label": {"color": "#D6E4FF", "fontSize": 12, "formatter": "{b}\n{d}%"},
        "labelLine": {"lineStyle": {"color": "#5C7398"}},
        "data": data,
    }]
    return option


def horizontal_bar_option(rows, title, color, unit="条"):
    """横向条形图。案例排名、成本、风险、Top10 视频都用它。"""
    names = [row["name"] for row in rows][::-1]
    values = [row["count"] for row in rows][::-1]

    option = base_option(title)
    option["grid"] = {"left": "3%", "right": "12%", "top": 56, "bottom": 20,
                      "containLabel": True}
    option["tooltip"] = dict(TOOLTIP_STYLE, trigger="axis",
                             axisPointer={"type": "shadow"},
                             formatter="{b}<br/>{c} " + unit)
    option["xAxis"] = {"type": "value", "axisLabel": AXIS_LABEL,
                       "splitLine": SPLIT_LINE, "axisLine": {"show": False},
                       "axisTick": {"show": False}}
    option["yAxis"] = {"type": "category", "data": names, "axisLabel": CATEGORY_LABEL,
                       "axisLine": {"lineStyle": {"color": "#1E3350"}},
                       "axisTick": {"show": False}}
    option["series"] = [{
        "type": "bar",
        "data": values,
        "barWidth": "52%",
        "label": {"show": True, "position": "right", "color": "#E8F1FF", "fontSize": 11},
        "itemStyle": {"color": color, "borderRadius": [0, 6, 6, 0]},
    }]
    return option


def vertical_bar_option(names, values, title, color):
    """纵向柱状图（关键词对比用）。"""
    option = base_option(title)
    option["grid"] = {"left": "3%", "right": "6%", "top": 56, "bottom": 26,
                      "containLabel": True}
    option["tooltip"] = dict(TOOLTIP_STYLE, trigger="axis",
                             axisPointer={"type": "shadow"}, formatter="{b}<br/>{c} 条")
    option["xAxis"] = {"type": "category", "data": names, "axisLabel": CATEGORY_LABEL,
                       "axisLine": {"lineStyle": {"color": "#1E3350"}},
                       "axisTick": {"show": False}}
    option["yAxis"] = {"type": "value", "axisLabel": AXIS_LABEL, "splitLine": SPLIT_LINE}
    option["series"] = [{
        "type": "bar",
        "data": values,
        "barWidth": "42%",
        "label": {"show": True, "position": "top", "color": "#E8F1FF", "fontSize": 11},
        "itemStyle": {"color": color, "borderRadius": [6, 6, 0, 0]},
    }]
    return option


def progress_option(payload):
    """弹幕随视频进度分布的折线图。"""
    distribution = payload.get("progress_distribution", [])

    option = base_option("弹幕数量随视频进度的分布")
    option["grid"] = {"left": "3%", "right": "5%", "top": 56, "bottom": 26,
                      "containLabel": True}
    option["tooltip"] = dict(TOOLTIP_STYLE, trigger="axis", formatter="{b}<br/>{c} 条")
    option["xAxis"] = {"type": "category", "boundaryGap": False,
                       "data": [item["bucket"] for item in distribution],
                       "axisLabel": AXIS_LABEL,
                       "axisLine": {"lineStyle": {"color": "#1E3350"}}}
    option["yAxis"] = {"type": "value", "axisLabel": AXIS_LABEL, "splitLine": SPLIT_LINE}
    option["series"] = [{
        "type": "line",
        "smooth": 0.3,
        "symbolSize": 8,
        "data": [item["count"] for item in distribution],
        "lineStyle": {"width": 3, "color": PALETTE[0]},
        "itemStyle": {"color": PALETTE[0]},
        "areaStyle": {"color": PALETTE[0], "opacity": 0.22},
    }]
    return option


# HTML 模板。用 CSS Grid 排版，分成"指标卡 + 图表网格"两层
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>大语言模型应用弹幕分析大屏 · {student_id}</title>
{echarts_tag}
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 20px 26px 40px;
    background: radial-gradient(circle at 20% 0%, #16294a 0%, #0b1524 45%, #070d17 100%);
    font-family: "Microsoft YaHei", "PingFang SC", "Hiragino Sans GB", sans-serif;
    color: #E8F1FF; min-height: 100vh;
  }}
  header {{ text-align: center; padding: 6px 0 18px; }}
  header h1 {{
    margin: 0; font-size: 30px; letter-spacing: 4px;
    background: linear-gradient(90deg, #4C8DFF, #38D9C0, #FFB84C);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }}
  header p {{ margin: 8px 0 0; color: #7C93B5; font-size: 13px; letter-spacing: 1px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 14px; margin-bottom: 18px; }}
  .kpi {{
    background: linear-gradient(160deg, rgba(76,141,255,.16), rgba(56,217,192,.06));
    border: 1px solid rgba(76,141,255,.32); border-radius: 12px;
    padding: 14px 18px; text-align: center;
    box-shadow: inset 0 0 26px rgba(76,141,255,.10);
  }}
  .kpi .value {{
    font-size: 26px; font-weight: 700; color: #7FE3FF;
    text-shadow: 0 0 14px rgba(76,141,255,.55);
  }}
  .kpi .label {{ font-size: 12px; color: #8FA7C7; margin-top: 4px; letter-spacing: 1px; }}
  .grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 16px; }}
  .card {{
    background: rgba(16, 30, 51, .72); border: 1px solid rgba(76,141,255,.20);
    border-radius: 14px; padding: 10px 12px 4px;
    box-shadow: 0 10px 26px rgba(0,0,0,.35);
  }}
  .card .chart {{ width: 100%; height: 300px; }}
  .card-title {{ color: #E8F1FF; font-size: 16px; font-weight: bold; padding: 10px 4px 4px; }}
  .card-note {{ color: #7C93B5; font-size: 13px; padding: 40px 10px; text-align: center; }}
  .card .cloud {{ width: 100%; height: 372px; object-fit: contain; display: block; }}
  .span-2 {{ grid-column: span 2; }}
  .span-3 {{ grid-column: span 3; }}
  .span-6 {{ grid-column: span 6; }}
  .tall .chart {{ height: 420px; }}
  footer {{ margin-top: 24px; text-align: center; color: #5C7398; font-size: 12px; }}
  @media (max-width: 1200px) {{
    .kpis {{ grid-template-columns: repeat(2, 1fr); }}
    .grid {{ grid-template-columns: repeat(2, 1fr); }}
    .span-2, .span-3, .span-6 {{ grid-column: span 2; }}
  }}
</style>
</head>
<body>
<header>
  <h1>大语言模型应用 · B站弹幕分析大屏</h1>
  <p>2025 软工 K 班个人编程任务 · 学号 {student_id} · 数据来源：哔哩哔哩综合排序前 300 视频弹幕</p>
</header>

<section class="kpis">
  <div class="kpi"><div class="value">{total_danmaku}</div><div class="label">有效弹幕总数</div></div>
  <div class="kpi"><div class="value">{total_videos}</div><div class="label">覆盖视频数</div></div>
  <div class="kpi"><div class="value">{domain_count}</div><div class="label">应用领域类别</div></div>
  <div class="kpi"><div class="value">{case_count}</div><div class="label">识别应用案例</div></div>
  <div class="kpi"><div class="value">{noise_ratio}</div><div class="label">噪声弹幕占比</div></div>
</section>

<section class="grid">
  {wordcloud_card}
  <div class="card span-3 tall"><div class="chart" id="category"></div></div>
  <div class="card span-3"><div class="chart" id="cases"></div></div>
  <div class="card span-3"><div class="chart" id="sentiment"></div></div>
  <div class="card span-2"><div class="chart" id="cost"></div></div>
  <div class="card span-2"><div class="chart" id="risk"></div></div>
  <div class="card span-2"><div class="chart" id="keyword"></div></div>
  <div class="card span-3"><div class="chart" id="progress"></div></div>
  <div class="card span-3"><div class="chart" id="topvideo"></div></div>
</section>

<footer>数据采集、统计与可视化由 Python 自动完成 · 图表引擎 Apache ECharts</footer>

{init_script}
</body>
</html>
"""


def build_dashboard(payload):
    """生成大屏 HTML，返回文件路径。"""
    top_videos = []
    for video in payload.get("video_stats", [])[:10]:
        title = video.get("title") or video.get("bvid", "")
        top_videos.append({"name": title[:16], "count": video.get("danmaku_clean", 0)})

    keyword_stats = payload.get("keyword_stats", [])
    top_n = payload.get("meta", {}).get("top_n", 8)

    charts = {
        "category": rose_option(payload),
        "cases": horizontal_bar_option(payload.get("case_ranking", []),
                                       f"数量排名前 {top_n} 的 LLM 应用案例",
                                       PALETTE[0]),
        "sentiment": sentiment_option(payload),
        "cost": horizontal_bar_option(
            payload.get("cost", []), "用户关注的应用成本维度", PALETTE[2]),
        "risk": horizontal_bar_option(
            payload.get("risk", []), "用户担忧的不利影响维度", PALETTE[3]),
        "keyword": vertical_bar_option(
            [item["name"] for item in keyword_stats],
            [item["count"] for item in keyword_stats],
            "各搜索关键词的弹幕量", PALETTE[1]),
        "progress": progress_option(payload),
        "topvideo": horizontal_bar_option(top_videos, "弹幕量 Top10 视频", PALETTE[4]),
    }

    html = HTML_TEMPLATE.format(
        student_id=STUDENT_ID,
        wordcloud_card=wordcloud_card(),
        total_danmaku=format(payload.get("total_danmaku", 0), ","),
        total_videos=format(payload.get("total_videos", 0), ","),
        domain_count=len(payload.get("category_stats", [])),
        case_count=len(payload.get("case_ranking", [])),
        noise_ratio=payload.get("clean_stats", {}).get("噪声占比", "-"),
        echarts_tag=ECHARTS_SCRIPT_TAG,
        init_script=ECHARTS_INIT_SCRIPT.format(
            charts_json=json.dumps(charts, ensure_ascii=False)),
    )

    path = HTML_DIR / "可视化大屏.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8", newline="\n")
    log.info("已生成可视化大屏：%s（%.0f KB）", path.name, path.stat().st_size / 1024.0)
    return path
