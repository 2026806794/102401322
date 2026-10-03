"""中文分词。

直接用 jieba 分词在弹幕上效果不好，主要有两个问题：

    1. 领域词会被切碎，比如"大语言模型"变成"大/语言/模型"；
    2. 弹幕里口语和灌水词太多，"哈哈哈""前排"这些分词出来会占满词频榜。

所以这个文件做了三件事：
    1. 加载自定义词典（noise_lexicon 里的 JIEBA_USER_WORDS）；
    2. 分词后按停用词表过滤；
    3. 过滤单字、纯数字、纯符号这些没信息量的 token。

另外加了一个分词结果缓存。这是用 cProfile 分析之后加的：
统计接口 68% 的时间都花在分词上，而弹幕里有不少重复的句子，
缓存一下能省点时间（实测命中率 26.8%）。
"""

import logging
import re

import jieba

from src.processing.noise_lexicon import JIEBA_USER_WORDS, STOPWORDS
from src.utils import get_logger

log = get_logger(__name__)

# 全是数字/字母/符号的 token 没意义
_meaningless = re.compile(r"^[\d\W_]+$")
# 有没有中文
_has_chinese = re.compile(r"[\u4e00-\u9fff]")


class Segmenter:
    """jieba 分词的封装。

    min_length：token 最短长度，默认 2（单字多是虚词）
    use_stopwords：要不要用停用词过滤
    cache_size：分词缓存最多存多少条，0 表示不用缓存
    """

    def __init__(self, min_length=2, use_stopwords=True, cache_size=50000):
        self.min_length = min_length
        self.use_stopwords = use_stopwords
        if use_stopwords:
            self.stopwords = STOPWORDS
        else:
            self.stopwords = set()
        self.cache_size = cache_size
        self.cache = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self._initialized = False

    def _ensure_initialized(self):
        """加载词典。第一次分词时才做，因为 jieba 加载词典要 0.3 秒左右。

        一开始我是在模块 import 的时候就初始化，结果只要 import 了这个模块
        就得等它加载完，哪怕根本不用分词。
        """
        if self._initialized:
            return

        logging.getLogger("jieba").setLevel(logging.WARNING)
        for word in JIEBA_USER_WORDS:
            jieba.add_word(word, freq=2000)
        jieba.initialize()

        self._initialized = True
        log.info("jieba 词典加载完成：自定义词 %d 个，停用词 %d 个",
                 len(JIEBA_USER_WORDS), len(self.stopwords))

    def is_meaningful(self, token):
        """判断一个 token 值不值得统计。"""
        token = token.strip()
        if len(token) < self.min_length:
            return False
        if token in self.stopwords:
            return False
        if _meaningless.match(token):
            return False
        return True

    def segment(self, text):
        """把一条文本切成词，返回过滤后的列表。

        注意：如果命中了缓存，返回的是缓存里那个列表本身。
        调用方只读不改就行（统计的时候都是 counter.update(tokens)，不会改）。
        """
        if not text:
            return []

        cached = self.cache.get(text)
        if cached is not None:
            self.cache_hits += 1
            return cached

        self.cache_misses += 1
        self._ensure_initialized()

        tokens = []
        for token in jieba.lcut(text, cut_all=False):
            if self.is_meaningful(token):
                tokens.append(self._normalize_token(token))

        if self.cache_size and len(self.cache) < self.cache_size:
            self.cache[text] = tokens
        return tokens

    @staticmethod
    def _normalize_token(token):
        """英文统一转小写，这样 GPT 和 gpt 不会各算一份。"""
        token = token.strip()
        if _has_chinese.search(token):
            return token
        return token.lower()

    def count_words(self, texts):
        """统计词频，返回 {词: 次数}。"""
        counter = {}
        for text in texts:
            for token in self.segment(text):
                counter[token] = counter.get(token, 0) + 1
        return counter

    def count_words_in_records(self, records):
        """直接对弹幕记录列表统计词频。"""
        return self.count_words([r.get("text", "") for r in records])

    def top_words(self, counter, top_n=8):
        """取词频前 N 个。

        排序规则是次数从多到少，次数一样就按词的字典序，
        这样保证每次跑出来的结果顺序都一样。
        """
        items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return items[:top_n]

    @property
    def cache_hit_rate(self):
        """缓存命中率，写性能报告的时候要用。"""
        total = self.cache_hits + self.cache_misses
        if not total:
            return 0.0
        return self.cache_hits * 1.0 / total
