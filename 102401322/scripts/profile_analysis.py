"""性能分析脚本。

用 cProfile 分析统计接口，找出最耗时的函数，再对比一下优化前后的差别。

运行：
    python scripts/profile_analysis.py

产出：
    output/performance/analyze.prof           cProfile 原始数据（可以用 snakeviz 打开看）
    output/performance/profile_report.txt     文字版的热点函数列表
    output/performance/benchmark.json         优化前后的对比数据
    output/figures/性能分析_热点函数.png       热点函数条形图
    output/figures/性能分析_优化对比.png       优化前后对比图
    output/html/性能分析报告.html              交互式报告（矩形树图）
"""

import argparse
import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# 让脚本能 import 到 src 里的模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis.analyzer import DanmakuAnalyzer
from src.analysis.lexicon import (
    COST_LEXICON,
    DOMAIN_LEXICON,
    PRODUCT_LEXICON,
    RISK_LEXICON,
    SENTIMENT_LEXICON,
)
from src.analysis.matcher import AhoCorasick, naive_match_count
from src.config import (
    DANMAKU_CLEAN_FILE,
    DEFAULT_ANALYSIS_CONFIG,
    FIGURE_DIR,
    HTML_DIR,
    OUTPUT_DIR,
    VIDEO_INDEX_FILE,
    ensure_directories,
)
from src.utils import get_logger, read_json, read_jsonl, write_json

log = get_logger("profile")
PERF_DIR = OUTPUT_DIR / "performance"

PALETTE = ["#4C8DFF", "#38D9C0", "#FFB84C", "#FF6B81", "#9B7BFF", "#3DDC97"]


def load_data():
    """读清洗后的弹幕和视频清单。数据不存在就用合成语料，至少能跑通流程。"""
    records = read_jsonl(DANMAKU_CLEAN_FILE)
    videos = read_json(VIDEO_INDEX_FILE, [])
    if records:
        log.info("载入真实数据：%d 条弹幕 / %d 个视频", len(records), len(videos))
        return records, videos

    log.warning("没找到清洗后的数据，用合成语料代替（结果只用于演示方法）")
    return make_synthetic_records(20000), []


def make_synthetic_records(count):
    """造一批假弹幕，方便在没有数据的时候也能测。"""
    import random

    templates = [
        "用 ChatGPT 写代码效率真的高",
        "DeepSeek 做数据分析很方便",
        "API 调用太贵了成本扛不住",
        "担心大模型会取代程序员导致失业",
        "显卡太贵了本地部署跑不动",
        "豆包画图挺好用的",
        "文心一言帮我写论文摘要",
        "模型经常出现幻觉胡说八道",
        "智能体工作流能自动化办公",
        "翻译和写文案都能用",
    ]
    rng = random.Random(42)
    records = []
    for i in range(count):
        records.append({
            "bvid": "BV%d" % (i % 500),
            "uid_hash": "u%d" % i,
            "keyword": "大模型",
            "text": rng.choice(templates),
            "time": float(i % 600),
        })
    return records


# ---------------- 1. cProfile 剖析 ----------------

def profile_analysis(records, videos):
    """对统计接口跑一次 cProfile。"""
    analyzer = DanmakuAnalyzer(records, videos, DEFAULT_ANALYSIS_CONFIG)

    profiler = cProfile.Profile()
    profiler.enable()
    analyzer.analyze()
    profiler.disable()

    PERF_DIR.mkdir(parents=True, exist_ok=True)
    prof_file = PERF_DIR / "analyze.prof"
    profiler.dump_stats(str(prof_file))
    log.info("cProfile 数据已保存：%s", prof_file)

    stats = pstats.Stats(profiler)
    stats.sort_stats("cumulative")
    return stats


def dump_text_report(stats, top=20):
    """把热点函数列表写成文本，方便直接贴到报告里。"""
    buffer = io.StringIO()
    stats.stream = buffer
    stats.print_stats(top)

    report = PERF_DIR / "profile_report.txt"
    report.write_text(buffer.getvalue(), encoding="utf-8")
    log.info("文字版性能报告：%s", report)
    return report


