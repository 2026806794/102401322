"""可视化相关的模块。

- theme             配色和字体（中文字体必须在这里注册好）
- wordcloud_chart   四张词云
- charts            六张统计图
- dashboard         可视化大屏（HTML）
- trend_report      附加题：媒体趋势报告
"""

from src.visualization.charts import build_stat_charts
from src.visualization.dashboard import build_dashboard
from src.visualization.trend_report import build_trend_visuals
from src.visualization.wordcloud_chart import build_wordclouds

__all__ = ["build_all_charts", "build_wordclouds", "build_stat_charts",
           "build_dashboard", "build_trend_visuals"]


def build_all_charts(payload):
    """根据分析结果生成全部可视化产物，返回文件路径列表。

    payload 是 DanmakuAnalyzer 的 analyze() 结果转成 dict 之后的数据。
    """
    paths = []
    paths.extend(build_wordclouds(payload))
    paths.extend(build_stat_charts(payload))
    paths.append(build_dashboard(payload))
    return paths
