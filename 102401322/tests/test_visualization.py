"""可视化测试。

这些用例会真的调用 matplotlib 画图、真的写文件，属于最基础的端到端检查。
能发现的问题包括：中文字体没配好（图里全是方框）、数据键名写错、
大屏的 ECharts 配置结构不对等等，这些光靠单元测试是看不出来的。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.visualization import build_all_charts

pytestmark = pytest.mark.filterwarnings("ignore::UserWarning")


@pytest.fixture(autouse=True)
def isolated_output_dirs(monkeypatch, tmp_path: Path) -> Path:
    """把可视化输出目录重定向到临时目录。

    这一步很关键：可视化测试会真实调用 matplotlib 出图，
    如果不隔离，测试用的合成数据会**覆盖 output/figures 下的真实交付图表**。
    （本项目实际踩过这个坑——跑完测试后词云里全是"词汇1、学习4"这类假数据。）
    """
    import src.visualization.charts as charts_module
    import src.visualization.dashboard as dashboard_module
    import src.visualization.trend_report as trend_module
    import src.visualization.wordcloud_chart as wordcloud_module

    figure_dir = tmp_path / "figures"
    html_dir = tmp_path / "html"
    figure_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)

    for module in (charts_module, wordcloud_module, dashboard_module, trend_module):
        monkeypatch.setattr(module, "FIGURE_DIR", figure_dir, raising=False)
    for module in (dashboard_module, trend_module):
        monkeypatch.setattr(module, "HTML_DIR", html_dir, raising=False)
    return tmp_path


@pytest.fixture(scope="module")
def payload() -> dict:
    """构造一份足够小但结构完整的分析结果。"""
    return {
        "meta": {"student_id": "102401322", "top_n": 8},
        "clean_stats": {"噪声占比": "9.5%"},
        "total_danmaku": 1200,
        "total_videos": 30,
        "total_words": 3000,
        "category_stats": [
            {"rank": 1, "name": "教育学习", "count": 400, "ratio": 0.33},
            {"rank": 2, "name": "编程开发", "count": 300, "ratio": 0.25},
            {"rank": 3, "name": "办公效率", "count": 200, "ratio": 0.17},
            {"rank": 4, "name": "硬件算力", "count": 120, "ratio": 0.10},
        ],
        "top_words": [{"rank": i, "word": f"词汇{i}", "count": 100 - i} for i in range(1, 9)],
        "top_words_by_category": {
            "教育学习": [{"rank": i, "word": f"学习{i}", "count": 40 - i} for i in range(1, 9)],
            "编程开发": [{"rank": i, "word": f"代码{i}", "count": 30 - i} for i in range(1, 9)],
        },
        "case_ranking": [
            {"rank": i, "name": name, "count": 50 - i * 3, "ratio": 0.05}
            for i, name in enumerate(["ChatGPT", "DeepSeek", "豆包", "Claude"], start=1)
        ],
        "sentiment": [
            {"rank": 1, "name": "正面评价", "count": 600, "ratio": 0.5},
            {"rank": 2, "name": "负面评价", "count": 300, "ratio": 0.25},
            {"rank": 3, "name": "中性观望", "count": 300, "ratio": 0.25},
        ],
        "cost": [{"rank": 1, "name": "API成本", "count": 120, "ratio": 0.4},
                 {"rank": 2, "name": "硬件成本", "count": 80, "ratio": 0.27}],
        "risk": [{"rank": 1, "name": "取代工作", "count": 60, "ratio": 0.3},
                 {"rank": 2, "name": "内容真实性", "count": 40, "ratio": 0.2}],
        "keyword_stats": [{"rank": 1, "name": "大模型", "count": 700, "ratio": 0.58},
                          {"rank": 2, "name": "LLM", "count": 500, "ratio": 0.42}],
        "video_stats": [{"bvid": "BV1", "title": "示例视频", "author": "UP",
                         "keyword": "大模型", "view": 1000, "duration": 600,
                         "danmaku_clean": 300, "danmaku_raw": 340}],
        "progress_distribution": [
            {"bucket": f"{i * 10}-{(i + 1) * 10}%", "count": 100 + i * 5} for i in range(10)
        ],
        "word_freq": [{"word": f"词汇{i}", "count": 100 - i} for i in range(1, 61)],
        "top_words_by_aspect": {
            "风险-取代工作": [{"rank": i, "word": f"担忧{i}", "count": 20 - i} for i in range(1, 9)]
        },
    }


class TestChartGeneration:
    """图表生成端到端。"""

    def test_build_all_charts_produces_files(self, payload: dict,
                                             isolated_output_dirs: Path) -> None:
        """全部图表与大屏都应被真实生成，且文件非空。"""
        paths = build_all_charts(payload)
        assert len(paths) >= 10
        for path in paths:
            assert Path(path).exists(), f"{path} 未生成"
            assert Path(path).stat().st_size > 1024, f"{path} 内容异常"

    def test_wordclouds_and_charts_are_named(self, payload: dict,
                                             isolated_output_dirs: Path) -> None:
        """产物命名应可读（中文名 + 用途前缀）。"""
        names = {Path(path).name for path in build_all_charts(payload)}
        assert "词云_总体弹幕.png" in names
        assert "统计图_Top8应用案例.png" in names
        assert "可视化大屏.html" in names


class TestDashboardContract:
    """大屏 HTML 的数据契约。"""

    @staticmethod
    def _load_charts(html: str) -> dict:
        match = re.search(r"const CHARTS = (\{.*?\});\n", html, re.S)
        assert match, "大屏 HTML 中未找到 CHARTS 配置"
        return json.loads(match.group(1))

    def test_dashboard_contains_valid_chart_options(self, payload: dict,
                                                    isolated_output_dirs: Path) -> None:
        """注入的 ECharts 配置必须是合法 JSON，且每个图表都有 series。"""
        build_all_charts(payload)
        html = (isolated_output_dirs / "html" / "可视化大屏.html").read_text(encoding="utf-8")
        charts = self._load_charts(html)

        expected = {"category", "cases", "sentiment", "cost", "risk",
                    "keyword", "progress", "topvideo"}
        assert expected.issubset(set(charts))
        for name, option in charts.items():
            assert option.get("series"), f"{name} 缺少 series"
            assert option["backgroundColor"] == "transparent"

    def test_dashboard_embeds_wordcloud_image(self, payload: dict,
                                              isolated_output_dirs: Path) -> None:
        """词云以静态高清图嵌入，避免依赖 ECharts 词云插件。"""
        build_all_charts(payload)
        html = (isolated_output_dirs / "html" / "可视化大屏.html").read_text(encoding="utf-8")
        assert '<img class="cloud"' in html
        assert "词云_总体弹幕.png" in html
        assert "echarts-wordcloud" not in html

    def test_dashboard_shows_key_metrics(self, payload: dict,
                                         isolated_output_dirs: Path) -> None:
        """指标卡应展示弹幕总数、视频数等关键数字。"""
        build_all_charts(payload)
        html = (isolated_output_dirs / "html" / "可视化大屏.html").read_text(encoding="utf-8")
        assert "1,200" in html
        assert "102401322" in html
