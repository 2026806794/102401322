"""流水线和配置的测试。

其中缓存遍历那条是回归测试：早期版本的缓存文件里没写 bvid，
统计的时候所有视频都被归到了"未知"，后来改成从文件名补全。
这个用例保证那段逻辑不会被误删。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import pipeline
from src.analysis.exporter import ExcelExporter
from src.config import (
    DEFAULT_ANALYSIS_CONFIG,
    DEFAULT_CRAWLER_CONFIG,
    AnalysisConfig,
    CrawlerConfig,
    detect_chinese_font,
    ensure_directories,
)
from src.crawler.danmaku_fetcher import iter_cached_danmaku
from src.utils import normalize_text, read_json, write_json


class TestConfig:
    """配置默认值与路径。"""

    def test_default_keywords_match_assignment(self) -> None:
        """作业要求覆盖"大语言模型/大模型/LLM"三个关键词。"""
        assert set(DEFAULT_CRAWLER_CONFIG.keywords) == {"大语言模型", "大模型", "LLM"}

    def test_top_n_is_eight(self) -> None:
        """作业要求排名前 8。"""
        assert DEFAULT_ANALYSIS_CONFIG.top_n == 8

    def test_default_config_values_are_sane(self) -> None:
        """默认参数要合理：重试次数、超时、请求间隔都不能是 0。"""
        assert DEFAULT_CRAWLER_CONFIG.max_retries >= 1
        assert DEFAULT_CRAWLER_CONFIG.timeout > 0
        low, high = DEFAULT_CRAWLER_CONFIG.request_interval
        assert 0 < low <= high, "请求间隔要留出时间，不然容易被限流"
        assert DEFAULT_CRAWLER_CONFIG.max_danmaku_per_video > 0

    def test_config_overrides(self) -> None:
        """支持按需覆盖参数（测试与调试用）。"""
        config = CrawlerConfig(videos_per_keyword=10, max_danmaku_per_video=100)
        assert config.videos_per_keyword == 10
        assert config.max_danmaku_per_video == 100
        assert AnalysisConfig(top_n=5).top_n == 5

    def test_ensure_directories_is_idempotent(self) -> None:
        """重复调用不应报错。"""
        ensure_directories()
        ensure_directories()

    def test_chinese_font_detection_returns_path_or_none(self) -> None:
        """字体探测要么返回存在的文件路径，要么返回 None。"""
        font = detect_chinese_font()
        assert font is None or Path(font).exists()


class TestUtils:
    """通用工具函数。"""

    def test_normalize_text_strips_invisible_and_spaces(self) -> None:
        assert normalize_text("  大\u200b模型  ") == "大模型"
        assert normalize_text("") == ""

    def test_write_and_read_json_roundtrip(self, tmp_path: Path) -> None:
        """JSON 读写应保持中文不被转义。"""
        target = tmp_path / "data" / "sample.json"
        write_json(target, {"名称": "大模型", "数量": 3})
        assert read_json(target) == {"名称": "大模型", "数量": 3}
        assert "大模型" in target.read_text(encoding="utf-8")

    def test_read_json_returns_default_for_broken_file(self, tmp_path: Path) -> None:
        """异常处理：文件损坏时返回默认值而不是抛异常。"""
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert read_json(broken, default=[]) == []
        assert read_json(tmp_path / "missing.json", default=None) is None

    def test_get_logger_configures_root_logger(self) -> None:
        """回归测试：任意模块的 logger 都应能输出 INFO 级日志。

        早期实现只给"第一个被创建的 logger"挂 handler，导致其他模块的
        INFO 日志被静默丢弃（日志文件几乎为空），排查问题时极易误判。
        """
        import logging

        from src.utils import get_logger

        get_logger("tests.some.module")
        root = logging.getLogger()
        assert any(isinstance(handler, logging.FileHandler) for handler in root.handlers)
        assert logging.getLogger("src.anything").getEffectiveLevel() <= logging.INFO


class TestCachedDanmakuIteration:
    """缓存遍历与字段补全。"""

    def test_bvid_is_recovered_from_filename(self, tmp_path: Path) -> None:
        """回归测试：缓存记录缺少 bvid 时，应从文件名补全。"""
        cache = tmp_path / "BV1TESTONLY.json"
        cache.write_text(
            json.dumps(
                {
                    "bvid": "BV1TESTONLY",
                    "keyword": "大模型",
                    "status": "ok",
                    "danmaku": [{"text": "模型真好用", "time": 1.0}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        records = list(iter_cached_danmaku(tmp_path))
        assert len(records) == 1
        assert records[0]["bvid"] == "BV1TESTONLY"
        assert records[0]["keyword"] == "大模型"

    def test_broken_cache_files_are_skipped(self, tmp_path: Path) -> None:
        """异常处理：损坏的缓存文件应被跳过，不影响其余数据。"""
        (tmp_path / "BV1BAD.json").write_text("{broken", encoding="utf-8")
        (tmp_path / "BV2GOOD.json").write_text(
            json.dumps({"danmaku": [{"text": "有效弹幕"}]}, ensure_ascii=False), encoding="utf-8"
        )
        records = list(iter_cached_danmaku(tmp_path))
        assert len(records) == 1
        assert records[0]["text"] == "有效弹幕"


class TestPipelineStages:
    """流水线阶段编排：清洗落盘 → 统计导出，全部重定向到临时目录。"""

    @staticmethod
    def _redirect_paths(monkeypatch, tmp_path: Path) -> None:
        """把流水线的输入输出文件全部指向临时目录。"""
        monkeypatch.setattr(pipeline, "DANMAKU_CLEAN_FILE", tmp_path / "clean.jsonl")
        monkeypatch.setattr(pipeline, "CLEAN_STATS_FILE", tmp_path / "clean_stats.json")
        monkeypatch.setattr(pipeline, "ANALYSIS_RESULT_FILE", tmp_path / "analysis.json")
        monkeypatch.setattr(pipeline, "VIDEO_INDEX_FILE", tmp_path / "videos.json")
        monkeypatch.setattr(pipeline, "ExcelExporter", lambda: ExcelExporter(tmp_path / "out.xlsx"))

    def test_run_clean_writes_jsonl_and_stats(self, monkeypatch, tmp_path: Path) -> None:
        """清洗阶段应产出 JSONL 明细与统计 JSON。"""
        self._redirect_paths(monkeypatch, tmp_path)
        monkeypatch.setattr(
            pipeline,
            "iter_cached_danmaku",
            lambda *args, **kwargs: [
                {"bvid": "BV1", "uid_hash": "u1", "text": "大模型很好用"},
                {"bvid": "BV1", "uid_hash": "u2", "text": "666"},
            ],
        )
        stats = pipeline.run_clean(force=True)
        assert stats["弹幕总数"] == 2
        assert stats["清洗后保留"] == 1
        assert (tmp_path / "clean.jsonl").read_text(encoding="utf-8").count("\n") == 1

    def test_run_clean_skips_when_result_exists(self, monkeypatch, tmp_path: Path) -> None:
        """幂等性：已有结果时默认跳过重算（除非 force=True）。"""
        self._redirect_paths(monkeypatch, tmp_path)
        (tmp_path / "clean.jsonl").write_text('{"text":"旧数据"}\n', encoding="utf-8")
        (tmp_path / "clean_stats.json").write_text(
            json.dumps({"弹幕总数": 99}, ensure_ascii=False), encoding="utf-8"
        )
        monkeypatch.setattr(
            pipeline, "iter_cached_danmaku",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应重新读取缓存")),
        )
        stats = pipeline.run_clean(force=False)
        assert stats["弹幕总数"] == 99

    def test_run_analyze_produces_result_and_excel(self, monkeypatch, tmp_path: Path) -> None:
        """统计阶段应产出分析结果 JSON 与 Excel，并回填视频元信息。"""
        self._redirect_paths(monkeypatch, tmp_path)
        (tmp_path / "clean.jsonl").write_text(
            "\n".join(
                json.dumps(row, ensure_ascii=False)
                for row in [
                    {"bvid": "BV1", "keyword": "大模型", "text": "ChatGPT 写代码很好用", "time": 1.0},
                    {"bvid": "BV1", "keyword": "大模型", "text": "API 成本太贵了", "time": 2.0},
                ]
            ) + "\n",
            encoding="utf-8",
        )
        (tmp_path / "videos.json").write_text(
            json.dumps([{"bvid": "BV1", "title": "示例", "duration": 100, "view": 5}],
                       ensure_ascii=False),
            encoding="utf-8",
        )
        (tmp_path / "clean_stats.json").write_text(json.dumps({"弹幕总数": 3}), encoding="utf-8")

        result = pipeline.run_analyze()
        assert result.total_danmaku == 2
        assert result.total_videos == 1
        assert result.video_stats[0]["title"] == "示例"
        assert (tmp_path / "analysis.json").exists()
        assert (tmp_path / "out.xlsx").exists()

    def test_run_analyze_raises_without_clean_data(self, monkeypatch, tmp_path: Path) -> None:
        """异常处理：缺少清洗结果时应给出明确的错误提示。"""
        self._redirect_paths(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            pipeline.run_analyze()

    def test_load_analysis_result_raises_when_missing(self, monkeypatch, tmp_path: Path) -> None:
        """异常处理：分析结果缺失时抛 FileNotFoundError。"""
        self._redirect_paths(monkeypatch, tmp_path)
        with pytest.raises(FileNotFoundError):
            pipeline.load_analysis_result()
