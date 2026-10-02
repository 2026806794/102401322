"""分析相关的模块。

- lexicon         五类领域词典（案例/领域/态度/成本/风险）
- matcher         Aho-Corasick 多模式匹配
- analyzer        统计分析主流程
- exporter        导出 Excel
- trend_analyzer  附加题：媒体趋势分析
"""

from src.analysis.analyzer import AnalysisResult, DanmakuAnalyzer
from src.analysis.matcher import AhoCorasick, naive_match_count

__all__ = ["DanmakuAnalyzer", "AnalysisResult", "AhoCorasick", "naive_match_count"]
