"""
utils/video_util.py
═══════════════════════════════════════════════════════════
FFmpeg 工具函数 — 音视频底层操作。

所有 FFmpeg / FFprobe 调用均通过 asyncio.create_subprocess_exec
异步执行，不阻塞事件循环。
"""

import asyncio
import io
import json
import logging
import os

import numpy as np

from core.exceptions import PipelineError

logger = logging.getLogger(__name__)


async def extract_audio(
    video_path: str,
    output_audio_path: str,
) -> None:
    """从视频中抽取音频为 16kHz 单声道 WAV。"""
    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_audio_path,
    ]

    logger.info("[FFmpeg] extract_audio: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace")[:500]
        raise PipelineError(
            f"FFmpeg extract_audio failed (code {proc.returncode}): {error_msg}"
        )
    logger.info("[FFmpeg] Audio extracted → %s", output_audio_path)


async def extract_keyframes(
    video_path: str,
    scenes: list[dict],
    output_dir: str,
) -> list[str]:
    """对每个场景的中点时间戳抽取一帧关键帧 JPEG。"""
    os.makedirs(output_dir, exist_ok=True)
    frame_paths: list[str] = []

    for i, scene in enumerate(scenes):
        midpoint = (scene["start_sec"] + scene["end_sec"]) / 2.0
        output_path = os.path.join(output_dir, f"scene_{i:04d}.jpg")
        await extract_keyframe_at(video_path, midpoint, output_path)
        frame_paths.append(output_path)

    return frame_paths


async def extract_keyframe_at(
    video_path: str,
    time_sec: float,
    output_path: str,
) -> None:
    """在指定时间点抽取一帧 JPEG。

    Args:
        video_path:  输入视频路径。
        time_sec:    时间戳（秒）。
        output_path: 输出 JPEG 路径。

    Raises:
        PipelineError: FFmpeg 失败。
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(time_sec),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "3",
        "-fps_mode", "vfr",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace")[:300]
        raise PipelineError(
            f"FFmpeg extract_keyframe_at failed (code {proc.returncode}): {error_msg}"
        )
    logger.debug("[FFmpeg] Keyframe extracted @ %.2fs → %s", time_sec, output_path)


async def extract_keyframe_to_memory(
    video_path: str,
    time_sec: float,
) -> np.ndarray:
    """在指定时间点抽取一帧，直接返回内存中的 numpy 数组 (H,W,C) uint8。

    使用 FFmpeg pipe 将 JPEG 输出到内存，避免写临时文件。
    后续不会从硬盘读回。

    Args:
        video_path: 输入视频路径。
        time_sec:   时间戳（秒）。

    Returns:
        (H, W, 3) uint8 numpy 数组，适合直接送入 VLM / Embedder 推理。

    Raises:
        PipelineError: FFmpeg 失败或图片解码失败。
    """
    cmd = [
        "ffmpeg",
        "-ss", str(time_sec),
        "-i", video_path,
        "-vframes", "1",
        "-f", "image2pipe",
        "-vcodec", "mjpeg",
        "-q:v", "3",
        "-",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0 or not stdout:
        error_msg = stderr.decode(errors="replace")[:300]
        raise PipelineError(
            f"FFmpeg pipe keyframe failed @ {time_sec}s "
            f"(code {proc.returncode}): {error_msg}"
        )

    try:
        from PIL import Image
        pil_image = Image.open(io.BytesIO(stdout))
        return np.array(pil_image)
    except Exception as e:
        raise PipelineError(
            f"Failed to decode keyframe image @ {time_sec}s: {e}"
        ) from e


async def get_video_duration(video_path: str) -> float:
    """使用 ffprobe 获取视频时长（秒）。"""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    if proc.returncode != 0:
        raise PipelineError(f"FFprobe failed (code {proc.returncode})")

    try:
        data = json.loads(stdout.decode())
        return float(data["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        raise PipelineError(f"Failed to parse ffprobe output: {e}") from e
