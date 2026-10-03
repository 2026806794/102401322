"""爬虫测试：wbi 签名、弹幕解析、请求重试。

里面测的都是纯函数或者用替身对象驱动的逻辑，不联网也能跑。
当初把这些解析函数从客户端类里拆出来，就是为了能这样单独测。
"""

from __future__ import annotations

import zlib

import pytest

from src.crawler.bilibili_client import (
    BilibiliAPIError,
    parse_danmaku_proto,
    parse_danmaku_xml,
    strip_search_highlight,
)
from src.crawler.danmaku_fetcher import _parse_duration
from src.crawler.wbi import extract_key_from_url, get_mixin_key, sign_params


class TestWbiSigning:
    """wbi 签名：置换表、密钥提取与签名确定性。"""

    def test_extract_key_from_url(self) -> None:
        """应从 wbi 图片 URL 中截取出 32 位密钥。"""
        url = "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png"
        assert extract_key_from_url(url) == "7cd084941338484aae1ad9425b84077c"

    def test_get_mixin_key_is_deterministic_and_32_chars(self) -> None:
        """mixin_key 长度固定为 32，且同样输入得到同样结果。"""
        img_key = "7cd084941338484aae1ad9425b84077c"
        sub_key = "4932caff0ff746eab6f01bf08b70ac45"
        first = get_mixin_key(img_key, sub_key)
        assert len(first) == 32
        assert first == get_mixin_key(img_key, sub_key)

    def test_get_mixin_key_rejects_short_keys(self) -> None:
        """边界值：密钥长度不足时应显式抛错，而不是静默产出错误签名。"""
        with pytest.raises(ValueError):
            get_mixin_key("short", "key")

    def test_sign_params_adds_wts_and_w_rid(self) -> None:
        """签名结果必须包含 wts 与 32 位十六进制的 w_rid。"""
        signed = sign_params(
            {"keyword": "大模型", "page": 1},
            "7cd084941338484aae1ad9425b84077c",
            "4932caff0ff746eab6f01bf08b70ac45",
            timestamp=1700000000,
        )
        assert signed["wts"] == 1700000000
        assert len(str(signed["w_rid"])) == 32
        assert int(str(signed["w_rid"]), 16) >= 0        # 合法十六进制

    def test_sign_params_is_reproducible_for_fixed_timestamp(self) -> None:
        """固定时间戳下签名可复现（便于回归测试）。"""
        args = ("7cd084941338484aae1ad9425b84077c", "4932caff0ff746eab6f01bf08b70ac45")
        first = sign_params({"keyword": "LLM"}, *args, timestamp=1700000000)
        second = sign_params({"keyword": "LLM"}, *args, timestamp=1700000000)
        assert first == second

    def test_sign_params_filters_special_characters(self) -> None:
        """参数值中的 !'()* 必须被过滤掉，否则服务端校验失败。"""
        signed = sign_params(
            {"keyword": "a!b'c(d)e*f"},
            "7cd084941338484aae1ad9425b84077c",
            "4932caff0ff746eab6f01bf08b70ac45",
            timestamp=1700000000,
        )
        assert signed["keyword"] == "abcdef"


