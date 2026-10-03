"""Aho-Corasick 匹配测试。

AC 自动机最容易写错的地方是失败指针，光靠几个功能用例不一定能发现。
所以除了基本功能，还专门加了一组"和朴素写法结果完全一致"的对比测试：
同一批语料、同一套模式，两种实现跑出来的计数必须一模一样。
"""

from __future__ import annotations

import random

from src.analysis.matcher import AhoCorasick, naive_match_count
from src.analysis.lexicon import DOMAIN_LEXICON, PRODUCT_LEXICON, iter_patterns


def _build(lexicon: dict[str, tuple[str, ...]]) -> AhoCorasick:
    return AhoCorasick((alias, name) for name, aliases in lexicon.items() for alias in aliases)


class TestAhoCorasickBasics:
    """基础功能：命中、去重、空文本、重叠模式。"""

    def test_find_labels_returns_all_matches(self) -> None:
        """一条文本命中多个模式时，应返回全部标签。"""
        ac = AhoCorasick([("大模型", "模型"), ("ChatGPT", "产品"), ("写代码", "编程")])
        labels = ac.find_labels("用 ChatGPT 大模型写代码")
        assert labels == {"模型", "产品", "编程"}

    def test_find_labels_deduplicates_within_text(self) -> None:
        """同一标签在一条文本中重复命中只应返回一次。"""
        ac = AhoCorasick([("代码", "编程"), ("写代码", "编程")])
        assert ac.find_labels("写代码和代码") == {"编程"}

    def test_empty_text_returns_no_labels(self) -> None:
        """边界值：空文本不应命中任何模式。"""
        ac = AhoCorasick([("大模型", "模型")])
        assert ac.find_labels("") == set()

    def test_overlapping_patterns_are_all_found(self) -> None:
        """重叠模式（"大模型" 与 "模型"）应同时命中。"""
        ac = AhoCorasick([("大模型", "长"), ("模型", "短")])
        assert ac.find_labels("大模型很强") == {"长", "短"}

    def test_same_alias_can_map_to_multiple_labels(self) -> None:
        """同一别名归属多个类别时，标签应全部保留。"""
        ac = AhoCorasick([("算力", "硬件成本"), ("算力", "硬件算力")])
        assert ac.find_labels("算力不够") == {"硬件成本", "硬件算力"}

    def test_count_occurrences_accumulates_repeats(self) -> None:
        """count_occurrences 统计总出现次数，count_labels 统计文本条数。"""
        ac = AhoCorasick([("模型", "模型")])
        texts = ["模型模型", "一个模型"]
        assert ac.count_occurrences(texts)["模型"] == 3
        assert ac.count_labels(texts)["模型"] == 2

    def test_automaton_metrics_are_reported(self) -> None:
        """节点数与模式数应可查询，供性能报告使用。"""
        ac = AhoCorasick([("abc", "a"), ("abd", "b")])
        assert len(ac) == 2
        assert ac.node_count >= 4          # 根 + a + b + c + d


class TestAhoCorasickEquivalence:
    """等价性测试：与朴素实现在同一语料上结果必须完全一致。"""

    def test_matches_naive_on_domain_lexicon(self) -> None:
        """领域词典 + 构造语料下，AC 与朴素实现的计数应逐项相等。"""
        patterns = list(iter_patterns({"domain": DOMAIN_LEXICON}))
        ac = AhoCorasick(patterns)
        corpus = [
            "用大模型写代码效率很高",
            "显卡太贵了，本地部署成本高",
            "帮学生写作业和论文",
            "翻译和旅游攻略都能做",
            "智能体工作流自动化办公",
            "完全无关的一句话",
        ]
        assert ac.count_labels(corpus) == naive_match_count(corpus, patterns)

    def test_matches_naive_on_random_corpus(self) -> None:
        """随机语料上的等价性测试，覆盖失败指针跳转的各种分支。"""
        patterns = list(iter_patterns({"product": PRODUCT_LEXICON, "domain": DOMAIN_LEXICON}))
        ac = AhoCorasick(patterns)
        naive = naive_match_count  # 便于断言时对照

        alphabet = "大模型chatgpt代码画图算力成本失业幻觉显卡论文豆包翻译"
        rng = random.Random(20251003)
        corpus = [
            "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
            for _ in range(300)
        ]
        assert ac.count_labels(corpus) == naive(corpus, patterns)

    def test_no_false_positive_on_unrelated_text(self) -> None:
        """无关文本不应产生任何命中（防止失败指针回退到错误的输出节点）。"""
        ac = _build(PRODUCT_LEXICON)
        assert ac.find_labels("今天天气不错适合出门散步") == set()
