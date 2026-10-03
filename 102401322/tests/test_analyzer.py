"""统计分析测试。

重点测三块：排名排序对不对、进度分桶的边界、以及空数据会不会报错。
分桶那块边界情况比较多（0%、刚好 50%、99.9%、超过时长），单独列了一组用例。
"""

from __future__ import annotations

from src.analysis.analyzer import DanmakuAnalyzer, progress_bucket, rank_items
from src.config import AnalysisConfig


class _StubSegmenter:
    """轻量分词替身：按空格切分，避免测试依赖 jieba 词典。"""

    min_length = 2

    def segment(self, text: str) -> list[str]:
        return [token for token in text.split() if len(token) >= 2]

    def top_words(self, counter, top_n: int = 8):
        return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:top_n]


def _make_analyzer(records: list[dict], videos: list[dict] | None = None) -> DanmakuAnalyzer:
    return DanmakuAnalyzer(
        records,
        videos or [],
        AnalysisConfig(top_n=8, min_word_length=2),
        segmenter=_StubSegmenter(),
    )


class TestRankingHelper:
    """排名工具函数。"""

    def test_ranking_sorts_by_count_then_name(self) -> None:
        from collections import Counter

        ranked = rank_items(Counter({"b": 5, "a": 5, "c": 9}))
        assert [item["name"] for item in ranked] == ["c", "a", "b"]
        assert [item["rank"] for item in ranked] == [1, 2, 3]

    def test_ranking_ratio_sums_to_one(self) -> None:
        from collections import Counter

        ranked = rank_items(Counter({"甲": 3, "乙": 1}))
        assert abs(sum(item["ratio"] for item in ranked) - 1.0) < 1e-9

    def test_ranking_respects_top_n(self) -> None:
        from collections import Counter

        ranked = rank_items(Counter({str(i): i + 1 for i in range(20)}), top_n=8)
        assert len(ranked) == 8


class TestProgressBucket:
    """弹幕进度分桶的边界值分析。"""

    def test_boundary_values(self) -> None:
        """0% 落在第 1 桶，99.9% 落在最后一桶，正好 50% 落在第 6 桶。"""
        assert progress_bucket(0, 100) == "0-10%"
        assert progress_bucket(9.9, 100) == "0-10%"
        assert progress_bucket(50, 100) == "50-60%"
        assert progress_bucket(99.9, 100) == "90-100%"

    def test_zero_or_missing_duration_falls_back_to_first_bucket(self) -> None:
        """边界值：时长缺失或为 0 时归入第一桶，不应除零。"""
        assert progress_bucket(123.0, 0) == "0-10%"
        assert progress_bucket(123.0, -5) == "0-10%"

    def test_out_of_range_time_is_clamped(self) -> None:
        """时间超出视频时长时钳制到最后一桶。"""
        assert progress_bucket(9999, 100) == "90-100%"


