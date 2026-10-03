"""附加题的测试：RSS 解析、趋势分析和趋势图。

这里最要紧的是两个"数据质量守卫"，它们直接决定趋势预测能不能信：
一个是把没过完的当月剔掉（否则会算出假的下降趋势），
一个是把 RSS 残缺的月份剔掉（否则会把"订阅源只有近期文章"当成"报道量暴涨"）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.analysis.trend_analyzer import (
    TrendAnalyzer,
    _complete_months,
    _contiguous_tail,
)
from src.crawler.media_spider import (
    MediaArticle,
    MediaSpider,
    _normalize_date,
    parse_feed,
    strip_html,
)

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>示例科技媒体</title>
  <item>
    <title>OpenAI 发布新一代大模型</title>
    <link>https://example.com/a</link>
    <pubDate>Tue, 30 Sep 2026 10:00:00 +0800</pubDate>
    <description><![CDATA[<p>这是一段<b>摘要</b>&nbsp;内容</p>]]></description>
  </item>
  <item>
    <title>国产开源模型再突破</title>
    <link>https://example.com/b</link>
    <pubDate>Wed, 01 Oct 2026 08:30:00 +0800</pubDate>
    <description>纯文本摘要</description>
  </item>
</channel></rss>
"""

ATOM_SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Feed</title>
  <entry>
    <title>LLM agents reshape workflows</title>
    <link href="https://example.org/1"/>
    <updated>2026-09-28T12:00:00Z</updated>
    <summary>Agent 工作流正在改变办公方式</summary>
  </entry>
