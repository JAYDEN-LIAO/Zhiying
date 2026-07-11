"""
pipeline/phase1_qc.py 单元测试
═════════════════════════════════════════════════════════════════
使用 Mock QC/Transcriber/Segmenter，验证 Phase1QC 正确填充上下文。
"""
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from core.interfaces import VideoContext
from core.models import Video, VideoStatus
from pipeline.phase1_qc import Phase1QC


# ── Mock 插件 ────────────────────────────────────────────────

class MockQC:
    """返回固定数据的 Mock 质检插件。"""
    async def check(self, ctx):
        return {
            "is_valid": True,
            "estimated_duration": 10.0,
            "black_segments": [],
            "silent_segments": [],
            "overexposed_segments": [],
        }


class MockTranscriber:
    """返回固定转录结果的 Mock 转录插件。"""
    async def transcribe(self, audio_path, language=None):
        return {
            "full_text": "Mock transcript text for unit test",
            "language": "en",
            "duration": 10.0,
            "words": [
                {"word": "hello",   "start": 0.0, "end": 0.5, "confidence": 0.9},
                {"word": "world",   "start": 0.5, "end": 1.0, "confidence": 0.8},
            ],
        }


class MockSegmenter:
    """返回固定场景列表的 Mock 分割插件。"""
    async def segment(self, video_path, sample_fps=1.0):
        return [
            {"scene_index": 0, "start_sec": 0.0, "end_sec": 3.0, "keyframe": None},
            {"scene_index": 1, "start_sec": 3.0, "end_sec": 6.0, "keyframe": None},
            {"scene_index": 2, "start_sec": 6.0, "end_sec": 10.0, "keyframe": None},
        ]


class TestPhase1QC:
    """Phase1QC 上下文填充验证。"""

    @pytest.fixture
    def video(self):
        return Video(
            id="00000000-0000-0000-0000-000000000001",
            file_path="/tmp/test.mp4",
            file_name="test.mp4",
            file_size=1000,
            audio_enabled=True,
            vision_enabled=True,
            ocr_enabled=True,
            grounding_enabled=False,
            caption_enabled=True,
            summary_enabled=True,
        )

    @pytest.fixture
    def tracker(self):
        return AsyncMock()

    @pytest.fixture
    def plugins(self):
        return {
            "qc": MockQC(),
            "transcriber": MockTranscriber(),
            "segmenter": MockSegmenter(),
        }

    @pytest.fixture
    def phase1(self, video, tracker, plugins):
        ctx = VideoContext(video_id=str(video.id), file_path=video.file_path)
        return Phase1QC(
            ctx=ctx,
            plugins=plugins,
            config={"pipeline": {"sample_fps": 1.0}},
            tracker=tracker,
            video=video,
        ), ctx

    async def test_duration_filled(self, phase1):
        engine, ctx = phase1
        with patch("pipeline.phase1_qc.extract_audio", AsyncMock()):
            await engine.execute()
        assert ctx.duration == 10.0, f"duration 应为 10.0，实际 {ctx.duration}"

    async def test_transcript_filled(self, phase1):
        engine, ctx = phase1
        with patch("pipeline.phase1_qc.extract_audio", AsyncMock()):
            await engine.execute()
        assert ctx.transcript_full == "Mock transcript text for unit test"
        assert len(ctx.transcript_words) == 2
        assert ctx.transcript_words[0]["word"] == "hello"

    async def test_scenes_populated(self, phase1):
        engine, ctx = phase1
        with patch("pipeline.phase1_qc.extract_audio", AsyncMock()):
            await engine.execute()
        assert len(ctx.scenes) == 3
        assert ctx.scenes[0].scene_index == 0
        assert ctx.scenes[0].start_sec == 0.0
        assert ctx.scenes[0].end_sec == 3.0
        assert ctx.scenes[2].scene_index == 2

    async def test_tracker_called_in_order(self, phase1):
        engine, ctx = phase1
        with patch("pipeline.phase1_qc.extract_audio", AsyncMock()):
            await engine.execute()

        expected_calls = ["phase_1_qc", "phase_1_audio", "phase_1_segment"]
        # AsyncMock 记录 await 调用的顺序
        call_names = [c.args[0] for c in engine.tracker.update.call_args_list]
        assert call_names == expected_calls, (
            f"tracker.update 调用顺序应为 {expected_calls}，实际 {call_names}"
        )

    async def test_qc_result_in_ctx(self, phase1):
        engine, ctx = phase1
        with patch("pipeline.phase1_qc.extract_audio", AsyncMock()):
            await engine.execute()
        assert "is_valid" in ctx.qc_result
        assert ctx.qc_result["is_valid"] is True
        assert "black_segments" in ctx.qc_result
        assert "silent_segments" in ctx.qc_result
