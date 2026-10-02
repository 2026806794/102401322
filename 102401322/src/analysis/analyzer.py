"""统计分析。

把清洗后的弹幕变成能写进 Excel、能画图的数字。统计口径有这几项：

    1. 每类弹幕的总数量 —— 按应用领域给弹幕打标签（一条弹幕可以属于多个领域）
    2. Top-N 弹幕词频   —— 整体和分领域都要
    3. Top-N 具体案例   —— 哪个大模型产品被提到得最多
    4. 态度 / 成本 / 风险 —— 作业 2.4 要求归纳的三类主流看法

实现上注意两点：
    * 领域、产品、态度这些标签全部交给 Aho-Corasick 一次扫完，不用逐个别名去 in 判断；
    * 一条弹幕只分一次词，分出来的词同时喂给"整体词频"和"各领域词频"两个计数器，
      不然同一批数据要分词两遍，白浪费一半时间。
"""

from src.analysis.lexicon import (
    COST_LEXICON,
    DOMAIN_LEXICON,
    PRODUCT_LEXICON,
    RISK_LEXICON,
    SENTIMENT_LEXICON,
)
from src.analysis.matcher import AhoCorasick
from src.config import DEFAULT_ANALYSIS_CONFIG, STUDENT_ID
from src.processing.segmenter import Segmenter
from src.utils import get_logger

log = get_logger(__name__)

