"""
pipeline/phase4_caption.py 单元测试
═════════════════════════════════════════════════════════════════
Mock captioner / embedder，验证 caption 调用次数、prev_caption 记忆传递、embedding 填充。
"""
import numpy as np
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.interfaces import VideoContext, Scene as SceneData
from core.prompt_loader import PromptLoader
from pipeline.phase4_caption import Phase4Caption


def _make_scene(i: int, start: float, end: float) -> SceneData:
    return SceneData(
        scene_id=i, scene_index=i,
        start_sec=start, end_sec=end,
        keyframe=np.full((10, 10, 3), 100, dtype=np.uint8),
    )


class TestPhase4Caption:
    """Phase4 深度描述 + 向量编码。"""

    @pytest.fixture
    def ctx(self):
        ctx = VideoContext(video_id="p4", file_path="/tmp/p4.mp4")
        ctx.scenes = [_make_scene(0, 0.0, 10.0),
                       _make_scene(1, 10.0, 20.0),
                       _make_scene(2, 20.0, 30.0)]
        return ctx

    @pytest.fixture
    def mock_captioner(self):
        m = AsyncMock()
        m.caption.return_value = "描述文本"
        return m

    @pytest.fixture
    def mock_embedder(self):
        m = AsyncMock()
        m.encode_image.return_value = [0.1] * 768
        return m

    @pytest.fixture
    def pl(self):
        return PromptLoader()

    @pytest.fixture
    def tracker(self):
        return AsyncMock()

    async def test_captioner_called_3_times(self, ctx, mock_captioner, mock_embedder, pl, tracker):
        plugins = {"captioner": mock_captioner, "embedder": mock_embedder}
        engine = Phase4Caption(ctx, plugins, {}, tracker, pl)
        await engine.execute()
        assert mock_captioner.caption.await_count == 3, (
            f"captioner.caption 应被调用 3 次，实际 {mock_captioner.caption.await_count}"
        )

    async def test_prev_caption_passed(self, ctx, mock_captioner, mock_embedder, pl, tracker):
        plugins = {"captioner": mock_captioner, "embedder": mock_embedder}
        # 让 captioner 每次返回不同的值
        mock_captioner.caption.side_effect = ["描述0", "描述1", "描述2"]
        engine = Phase4Caption(ctx, plugins, {}, tracker, pl)
        await engine.execute()
        # scene[1].prev_caption == scene[0].caption
        assert ctx.scenes[1].prev_caption == "描述0", (
            f"scene[1].prev_caption 应为 '描述0'，实际 '{ctx.scenes[1].prev_caption}'"
        )
        assert ctx.scenes[2].prev_caption == "描述1"

    async def test_embedding_filled(self, ctx, mock_captioner, mock_embedder, pl, tracker):
        plugins = {"captioner": mock_captioner, "embedder": mock_embedder}
        engine = Phase4Caption(ctx, plugins, {}, tracker, pl)
        await engine.execute()
        for i, scene in enumerate(ctx.scenes):
            assert scene.embedding is not None, f"scene[{i}] embedding 不应为 None"
            assert len(scene.embedding) == 768, f"scene[{i}] embedding 应为 768 维"

    async def test_no_crash_without_captioner(self, ctx, mock_embedder, pl, tracker):
        plugins = {"captioner": None, "embedder": mock_embedder}
        engine = Phase4Caption(ctx, plugins, {}, tracker, pl)
        await engine.execute()
        for scene in ctx.scenes:
            assert scene.caption is None
            assert scene.embedding is not None
