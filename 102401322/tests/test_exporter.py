"""Excel 导出单元测试：工作表完整性、表头中文化、样式与内容正确性。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.analysis.analyzer import AnalysisResult
from src.analysis.exporter import ExcelExporter

EXPECTED_SHEETS = [
    "总览",
    "每类弹幕总数量",
    "Top8弹幕词频",
    "Top8应用案例",
    "分领域Top8词频",
    "用户态度分布",
    "应用成本关注",
    "不利影响关注",
    "分维度Top8词频",
    "关键词统计",
    "视频清单",
    "弹幕进度分布",
    "词频明细Top500",
]


@pytest.fixture()
def sample_result() -> AnalysisResult:
    """构造一份内容完整的小型分析结果。"""
    result = AnalysisResult()
    result.meta = {"student_id": "102401322", "total_records": 100, "top_n": 8}
    result.clean_stats = {"弹幕总数": 120, "清洗后保留": 100, "噪声占比": "16.7%"}
    result.total_danmaku = 100
    result.total_videos = 5
    result.total_words = 400
    result.category_stats = [{"rank": 1, "name": "教育学习", "count": 40, "ratio": 0.4}]
    result.top_words = [{"rank": 1, "word": "模型", "count": 30}]
    result.top_words_by_category = {"教育学习": [{"rank": 1, "word": "学习", "count": 12}]}
    result.case_ranking = [{"rank": 1, "name": "ChatGPT", "count": 20, "ratio": 0.2}]
    result.sentiment = [{"rank": 1, "name": "正面评价", "count": 60, "ratio": 0.6}]
    result.cost = [{"rank": 1, "name": "API成本", "count": 15, "ratio": 0.15}]
    result.risk = [{"rank": 1, "name": "取代工作", "count": 8, "ratio": 0.08}]
    result.keyword_stats = [{"rank": 1, "name": "大模型", "count": 60, "ratio": 0.6}]
    result.video_stats = [{"bvid": "BV1", "title": "测试视频", "author": "UP",
                           "keyword": "大模型", "view": 1000, "duration": 600,
                           "danmaku_clean": 40, "danmaku_raw": 50}]
    result.progress_distribution = [{"bucket": "0-10%", "count": 20}]
    result.word_freq = [{"word": "模型", "count": 30}]
    result.top_words_by_aspect = {"风险-取代工作": [{"rank": 1, "word": "失业", "count": 5}]}
    return result


class TestExcelExporter:
    """导出行为与产物结构。"""

    def test_export_creates_all_sheets(self, sample_result: AnalysisResult, tmp_path: Path) -> None:
        """13 个工作表应全部生成（覆盖作业要求的三类核心数据）。"""
        path = ExcelExporter(tmp_path / "out.xlsx").export(sample_result)
        assert path.exists()
        with pd.ExcelFile(path) as workbook:
            for sheet in EXPECTED_SHEETS:
                assert sheet in workbook.sheet_names, f"缺少工作表 {sheet}"

    def test_export_uses_chinese_headers(self, sample_result: AnalysisResult,
                                         tmp_path: Path) -> None:
        """列名应转换为中文表头，便于阅读。"""
        path = ExcelExporter(tmp_path / "out.xlsx").export(sample_result)
        frame = pd.read_excel(path, sheet_name="Top8应用案例")
        assert list(frame.columns) == ["排名", "名称", "数量", "占比"]

    def test_overview_sheet_contains_key_metrics(self, sample_result: AnalysisResult,
                                                 tmp_path: Path) -> None:
        """总览表应包含视频数、弹幕数等关键指标。"""
        path = ExcelExporter(tmp_path / "out.xlsx").export(sample_result)
        frame = pd.read_excel(path, sheet_name="总览")
        metrics = dict(zip(frame["指标"], frame["数值"]))
        assert metrics["视频总数"] == 5
        assert metrics["弹幕总数(清洗后)"] == 100
        assert metrics["学生学号"] == "102401322"

    def test_export_creates_parent_directory(self, sample_result: AnalysisResult,
                                             tmp_path: Path) -> None:
        """异常处理：目标目录不存在时应自动创建。"""
        target = tmp_path / "nested" / "deep" / "out.xlsx"
        path = ExcelExporter(target).export(sample_result)
        assert path.exists()

    def test_empty_result_still_exports(self, tmp_path: Path) -> None:
        """边界值：空结果也应产出合法 Excel，而不是抛异常。"""
        path = ExcelExporter(tmp_path / "empty.xlsx").export(AnalysisResult())
        assert path.exists()
        with pd.ExcelFile(path) as workbook:
            assert "总览" in workbook.sheet_names

    def test_header_style_is_applied(self, sample_result: AnalysisResult, tmp_path: Path) -> None:
        """表头应套用深色底白字样式，且首行被冻结。"""
        from openpyxl import load_workbook

        path = ExcelExporter(tmp_path / "out.xlsx").export(sample_result)
        workbook = load_workbook(path)
        sheet = workbook["每类弹幕总数量"]
        assert sheet["A1"].font.bold is True
        assert sheet["A1"].fill.fgColor.rgb.endswith("1F4E79")
        assert sheet.freeze_panes == "A2"
