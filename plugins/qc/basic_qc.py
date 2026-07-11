"""
plugins/qc/basic_qc.py
═══════════════════════════════════════════════════════════
基础质检插件 — 黑屏检测 + 静音检测 + 视频时长估算。

使用 FFmpeg blackdetect / silencedetect 滤镜实现，
全部通过 asyncio.create_subprocess_exec 异步执行，不阻塞事件循环。
"""

import asyncio
import logging
import re

from core.interfaces import BaseQC, VideoContext
from core.exceptions import PipelineError
from utils.video_util import get_video_duration

logger = logging.getLogger(__name__)

# blackdetect 输出解析: black_start:10 black_end:15.5 black_duration:5.5
_RE_BLACK = re.compile(
    r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)\s+black_duration:\s*([\d.]+)"
)

# silencedetect 输出解析:
#   [silencedetect] silence_start: 120
#   [silencedetect] silence_end: 180 | silence_duration: 60
_RE_SILENCE_START = re.compile(r"silence_start:\s*([\d.]+)")
_RE_SILENCE_END = re.compile(r"silence_end:\s*([\d.]+)\s*\|")


class BasicQC(BaseQC):
    """基础视频质检器。

    Args:
        black_threshold: 黑屏判定阈值（像素值 0~255），默认 10。
        black_min_duration: 最短黑屏时长（秒），默认 0.5。
        silent_threshold_db: 静音判定阈值（dB），默认 -40。
    """

    def __init__(
        self,
        black_threshold: float = 10,
        black_min_duration: float = 0.5,
        silent_threshold_db: float = -40,
        **kwargs,
    ):
        self.black_threshold = black_threshold
        self.black_min_duration = black_min_duration
        self.silent_threshold_db = silent_threshold_db

    async def check(self, ctx: VideoContext) -> dict:
        """执行视频质量检测。

        Args:
            ctx: VideoContext，需含 file_path。

        Returns:
            {
                "is_valid": bool,
                "estimated_duration": float,
                "black_segments": [{"start_sec": float, "end_sec": float}],
                "silent_segments": [{"start_sec": float, "end_sec": float}],
                "overexposed_segments": [],
            }
        """
        video_path = ctx.file_path

        # ── 获取视频时长 ──
        duration = await get_video_duration(video_path)

        # ── 黑屏检测 ──
        black_segments = await self._detect_black(video_path)

        # ── 静音检测 ──
        silent_segments = await self._detect_silence(video_path)

        # ── 综合判定 ──
        # 黑屏/静音总时长占比 > 30% 视为异常
        total_black = sum(s["end_sec"] - s["start_sec"] for s in black_segments)
        total_silent = sum(s["end_sec"] - s["start_sec"] for s in silent_segments)
        anomaly_ratio = (total_black + total_silent) / duration if duration > 0 else 0
        is_valid = anomaly_ratio < 0.30

        result = {
            "is_valid": is_valid,
            "estimated_duration": duration,
            "black_segments": black_segments,
            "silent_segments": silent_segments,
            "overexposed_segments": [],
        }

        logger.info(
            "[BasicQC] duration=%.1fs black=%d silent=%d valid=%s",
            duration, len(black_segments), len(silent_segments), is_valid,
        )
        return result

    # ──────────────────────────────────────────────────────
    # 黑屏检测
    # ──────────────────────────────────────────────────────

    async def _detect_black(self, video_path: str) -> list[dict]:
        """使用 ffmpeg blackdetect 检测黑屏段。"""
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vf",
            f"blackdetect=d={self.black_min_duration}:pic_th={self.black_threshold / 255:.2f}",
            "-f", "null",
            "-",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        stderr_text = stderr.decode(errors="replace")

        segments = []
        for match in _RE_BLACK.finditer(stderr_text):
            segments.append({
                "start_sec": float(match.group(1)),
                "end_sec": float(match.group(2)),
            })

        return segments

    # ──────────────────────────────────────────────────────
    # 静音检测
    # ──────────────────────────────────────────────────────

    async def _detect_silence(self, video_path: str) -> list[dict]:
        """使用 ffmpeg silencedetect 检测静音段。"""
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-af",
            f"silencedetect=noise={self.silent_threshold_db}dB:d=0.5",
            "-f", "null",
            "-",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        stderr_text = stderr.decode(errors="replace")

        starts = [float(m) for m in _RE_SILENCE_START.findall(stderr_text)]
        ends = [float(m) for m in _RE_SILENCE_END.findall(stderr_text)]

        segments = []
        for start, end in zip(starts, ends):
            segments.append({"start_sec": start, "end_sec": end})

        return segments
