"""
pipeline/phase5_summary.py 单元测试
═════════════════════════════════════════════════════════════════
Mock summarizer，验证 script 构建、summary 赋值、prompt 传入。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.interfaces import VideoContext, Scene as SceneData
from core.prompt_loader import PromptLoader
from core.schemas import VideoSummary
from pipeline.phase5_summary import Phase5Summary


def _make_scene(i: int, start: float, end: float, caption="", ocr="", transcript="") -> SceneData:
    return SceneData(
        scene_id=i, scene_index=i,
        start_sec=start, end_sec=end,
        keyframe=None,
        caption=caption, ocr_text=ocr, aligned_transcript=transcript,
    )


class TestPhase5Summary:
    """Phase5 LLM 摘要生成。"""

    FAKE_SUMMARY = {
        "one_liner": "测试摘要",
        "scenes_summary": [],
        "tags": ["test"],
        "main_topics": ["topic"],
        "main_entities": ["entity"],
    }

    @pytest.fixture
    def ctx(self):
        ctx = VideoContext(video_id="p5", file_path="/tmp/p5.mp4")
        ctx.transcript_full = "大家好 这是功能 谢谢观看"
        ctx.scenes = [
            _make_scene(0, 0.0, 10.0, caption="开场", ocr="标题", transcript="大家好"),
            _make_scene(1, 10.0, 20.0, caption="演示", ocr="代码", transcript="这是功能"),
            _make_scene(2, 20.0, 30.0, caption="结尾", ocr="LOGO", transcript="谢谢观看"),
        ]
        return ctx

    @pytest.fixture
    def mock_summarizer(self):
        m = AsyncMock()
        m.summarize.return_value = dict(self.FAKE_SUMMARY)
        return m

    @pytest.fixture
    def pl(self):
        return PromptLoader()

    @pytest.fixture
    def tracker(self):
        return AsyncMock()

    async def test_script_contains_all_scenes(self, ctx, mock_summarizer, pl, tracker):
        """script 应包含所有 3 个场景的 caption/ocr/transcript。"""
        engine = Phase5Summary(ctx, {"summarizer": mock_summarizer}, {}, tracker, pl)
        await engine.execute()

        # 验证传给 summarize 的 script 包含每个场景的信息
        call_args = mock_summarizer.summarize.call_args
        assert call_args is not None, "summarize 应被调用"
        script = call_args[0][0]  # 第一个位置参数
        assert isinstance(script, str)
        assert "开场" in script
        assert "标题" in script
        assert "大家好" in script
        assert "演示" in script
        assert "代码" in script
        assert "这是功能" in script
        assert "结尾" in script

    async def test_summary_assigned(self, ctx, mock_summarizer, pl, tracker):
        engine = Phase5Summary(ctx, {"summarizer": mock_summarizer}, {}, tracker, pl)
        await engine.execute()
        assert ctx.summary is not None
        assert ctx.summary["one_liner"] == "测试摘要"

    async def test_system_and_user_prompts_nonempty(self, ctx, mock_summarizer, pl, tracker):
        engine = Phase5Summary(ctx, {"summarizer": mock_summarizer}, {}, tracker, pl)
        await engine.execute()

        call_args = mock_summarizer.summarize.call_args
        script, system_prompt, user_prompt = call_args[0]
        assert isinstance(system_prompt, str) and len(system_prompt) > 0
        assert isinstance(user_prompt, str) and len(user_prompt) > 0

    async def test_no_crash_without_summarizer(self, ctx, pl, tracker):
        engine = Phase5Summary(ctx, {"summarizer": None}, {}, tracker, pl)
        await engine.execute()
        assert ctx.summary is None

    async def test_no_crash_without_scenes(self, mock_summarizer, pl, tracker):
        ctx = VideoContext(video_id="p5", file_path="/tmp/p5.mp4")
        ctx.scenes = []
        engine = Phase5Summary(ctx, {"summarizer": mock_summarizer}, {}, tracker, pl)
        await engine.execute()
        assert mock_summarizer.summarize.await_count == 0