def plot_hotspots(stats, top=12):
    """画热点函数条形图：累计耗时 vs 自身耗时。"""
    from src.visualization.theme import new_figure, style_axes

    entries = sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:top]

    labels = []
    cumulative = []
    total_time = []
    for (filename, lineno, func), info in entries:
        # info 是 (调用次数, 递归次数, 自身耗时, 累计耗时, 调用者)
        labels.append("%s\n(%s:%d)" % (func, Path(filename).name, lineno))
        cumulative.append(info[3])
        total_time.append(info[2])

    # 反过来排，耗时最大的画在最上面
    labels = labels[::-1]
    cumulative = cumulative[::-1]
    total_time = total_time[::-1]

    positions = np.arange(len(labels))
    height = 0.38

    figure, axes = new_figure((13, 7.5))
    axes.barh(positions + height / 2, cumulative, height,
              label="累计耗时 (cumtime)", color=PALETTE[0])
    axes.barh(positions - height / 2, total_time, height,
              label="自身耗时 (tottime)", color=PALETTE[2])
    axes.set_yticks(positions)
    axes.set_yticklabels(labels, fontsize=9)

    for index, value in enumerate(cumulative):
        axes.text(value + max(cumulative) * 0.01, index + height / 2,
                  "%.3fs" % value, va="center", fontsize=9, color="#1F2937")

    axes.set_xlim(0, max(cumulative) * 1.18)
    axes.legend(loc="lower right", fontsize=10)
    style_axes(axes, "数据统计接口性能热点（cProfile，按累计耗时排序）", "耗时（秒）")
    axes.grid(axis="x", linestyle="--", alpha=0.35)
    axes.grid(axis="y", visible=False)

    target = FIGURE_DIR / "性能分析_热点函数.png"
    figure.savefig(target, dpi=DEFAULT_ANALYSIS_CONFIG.figure_dpi, bbox_inches="tight")
    plt.close(figure)
    log.info("热点函数图：%s", target)
    return target


def build_hotspot_html(stats, top=25):
    """生成一个交互式的热点报告（矩形树图 + 表格），用的是本地 echarts。"""
    entries = sorted(stats.stats.items(), key=lambda item: item[1][3], reverse=True)[:top]

    nodes = []
    for (filename, lineno, func), info in entries:
        nodes.append({
            "name": "%s  (%s:%d)" % (func, Path(filename).name, lineno),
            "value": round(info[3], 4),
            "tottime": round(info[2], 4),
            "ncalls": info[0],
        })

    if not nodes:
        log.warning("剖析数据是空的，跳过热点报告")
        return HTML_DIR / "性能分析报告.html"

    total = sum(item["value"] for item in nodes)
    if total == 0:
        total = 1.0

    rows = ""
    for index, node in enumerate(nodes, start=1):
        rows += ("<tr><td>%d</td><td class='fn'>%s</td><td>%d</td>"
                 "<td>%.4f</td><td>%.4f</td><td>%.1f%%</td></tr>"
                 % (index, node["name"], node["ncalls"], node["tottime"],
                    node["value"], node["value"] * 100.0 / total))

    option = {
        "backgroundColor": "transparent",
        "tooltip": {"formatter": "{b}<br/>累计耗时 {c} 秒"},
        "series": [{
            "type": "treemap",
            "roam": False,
            "nodeClick": False,
            "breadcrumb": {"show": False},
            "label": {"show": True, "formatter": "{b}", "fontSize": 11, "color": "#0B1524"},
            "upperLabel": {"show": False},
            "itemStyle": {"borderColor": "#0F1B2D", "borderWidth": 2, "gapWidth": 2},
            "levels": [
                {"itemStyle": {"borderColor": "#0F1B2D", "borderWidth": 3, "gapWidth": 3}},
                {"colorSaturation": [0.35, 0.75]},
            ],
            "data": nodes,
        }],
    }

    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>数据统计接口性能分析报告</title>
