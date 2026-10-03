"""附加题：科技媒体观点分析 + 趋势预测。

分析四件事：

    1. 话题分布：媒体都在报道哪些应用领域（用的是和弹幕分析同一套领域词典）
    2. 时间趋势：每个月有多少篇"大模型相关"的报道
    3. 趋势外推：用最小二乘拟合最近几个月的数量，预测未来 3 个月
    4. 媒体 vs 用户：把媒体的话题占比和 B站弹幕的话题占比放一起对比，
       看哪边关注得多、哪边关注得少——这个对比我觉得是附加题里最有意思的部分

关于预测方法：故意用最简单的一元线性拟合，并且在报告里写清楚局限。
媒体发文量是被突发事件驱动的，线性外推只能反映"惯性"，不算严谨预测。
"""

from datetime import datetime

import numpy as np

from src.analysis.lexicon import DOMAIN_LEXICON
from src.analysis.matcher import AhoCorasick
from src.processing.segmenter import Segmenter
from src.utils import get_logger

log = get_logger(__name__)

# 判断一篇文章是不是"大模型相关"，命中任意一个词就算
LLM_TRIGGER_TERMS = [
    "大模型", "大语言模型", "LLM", "GPT", "ChatGPT", "DeepSeek", "Claude", "Gemini",
    "生成式", "AIGC", "AGI", "人工智能", "AI", "机器学习", "深度学习", "神经网络",
    "智能体", "Agent", "多模态", "transformer", "OpenAI", "Anthropic", "算力",
]

# 英文虚词。科技媒体的摘要经常中英混排，这些词出现频率很高但没信息量
EN_STOPWORDS = set("""
the a an and or of to in for on with at by from is are was were be been being
this that these those it its as we you they he she not no yes new how what why
when where who which will would can could should may might must do does did done
have has had more most other some such only own same so than too very just also
into over after before between during about against all any both each few
""".split())

# 站点样板词，RSS 摘要里固定会出现的
SITE_BOILERPLATE = {
    "查看", "原文", "点击", "阅读", "详情", "更多", "发布", "作者", "来源", "评论",
    "分享", "标签", "链接", "全文", "图片", "编辑", "报道", "消息", "记者",
}


class TrendResult:
    """媒体分析的结果。"""

    def __init__(self):
        self.meta = {}
        self.source_stats = []            # 每个媒体源的文章数
        self.region_stats = []            # 国内 / 国际
        self.monthly_trend = []           # 媒体按月统计
        self.forecast = []                # 媒体趋势外推
        self.forecast_note = ""
        self.video_monthly_trend = []     # B站视频按月统计
        self.video_forecast = []          # 视频趋势外推
        self.video_forecast_note = ""
        self.topic_distribution = []      # 话题分布
        self.top_keywords = []            # 高频词
        self.media_vs_danmaku = []        # 媒体 vs 用户
        self.sample_titles = []           # 一些代表性文章

    def to_dict(self):
        return dict(self.__dict__)