class TestDanmakuXmlParsing:
    """XML 弹幕通道：deflate 解压与属性字段解析。"""

    @staticmethod
    def _make_payload(items: list[tuple[str, str]]) -> bytes:
        """把 (p 属性, 正文) 列表打包成 deflate 压缩的 XML。"""
        body = "".join(f'<d p="{param}">{text}</d>' for param, text in items)
        xml = f"<i><chatserver>chat.bilibili.com</chatserver>{body}</i>".encode("utf-8")
        compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
        return compressor.compress(xml) + compressor.flush()

    def test_parse_deflated_xml(self) -> None:
        """标准场景：deflate 压缩流应被正确解压并解析出弹幕。"""
        payload = self._make_payload([
            ("10.5,1,25,16777215,1700000000,0,abc123,1001", "大模型真好用"),
            ("20.0,4,25,16711680,1700000001,0,def456,1002", "太强了"),
        ])
        records = parse_danmaku_xml(payload)
        assert len(records) == 2
        assert records[0]["text"] == "大模型真好用"
        assert records[0]["time"] == 10.5
        assert records[0]["mode"] == 1
        assert records[0]["color"] == 16777215
        assert records[0]["uid_hash"] == "abc123"

    def test_parse_plain_xml_fallback(self) -> None:
        """边界场景：未压缩的明文 XML 也应能解析（接口偶发不压缩）。"""
        xml = '<i><d p="1.0,1,25,16777215,1700000000,0,xyz,1">明文弹幕</d></i>'.encode("utf-8")
        records = parse_danmaku_xml(xml)
        assert len(records) == 1
        assert records[0]["text"] == "明文弹幕"

    def test_parse_empty_content(self) -> None:
        """边界值：空内容返回空列表，不应抛异常。"""
        assert parse_danmaku_xml(b"") == []

    def test_malformed_items_are_skipped(self) -> None:
        """异常处理：属性字段不足的弹幕应被跳过而非中断解析。"""
        payload = self._make_payload([("1.0,1,25", "坏数据"), ("2.0,1,25,16777215,1,0,h,1", "好数据")])
        records = parse_danmaku_xml(payload)
        assert len(records) == 1
        assert records[0]["text"] == "好数据"


class TestDanmakuProtoParsing:
    """protobuf 弹幕通道：手写 varint 解析器的正确性。"""

    @staticmethod
    def _varint(value: int) -> bytes:
        out = bytearray()
        while True:
            byte = value & 0x7F
            value >>= 7
            out.append(byte | (0x80 if value else 0))
            if not value:
                return bytes(out)

    @classmethod
    def _elem(cls, progress_ms: int, mode: int, color: int, text: str) -> bytes:
        content = text.encode("utf-8")
        body = (
            b"\x10" + cls._varint(progress_ms)
            + b"\x18" + cls._varint(mode)
            + b"\x28" + cls._varint(color)
            + b"\x3a" + cls._varint(len(content)) + content
        )
        return b"\x0a" + cls._varint(len(body)) + body

    def test_parse_proto_elements(self) -> None:
        """标准场景：解析出毫秒时间、模式、颜色与正文。"""
        payload = self._elem(12500, 1, 16777215, "大模型弹幕") + self._elem(30000, 4, 16711680, "底部弹幕")
        records = parse_danmaku_proto(payload)
        assert len(records) == 2
        assert records[0]["time"] == 12.5
        assert records[0]["text"] == "大模型弹幕"
        assert records[1]["mode"] == 4
        assert records[1]["color"] == 16711680

    def test_parse_empty_proto(self) -> None:
        """边界值：空字节串返回空列表。"""
        assert parse_danmaku_proto(b"") == []

    def test_unknown_fields_are_skipped(self) -> None:
        """健壮性：出现未知字段类型时不应死循环或崩溃。"""
        payload = self._elem(1000, 1, 0, "abc") + b"\x7d\x01\x02"
        records = parse_danmaku_proto(payload)
        assert len(records) == 1
        assert records[0]["text"] == "abc"


