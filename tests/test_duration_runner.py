"""DurationRunner 时长探测回退逻辑单测（纯函数，无 ffprobe 依赖）。

回归保护：ffprobe 对损坏/异常文件（如 NVR 私有头录像）返回的 format
可能没有 duration 键——曾直接 `info["format"]["duration"]` 崩 KeyError
导致整条管道失败。此测试锁定多级回退与兜底行为。
"""

from pipeline.runners.duration import _parse_hms, extract_duration


class TestParseHms:
    def test_valid(self):
        assert _parse_hms("00:02:30.000000000") == 150.0
        assert _parse_hms("1:02:03.5") == 3723.5

    def test_invalid(self):
        assert _parse_hms("not-a-time") is None
        assert _parse_hms("12:34") is None
        assert _parse_hms("1:2:3:4") is None


class TestExtractDuration:
    def test_format_duration(self):
        info = {"format": {"duration": "123.45"}, "streams": []}
        assert extract_duration(info) == 123.45

    def test_stream_duration_fallback(self):
        info = {
            "format": {},
            "streams": [
                {"codec_type": "audio", "duration": "999.0"},
                {"codec_type": "video", "duration": "88.5"},
            ],
        }
        assert extract_duration(info) == 88.5

    def test_stream_tag_duration_fallback(self):
        info = {
            "format": {},
            "streams": [
                {"codec_type": "video", "tags": {"DURATION": "00:01:30.000000000"}},
            ],
        }
        assert extract_duration(info) == 90.0

    def test_non_numeric_format_duration_falls_through(self):
        # format.duration 为 "N/A"（不可转 float）→ 落到 stream.duration
        info = {
            "format": {"duration": "N/A"},
            "streams": [{"codec_type": "video", "duration": "10"}],
        }
        assert extract_duration(info) == 10.0

    def test_missing_returns_none(self):
        # 损坏文件：所有来源都拿不到时长 → None（调用方应报清晰错误而非 KeyError）
        info = {"format": {}, "streams": []}
        assert extract_duration(info) is None

    def test_no_format_key_returns_none(self):
        assert extract_duration({}) is None
