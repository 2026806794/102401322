"""一些通用的小工具：日志、读写 json、计时、文本处理。

这些函数好几个模块都要用，所以抽出来放在这里。
"""

import json
import logging
import re
import time

from src.config import LOG_DIR, setup_console_encoding

# 日志格式：时间 | 级别 | 模块名 | 内容
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"


def get_logger(name):
    """拿到一个 logger，日志同时打到控制台和 logs/run.log。

    注意这里配置的是 root logger。我一开始是给"第一个创建的 logger"加 handler，
    结果其他模块的 logger 没有 handler，INFO 级别的日志全被丢掉了，
    排查问题时看日志一片空白，还以为是程序卡住了。
    """
    root = logging.getLogger()

    # 判断有没有配置过：看 root logger 上有没有文件 handler
    configured = False
    for handler in root.handlers:
        if isinstance(handler, logging.FileHandler):
            configured = True

    if not configured:
        setup_console_encoding()
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(message)s", "%H:%M:%S"))
        root.addHandler(console)

        file_handler = logging.FileHandler(LOG_DIR / "run.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(file_handler)

        # jieba 加载词典时会打一堆日志，压掉
        logging.getLogger("jieba").setLevel(logging.WARNING)

    # 级别每次都设，因为别的库（比如 pytest）可能把 root 改成 WARNING，
    # 那样我们自己的 INFO 日志就看不到了
    root.setLevel(logging.INFO)

    return logging.getLogger(name)


def read_json(path, default=None):
    """读 json 文件。文件不存在或者内容坏了都返回 default，不抛异常。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path, data, indent=2):
    """把对象写成 json 文件，父目录不存在会自动建。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def append_jsonl(path, rows):
    """追加写 JSON Lines（一行一个 json）。弹幕数据量大，用这个格式方便边抓边存。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path):
    """读 JSON Lines 文件，个别行坏了就跳过。"""
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


class Timer:
    """用来统计一段代码跑了多久。

    用法：
        with Timer("清洗弹幕", logger) as t:
            ...
        print(t.elapsed)
    """

    def __init__(self, label, logger=None):
        self.label = label
        self.logger = logger
        self.start = 0.0
        self.elapsed = 0.0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.elapsed = time.perf_counter() - self.start
        if self.logger:
            self.logger.info("%s 耗时 %.3f 秒", self.label, self.elapsed)


# 匹配连续空白、零宽字符
_multi_space = re.compile(r"\s+")
_invisible = re.compile(r"[\u200b-\u200f\ufeff]")


def normalize_text(text):
    """弹幕文本的基本清理：去掉零宽字符、把连续空白压成一个、去首尾空格。

    零宽字符是 B 站上绕过关键词检测的常见手段，必须清掉。
    """
    if not text:
        return ""
    text = _invisible.sub("", str(text))
    text = _multi_space.sub(" ", text)
    return text.strip()