</feed>
"""


class TestFeedParsing:
    """RSS/Atom 解析与字段归一化。"""

    def test_parse_rss_items(self) -> None:
        """RSS 2.0：标题、链接、时间、摘要都应被提取。"""
        articles = parse_feed(RSS_SAMPLE, "示例媒体", "国内")
        assert len(articles) == 2
        assert articles[0].title == "OpenAI 发布新一代大模型"
        assert articles[0].link == "https://example.com/a"
        assert articles[0].published.startswith("2026-09-30")
        assert "摘要" in articles[0].summary
        assert articles[0].region == "国内"

    def test_parse_atom_entry(self) -> None:
        """Atom：link 是属性而非文本，需单独处理。"""
        articles = parse_feed(ATOM_SAMPLE, "Example", "国际")
        assert len(articles) == 1
        assert articles[0].title == "LLM agents reshape workflows"
        assert articles[0].link == "https://example.org/1"
        assert articles[0].published.startswith("2026-09-28")

    def test_parse_invalid_xml_returns_empty(self) -> None:
        """异常处理：非法 XML 不应抛异常，返回空列表。"""
        assert parse_feed("<rss><channel><item>", "坏源", "国内") == []
        assert parse_feed("", "空源", "国内") == []

    def test_strip_html_removes_tags_and_entities(self) -> None:
        """摘要应去掉 HTML 标签并反转义实体。"""
        cleaned = strip_html("<p>你好&nbsp;<b>世界</b>&amp;再见</p>")
        assert "<" not in cleaned
        assert cleaned == "你好 世界 &再见"

    @pytest.mark.parametrize(
        ("raw", "prefix"),
        [
            ("Tue, 30 Sep 2026 10:00:00 +0800", "2026-09-30"),
            ("2026-09-28T12:00:00Z", "2026-09-28"),
            ("", ""),
            ("不是时间", "不是时间"),
        ],
    )
    def test_normalize_date(self, raw: str, prefix: str) -> None:
        """时间归一化：RFC822、ISO8601、空值与非法值。"""
        assert _normalize_date(raw).startswith(prefix)


class TestMediaSpiderCache:
    """媒体爬虫的缓存行为。"""

    def test_uses_cache_when_available(self, tmp_path: Path) -> None:
        """命中缓存时不应发起网络请求。"""
        spider = MediaSpider(raw_dir=tmp_path)
        cache = spider._cache_path("测试源")
        cache.write_text(
            '{"source": "测试源", "articles": [{"source": "测试源", "region": "国内",'
            ' "title": "缓存文章", "link": "", "published": "", "summary": "", "fetched_at": ""}]}',
            encoding="utf-8",
        )
        spider.session.get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应发起请求"))
        articles = spider.fetch_feed({"name": "测试源", "url": "https://x", "region": "国内"})
        assert len(articles) == 1
        assert articles[0].title == "缓存文章"
        spider.close()

    def test_cache_path_is_filesystem_safe(self, tmp_path: Path) -> None:
        """含特殊字符的源名应被转成安全文件名。"""
        spider = MediaSpider(raw_dir=tmp_path)
        name = spider._cache_path("InfoQ 中国/AI").name
        assert "/" not in name and "\\" not in name
        spider.close()


@pytest.fixture()
def media_articles() -> list[dict]:
    """构造覆盖多月、多来源、多话题的媒体文章。"""
    rows = []
    for index, (month, source, region, title) in enumerate([
        ("2026-06", "量子位", "国内", "大模型在办公场景落地"),
        ("2026-07", "量子位", "国内", "开源大模型发布新版本"),
        ("2026-07", "TechCrunch AI", "国际", "AI agents for coding"),
        ("2026-08", "量子位", "国内", "大模型辅助编程实践"),
        ("2026-08", "TechCrunch AI", "国际", "GPU cluster cost"),
        ("2026-08", "Solidot", "国内", "本周科技简讯"),
        ("2026-09", "量子位", "国内", "医疗大模型进展"),
        ("2026-09", "TechCrunch AI", "国际", "LLM research funding"),
        ("2026-09", "量子位", "国内", "办公自动化智能体"),
    ]):
        rows.append({
            "source": source, "region": region, "title": title,
            "link": f"https://example.com/{index}", "published": f"{month}-15T00:00:00+00:00",
            "summary": title, "fetched_at": "",
        })
    return rows


@pytest.fixture()
def danmaku_result() -> dict:
    """构造弹幕分析结果（仅保留话题对比所需字段）。"""
    return {
        "category_stats": [
            {"name": "办公效率", "count": 300, "ratio": 0.30},
            {"name": "编程开发", "count": 200, "ratio": 0.20},
            {"name": "教育学习", "count": 500, "ratio": 0.50},
        ]
    }


class TestTrendAnalyzer:
    """趋势分析主流程。"""

    def test_source_and_region_stats(self, media_articles: list[dict]) -> None:
        """来源与地区统计应覆盖全部文章。"""
        result = TrendAnalyzer(media_articles).analyze()
        assert sum(item["count"] for item in result.source_stats) == len(media_articles)
        assert sum(item["count"] for item in result.region_stats) == len(media_articles)
        regions = {item["name"] for item in result.region_stats}
        assert {"国内", "国际"} <= regions

    def test_monthly_trend_is_sorted(self, media_articles: list[dict]) -> None:
        """月度趋势应按时间升序，且每月总量等于该月文章数。"""
        result = TrendAnalyzer(media_articles).analyze()
        months = [item["month"] for item in result.monthly_trend]
        assert months == sorted(months)
        assert sum(item["total"] for item in result.monthly_trend) == len(media_articles)

    def test_topic_distribution_and_comparison(self, media_articles: list[dict],
                                               danmaku_result: dict) -> None:
        """话题分布与"媒体 vs 用户"对比应产出差值字段。"""
        result = TrendAnalyzer(media_articles, danmaku_result).analyze()
        assert result.topic_distribution
        assert result.media_vs_danmaku
        assert all("gap" in row for row in result.media_vs_danmaku)

    def test_comparison_empty_without_danmaku_result(self, media_articles: list[dict]) -> None:
        """边界值：没有弹幕结果时不做对比，返回空列表而不是报错。"""
        result = TrendAnalyzer(media_articles).analyze()
        assert result.media_vs_danmaku == []

    def test_keywords_exclude_english_stopwords(self, media_articles: list[dict]) -> None:
        """高频词里不应出现英文虚词与站点样板词。"""
        result = TrendAnalyzer(media_articles).analyze()
        words = {item["word"] for item in result.top_keywords}
        assert not (words & {"the", "and", "for", "查看", "原文"})

    def test_empty_articles_is_handled(self) -> None:
        """健壮性：没有文章时返回空结果而不是抛异常。"""
        result = TrendAnalyzer([]).analyze()
        assert result.meta["article_count"] == 0
        assert result.monthly_trend == []


class TestForecastGuards:
    """趋势预测的数据质量守卫（白盒测试）。"""

    def test_complete_months_drops_current_month(self) -> None:
        """当前月尚未结束，必须剔除，否则会拉出虚假的下降趋势。"""
        monthly = [{"month": "2026-08", "llm_related": 30},
                   {"month": "2026-09", "llm_related": 40},
                   {"month": "2026-10", "llm_related": 5}]
        kept = _complete_months(monthly, today=datetime(2026, 10, 3))
        assert [item["month"] for item in kept] == ["2026-08", "2026-09"]

    def test_contiguous_tail_stops_at_gap(self) -> None:
        """只保留与最新月份连续相接的窗口，断开处之前的残缺月份被剔除。"""
        monthly = [{"month": "2026-01", "llm_related": 2},
                   {"month": "2026-08", "llm_related": 3},
                   {"month": "2026-09", "llm_related": 35}]
        window = _contiguous_tail(monthly)
        assert [item["month"] for item in window] == ["2026-08", "2026-09"]

    def test_contiguous_tail_handles_year_boundary(self) -> None:
        """跨年时月差计算应正确（2025-12 → 2026-01 视为连续）。"""
        monthly = [{"month": "2025-12", "llm_related": 10},
                   {"month": "2026-01", "llm_related": 12}]
        assert len(_contiguous_tail(monthly)) == 2

    def test_no_forecast_when_sample_too_small(self) -> None:
        """样本不足 3 个连续完整月份时应拒绝预测，并给出说明。"""
        monthly = [{"month": "2026-09", "llm_related": 35}]
        analyzer = TrendAnalyzer([])
        forecast, note = analyzer._forecast(monthly)
        assert forecast == []
        assert "不足 3 个" in note

    def test_forecast_produces_three_months(self) -> None:
        """样本充足时应给出未来 3 个月预测，且区间包含预测值。"""
        monthly = [
            {"month": "2026-03", "llm_related": 10, "total": 10},
            {"month": "2026-04", "llm_related": 14, "total": 14},
            {"month": "2026-05", "llm_related": 18, "total": 18},
            {"month": "2026-06", "llm_related": 22, "total": 22},
        ]
        analyzer = TrendAnalyzer([])
        forecast, note = analyzer._forecast(monthly)
        assert len(forecast) == 3
        assert forecast[0]["month"] == "2026-07"
        for item in forecast:
            assert item["lower"] <= item["predicted"] <= item["upper"]
        assert "上升" in note

    def test_video_monthly_trend_from_pubdate(self, danmaku_result: dict) -> None:
        """视频发布时间应能正确聚合为月度序列。"""
        import calendar

        payload = {"video_stats": [
            {"pubdate": calendar.timegm((2026, 9, 10, 0, 0, 0, 0, 0, 0))},
            {"pubdate": calendar.timegm((2026, 9, 20, 0, 0, 0, 0, 0, 0))},
            {"pubdate": 0},                      # 边界值：缺失时间应被跳过
        ]}
        analyzer = TrendAnalyzer([], payload)
        trend = analyzer._video_monthly_trend()
        assert trend == [{"month": "2026-09", "total": 2, "llm_related": 2}]


class TestTrendVisuals:
    """趋势可视化冒烟测试。"""

    def test_build_trend_visuals(self, media_articles: list[dict], danmaku_result: dict,
                                 monkeypatch, tmp_path) -> None:
        """趋势图与趋势报告都应被真实生成（输出重定向到临时目录，避免覆盖交付产物）。"""
        import src.visualization.trend_report as trend_module
        from src.visualization.trend_report import build_trend_visuals

        figure_dir = tmp_path / "figures"
        figure_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(trend_module, "FIGURE_DIR", figure_dir)
        monkeypatch.setattr(trend_module, "HTML_DIR", tmp_path / "html")

        trend = TrendAnalyzer(media_articles, danmaku_result).analyze().to_dict()
        paths = build_trend_visuals(trend)
        assert len(paths) >= 4
        for path in paths:
            assert Path(path).exists()
            assert Path(path).stat().st_size > 1024

    def test_media_article_roundtrip(self) -> None:
        """MediaArticle 应可无损序列化/反序列化（缓存契约）。"""
        article = MediaArticle(source="源", region="国内", title="标题", link="u")
        restored = MediaArticle(**article.to_dict())
        assert restored == article