class TestAnalyzer:
    """统计主流程。"""

    def test_category_counts_are_multi_label(self, analyzer_records: list[dict]) -> None:
        """一条弹幕可同时归入多个领域，各类数量应正确累加。"""
        result = _make_analyzer(analyzer_records).analyze()
        categories = {item["name"]: item["count"] for item in result.category_stats}
        assert categories.get("编程开发", 0) >= 2
        assert categories.get("科研学术", 0) >= 1

    def test_case_ranking_limited_to_top_n(self, analyzer_records: list[dict]) -> None:
        """具体应用案例排名不应超过 Top-N，且按提及弹幕数降序。"""
        result = _make_analyzer(analyzer_records).analyze()
        assert 1 <= len(result.case_ranking) <= 8
        counts = [item["count"] for item in result.case_ranking]
        assert counts == sorted(counts, reverse=True)
        names = {item["name"] for item in result.case_ranking}
        assert {"ChatGPT", "DeepSeek", "豆包"} & names

    def test_sentiment_cost_risk_are_counted(self, analyzer_records: list[dict]) -> None:
        """态度 / 成本 / 风险三类词典都应命中并统计。"""
        result = _make_analyzer(analyzer_records).analyze()
        assert {item["name"] for item in result.sentiment}
        assert {item["name"] for item in result.cost}
        assert {item["name"] for item in result.risk}
        risk_names = {item["name"] for item in result.risk}
        assert "取代工作" in risk_names or "内容真实性" in risk_names

    def test_top_words_are_limited(self, analyzer_records: list[dict]) -> None:
        """整体 Top-N 词频长度不超过配置的 top_n。"""
        result = _make_analyzer(analyzer_records).analyze()
        assert 0 < len(result.top_words) <= 8
        counts = [item["count"] for item in result.top_words]
        assert counts == sorted(counts, reverse=True)

    def test_video_and_keyword_statistics(self, analyzer_records: list[dict],
                                          fake_videos: list[dict]) -> None:
        """视频与关键词维度统计应覆盖全部输入。"""
        result = _make_analyzer(analyzer_records, fake_videos).analyze()
        assert result.total_videos == 3
        assert sum(item["count"] for item in result.keyword_stats) == len(analyzer_records)
        assert result.video_stats[0]["danmaku_clean"] >= result.video_stats[-1]["danmaku_clean"]

    def test_progress_distribution_uses_video_duration(self, fake_videos: list[dict]) -> None:
        """进度分布应基于各视频时长做归一化，而不是绝对秒数。"""
        records = [
            {"bvid": "BV1", "uid_hash": "x", "keyword": "k", "text": "模型", "time": 5},     # 5/100
            {"bvid": "BV2", "uid_hash": "y", "keyword": "k", "text": "模型", "time": 190},   # 190/200
        ]
        result = _make_analyzer(records, fake_videos).analyze()
        buckets = {item["bucket"]: item["count"] for item in result.progress_distribution}
        assert buckets["0-10%"] == 1
        assert buckets["90-100%"] == 1

    def test_progress_distribution_excludes_truncated_videos(self) -> None:
        """弹幕池被截断的视频不纳入进度分布，否则第一桶会出现假尖峰。"""
        videos = [
            {"bvid": "FULL", "duration": 100, "danmaku_total": 100, "fetched": 100},
            {"bvid": "TRUNC", "duration": 10000, "danmaku_total": 10000, "fetched": 200},
        ]
        records = [
            {"bvid": "FULL", "uid_hash": "a", "keyword": "k", "text": "模型", "time": 95},
            {"bvid": "TRUNC", "uid_hash": "b", "keyword": "k", "text": "模型", "time": 10},
        ]
        result = _make_analyzer(records, videos).analyze()
        buckets = {item["bucket"]: item["count"] for item in result.progress_distribution}
        assert buckets["90-100%"] == 1, "抓全的视频应计入"
        assert buckets["0-10%"] == 0, "被截断的视频不应计入"

    def test_empty_input_is_handled(self) -> None:
        """健壮性：空数据集应产出空结果而不是抛异常。"""
        result = _make_analyzer([]).analyze()
        assert result.total_danmaku == 0
        assert result.total_videos == 0
        assert result.category_stats == []
        assert result.case_ranking == []

    def test_records_without_text_are_skipped(self) -> None:
        """text 是空字符串的记录不应该影响统计。"""
        records = [{"bvid": "BV1", "uid_hash": "x", "keyword": "k", "text": ""},
                   {"bvid": "BV1", "uid_hash": "y", "keyword": "k", "text": "大模型"}]
        result = _make_analyzer(records).analyze()
        assert result.total_danmaku == 2

    def test_result_is_serializable(self, analyzer_records: list[dict]) -> None:
        """结果对象必须可直接序列化为 JSON（可视化层的数据契约）。"""
        import json

        payload = _make_analyzer(analyzer_records).analyze().to_dict()
        text = json.dumps(payload, ensure_ascii=False)
        assert "case_ranking" in text
        assert json.loads(text)["total_danmaku"] == len(analyzer_records)
