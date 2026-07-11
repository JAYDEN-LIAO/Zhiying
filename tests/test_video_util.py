"""
utils/video_util.py 集成测试
═════════════════════════════════════════════════════════════════
使用 FFmpeg 生成的短测试视频，验证抽取音频、获取时长、
关键帧提取、不存在的视频路径等场景。
"""
import os
import shutil

import pytest

from utils.video_util import extract_audio, get_video_duration, extract_keyframes
from core.exceptions import PipelineError


# ── 全局测试视频路径（各测试共享） ──
_TEST_VIDEO = "/tmp/cerno_test_5s.mp4"
_TEST_AUDIO = "/tmp/cerno_test_audio.wav"
_TEST_KF_DIR = "/tmp/cerno_test_kf"


@pytest.fixture(scope="module")
def test_video():
    """生成 5 秒测试视频（一次创建，模块级共享）。"""
    if not os.path.exists(_TEST_VIDEO):
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
        import subprocess
        subprocess.run(cmd, check=True, capture_output=True)
    yield _TEST_VIDEO
    # 模块级清理在最后一个测试完成后
    # 不立即删除，供其他测试模块复用


@pytest.fixture(autouse=True)
def _clean_artifacts():
    """每个测试前清理之前残留的音频／关键帧产物。"""
    for p in [_TEST_AUDIO, _TEST_KF_DIR]:
        if os.path.exists(p):
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
    yield


class TestExtractAudio:
    """extract_audio 输出 WAV 文件验证。"""

    async def test_extract_audio_success(self, test_video):
        await extract_audio(test_video, _TEST_AUDIO)
        assert os.path.exists(_TEST_AUDIO), "WAV 文件应已生成"
        assert os.path.getsize(_TEST_AUDIO) > 0, "WAV 文件大小应 > 0"

    async def test_extract_audio_nonexistent_video(self):
        with pytest.raises(PipelineError, match="FFmpeg extract_audio failed"):
            await extract_audio("/tmp/__nonexistent_video__.mp4", _TEST_AUDIO)


class TestGetVideoDuration:
    """get_video_duration 准确性验证。"""

    async def test_duration_positive_and_close(self, test_video):
        duration = await get_video_duration(test_video)
        assert isinstance(duration, float)
        assert duration > 0
        # 5 秒视频，允许 1 秒误差
        assert 4.0 <= duration <= 6.0, f"时长应在 5s 附近，实际 {duration}s"

    async def test_duration_nonexistent_video(self):
        with pytest.raises(PipelineError, match="FFprobe failed"):
            await get_video_duration("/tmp/__nonexistent_video__.mp4")


class TestExtractKeyframes:
    """extract_keyframes 输出关键帧 JPEG 文件验证。"""

    async def test_extract_three_keyframes(self, test_video):
        scenes = [
            {"start_sec": 0.0, "end_sec": 1.5},
            {"start_sec": 1.5, "end_sec": 3.0},
            {"start_sec": 3.0, "end_sec": 5.0},
        ]
        paths = await extract_keyframes(test_video, scenes, _TEST_KF_DIR)

        assert len(paths) == 3, "应返回 3 个文件路径"
        for i, path in enumerate(paths):
            assert os.path.exists(path), f"scene_{i:04d}.jpg 应存在: {path}"
            assert os.path.getsize(path) > 0, f"scene_{i:04d}.jpg 大小应 > 0"
            assert path.endswith(".jpg")

    async def test_extract_keyframes_nonexistent_video(self):
        scenes = [{"start_sec": 0.0, "end_sec": 2.0}]
        with pytest.raises(PipelineError, match="FFmpeg extract_keyframe_at failed"):
            await extract_keyframes("/tmp/__nonexistent__.mp4", scenes, _TEST_KF_DIR)