class TestDanmakuChannelFallback:
    """三级弹幕通道的降级和熔断。

    用一个假的客户端控制每次调用成功还是失败，检查通道顺序对不对、
    连续失败之后会不会熔断、以及零弹幕的视频会不会被提前短路掉。
    """

    @staticmethod
    def _crawler(tmp_path, client):
        from src.config import CrawlerConfig
        from src.crawler.danmaku_fetcher import DanmakuCrawler

        return DanmakuCrawler(
            client=client,
            config=CrawlerConfig(channel_failure_limit=2, max_segments=2),
            raw_dir=tmp_path,
        )

    def test_zero_expected_total_short_circuits(self, tmp_path) -> None:
        """弹幕总数为 0 的视频不应发起任何弹幕请求（近期新视频常见）。"""

        class _NoCallClient:
            def __getattr__(self, name: str):
                raise AssertionError(f"不应调用 {name}")

        crawler = self._crawler(tmp_path, _NoCallClient())
        records, source = crawler._fetch_danmaku_by_cid(123, duration=600, expected_total=0)
        assert records == []
        assert source == ""

    def test_prefers_comment_channel(self, tmp_path) -> None:
        """主通道可用时应直接返回，不再尝试后续通道。"""

        class _Client:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def fetch_danmaku_comment_xml(self, cid: int):
                self.calls.append("comment")
                return [{"time": 1.0, "text": f"弹幕{i}"} for i in range(120)]

            def fetch_danmaku_xml(self, cid: int):
                self.calls.append("list")
                return []

            def fetch_danmaku_segment(self, cid: int, index: int = 1):
                self.calls.append("seg")
                return []

        client = _Client()
        crawler = self._crawler(tmp_path, client)
        records, source = crawler._fetch_danmaku_by_cid(1, duration=600, expected_total=200)
        assert source == "comment.xml"
        assert len(records) == 120
        assert client.calls == ["comment"]

    def test_falls_back_and_trips_circuit_breaker(self, tmp_path) -> None:
        """主通道连续失败到阈值后应被熔断，后续直接走下一通道。"""

        class _Client:
            def __init__(self) -> None:
                self.comment_calls = 0
                self.seg_calls = 0

            def fetch_danmaku_comment_xml(self, cid: int):
                self.comment_calls += 1
                raise BilibiliAPIError(-1, "412 Precondition Failed")

            def fetch_danmaku_xml(self, cid: int):
                raise BilibiliAPIError(-1, "412 Precondition Failed")

            def fetch_danmaku_segment(self, cid: int, index: int = 1):
                self.seg_calls += 1
                return [{"time": float(index), "text": f"分段{index}"}]

        client = _Client()
        crawler = self._crawler(tmp_path, client)

        # 前两次：主通道各尝试一次，失败后由分段通道兜底
        for cid in (1, 2):
            records, source = crawler._fetch_danmaku_by_cid(cid, duration=600, expected_total=50)
            assert source == "seg.so"
            assert records
        assert client.comment_calls == 2

        # 第三次：熔断已生效，不再调用主通道
        crawler._fetch_danmaku_by_cid(3, duration=600, expected_total=50)
        assert client.comment_calls == 2, "熔断后不应再调用已失效的通道"

    def test_empty_result_does_not_set_source(self, tmp_path) -> None:
        """通道返回空数据时不应把 source 记成该通道（避免误报数据来源）。"""

        class _Client:
            def fetch_danmaku_comment_xml(self, cid: int):
                return []

            def fetch_danmaku_xml(self, cid: int):
                return []

            def fetch_danmaku_segment(self, cid: int, index: int = 1):
                return []

        crawler = self._crawler(tmp_path, _Client())
        records, source = crawler._fetch_danmaku_by_cid(1, duration=600, expected_total=50)
        assert records == []
        assert source == ""


class TestSegmentFallbackDecision:
    """分段兜底的触发条件（避免为"本来就没弹幕"的视频白跑十几次请求）。"""

    @pytest.mark.parametrize(
        ("records", "expected", "need"),
        [
            ([], 0, True),                       # 通道全挂：必须兜底
            ([], 500, True),
            ([{"text": "a"}] * 30, 30, False),   # 拿到了全部：不该再抓
            ([{"text": "a"}] * 80, 90, False),   # 数量偏少但总数不大：不值得
            ([{"text": "a"}] * 40, 500, True),   # 相对总数明显偏少：疑似截断
            ([{"text": "a"}] * 300, 500, False),  # 超过一半：认为完整
        ],
    )
    def test_decision_table(self, records: list[dict], expected: int, need: bool) -> None:
        from src.crawler.danmaku_fetcher import DanmakuCrawler

        assert DanmakuCrawler._need_segment_fallback(records, expected) is need


