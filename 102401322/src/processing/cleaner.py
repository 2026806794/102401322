"""弹幕清洗。

这个文件的职责很单一：把一条原始弹幕变成"能拿去统计的干净文本"，
或者判定它是噪声直接丢掉。统计口径的事不在这里管。

清洗分几步：
    1. 规范化：去掉零宽字符、把连续重复的字压缩（"哈哈哈哈" -> "哈哈"）
    2. 去掉正文里的链接、@某人、[表情] 标签
    3. 判断是不是噪声（查词表 / 匹配正则）
    4. 太短的丢掉
    5. 批量清洗时，同一个用户在同一视频里重复刷屏的只保留一条
"""

import re

from src.processing.noise_lexicon import NOISE_PATTERNS, NOISE_WORDS
from src.utils import normalize_text

# 判断是不是纯噪声之前，先把首尾的标点去掉
_edge_punct = re.compile(r"^[\s\W_]+|[\s\W_]+$", re.UNICODE)
# 同一个字连续出现 3 次以上
_repeat_char = re.compile(r"(.)\1{2,}")
# 整个弹幕就是"哈/嘿/嘻/呵/h"这几种字
_laugh_only = re.compile(r"^[哈嘿嘻呵h]+$", re.IGNORECASE)

# 需要从正文里抹掉的东西（抹掉之后剩下的文字还要继续用）
_strip_inline = [
    re.compile(r"https?://\S+"),                  # 链接
    re.compile(r"@[\w\u4e00-\u9fff\-]{1,20}"),    # @某人
    re.compile(r"\[[^\[\]]{1,12}\]"),             # B站表情，比如 [doge]
]


class CleanStats:
    """清洗过程的统计，用来在报告里说明噪声占比。

    注意 kept 是"最后真正保留下来"的条数（噪声过滤和去重都做完之后的），
    所以有个恒等式：
        总数 = 保留 + 精确命中 + 规则命中 + 太短 + 重复 + 空文本
    """

    def __init__(self, total=0, noise_exact=0, noise_pattern=0, noise_too_short=0,
                 duplicated=0, kept=0, empty_text=0):
        self.total = total
        self.noise_exact = noise_exact          # 命中噪声词表的
        self.noise_pattern = noise_pattern      # 命中正则规则的
        self.noise_too_short = noise_too_short  # 太短的
        self.duplicated = duplicated            # 同一用户刷屏被去掉的
        self.kept = kept
        self.empty_text = empty_text
        # 每类噪声留几条样例，写报告的时候可以举例
        self.samples = {"exact": [], "pattern": [], "short": []}

    def as_dict(self):
        """转成字典，好写进 Excel 和 json。"""
        if self.total:
            noise_ratio = f"{(self.total - self.kept) * 100.0 / self.total:.1f}%"
        else:
            noise_ratio = "0.0%"

        return {
            "弹幕总数": self.total,
            "噪声-精确命中": self.noise_exact,
            "噪声-规则命中": self.noise_pattern,
            "噪声-过短丢弃": self.noise_too_short,
            "重复弹幕": self.duplicated,
            "清洗后保留": self.kept,
            "噪声占比": noise_ratio,
        }


def strip_punctuation(text):
    """去掉首尾的标点和空白，方便和噪声词表比对。"""
    return _edge_punct.sub("", text or "")


def squeeze_repeats(text):
    """把连续重复的字压缩一下："哈哈哈哈" -> "哈哈"。

    这样"哈哈哈哈"和"哈哈哈哈哈"就会归到同一个词，统计更准。
    """
    return _repeat_char.sub(r"\1\1", text)


def remove_inline_noise(text):
    """抹掉正文里的链接、@某人和表情标签。"""
    for pattern in _strip_inline:
        text = pattern.sub("", text)
    return text.strip()


def is_noise(text):
    """判断一条弹幕是不是应该整条丢掉。"""
    stripped = strip_punctuation(text)
    if not stripped:
        return True
    if stripped in NOISE_WORDS:
        return True
    if _laugh_only.match(stripped):
        return True

    for pattern in NOISE_PATTERNS:
        if pattern.search(text):
            return True
    return False


def _remember_sample(bucket, sample, limit=5):
    """记几条噪声样例，最多存 limit 条。"""
    if len(bucket) < limit:
        bucket.append(sample)


class DanmakuCleaner:
    """弹幕清洗器。

    min_length 是最短长度，比这个短的当成噪声（弹幕里单字基本没信息量）。
    dedupe 控制要不要去重。
    """

    def __init__(self, min_length=2, dedupe=True):
        self.min_length = min_length
        self.dedupe = dedupe

    def clean_text(self, text):
        """清洗一条文本，返回清洗后的结果（空字符串表示该丢）。"""
        result = normalize_text(text)
        if not result:
            return ""
        result = remove_inline_noise(result)
        result = squeeze_repeats(result)
        return result.strip()

    def clean_record(self, record, stats=None):
        """清洗一条弹幕记录，返回干净文本或 None。

        record 是一个字典，里面要有 text 字段。
        stats 传进来的话会顺便累加统计。
        """
        raw = record.get("text", "")
        cleaned = self.clean_text(raw)

        if stats is not None:
            stats.total += 1

        if not cleaned:
            if stats is not None:
                stats.empty_text += 1
            return None

        # 去掉首尾标点后再和噪声词表比对
        stripped = strip_punctuation(cleaned)

        if stripped in NOISE_WORDS or _laugh_only.match(stripped):
            if stats is not None:
                stats.noise_exact += 1
                _remember_sample(stats.samples["exact"], raw)
            return None

        for pattern in NOISE_PATTERNS:
            if pattern.search(cleaned):
                if stats is not None:
                    stats.noise_pattern += 1
                    _remember_sample(stats.samples["pattern"], raw)
                return None

        if len(stripped) < self.min_length:
            if stats is not None:
                stats.noise_too_short += 1
                _remember_sample(stats.samples["short"], raw)
            return None

        return cleaned

    def clean_batch(self, records):
        """批量清洗，返回 (保留下来的记录列表, 统计对象)。

        去重的规则是"同一个视频 + 同一个用户 + 同一句话"。
        这里我纠结过：一开始是按"视频 + 文本"去重的，后来发现不对——
        同一个视频里"打开中文字幕"这句话出现了 1476 次，如果按"视频 + 文本"去重，
        就只剩 1 条了。但这 1476 条是 1476 个不同用户在说同一句话，
        这本身就是"很多人都这么想"的信号，不能删。

        实测按"视频 + 文本"会多删 13469 条，加上用户哈希之后只有 2085 条
        （同一用户自己刷屏的），差别很大。
        """
        stats = CleanStats()
        kept = []
        seen = set()

        for record in records:
            cleaned = self.clean_record(record, stats)
            if cleaned is None:
                continue

            if self.dedupe:
                key = (str(record.get("bvid", "")),
                       str(record.get("uid_hash", "")),
                       cleaned)
                if key in seen:
                    stats.duplicated += 1
                    continue
                seen.add(key)

            stats.kept += 1
            item = dict(record)
            item["text"] = cleaned
            kept.append(item)

        return kept, stats
