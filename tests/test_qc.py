"""
plugins/qc/basic_qc.py 集成测试
═════════════════════════════════════════════════════════════════
使用短测试视频，验证 BasicQC.check() 返回完整质检结构。
"""
import os

import pytest

from core.interfaces import VideoContext
from plugins.qc.basic_qc import BasicQC
from utils.video_util import get_video_duration


# 复用 video_util 测试的测试视频
_TEST_VIDEO = "/tmp/cerno_test_5s.mp4"


@pytest.fixture(scope="module")
def test_video():
    """确保测试视频存在（与 test_video_util 共用）。"""
    if not os.path.exists(_TEST_VIDEO):
        import subprocess
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "testsrc=duration=5:size=640x480:rate=10",
            "-f", "lavfi",
            "-i", "sine=frequency=440:duration=5",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-shortest",
            _TEST_VIDEO,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    yield _TEST_VIDEO


class TestBasicQC:
    """BasicQC 质检流程完整性。"""

    async def test_check_returns_full_structure(self, test_video):
        qc = BasicQC()
        ctx = VideoContext(video_id="qc-test", file_path=test_video)
        result = await qc.check(ctx)

        # ── 顶层键 ──
        assert isinstance(result, dict)
        assert "is_valid" in result
        assert "estimated_duration" in result
        assert "black_segments" in result
        assert "silent_segments" in result
        assert "overexposed_segments" in result

        # ── 类型断言 ──
        assert isinstance(result["is_valid"], bool)
        assert isinstance(result["estimated_duration"], float)
        assert isinstance(result["black_segments"], list)
        assert isinstance(result["silent_segments"], list)
        assert isinstance(result["overexposed_segments"], list)

    async def test_estimated_duration_matches(self, test_video):
        qc = BasicQC()
        ctx = VideoContext(video_id="qc-dur", file_path=test_video)
        result = await qc.check(ctx)

        expected = await get_video_duration(test_video)
        assert abs(result["estimated_duration"] - expected) < 0.5, (
            f"estimated_duration({result['estimated_duration']}) "
            f"应与 get_video_duration({expected}) 接近"
        )
