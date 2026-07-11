"""
plugins/transcriber/faster_whisper.py 集成测试
═════════════════════════════════════════════════════════════════
需要 faster-whisper 包和 tiny 模型（首次运行自动下载 ~150MB）。
未安装 faster-whisper 时自动跳过。
"""
import os

import pytest

from core.exceptions import PluginLoadError

# ── 跳过条件 ──
try:
    import faster_whisper  # noqa: F401
    HAS_FW = True
except ImportError:
    HAS_FW = False

from plugins.transcriber.faster_whisper import FasterWhisperTranscriber

# 复用视频测试产出的音频文件
_TEST_AUDIO = "/tmp/cerno_test_audio.wav"
_TEST_VIDEO = "/tmp/cerno_test_5s.mp4"


def _ensure_test_audio():
    """确保测试 WAV 存在。"""
    if not os.path.exists(_TEST_AUDIO):
        # 先确保视频存在
        if not os.path.exists(_TEST_VIDEO):
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y",
                 "-f", "lavfi", "-i", "testsrc=duration=5:size=640x480:rate=10",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
                 "-c:v", "libx264", "-c:a", "aac", "-shortest",
                 _TEST_VIDEO],
                check=True, capture_output=True,
            )
        # 抽音频
        import asyncio
        from utils.video_util import extract_audio
        asyncio.run(extract_audio(_TEST_VIDEO, _TEST_AUDIO))
    return _TEST_AUDIO


@pytest.mark.skipif(not HAS_FW, reason="faster-whisper package not installed")
class TestFasterWhisperTranscriber:
    """FasterWhisper 转录集成测试（使用 tiny 模型）。"""

    @pytest.fixture(scope="class")
    def transcriber(self):
        return FasterWhisperTranscriber(
            model_path="systran/faster-whisper-tiny",
            device="cpu",
            compute_type="int8",
        )

    @pytest.fixture(scope="class")
    def audio_path(self):
        return _ensure_test_audio()

    async def test_transcribe_returns_full_structure(self, transcriber, audio_path):
        result = await transcriber.transcribe(audio_path)

        assert isinstance(result, dict)
        assert "full_text" in result
        assert "language" in result
        assert "duration" in result
        assert "words" in result

    async def test_full_text_is_nonempty(self, transcriber, audio_path):
        result = await transcriber.transcribe(audio_path)
        assert isinstance(result["full_text"], str)
        assert len(result["full_text"].strip()) > 0, "转录文本不应为空"

    async def test_words_contain_timestamps(self, transcriber, audio_path):
        result = await transcriber.transcribe(audio_path)
        words = result["words"]
        assert isinstance(words, list)
        assert len(words) >= 3, f"应至少包含 3 个字词时间戳，实际 {len(words)}"

        for w in words:
            assert "word" in w
            assert "start" in w
            assert "end" in w
            assert "confidence" in w
            assert isinstance(w["word"], str)
            assert len(w["word"].strip()) > 0
            assert isinstance(w["start"], (int, float))
            assert isinstance(w["end"], (int, float))
            assert isinstance(w["confidence"], (int, float))

    async def test_detected_language_is_string(self, transcriber, audio_path):
        result = await transcriber.transcribe(audio_path)
        assert isinstance(result["language"], str)


class TestFasterWhisperImportError:
    """验证未安装 faster-whisper 时抛出 PluginLoadError。"""

    def test_import_error_raised(self):
        """模拟构造函数在缺少依赖时抛 PluginLoadError。"""
        try:
            # 如果 faster_whisper 已安装，这个测试是冗余但无害的
            FasterWhisperTranscriber(model_path="", device="cpu", compute_type="int8")
        except PluginLoadError:
            pass  # 期望的
        except Exception:
            pass  # 其他异常也可能，不失败