# 弹幕进度分成 10 个桶
PROGRESS_BUCKETS = ["0-10%", "10-20%", "20-30%", "30-40%", "40-50%",
                    "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]


def build_automaton(lexicon):
    """把一个词典变成 AC 自动机，标签用标准名。"""
    patterns = []
    for canonical, aliases in lexicon.items():
        for alias in aliases:
            patterns.append((alias, canonical))
    return AhoCorasick(patterns)


def rank_items(counter, top_n=None):
    """把 {名称: 次数} 排成带名次的列表。

    排序规则：次数从多到少，次数相同的按名称排，保证每次跑出来顺序都一样。
    """
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    if top_n is not None:
        items = items[:top_n]

    total = sum(counter.values())
    if total == 0:
        total = 1

    result = []
    for index, (name, count) in enumerate(items, start=1):
        result.append({
            "rank": index,
            "name": name,
            "count": count,
            "ratio": round(count * 1.0 / total, 4),
        })
    return result


def progress_bucket(time_seconds, duration):
    """把弹幕的出现时间换算成"视频进度的第几桶"。

    这里必须按时长归一化。不归一化的话，一个 15 小时的课程视频
    弹幕数会碾压一个 1 分钟的视频，图表就失真了。
    """
    if not duration or duration <= 0:
        return PROGRESS_BUCKETS[0]

    ratio = float(time_seconds) / float(duration)
    ratio = max(0.0, min(ratio, 0.999))
    return PROGRESS_BUCKETS[int(ratio * 10)]


class AnalysisResult:
    """一次分析的全部结果。

    做成一个类是为了方便整体转成 json 存起来，可视化那边直接读这个 json，
    不用重新算一遍。
    """

    def __init__(self):
        self.meta = {}
        self.clean_stats = {}
        self.total_danmaku = 0
        self.total_videos = 0
        self.total_words = 0
        self.category_stats = []            # 每类弹幕的总数量
        self.top_words = []                 # 整体 Top-8 词频
        self.top_words_by_category = {}     # 分领域词频
        self.case_ranking = []              # Top-8 具体案例
        self.sentiment = []                 # 态度分布
        self.cost = []                      # 成本关注点
        self.risk = []                      # 风险关注点
        self.keyword_stats = []             # 各关键词的弹幕量
        self.video_stats = []               # 视频清单
        self.progress_distribution = []     # 弹幕随进度的分布
        self.word_freq = []                 # 完整词频（画词云用）
        self.top_words_by_aspect = {}       # 分维度词频（画"担忧"词云用）

    def to_dict(self):
        return dict(self.__dict__)


class DanmakuAnalyzer:
    """弹幕统计器。

    records 是清洗后的弹幕列表，videos 是视频清单（可以不给，
    不给的话视频相关的统计会缺标题、播放量这些信息）。
    segmenter 可以传一个自己的分词器进去，测试的时候用。
    """

    def __init__(self, records, videos=None, config=None, segmenter=None):
        self.records = list(records)
        self.videos = list(videos or [])
        self.config = config or DEFAULT_ANALYSIS_CONFIG
        if segmenter is not None:
            self.segmenter = segmenter
        else:
            self.segmenter = Segmenter(min_length=self.config.min_word_length)

        # 五类词典各建一个自动机
        self.product_ac = build_automaton(PRODUCT_LEXICON)
        self.domain_ac = build_automaton(DOMAIN_LEXICON)
        self.sentiment_ac = build_automaton(SENTIMENT_LEXICON)
        self.cost_ac = build_automaton(COST_LEXICON)
        self.risk_ac = build_automaton(RISK_LEXICON)

    def analyze(self, clean_stats=None):
        """跑完整套统计，返回 AnalysisResult。"""
        result = AnalysisResult()
        result.meta = {
            "student_id": STUDENT_ID,
            "total_records": len(self.records),
            "top_n": self.config.top_n,
        }
        result.clean_stats = clean_stats or {}
        result.total_danmaku = len(self.records)

        video_set = set()
        for record in self.records:
            if record.get("bvid"):
                video_set.add(record["bvid"])
        result.total_videos = len(video_set)

        log.info("开始统计：%d 条弹幕 / %d 个视频", result.total_danmaku, result.total_videos)

        # 每个视频的时长，算进度分布要用
        durations = {}
        for video in self.videos:
            durations[video.get("bvid")] = video.get("duration", 0)

        # 只有弹幕池抓全了的视频才算进度分布，原因见下面那个函数
        covered_videos = self._fully_covered_videos()

        # 下面这一大段就是一次遍历，所有统计都在里面累加
        domain_counter = {}
        product_counter = {}
        sentiment_counter = {}
        cost_counter = {}
        risk_counter = {}
        keyword_counter = {}
        video_counter = {}
        progress_counter = {}
        word_counter = {}
        words_by_domain = {}
        words_by_aspect = {}

        for record in self.records:
            text = record.get("text", "")
            if not text:
                continue

            # 1) 领域标签（一条弹幕可能有多个）
            domains = self.domain_ac.find_labels(text)
            for domain in domains:
                domain_counter[domain] = domain_counter.get(domain, 0) + 1

            # 2) 其他四类标签
            self._add_counts(product_counter, self.product_ac.find_labels(text))
            sentiments = self.sentiment_ac.find_labels(text)
            costs = self.cost_ac.find_labels(text)
            risks = self.risk_ac.find_labels(text)
            self._add_counts(sentiment_counter, sentiments)
            self._add_counts(cost_counter, costs)
            self._add_counts(risk_counter, risks)

            # 3) 关键词、视频、进度
            keyword = record.get("keyword") or "未标注"
            keyword_counter[keyword] = keyword_counter.get(keyword, 0) + 1

            bvid = record.get("bvid") or "未知"
            video_counter[bvid] = video_counter.get(bvid, 0) + 1

            if bvid in covered_videos:
                bucket = progress_bucket(record.get("time", 0), durations.get(bvid, 0))
                progress_counter[bucket] = progress_counter.get(bucket, 0) + 1

            # 4) 分词。只分一次，然后同时喂给整体词频和各个领域的词频
            tokens = self.segmenter.segment(text)
            for token in tokens:
                word_counter[token] = word_counter.get(token, 0) + 1

            for domain in domains:
                if domain not in words_by_domain:
                    words_by_domain[domain] = {}
                counter = words_by_domain[domain]
                for token in tokens:
                    counter[token] = counter.get(token, 0) + 1

            # 成本/风险/态度这几个维度的词频，用来画"担忧"主题的词云
            for label in costs:
                self._add_tokens(words_by_aspect, "成本-" + label, tokens)
            for label in risks:
                self._add_tokens(words_by_aspect, "风险-" + label, tokens)
            for label in sentiments:
                self._add_tokens(words_by_aspect, "态度-" + label, tokens)

        # ---------------- 汇总成结果 ----------------
        result.total_words = sum(word_counter.values())
        result.category_stats = rank_items(domain_counter)
        result.case_ranking = rank_items(product_counter, self.config.top_n)
        result.sentiment = rank_items(sentiment_counter)
        result.cost = rank_items(cost_counter)
        result.risk = rank_items(risk_counter)
        result.keyword_stats = rank_items(keyword_counter)

        result.top_words = []
        for index, (word, count) in enumerate(
                self.segmenter.top_words(word_counter, self.config.top_n), start=1):
            result.top_words.append({"rank": index, "word": word, "count": count})

        result.word_freq = []
        sorted_words = sorted(word_counter.items(), key=lambda kv: (-kv[1], kv[0]))
        for word, count in sorted_words[:500]:
            result.word_freq.append({"word": word, "count": count})

        # 分领域词频。这里刻意多存一些词（60 个），因为分领域词云需要足够的词量；
        # 写进 Excel 的表格会再截取前 8 个
        domain_order = sorted(words_by_domain.keys(),
                              key=lambda d: -domain_counter.get(d, 0))
        for domain in domain_order:
            words = []
            top = self.segmenter.top_words(words_by_domain[domain],
                                           self.config.category_word_pool)
            for index, (word, count) in enumerate(top, start=1):
                words.append({"rank": index, "word": word, "count": count})
            result.top_words_by_category[domain] = words

        aspect_order = sorted(words_by_aspect.keys(),
                              key=lambda a: -sum(words_by_aspect[a].values()))
        for aspect in aspect_order:
            words = []
            top = self.segmenter.top_words(words_by_aspect[aspect], self.config.top_n * 4)
            for index, (word, count) in enumerate(top, start=1):
                words.append({"rank": index, "word": word, "count": count})
            result.top_words_by_aspect[aspect] = words

        result.progress_distribution = []
        for bucket in PROGRESS_BUCKETS:
            result.progress_distribution.append({
                "bucket": bucket,
                "count": progress_counter.get(bucket, 0),
            })

        result.video_stats = self._video_stats(video_counter)

        log.info("统计完成：领域 %d 类，产品案例 %d 个，有效词 %d 个",
                 len(result.category_stats), len(product_counter), result.total_words)
        return result

    @staticmethod
    def _add_counts(counter, keys):
        """把一组标签各加 1。"""
        for key in keys:
            counter[key] = counter.get(key, 0) + 1

    @staticmethod
    def _add_tokens(words_by_aspect, aspect, tokens):
        """把一条弹幕的分词结果加到某个维度的计数器里。"""
        if aspect not in words_by_aspect:
            words_by_aspect[aspect] = {}
        counter = words_by_aspect[aspect]
        for token in tokens:
            counter[token] = counter.get(token, 0) + 1

    def _fully_covered_videos(self):
        """挑出"弹幕池基本抓全"的视频。

        为什么需要这个：B站对超长视频的弹幕池会截断。比如一个 15 小时、
        1 万条弹幕的合集课，接口只返回最早的 1200 条。这些弹幕全部落在视频开头，
        如果不剔除，进度分布图的第一桶会被灌成一个假尖峰，
        看起来就像"用户只看开头"——其实只是数据被截断了。

        判断标准是 抓到的条数 / 视频标注的总条数 >= 0.6。
        """
        covered = set()
        for video in self.videos:
            bvid = video.get("bvid")
            total = video.get("danmaku_total") or 0
            fetched = video.get("fetched") or 0
            if not bvid or total < 30:
                continue
            if fetched * 1.0 / total >= 0.6:
                covered.add(bvid)
        return covered

    def _video_stats(self, video_counter):
        """按弹幕条数排序的视频清单，把视频信息也合并进来。"""
        info_by_bvid = {}
        for video in self.videos:
            info_by_bvid[video.get("bvid")] = video

        rows = []
        for bvid, count in sorted(video_counter.items(), key=lambda kv: (-kv[1], kv[0])):
            info = info_by_bvid.get(bvid, {})
            rows.append({
                "bvid": bvid,
                "title": info.get("title", ""),
                "author": info.get("author", ""),
                "keyword": info.get("keyword", ""),
                "view": info.get("view", 0),
                "duration": info.get("duration", 0),
                "pubdate": info.get("pubdate", 0),
                "danmaku_clean": count,
                "danmaku_raw": info.get("danmaku_total", 0),
            })
        return rows


def analyze_records(records, videos=None, clean_stats=None, config=None):
    """偷懒用的函数：一步跑完分析。"""
    analyzer = DanmakuAnalyzer(records, videos, config)
    return analyzer.analyze(clean_stats)
