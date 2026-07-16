"""
pipeline/runners/keyframe.py
═══════════════════════════════════════════════════════════
关键帧抽取 runner — 1fps 逐帧抽取到内存，保存缩略图。

提取自 pipeline/engine.py:_extract_keyframes()
"""

import logging
import os

import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext
from utils.video_util import extract_keyframe_to_memory

logger = logging.getLogger(__name__)


class KeyframeRunner(OperationRunner):
    """关键帧抽取执行器 — FFmpeg pipe → 内存，1fps 帧池 + 缩略图。"""

    async def run(self, pctx: PipelineContext) -> None:
        scenes = pctx.ctx.scenes
        if not scenes:
            logger.info("[KeyframeRunner] No scenes, skipping")
            return

        summary_mode = getattr(pctx.video, "summary_mode", "native_video")
        logger.info("[KeyframeRunner] Extracting frame pool @ 1fps (mode=%s)", summary_mode)

        total_scenes = len(scenes)
        for i, scene in enumerate(scenes):
            await pctx.tracker.update(
                "keyframes",
                sub_progress=(i) / total_scenes,
                description=f"正在抽取第 {i + 1}/{total_scenes} 个场景的关键帧",
            )

            timestamps = list(range(
                int(scene.start_sec), int(scene.end_sec),
            ))
            if not timestamps:
                timestamps = [scene.start_sec + 0.1]

            frames: list[np.ndarray] = []
            frame_times: list[float] = []
            for t in timestamps:
                try:
                    frame = await extract_keyframe_to_memory(
                        pctx.ctx.file_path, t,
                    )
                    if frame is not None:
                        frames.append(frame)
                        frame_times.append(t)
                except Exception as e:
                    logger.warning(
                        "[KeyframeRunner] Frame extraction failed @ %.1f: %s", t, e,
                    )

            if not frames:
                continue

            scene.keyframes = frames
            scene.frame_timestamps = frame_times
            scene.keyframe = frames[len(frames) // 2]  # 中点帧（缩略图）

            # vlm_llm 模式：均匀选 3-7 帧代表帧（API captioner 用）
            if summary_mode == "vlm_llm":
                num_cf = min(len(frames), 7)
                step = max(1, len(frames) // num_cf)
                scene.caption_frames = [frames[k * step] for k in range(num_cf)]

            # 保存缩略图
            try:
                from PIL import Image
                thumb_dir = os.path.join(
                    pctx.config.get("storage", {}).get(
                        "artifact_dir", "data/artifacts",
                    ),
                    "thumbnails", str(pctx.video.id),
                )
                os.makedirs(thumb_dir, exist_ok=True)
                thumb_path = os.path.join(
                    thumb_dir, f"scene_{scene.scene_index:04d}.jpg",
                )
                Image.fromarray(scene.keyframe).save(thumb_path, "JPEG", quality=80)
                scene.keyframe_path = thumb_path
            except Exception as e:
                logger.warning(
                    "[KeyframeRunner] Thumbnail save failed for scene %d: %s", i, e,
                )

        total_frames = sum(len(s.keyframes) for s in scenes if s.keyframes)
        await pctx.tracker.update("keyframes", sub_progress=1.0)
        logger.info("[KeyframeRunner] Frame pool: %d frames @ 1fps", total_frames)