class TrendAnalyzer:
    """媒体趋势分析器。

    articles 是媒体文章列表，danmaku_result 是弹幕分析的结果
    （有它才能做"媒体 vs 用户"的对比，没有就跳过这一项）。
    """

    def __init__(self, articles, danmaku_result=None, forecast_months=8, segmenter=None):
        self.articles = [a for a in articles if a.get("title")]
        self.danmaku_result = danmaku_result or {}
        self.forecast_months = forecast_months
        self.segmenter = segmenter or Segmenter(min_length=2)

        # 话题匹配和弹幕分析用的是同一套领域词典，这样两边才可比
        patterns = []
        for name, aliases in DOMAIN_LEXICON.items():
            for alias in aliases:
                patterns.append((alias, name))
        self.domain_ac = AhoCorasick(patterns)

        trigger_patterns = [(term, "llm") for term in LLM_TRIGGER_TERMS]
        self.trigger_ac = AhoCorasick(trigger_patterns)

    def analyze(self):
        """跑完所有分析，返回 TrendResult。"""
        result = TrendResult()
        result.meta = {
            "article_count": len(self.articles),
            "source_count": len(set(a.get("source") for a in self.articles)),
        }

        if not self.articles:
            log.warning("没有媒体文章可以分析")
            return result

        result.source_stats = self._source_stats()
        result.region_stats = self._region_stats()
        result.monthly_trend = self._monthly_trend()
        result.forecast, result.forecast_note = self._forecast(result.monthly_trend)

        # 视频发布量这条序列比 RSS 可靠得多（RSS 只有近期文章），
        # 所以趋势外推主要看这条
        result.video_monthly_trend = self._video_monthly_trend()
        result.video_forecast, result.video_forecast_note = self._forecast(
            result.video_monthly_trend, value_key="llm_related", label="B站相关视频")

        result.topic_distribution = self._topic_distribution()
        result.top_keywords = self._top_keywords()
        result.media_vs_danmaku = self._compare_with_danmaku(result.topic_distribution)

        for article in self.articles[:15]:
            result.sample_titles.append({
                "source": article.get("source"),
                "title": article.get("title"),
                "link": article.get("link"),
            })

        log.info("媒体分析完成：%d 篇，话题 %d 类，趋势月份 %d 个",
                 len(self.articles), len(result.topic_distribution),
                 len(result.monthly_trend))
        return result

    def _is_llm_related(self, article):
        """标题或摘要里有没有大模型相关的词。"""
        text = article.get("title", "") + " " + article.get("summary", "")
        return bool(self.trigger_ac.find_labels(text))

    def _source_stats(self):
        """按媒体来源统计文章数和大模型相关占比。"""
        total = {}
        llm = {}
        region = {}
        for article in self.articles:
            source = article.get("source", "未知")
            total[source] = total.get(source, 0) + 1
            region[source] = article.get("region", "")
            if self._is_llm_related(article):
                llm[source] = llm.get(source, 0) + 1

        rows = []
        for source, count in sorted(total.items(), key=lambda kv: -kv[1]):
            rows.append({
                "name": source,
                "count": count,
                "llm_related": llm.get(source, 0),
                "llm_ratio": round(llm.get(source, 0) * 1.0 / count, 4),
                "region": region.get(source, ""),
            })
        return rows

    def _region_stats(self):
        """按国内/国际分组统计。"""
        total = {}
        llm = {}
        for article in self.articles:
            region = article.get("region", "未知")
            total[region] = total.get(region, 0) + 1
            if self._is_llm_related(article):
                llm[region] = llm.get(region, 0) + 1

        rows = []
        for region, count in sorted(total.items(), key=lambda kv: -kv[1]):
            rows.append({
                "name": region,
                "count": count,
                "llm_related": llm.get(region, 0),
                "llm_ratio": round(llm.get(region, 0) * 1.0 / count, 4),
            })
        return rows

    def _monthly_trend(self):
        """按月统计文章总数和大模型相关数。"""
        total = {}
        llm = {}
        for article in self.articles:
            month = str(article.get("published", ""))[:7]
            # 时间格式不对的跳过，只留 "2026-09" 这种
            if len(month) != 7 or not month.startswith("20"):
                continue
            total[month] = total.get(month, 0) + 1
            if self._is_llm_related(article):
                llm[month] = llm.get(month, 0) + 1

        rows = []
        for month in sorted(total.keys()):
            rows.append({
                "month": month,
                "total": total[month],
                "llm_related": llm.get(month, 0),
            })
        return rows

    def _video_monthly_trend(self):
        """按视频发布时间统计每月新增多少个"大模型相关视频"。

        这条序列比 RSS 靠谱：B站视频的发布时间是完整历史，
        不像 RSS 只有最近几十篇文章，不会出现"早期月份数据残缺"的问题。
        """
        counter = {}
        for video in self.danmaku_result.get("video_stats", []):
            pubdate = video.get("pubdate") or 0
            if not pubdate:
                continue
            try:
                month = datetime.fromtimestamp(int(pubdate)).strftime("%Y-%m")
            except (OverflowError, OSError, ValueError):
                continue
            counter[month] = counter.get(month, 0) + 1

        rows = []
        for month in sorted(counter.keys()):
            rows.append({
                "month": month,
                "total": counter[month],
                "llm_related": counter[month],
            })
        return rows

    def _forecast(self, monthly, value_key="llm_related", label="大模型相关报道"):
        """对最近几个月做线性拟合，预测未来 3 个月。

        这里有两个坑，都是数据质量的问题，不处理的话预测结果会很离谱：

        1. 当前月份还没过完。比如今天才 10 月 3 号，10 月的文章数天然偏低，
           混进去会拉出一条假的下降趋势，所以要剔掉；
        2. RSS 只暴露最近几十篇文章，更早的月份是"残缺月份"。
           如果把它当成真实的低谷，拟合出来就是"暴涨"的假趋势。
           所以只取和最新月份连续相接的那一段。

        返回 (预测列表, 说明文字)。样本不足时预测列表为空，并在说明里写清楚原因。
        """
        window = _contiguous_tail(_complete_months(monthly))

        if len(window) < 3:
            return [], (label + "：完整且连续的月份不足 3 个"
                        "（RSS 订阅源只暴露近期文章），样本量太小，不给出预测。")

        recent = window[-self.forecast_months:]
        x = np.arange(len(recent), dtype=float)
        y = np.array([item[value_key] for item in recent], dtype=float)

        slope, intercept = np.polyfit(x, y, 1)
        fitted = slope * x + intercept

        # 算一下拟合优度 R² 和残差标准差
        ss_res = float(np.sum((y - fitted) ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1.0
        r_squared = 1 - ss_res / ss_tot
        residual_std = float(np.std(y - fitted))

        last_month = datetime.strptime(recent[-1]["month"], "%Y-%m")
        forecast = []
        for step in range(1, 4):
            year = last_month.year
            month = last_month.month + step
            # 跨年处理
            year += (month - 1) // 12
            month = (month - 1) % 12 + 1

            value = slope * (len(recent) - 1 + step) + intercept
            if value < 0:
                value = 0.0

            forecast.append({
                "month": f"{year:04d}-{month:02d}",
                "predicted": int(round(value)),
                "lower": int(round(max(0.0, value - 1.96 * residual_std))),
                "upper": int(round(value + 1.96 * residual_std)),
                "is_forecast": True,
            })

        if slope > 0.2:
            direction = "上升"
        elif slope < -0.2:
            direction = "下降"
        else:
            direction = "基本持平"

        note = (f"{label}：对最近 {len(recent)} 个完整连续月份"
                f"（{recent[0]['month']} ~ {recent[-1]['month']}）做一元线性拟合，"
                f"斜率 {slope:+.2f} 篇/月，R²={r_squared:.2f}，"
                f"趋势判断为「{direction}」。"
                "预测区间是 ±1.96 倍残差标准差（约 95% 置信）。"
                "局限说明：媒体发文量和视频发布量都受突发事件驱动，"
                "线性外推只能反映惯性，不算严谨预测。")
        return forecast, note

    def _topic_distribution(self):
        """媒体文章的话题分布。"""
        counter = {}
        for article in self.articles:
            text = article.get("title", "") + " " + article.get("summary", "")
            for name in self.domain_ac.find_labels(text):
                counter[name] = counter.get(name, 0) + 1

        total = sum(counter.values())
        if total == 0:
            total = 1

        rows = []
        items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        for index, (name, count) in enumerate(items, start=1):
            rows.append({
                "rank": index,
                "name": name,
                "count": count,
                "ratio": round(count * 1.0 / total, 4),
            })
        return rows

    def _top_keywords(self, top_n=20):
        """媒体标题和摘要里的高频词。"""
        texts = []
        for article in self.articles:
            texts.append(article.get("title", "") + " " + article.get("summary", ""))

        counter = self.segmenter.count_words(texts)
        # 把英文虚词和站点样板词去掉
        for word in list(counter.keys()):
            if word in EN_STOPWORDS or word in SITE_BOILERPLATE:
                del counter[word]

        rows = []
        for index, (word, count) in enumerate(self.segmenter.top_words(counter, top_n), start=1):
            rows.append({"rank": index, "word": word, "count": count})
        return rows

    def _compare_with_danmaku(self, media_topics):
        """媒体话题占比 vs 弹幕话题占比。

        注意两边的分母不一样（各自话题命中的总数），所以比的是"相对关注度"，
        不是绝对数量。
        """
        danmaku_ratio = {}
        for item in self.danmaku_result.get("category_stats", []):
            danmaku_ratio[item["name"]] = item.get("ratio", 0.0)

        if not danmaku_ratio:
            return []

        rows = []
        for item in media_topics:
            name = item["name"]
            media = item.get("ratio", 0.0)
            user = danmaku_ratio.get(name, 0.0)
            rows.append({
                "name": name,
                "media_ratio": round(media, 4),
                "danmaku_ratio": round(user, 4),
                "gap": round(media - user, 4),
            })

        # 差值大的排前面，因为这是最值得说的部分
        rows.sort(key=lambda r: -abs(r["gap"]))
        return rows


def _contiguous_tail(monthly):
    """取和最后一个月份连续相接的那一段。

    比如月份是 [2026-01, 2026-08, 2026-09]，最后一个 09 往前看是 08（差 1 个月，
    连续），再往前是 01（差 7 个月，断了），所以只取 [2026-08, 2026-09]。
    """
    if not monthly:
        return []

    window = [monthly[-1]]
    for item in reversed(monthly[:-1]):
        current = datetime.strptime(window[0]["month"], "%Y-%m")
        previous = datetime.strptime(item["month"], "%Y-%m")
        gap = (current.year - previous.year) * 12 + (current.month - previous.month)
        if gap != 1:
            break
        window.insert(0, item)
    return window


def _complete_months(monthly, today=None):
    """把还没过完的当前月份剔掉。"""
    if today is None:
        today = datetime.now()
    current = f"{today.year:04d}-{today.month:02d}"

    result = []
    for item in monthly:
        if item["month"] != current:
            result.append(item)
    return result
