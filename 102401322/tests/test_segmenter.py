"""分词器单元测试：停用词过滤、领域词典、英文归一化与排序稳定性。"""

from __future__ import annotations

import pytest

from src.processing.segmenter import Segmenter


@pytest.fixture(scope="module")
def segmenter() -> Segmenter:
    """模块级共享分词器（jieba 初始化较慢，避免重复加载）。"""
    return Segmenter(min_length=2)


class TestSegmenter:
    """分词与过滤行为。"""

    def test_domain_terms_are_not_split(self, segmenter: Segmenter) -> None:
        """领域词典生效："大语言模型" 必须是一个完整 token。"""
        tokens = segmenter.segment("大语言模型的应用场景")
        assert "大语言模型" in tokens

    def test_stopwords_are_filtered(self, segmenter: Segmenter) -> None:
        """虚词与灌水词应被剔除。"""
        tokens = segmenter.segment("这个 视频 真的 太 好用 了 哈哈哈")
        assert "这个" not in tokens
        assert "视频" not in tokens
        assert "真的" not in tokens
        assert "哈哈哈" not in tokens

    def test_single_characters_are_filtered(self, segmenter: Segmenter) -> None:
        """边界值：单字 token 低于 min_length，应被过滤。"""
        assert segmenter.is_meaningful("好") is False
        assert segmenter.is_meaningful("模型") is True

    def test_english_tokens_are_lowercased(self, segmenter: Segmenter) -> None:
        """英文 token 统一小写，避免 GPT/gpt 重复计数。"""
        tokens = segmenter.segment("GPT 和 gpt 是同一个东西")
        assert tokens.count("gpt") == 2
        assert "GPT" not in tokens

    def test_meaningless_tokens_rejected(self, segmenter: Segmenter) -> None:
        """纯数字/符号 token 不应进入统计。"""
        assert segmenter.is_meaningful("12345") is False
        assert segmenter.is_meaningful("!!!") is False

    def test_count_words_and_top_words(self, segmenter: Segmenter) -> None:
        """词频统计与 Top-N 排序：次数降序，同次数按词语升序。"""
        counter = segmenter.count_words(["模型 模型 编程", "模型 编程", "编程"])
        top = segmenter.top_words(counter, top_n=2)
        assert top[0][0] == "模型" and top[0][1] == 3
        assert top[1][0] == "编程" and top[1][1] == 3

    def test_top_words_stable_tie_break(self, segmenter: Segmenter) -> None:
        """并列次数时按词语字典序升序，保证多次运行结果一致。"""
        counter = segmenter.count_words(["乙甲 乙甲", "甲乙 甲乙"])
        top = segmenter.top_words(counter, top_n=2)
        assert [word for word, _ in top] == sorted(word for word, _ in top)

    def test_empty_text_returns_empty_list(self, segmenter: Segmenter) -> None:
        """边界值：空文本返回空列表。"""
        assert segmenter.segment("") == []

    def test_count_words_in_records(self, segmenter: Segmenter) -> None:
        """可直接对弹幕记录列表统计词频。"""
        records = [{"text": "模型 模型"}, {"text": "模型"}]
        counter = segmenter.count_words_in_records(records)
        assert counter["模型"] == 3
