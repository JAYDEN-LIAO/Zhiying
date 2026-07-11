"""
plugins/segmenter/time_based.py
═══════════════════════════════════════════════════════════
固定时间间隔镜头分割插件 — 无需任何深度学习依赖。

按固定间隔（默认 30 秒）将视频切分为场景，
每场景取中点作为关键帧时间戳。
适合 Demo / 轻量场景，可用于替代 TransNetV2。
"""

import logging

from core.interfaces import BaseSegmenter
from utils.video_util import get_video_duration

logger = logging.getLogger(__name__)


class TimeBasedSegmenter(BaseSegmenter):
    """基于固定时间间隔的镜头分割。

    Args:
        segment_duration: 每个场景的固定时长（秒），默认 30.0。
        scene_min_duration: 最短场景时长（秒），尾部不足此值则舍弃。
    """

    def __init__(
        self,
        segment_duration: float = 30.0,
        scene_min_duration: float = 1.0,
        **kwargs,
    ):
        self.segment_duration = segment_duration
        self.scene_min_duration = scene_min_duration
        logger.info(
            "[TimeBasedSegmenter] Ready: segment_duration=%.1fs min_duration=%.1fs",
            segment_duration, scene_min_duration,
        )

    async def segment(
        self,
        video_path: str,
        sample_fps: float = 1.0,
    ) -> list[dict]:
        """按固定时间间隔切分视频。

        Args:
            video_path: 视频文件路径。
            sample_fps: （本实现忽略，保持接口兼容）。

        Returns:
            [
                {
                    "scene_index": int,
                    "start_sec": float,
                    "end_sec": float,
                    "keyframe": None,
                },
            ]
        """
        duration = await get_video_duration(video_path)
        if duration <= 0:
            logger.warning("[TimeBasedSegmenter] Invalid duration: %s", video_path)
            return []

        scenes: list[dict] = []
        start = 0.0
        index = 0

        while start < duration:
            end = min(start + self.segment_duration, duration)
            seg_len = end - start

            if seg_len >= self.scene_min_duration:
                scenes.append({
                    "scene_index": index,
                    "start_sec": round(start, 2),
                    "end_sec": round(end, 2),
                    "keyframe": None,
                })
                index += 1

            start = end

        logger.info(
            "[TimeBasedSegmenter] %s → %d scenes (%.1fs each)",
            video_path, len(scenes), self.segment_duration,
        )
        return scenes
