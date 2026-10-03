"""pytest 公共配置与测试夹具。

把项目根目录加入 ``sys.path``，使 ``import src.*`` 在任意工作目录下都可用。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def sample_records() -> list[dict]:
    """构造一批覆盖多种情况的弹幕样本（等价类划分 + 边界值）。"""
    return [
        # 正常有效弹幕
        {"bvid": "BV1", "uid_hash": "u1", "text": "大模型写代码真的太好用了", "time": 10.0, "keyword": "大模型"},
        {"bvid": "BV1", "uid_hash": "u2", "text": "用 DeepSeek 做科研数据分析",
         "time": 100.0, "keyword": "大模型"},
        {"bvid": "BV2", "uid_hash": "u3", "text": "ChatGPT 翻译很准确", "time": 200.0, "keyword": "LLM"},
        # 噪声：整条命中词表
        {"bvid": "BV1", "uid_hash": "u4", "text": "666", "time": 1.0, "keyword": "大模型"},
        {"bvid": "BV1", "uid_hash": "u5", "text": "前排", "time": 2.0, "keyword": "大模型"},
        {"bvid": "BV1", "uid_hash": "u6", "text": "哈哈哈哈", "time": 3.0, "keyword": "大模型"},
        {"bvid": "BV1", "uid_hash": "u7", "text": "求资料", "time": 4.0, "keyword": "大模型"},
        # 噪声：正则规则命中
        {"bvid": "BV1", "uid_hash": "u8", "text": "123456", "time": 5.0, "keyword": "大模型"},
        {"bvid": "BV1", "uid_hash": "u9", "text": "@某某某 快来看", "time": 6.0, "keyword": "大模型"},
        {"bvid": "BV1", "uid_hash": "u10", "text": "https://example.com/a",
         "time": 7.0, "keyword": "大模型"},
        # 噪声：长度不足
        {"bvid": "BV1", "uid_hash": "u11", "text": "好", "time": 8.0, "keyword": "大模型"},
        # 同一用户在同一视频重复刷屏（应去重）
        {"bvid": "BV2", "uid_hash": "u12", "text": "讲得很清楚", "time": 9.0, "keyword": "LLM"},
        {"bvid": "BV2", "uid_hash": "u12", "text": "讲得很清楚", "time": 10.0, "keyword": "LLM"},
        # 不同用户说同样的话（必须保留）
        {"bvid": "BV2", "uid_hash": "u13", "text": "讲得很清楚", "time": 11.0, "keyword": "LLM"},
        # 需要规范化的文本
        {"bvid": "BV3", "uid_hash": "u14", "text": "太​厉​害了",
         "time": 12.0, "keyword": "大语言模型"},
        {"bvid": "BV3", "uid_hash": "u15", "text": "好好好好好", "time": 13.0, "keyword": "大语言模型"},
    ]


@pytest.fixture()
def analyzer_records() -> list[dict]:
    """构造统计口径测试所需的弹幕（领域、案例、态度、成本、风险各有着落）。"""
    return [
        {"bvid": "BV1", "uid_hash": "a1", "keyword": "大模型", "time": 1.0,
         "text": "用 ChatGPT 写代码效率很高"},
        {"bvid": "BV1", "uid_hash": "a2", "keyword": "大模型", "time": 2.0,
         "text": "DeepSeek 做数据分析很方便"},
        {"bvid": "BV1", "uid_hash": "a3", "keyword": "大模型", "time": 3.0,
         "text": "文心一言帮我写论文摘要"},
        {"bvid": "BV2", "uid_hash": "a4", "keyword": "LLM", "time": 4.0,
         "text": "豆包画图还挺好用的"},
        {"bvid": "BV2", "uid_hash": "a5", "keyword": "LLM", "time": 5.0,
         "text": "API 调用太贵了，成本很高"},
        {"bvid": "BV2", "uid_hash": "a6", "keyword": "LLM", "time": 6.0,
         "text": "担心大模型会取代程序员导致失业"},
        {"bvid": "BV3", "uid_hash": "a7", "keyword": "大语言模型", "time": 7.0,
         "text": "大模型有幻觉经常胡说八道"},
        {"bvid": "BV3", "uid_hash": "a8", "keyword": "大语言模型", "time": 8.0,
         "text": "显卡太贵了本地部署跑不动"},
    ]


@pytest.fixture()
def fake_videos() -> list[dict]:
    """视频元信息（用于验证时长归一化的进度分桶）。

    ``danmaku_total`` 与 ``fetched`` 用于判断"弹幕池是否抓全"——
    只有抓全的视频才纳入进度分布统计，因此这里给出完整覆盖的取值。
    """
    return [
        {"bvid": "BV1", "title": "视频一", "author": "UP1", "duration": 100, "view": 1000,
         "keyword": "大模型", "danmaku_total": 100, "fetched": 100},
        {"bvid": "BV2", "title": "视频二", "author": "UP2", "duration": 200, "view": 2000,
         "keyword": "LLM", "danmaku_total": 200, "fetched": 200},
        {"bvid": "BV3", "title": "视频三", "author": "UP3", "duration": 400, "view": 3000,
         "keyword": "大语言模型", "danmaku_total": 300, "fetched": 300},
    ]
