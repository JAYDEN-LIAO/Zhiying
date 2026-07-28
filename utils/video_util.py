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
from contextlib import contextmanager

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


async def export_video_segment(
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
    reencode: bool = False,
    video_filters: str | None = None,
) -> None:
    """导出视频片段。

    - reencode=False 且无 video_filters: 使用 -c copy 流复制（极速，无质量损失）
    - reencode=True 或有 video_filters: 重编码为 libx264 (用于 bbox 叠加等场景)

    Args:
        video_path:   输入视频路径。
        start_sec:    起始时间（秒）。
        end_sec:      结束时间（秒）。
        output_path:  输出文件路径。
        reencode:     是否强制重编码。
        video_filters: FFmpeg -vf 滤镜字符串（如 drawbox），设置后自动重编码。

    Raises:
        PipelineError: FFmpeg 执行失败。
    """
    do_reencode = reencode or video_filters is not None

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start_sec),
        "-to", str(end_sec),
        "-i", video_path,
    ]

    if do_reencode:
        cmd += [
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
        ]
        if video_filters:
            cmd += ["-vf", video_filters]
    else:
        cmd += ["-c", "copy"]

    cmd += [
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ]

    logger.info("[FFmpeg] export segment %.1f-%.1f → %s (reencode=%s)",
                start_sec, end_sec, output_path, do_reencode)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace")[:500]
        raise PipelineError(
            f"FFmpeg export segment failed (code {proc.returncode}): {error_msg}"
        )
    logger.info("[FFmpeg] Segment exported → %s", output_path)


# ═══════════════════════════════════════════════════════════
# NVDEC 硬件解码帧流
# ═══════════════════════════════════════════════════════════


async def stream_frames_nvdec(
    video_path: str,
    fps: float = 1.0,
    output_width: int | None = None,
    output_height: int | None = None,
):
    """NVDEC 硬解 → 异步 RGB 帧生成器（MJPEG pipe 传输）。

    GPU 解码 + 缩放（scale_cuda），输出 MJPEG 压缩流（~100KB/帧），
    替代 raw NV12（3.1MB/帧 @ 1080p），消除长视频下的 asyncio pipe I/O 瓶颈。

    Args:
        video_path: 视频文件路径。
        fps: 采样帧率。
        output_width / output_height: 输出分辨率。未指定时使用原始分辨率。

    Yields:
        (H, W, 3) uint8 numpy RGB 帧数组。
    """
    import io as _io
    import numpy as np
    from PIL import Image

    # ── 构建 FFmpeg NVDEC 命令（MJPEG 输出）──
    scale_filter = ""
    if output_width is not None and output_height is not None:
        scale_filter = f",scale_cuda={output_width}:{output_height}"

    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda",
        "-i", video_path,
        "-vf", f"fps={fps}{scale_filter},hwdownload,format=nv12",
        "-c:v", "mjpeg",
        "-q:v", "3",
        "-f", "image2pipe",
        "pipe:1",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    if output_width and output_height:
        logger.info(
            "[NVDEC] Streaming %dx%d @ %.1f fps via NVDEC (MJPEG pipe)",
            output_width, output_height, fps,
        )
    else:
        logger.info(
            "[NVDEC] Streaming @ %.1f fps via NVDEC (MJPEG pipe, native resolution)",
            fps,
        )

    # ── MJPEG 流解析：从 pipe 读取 JPEG 片段 → 解码为 RGB ndarray ──
    _SOI = b'\xff\xd8'   # JPEG Start of Image
    _EOI = b'\xff\xd9'   # JPEG End of Image

    buffer = bytearray()
    try:
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            buffer.extend(chunk)

            # 处理 buffer 中所有完整 JPEG 帧
            while True:
                start = buffer.find(_SOI)
                if start == -1:
                    buffer.clear()
                    break
                if start > 0:
                    del buffer[:start]

                end = buffer.find(_EOI, 2)  # 跳过 SOI 标记
                if end == -1:
                    break  # 帧不完整，等下一块数据

                jpeg_bytes = bytes(buffer[:end + 2])
                del buffer[:end + 2]

                try:
                    pil_img = Image.open(_io.BytesIO(jpeg_bytes))
                    rgb = np.array(pil_img)
                    yield rgb
                except Exception:
                    logger.warning("[NVDEC] JPEG decode failed for one frame, skipping")
                    continue
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            proc.terminate()
        except Exception:
            pass
        await proc.wait()


