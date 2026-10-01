"""B站 wbi 接口签名。

2023 年之后 B站 web 端的接口大部分都要带 w_rid 和 wts 两个参数，
不带就会返回 -403 或 -412。签名算法是前端 js 里的，我照着它的逻辑用 Python 重写了一遍：

    1. 先请求 nav 接口，拿到 img_url 和 sub_url，把文件名（去掉 .png）截出来，
       分别叫 img_key 和 sub_key；
    2. 把两个 key 拼成一个 64 位的字符串，按下面这张固定的置换表重新排列，
       取前 32 位，得到 mixin_key（这个 key 每天会换）；
    3. 请求参数里加上时间戳 wts，按参数名的字母顺序排好，
       并且把值里的 !'()* 这几个字符去掉；
    4. 把排好的参数拼成 query 字符串，后面接上 mixin_key，算 md5，就是 w_rid。

这里的函数都是纯函数（不联网），所以可以直接写单元测试。
"""

import hashlib
import time
from urllib.parse import urlencode

# 前端里写死的置换表，共 64 个位置
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# 参与签名的参数值里需要过滤掉的字符
FILTER_CHARS = "!'()*"


def extract_key_from_url(url):
    """从 wbi 图片地址里截出 key。

    例：https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png
        -> 7cd084941338484aae1ad9425b84077c
    """
    filename = url.rsplit("/", 1)[-1]      # 取最后一段
    return filename.rsplit(".", 1)[0]      # 去掉扩展名


def get_mixin_key(img_key, sub_key):
    """把 img_key + sub_key 按置换表打乱，取前 32 位作为 mixin_key。"""
    raw = img_key + sub_key
    if len(raw) < 64:
        # 长度不够说明 key 拿错了，直接报错比默默算出个错的签名好
        raise ValueError("img_key/sub_key 长度不足，无法生成 mixin_key")

    shuffled = ""
    for index in MIXIN_KEY_ENC_TAB:
        shuffled += raw[index]
    return shuffled[:32]


def sign_params(params, img_key, sub_key, timestamp=None):
    """给请求参数加上 wts 和 w_rid。

    参数：
        params    —— 原始参数字典
        img_key   —— nav 接口返回的 img_key
        sub_key   —— nav 接口返回的 sub_key
        timestamp —— 时间戳，传进来是为了测试时能固定住结果

    返回一个新的字典（不修改传进来的 params）。
    """
    mixin_key = get_mixin_key(img_key, sub_key)

    # 先把参数值的特殊字符过滤掉
    signed = {}
    for key, value in params.items():
        cleaned = ""
        for ch in str(value):
            if ch not in FILTER_CHARS:
                cleaned += ch
        signed[key] = cleaned

    # 加时间戳，然后按参数名排序
    if timestamp is None:
        timestamp = time.time()
    signed["wts"] = int(timestamp)

    sorted_keys = sorted(signed.keys())
    ordered = {}
    for key in sorted_keys:
        ordered[key] = signed[key]

    query = urlencode(ordered)
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return signed
