# 大语言模型应用相关视频弹幕分析挖掘

> 2025 软工 K 班个人编程任务 · 学号 **102401322**
> 代码仓库：https://github.com/2026806794/102401322
> 数据来源：哔哩哔哩（B站）综合排序前 300 的相关视频弹幕

## 一、项目简介

以「大语言模型 / 大模型 / LLM」为关键词，爬取 B 站综合排序靠前的相关视频弹幕，
过滤灌水噪声后做中文分词与统计，产出：

1. **每类弹幕的总数量**（按应用领域多标签归类）；
2. **词频 Top-8 弹幕**（整体 + 分领域）；
3. **数量排名前 8 的具体 LLM 应用案例**；
4. 用户**态度 / 成本关注 / 不利影响**三类结论性统计；
5. **词云图与可视化大屏**；
6. 附加题：**主流科技媒体观点爬取 + 趋势外推 + 媒体与用户话题差异对比**。

## 二、目录结构

作业要求在代码仓库里建一个学号为名的文件夹，所以仓库结构是：

```
102401322/                        ← 仓库根目录
└── 102401322/                    ← 学号为名的文件夹，代码都放这里
    ├── main.py                   # 命令行入口（crawl/clean/analyze/visualize/media/all）
    ├── requirements.txt          # 依赖清单
    ├── pytest.ini / conftest.py  # 测试配置
    ├── setup.cfg / .pylintrc     # 代码质量检查配置（flake8 / pylint）
    ├── .vscode/                  # VS Code 的工作区配置和调试配置
    ├── src/
    │   ├── config.py             # 全局配置（路径、爬虫参数、分析参数、媒体源）
    │   ├── utils.py              # 日志、JSON 读写、计时、文本规范化
    │   ├── pipeline.py           # 流水线编排：清洗 → 统计 → 导出 → 可视化 → 媒体
    │   ├── crawler/              # 爬虫层
    │   │   ├── wbi.py            # B站 wbi 签名（置换表 + md5）
    │   │   ├── bilibili_client.py  # 会话/限流/重试 + 弹幕 XML 与 protobuf 解析
    │   │   ├── danmaku_fetcher.py  # 任务编排、缓存、断点续爬
    │   │   └── media_spider.py     # 附加题：科技媒体 RSS 爬虫
    │   ├── processing/           # 处理层
    │   │   ├── noise_lexicon.py  # 噪声词表 / 停用词 / jieba 领域词典
    │   │   ├── cleaner.py        # 弹幕清洗与去重
    │   │   └── segmenter.py      # jieba 分词（带结果缓存）
    │   ├── analysis/             # 分析层
    │   │   ├── lexicon.py        # 案例/领域/态度/成本/风险五类领域词典
    │   │   ├── matcher.py        # Aho-Corasick 多模式匹配自动机
    │   │   ├── analyzer.py       # 统计分析主流程
    │   │   ├── exporter.py       # xlsx 导出（13 个工作表）
    │   │   └── trend_analyzer.py # 附加题：媒体趋势与预测
    │   └── visualization/        # 可视化层
    │       ├── theme.py          # 统一配色与中文字体
    │       ├── wordcloud_chart.py  # 四张中文词云
    │       ├── charts.py         # 六张统计图
    │       ├── dashboard.py      # 可视化大屏（自建 ECharts 配置 + CSS Grid）
    │       ├── html_common.py    # 两个 HTML 页面共用的 echarts 脚本
    │       └── trend_report.py   # 附加题趋势报告
    ├── tests/                    # 155 个单元测试（语句覆盖率 81%，分支覆盖率 90%）
    ├── scripts/                  # 性能剖析、博客数据注入、API 推送脚本
    ├── data/                     # 原始缓存与中间结果
    ├── output/                   # 交付物：图表 / Excel / HTML / 性能报告
    └── docs/                     # PSP 表、博客、性能分析、设计说明、测试报告
```

## 三、快速开始

```bash
pip install -r requirements.txt

python main.py crawl --per-keyword 300   # 1. 爬取弹幕（支持断点续爬）
python main.py clean                     # 2. 清洗去噪 + 分词
python main.py analyze                   # 3. 统计并导出 Excel
python main.py visualize                 # 4. 词云图 + 统计图 + 可视化大屏
python main.py media                     # 5. 附加题：媒体观点与趋势报告
python main.py all                       # 一键跑完 1~4

python -m pytest -q --cov=src            # 单元测试与覆盖率
python scripts/profile_analysis.py       # 性能剖析
```

## 四、技术栈

| 层次 | 选型 | 说明 |
| ---- | ---- | ---- |
| 语言 | Python 3.13 | 作业要求 Python3，附 `requirements.txt` |
| 爬虫 | requests + 自研 wbi 签名 | 不依赖第三方 B 站 SDK，签名算法自行实现 |
| 解析 | 标准库 `zlib` / 手写 protobuf varint 解析 | XML(deflate) 与 protobuf 双通道互为兜底 |
| 中文处理 | jieba（自定义领域词典） | 避免"大语言模型"被切碎 |
| 匹配加速 | 自研 Aho-Corasick 自动机 | 433 个模式一次扫描，实测提速 16.5 倍 |
| 统计与导出 | pandas + openpyxl | 13 个工作表，带表头样式 |
| 可视化 | matplotlib + wordcloud + Apache ECharts | 词云/统计图离线生成，大屏为自建 HTML |
| 测试 | pytest + pytest-cov | 155 个用例，核心模块覆盖率 92%~99% |
| 性能 | cProfile + pstats + snakeviz(可选) | 热点定位 + 优化前后量化对比 |
| 代码质量 | flake8 + pylint | 0 个警告 / 10.00 分（配置见 setup.cfg、.pylintrc） |

## 五、交付物清单

| 产物 | 路径 |
| ---- | ---- |
| 统计 Excel（13 表） | `output/xlsx/大语言模型弹幕分析统计.xlsx` |
| 词云图 ×4 | `output/figures/词云_*.png` |
| 统计图 ×6 | `output/figures/统计图_*.png` |
| 可视化大屏 | `output/html/可视化大屏.html` |
| 性能分析图 ×2 | `output/figures/性能分析_*.png` |
| 性能交互报告 | `output/html/性能分析报告.html` |
| 媒体趋势报告 | `output/html/媒体趋势报告.html` |
| 性能原始数据 | `output/performance/analyze.prof`、`benchmark.json` |
| 覆盖率报告 | `output/htmlcov/index.html` |

## 六、说明与限制

* **爬取礼貌性**：请求间隔 1.2~2.8 秒随机，遇 412 限流指数退避并做长冷却；
  所有原始响应落盘缓存，重复运行不会重复请求。
* **单视频弹幕上限**：默认 4000 条（配置项 `max_danmaku_per_video`），
  避免个别头部视频（十几小时的合集课）数据量失控。
* **趋势预测的局限**：RSS 订阅源只暴露近期文章，媒体侧时间序列样本有限；
  因此趋势外推的主证据使用 B 站视频的发布时间序列，并在报告中明确标注局限。
* **仓库里的数据**：清洗后的弹幕明细（`data/processed/danmaku_clean.jsonl`，约 19MB）
  已经入库，所以 clone 下来可以直接跑 `analyze`、`visualize`、`media` 复现结果。
  爬取的原始缓存（`data/raw/danmaku/`，27MB）没有入库，
  想从零走一遍完整流程的话执行 `python main.py all` 重新爬（大约 40 分钟）。
* **本机 github.com 访问受限时**：如果 `git push` 报连接重置，
  可以用 `python scripts/push_via_api.py <用户名>/<仓库名>` 走 GitHub API 推送。