<script src="../assets/echarts.min.js"></script>
<style>
  body { margin:0; padding:24px 30px; background:#0b1524; color:#E8F1FF;
         font-family:"Microsoft YaHei",sans-serif; }
  h1 { font-size:22px; margin:0 0 6px; }
  p.sub { color:#7C93B5; font-size:13px; margin:0 0 18px; }
  #treemap { width:100%; height:460px; }
  table { width:100%; border-collapse:collapse; margin-top:18px; font-size:13px; }
  th, td { padding:7px 10px; border-bottom:1px solid #1E3350; text-align:right; }
  th { background:#12233c; color:#9FB3D1; }
  td.fn { text-align:left; color:#D6E4FF; }
  tr:hover td { background:#12233c; }
</style>
</head>
<body>
  <h1>数据统计接口性能分析报告（cProfile）</h1>
  <p class="sub">矩形面积 = 函数累计耗时（cumtime），取前 __COUNT__ 个热点函数</p>
  <div id="treemap"></div>
  <table>
    <thead><tr><th>#</th><th style="text-align:left">函数</th><th>调用次数</th>
    <th>自身耗时(s)</th><th>累计耗时(s)</th><th>占比</th></tr></thead>
    <tbody>__ROWS__</tbody>
  </table>
  <script>
    echarts.init(document.getElementById('treemap'), null, {renderer:'canvas'})
           .setOption(__OPTION__);
  </script>
</body>
</html>
"""
    html = html.replace("__COUNT__", str(len(nodes)))
    html = html.replace("__ROWS__", rows)
    html = html.replace("__OPTION__", json.dumps(option, ensure_ascii=False))

    target = HTML_DIR / "性能分析报告.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    log.info("性能热点交互报告：%s", target)
    return target


# ---------------- 2. 优化前后对比 ----------------

def all_patterns():
    """把五类词典里的别名全拿出来，作为匹配用的模式。"""
    patterns = []
    for lexicon in (DOMAIN_LEXICON, PRODUCT_LEXICON, SENTIMENT_LEXICON,
                    COST_LEXICON, RISK_LEXICON):
        for canonical, aliases in lexicon.items():
            for alias in aliases:
                patterns.append((alias, canonical))
    return patterns


def time_it(func, repeat=3):
    """跑 repeat 次取中位数。

    只跑一次的话结果抖动很大（同一份代码测出来 12 倍和 18 倍都有），
    取中位数稳一些。
    """
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        func()
        times.append(time.perf_counter() - start)
    times.sort()
    return times[len(times) // 2]


def benchmark_matcher(records, sample_size=3000):
    """对比朴素子串匹配和 AC 自动机的耗时。

    朴素写法在全部数据上要跑几秒，所以只取前 sample_size 条测，
    再按比例估算全量耗时。
    """
    patterns = all_patterns()
    texts = [r.get("text", "") for r in records]
    sample = texts[:min(sample_size, len(texts))]
    total = len(texts)
    scale = total * 1.0 / max(len(sample), 1)

    build_time = time_it(lambda: AhoCorasick(patterns))
    automaton = AhoCorasick(patterns)

    ac_time = time_it(lambda: automaton.count_labels(sample))
    naive_time = time_it(lambda: naive_match_count(sample, patterns))

    speedup = 0
    if ac_time:
        speedup = naive_time / ac_time

    result = {
        "弹幕总数": total,
        "基准样本量": len(sample),
        "模式数": len(patterns),
        "自动机节点数": automaton.node_count,
        "自动机构建耗时(秒)": round(build_time, 4),
        "AC样本耗时(秒)": round(ac_time, 4),
        "朴素样本耗时(秒)": round(naive_time, 4),
        "AC单条耗时(微秒)": round(ac_time / max(len(sample), 1) * 1e6, 2),
        "朴素单条耗时(微秒)": round(naive_time / max(len(sample), 1) * 1e6, 2),
        "提速倍数": round(speedup, 1),
        "AC全量预估(秒)": round(ac_time * scale, 2),
        "朴素全量预估(秒)": round(naive_time * scale, 2),
    }
    log.info("匹配对比：AC 快 %.1f 倍（朴素 %.4fs -> AC %.4fs，样本 %d 条）",
             result["提速倍数"], naive_time, ac_time, len(sample))
    return result


def benchmark_segmenter(records):
    """对比分词有缓存和没缓存的差别。

    这里分两种情况报告，因为它们的意义完全不一样：

    * 首次运行：缓存是空的，只有重复出现的句子能命中。程序每次跑都是一次
      "首次运行"，所以这个数字才是实际收益；
    * 缓存已热：所有句子都命中缓存，反映的是缓存的上限。

    只报后者会显得优化效果特别好（几十倍），但那不是真实场景，所以两个都写出来。
    """
    from src.processing.segmenter import Segmenter

    texts = [r.get("text", "") for r in records]

    # 不用缓存
    plain = Segmenter(min_length=2, cache_size=0)
    plain._ensure_initialized()
    plain_time = time_it(lambda: plain.count_words(texts))

    # 用缓存，但每次都新建一个分词器 —— 程序每次运行都是"冷缓存"，
    # 如果重复用同一个实例，第二次开始缓存就热了，测出来的不是真实情况
    def cold_run():
        seg = Segmenter(min_length=2, cache_size=50000)
        seg._ensure_initialized()
        seg.count_words(texts)
        return seg

    sample_run = cold_run()             # 单独跑一次拿命中率
    cached_time = time_it(cold_run)

    # 预热之后再测一次，看看全命中能多快
    warm = Segmenter(min_length=2, cache_size=50000)
    warm._ensure_initialized()
    warm.count_words(texts)
    warm_time = time_it(lambda: warm.count_words(texts))

    cold_speedup = 0
    if cached_time:
        cold_speedup = plain_time / cached_time
    warm_speedup = 0
    if warm_time:
        warm_speedup = plain_time / warm_time

    result = {
        "弹幕总数": len(texts),
        "去重后文本数": len(set(texts)),
        "无缓存耗时(秒)": round(plain_time, 4),
        "带缓存首次耗时(秒)": round(cached_time, 4),
        "首次运行提速倍数": round(cold_speedup, 2),
        "首次运行缓存命中率": "%.1f%%" % (sample_run.cache_hit_rate * 100),
        "缓存已热耗时(秒)": round(warm_time, 4),
        "缓存全命中提速倍数": round(warm_speedup, 1),
    }
    log.info("分词对比：首次运行 %.2fs -> %.2fs（快 %.2f 倍，命中率 %s）；"
             "缓存全命中时只要 %.2fs",
             plain_time, cached_time, cold_speedup,
             result["首次运行缓存命中率"], warm_time)
    return result


def plot_benchmark(benchmark, segment_benchmark):
    """画优化前后的对比图。"""
    from src.visualization.theme import style_axes

    figure, (axes_left, axes_right) = plt.subplots(1, 2, figsize=(14, 5.8),
                                                   dpi=DEFAULT_ANALYSIS_CONFIG.figure_dpi)

    # 左图：单条弹幕的标签识别耗时
    labels = ["朴素子串匹配\n(优化前)", "Aho-Corasick\n(优化后)"]
    per_item = [benchmark["朴素单条耗时(微秒)"], benchmark["AC单条耗时(微秒)"]]
    bars = axes_left.bar(labels, per_item, color=[PALETTE[3], PALETTE[1]], width=0.5)
    for bar, value in zip(bars, per_item):
        axes_left.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.03,
                       "%.1f μs" % value, ha="center", fontsize=12, fontweight="bold")
    axes_left.set_ylim(0, max(per_item) * 1.22)
    style_axes(axes_left, "① 多模式匹配：提速 %s 倍" % benchmark["提速倍数"],
               "实现方式", "微秒/条")

    # 右图：分词耗时（这是剖析找出来的最大瓶颈）
    labels = ["无缓存\n(优化前)", "带缓存\n(首次运行)", "缓存已热\n(理论上限)"]
    seconds = [segment_benchmark["无缓存耗时(秒)"],
               segment_benchmark["带缓存首次耗时(秒)"],
               segment_benchmark["缓存已热耗时(秒)"]]
    bars = axes_right.bar(labels, seconds,
                          color=[PALETTE[3], PALETTE[1], PALETTE[5]], width=0.55)
    for bar, value in zip(bars, seconds):
        axes_right.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.03,
                        "%.2f s" % value, ha="center", fontsize=12, fontweight="bold")
    axes_right.set_ylim(0, max(seconds) * 1.22)
    style_axes(axes_right,
               "② 分词缓存：首次运行提速 %s 倍（命中率 %s）"
               % (segment_benchmark["首次运行提速倍数"],
                  segment_benchmark["首次运行缓存命中率"]),
               "实现方式", "%s 条弹幕总耗时（秒）" % format(segment_benchmark["弹幕总数"], ","))

    figure.suptitle("数据统计接口性能优化前后对比", fontsize=17, fontweight="bold")
    target = FIGURE_DIR / "性能分析_优化对比.png"
    figure.savefig(target, dpi=DEFAULT_ANALYSIS_CONFIG.figure_dpi, bbox_inches="tight")
    plt.close(figure)
    log.info("优化对比图：%s", target)
    return target


def main():
    parser = argparse.ArgumentParser(description="统计接口性能剖析")
    parser.add_argument("--sample", type=int, default=3000, help="基准测试取多少条弹幕")
    args = parser.parse_args()

    ensure_directories()
    PERF_DIR.mkdir(parents=True, exist_ok=True)

    records, videos = load_data()

    stats = profile_analysis(records, videos)
    dump_text_report(stats)
    build_hotspot_html(stats)
    plot_hotspots(stats)

    benchmark = benchmark_matcher(records, sample_size=args.sample)
    segment_benchmark = benchmark_segmenter(records)
    write_json(PERF_DIR / "benchmark.json",
               {"多模式匹配": benchmark, "分词缓存": segment_benchmark})
    plot_benchmark(benchmark, segment_benchmark)

    log.info("性能剖析完成，产物在 %s", PERF_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
