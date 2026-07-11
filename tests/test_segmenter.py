"""
plugins/segmenter/transnet_v2.py 集成测试
═════════════════════════════════════════════════════════════════
需要 transnetv2 包（首次运行自动下载模型权重 ~50MB）。
未安装 transnetv2 时自动跳过。
"""
import os

import pytest

# ── 跳过条件 ──
try:
    import transnetv2  # noqa: F401
    HAS_TNV2 = True
except ImportError:
    HAS_TNV2 = False

from plugins.segmenter.transnet_v2 import TransNetV2Segmenter

_TEST_VIDEO = "/tmp/cerno_test_5s.mp4"


def _ensure_test_video():
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
    return _TEST_VIDEO


@pytest.mark.skipif(not HAS_TNV2, reason="transnetv2 package not installed")
class TestTransNetV2Segmenter:
    """TransNetV2 镜头分割集成测试。"""

    @pytest.fixture(scope="class")
    def segmenter(self):
        return TransNetV2Segmenter(device="cpu", scene_min_duration=1.0)

    @pytest.fixture(scope="class")
    def video_path(self):
        return _ensure_test_video()

    async def test_segment_returns_list(self, segmenter, video_path):
        scenes = await segmenter.segment(video_path, sample_fps=1.0)
        assert isinstance(scenes, list)
        assert len(scenes) >= 1, "应至少分割出 1 个场景"

    async def test_each_scene_has_required_keys(self, segmenter, video_path):
        scenes = await segmenter.segment(video_path, sample_fps=1.0)

        for i, scene in enumerate(scenes):
            assert isinstance(scene, dict)
            assert "scene_index" in scene
            assert "start_sec" in scene
            assert "end_sec" in scene
            assert "keyframe" in scene

            # scene_index 从 0 递增
            assert scene["scene_index"] == i, (
                f"scene_index 应递增，第 {i} 个为 {scene['scene_index']}"
            )
            # start_sec >= 0
            assert scene["start_sec"] >= 0.0, (
                f"场景 {i} start_sec({scene['start_sec']}) 应 >= 0"
            )
            # end_sec > start_sec
            assert scene["end_sec"] > scene["start_sec"], (
                f"场景 {i} end_sec({scene['end_sec']}) 应 > start_sec({scene['start_sec']})"
            )
            # 过滤生效：时长 >= scene_min_duration
            duration = scene["end_sec"] - scene["start_sec"]
            assert duration >= 0.95, (
                f"场景 {i} 时长({duration}) 应 >= scene_min_duration(1.0)"
            )

    async def test_keyframe_is_none(self, segmenter, video_path):
        """引擎层后续会统一抽取关键帧，segmenter 返回 None。"""
        scenes = await segmenter.segment(video_path, sample_fps=1.0)
        for scene in scenes:
            assert scene["keyframe"] is None