class TestRequestRetryAndErrors:
    """请求的重试和错误处理。

    用假的响应对象喂给客户端，不发真实请求；同时把 time.sleep 换掉，
    不然测试会真的等指数退避那几十秒。
    """

    @staticmethod
    def _client(monkeypatch, responses: list):
        import src.crawler.bilibili_client as module
        from src.config import CrawlerConfig
        from src.crawler.bilibili_client import BilibiliClient

        client = BilibiliClient(CrawlerConfig(max_retries=3, block_cooldown=(0.0, 0.0)))
        queue = list(responses)

        def fake_get(url, params=None, timeout=None):
            item = queue.pop(0) if queue else responses[-1]
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(client.session, "get", fake_get)
        monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
        return client

    def test_returns_data_on_success(self, monkeypatch) -> None:
        """正常响应应直接返回 data 字段。"""
        client = self._client(monkeypatch, [_FakeResponse(payload={"code": 0, "data": {"ok": 1}})])
        assert client._request("https://example.com") == {"ok": 1}

    def test_retries_transient_412_then_succeeds(self, monkeypatch) -> None:
        """限流 412 属于可恢复错误，重试成功即返回数据。"""
        client = self._client(monkeypatch, [
            _FakeResponse(status=412),
            _FakeResponse(payload={"code": 0, "data": {"ok": 2}}),
        ])
        assert client._request("https://example.com") == {"ok": 2}

    def test_raises_after_exhausting_retries(self, monkeypatch) -> None:
        """连续失败到上限后应抛出 BilibiliAPIError，而不是静默返回空。"""
        client = self._client(monkeypatch, [_FakeResponse(status=412)])
        with pytest.raises(BilibiliAPIError):
            client._request("https://example.com")

    def test_business_error_raises_without_retry(self, monkeypatch) -> None:
        """业务错误码（如稿件不可见 62002）应立即失败，重试没有意义。"""
        client = self._client(monkeypatch, [
            _FakeResponse(payload={"code": 62002, "message": "稿件不可见"}),
            _FakeResponse(payload={"code": 0, "data": {}}),
        ])
        with pytest.raises(BilibiliAPIError) as excinfo:
            client._request("https://example.com")
        assert excinfo.value.code == 62002

    def test_accept_codes_are_tolerated(self, monkeypatch) -> None:
        """nav 接口未登录返回 -101，但密钥仍可用，因此需显式接受该码。"""
        client = self._client(monkeypatch, [
            _FakeResponse(payload={"code": -101, "data": {"wbi_img": {}}}),
        ])
        assert client._request("https://example.com", accept_codes=(-101,)) == {"wbi_img": {}}

    def test_raw_mode_returns_bytes(self, monkeypatch) -> None:
        """raw=True 时返回原始字节流（弹幕压缩数据走这条路径）。"""
        client = self._client(monkeypatch, [_FakeResponse(content=b"<i></i>")])
        assert client._request("https://example.com", raw=True) == b"<i></i>"

    def test_retries_parameter_overrides_default(self, monkeypatch) -> None:
        """弹幕接口可指定更少的重试次数，以节省退避时间。"""
        import src.crawler.bilibili_client as module

        client = self._client(monkeypatch, [_FakeResponse(status=412)])
        calls: list[float] = []
        monkeypatch.setattr(module.time, "sleep", lambda seconds: calls.append(seconds))
        with pytest.raises(BilibiliAPIError):
            client._request("https://example.com", raw=True, retries=1)
        assert len(calls) == 1, "指定 retries=1 时只应重试一次"


class _FakeResponse:
    """替身 HTTP 响应，用于在不联网的情况下驱动客户端逻辑。"""

    def __init__(self, status: int = 200, payload: dict | None = None,
                 content: bytes = b"") -> None:
        self.status_code = status
        self._payload = payload or {}
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            error = requests.HTTPError(f"{self.status_code} Client Error")
            error.response = self          # type: ignore[assignment]
            raise error

    def json(self) -> dict:
        return self._payload


class TestHelpers:
    """辅助函数：标题高亮清理与时长解析。"""

    def test_strip_search_highlight(self) -> None:
        """搜索结果标题中的 <em> 高亮标签应被移除并反转义。"""
        raw = '【全748集】<em class="keyword">大模型</em>教程 &amp; 实战'
        assert strip_search_highlight(raw) == "【全748集】大模型教程 & 实战"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("12:34", 754), ("1:02:03", 3723), ("0:45", 45), (90, 90), ("", 0), ("abc", 0)],
    )
    def test_parse_duration(self, raw, expected: int) -> None:
        """时长解析：mm:ss、h:mm:ss、纯秒数与非法输入。"""
        assert _parse_duration(raw) == expected