async def stream_frames_cv2(
    video_path: str,
    fps: float = 1.0,
    target_width: int | None = None,
    target_height: int | None = None,
    total_frames: int | None = None,
):
    """cv2 软件解码 → 异步 RGB 帧生成器（CPU decode，NVDEC 的 fallback）。

    与 stream_frames_nvdec 接口完全一致，可直接互换。
    使用线程 + Queue 实现真正的流式输出，内存上限 = _Q_SIZE 帧，
    而非全部帧常驻内存。

    Args:
        total_frames: 需要抽取的总帧数。传入时使用计数驱动（准确，推荐）；
                      未传入时回退到时长驱动（依赖 CAP_PROP_FRAME_COUNT，不可靠）。
    """
    import asyncio
    import queue
    import threading
    import cv2

    _Q_SIZE = 256       # 缓冲区帧数上限，约 1.5GB @ 1080p
    _SENTINEL = None    # 帧始终是 np.ndarray，None 可安全用作结束信号

    q: queue.Queue = queue.Queue(maxsize=_Q_SIZE)
    reader_error: list[Exception] = []

    def _read() -> None:
        """在线程中运行 — cv2 读帧 → queue，不阻塞事件循环。"""
        cap = None
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return
            source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_idx = 0
            collected = 0
            next_ts = 0.0
            do_resize = target_width is not None and target_height is not None

            if total_frames is not None:
                # ── 计数驱动（准确，不依赖 CAP_PROP_FRAME_COUNT）──
                while collected < total_frames:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    ts = frame_idx / source_fps
                    if ts >= next_ts - 0.001:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        if do_resize:
                            rgb = cv2.resize(
                                rgb, (target_width, target_height),
                                interpolation=cv2.INTER_LINEAR,
                            )
                        q.put(rgb)          # 队列满时阻塞，提供反压
                        collected += 1
                        next_ts += 1.0 / fps
                    frame_idx += 1
            else:
                # ── 时长驱动（legacy fallback）──
                duration = float(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / source_fps
                while next_ts <= duration:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    ts = frame_idx / source_fps
                    if ts >= next_ts - 0.001:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        if do_resize:
                            rgb = cv2.resize(
                                rgb, (target_width, target_height),
                                interpolation=cv2.INTER_LINEAR,
                            )
                        q.put(rgb)
                        next_ts += 1.0 / fps
                    frame_idx += 1
        except Exception as e:
            reader_error.append(e)
        finally:
            if cap is not None:
                cap.release()
            q.put(_SENTINEL)

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()

    while True:
        frame = await asyncio.to_thread(q.get)
        if frame is _SENTINEL:
            break
        yield frame

    thread.join()
    if reader_error:
        raise reader_error[0]


async def stream_frames(
    video_path: str,
    fps: float = 1.0,
    output_width: int | None = None,
    output_height: int | None = None,
    use_nvdec: bool = True,
    total_frames: int | None = None,
):
    """统一帧流接口 — 优先 NVDEC，不可用时自动 fallback 到 cv2。

    Args:
        video_path: 视频文件路径。
        fps: 采样帧率。
        output_width / output_height: 输出分辨率。None 为原始分辨率。
        use_nvdec: 是否尝试 NVDEC 硬解。
        total_frames: 需要抽取的总帧数（传入时使用计数驱动，准确可靠）。

    Yields:
        (H, W, 3) uint8 numpy RGB 帧数组。
    """
    if use_nvdec:
        try:
            async for frame in stream_frames_nvdec(
                video_path, fps, output_width, output_height,
            ):
                yield frame
            return
        except (FileNotFoundError, Exception) as e:
            logger.warning(
                "[stream_frames] NVDEC unavailable (%s), falling back to cv2", e,
            )

    async for frame in stream_frames_cv2(
        video_path, fps, output_width, output_height, total_frames,
    ):
        yield frame


# ═══════════════════════════════════════════════════════════
# 杂项工具
# ═══════════════════════════════════════════════════════════

@contextmanager
def suppress_ffmpeg_stderr():
    """上下文管理器 — 在 with 块内将 stderr 重定向到 /dev/null。

    cv2/FFmpeg 解码器将 HEVC/GOP 损坏警告直接写到 fd=2，
    绕过 Python logging 和 OpenCV API。此工具在 cv2 操作期间屏蔽这些噪声。
    """
    import sys
    stderr_fd = sys.stderr.fileno()
    saved = os.dup(stderr_fd)
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, stderr_fd)
    os.close(devnull)
    try:
        yield
    finally:
        os.dup2(saved, stderr_fd)
        os.close(saved)
