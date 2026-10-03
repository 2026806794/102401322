"""弹幕清洗测试。

输入按等价类分成几组：正常弹幕、命中噪声词表的、命中正则的、太短的、重复刷屏的。
边界值单独测了两个地方：重复字符刚好 3 次（不算噪声）和 4 次（算噪声）。
"""

from __future__ import annotations

import pytest

from src.processing.cleaner import (
    CleanStats,
    DanmakuCleaner,
    is_noise,
    remove_inline_noise,
    squeeze_repeats,
    strip_punctuation,
)


class TestNoiseDetection:
    """噪声识别：验证词表、正则与叠字三类规则。"""

    @pytest.mark.parametrize(
        "text",
        ["666", "6666", "前排", "打卡", "哈哈哈哈", "awsl", "求资料", "已三连求资料",
         "三连", "点赞", "白嫖", "下次一定"],
    )
    def test_exact_noise_words_are_detected(self, text: str) -> None:
        """词表中的灌水弹幕应被判定为噪声。"""
        assert is_noise(text) is True

    @pytest.mark.parametrize(
        "text",
        ["12345", "!!!???", "@张三 你看", "https://b23.tv/abc", "😀😀😀", "啊啊啊啊啊"],
    )
    def test_regex_noise_patterns_are_detected(self, text: str) -> None:
        """纯数字、纯符号、@提及、链接、纯表情、单字刷屏应被判定为噪声。"""
        assert is_noise(text) is True

    @pytest.mark.parametrize(
        "text",
        ["大模型写代码效率很高", "DeepSeek 的推理能力不错", "这个模型有幻觉"],
    )
    def test_meaningful_text_is_not_noise(self, text: str) -> None:
        """包含真实观点的弹幕不能被误杀。"""
        assert is_noise(text) is False

    def test_boundary_repeated_char_three_vs_four(self) -> None:
        """边界值：单字符重复 3 次不算刷屏，4 次算。"""
        assert is_noise("好好好") is False
        assert is_noise("好好好好") is True


class TestTextNormalization:
    """文本规范化：叠字压缩、标点剥离、内联噪声抹除。"""

    def test_squeeze_repeats_compresses_long_runs(self) -> None:
        """连续重复字符应压缩为两个。"""
        assert squeeze_repeats("哈哈哈哈") == "哈哈"
        assert squeeze_repeats("好好好好好") == "好好"
        assert squeeze_repeats("正常文本") == "正常文本"

    def test_strip_punctuation_removes_edges_only(self) -> None:
        """只剥离首尾标点，中间标点保留。"""
        assert strip_punctuation("。。。666！！！") == "666"
        assert strip_punctuation("讲得很好，赞") == "讲得很好，赞"

    def test_remove_inline_noise_strips_mentions_and_urls(self) -> None:
        """@提及、链接、表情标签应被抹掉，其余文字保留。"""
        cleaned = remove_inline_noise("@小明 大模型真好用 https://b23.tv/x [doge]")
        assert "@小明" not in cleaned
        assert "http" not in cleaned
        assert "doge" not in cleaned
        assert "大模型真好用" in cleaned


class TestCleaner:
    """清洗器主流程：单条清洗、批量清洗与统计口径。"""

    def test_clean_text_removes_zero_width_characters(self) -> None:
        """零宽字符必须被清除（B 站弹幕常见的绕过检测手段）。"""
        cleaner = DanmakuCleaner()
        assert cleaner.clean_text("太\u200b厉\u200b害了") == "太厉害了"

    def test_clean_record_returns_none_for_noise(self) -> None:
        """噪声弹幕清洗后应返回 None。"""
        cleaner = DanmakuCleaner()
        assert cleaner.clean_record({"text": "666"}) is None
        assert cleaner.clean_record({"text": "哈哈哈哈"}) is None

    def test_clean_record_keeps_meaningful_text(self) -> None:
        """有效弹幕应原样（规范化后）返回。"""
        cleaner = DanmakuCleaner()
        assert cleaner.clean_record({"text": "  大模型  很好用 "}) == "大模型 很好用"

    def test_clean_batch_dedupes_only_same_user(self, sample_records: list[dict]) -> None:
        """同一用户重复刷屏去重，不同用户的相同观点保留。"""
        cleaner = DanmakuCleaner(min_length=2, dedupe=True)
        kept, stats = cleaner.clean_batch(sample_records)

        same_text = [row for row in kept if row["text"] == "讲得很清楚"]
        assert len(same_text) == 2, "同一用户刷屏应只保留 1 条，不同用户的 1 条保留"
        assert stats.duplicated == 1

    def test_clean_batch_statistics_are_consistent(self, sample_records: list[dict]) -> None:
        """统计口径自洽：总数 = 保留 + 各类噪声 + 重复。"""
        cleaner = DanmakuCleaner(min_length=2)
        kept, stats = cleaner.clean_batch(sample_records)

        dropped = (stats.noise_exact + stats.noise_pattern + stats.noise_too_short
                   + stats.duplicated + stats.empty_text)
        assert stats.total == len(sample_records)
        assert stats.total == len(kept) + dropped
        assert stats.kept == len(kept)
        assert 0.0 <= (stats.total - stats.kept) / stats.total <= 1.0

    def test_clean_stats_dict_has_expected_keys(self) -> None:
        """统计字典应包含报告所需字段，且噪声占比为百分比字符串。"""
        stats = CleanStats(total=100, kept=90)
        payload = stats.as_dict()
        assert payload["弹幕总数"] == 100
        assert payload["清洗后保留"] == 90
        assert payload["噪声占比"].endswith("%")
