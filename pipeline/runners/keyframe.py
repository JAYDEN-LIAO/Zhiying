"""
pipeline/runners/keyframe.py
═══════════════════════════════════════════════════════════
关键帧抽取 runner — cv2 流式读帧, 零子进程, 1fps 帧池 + 缩略图。
"""

import logging
import os

import cv2
import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class KeyframeRunner(OperationRunner):
    """关键帧抽取 — cv2 一次打开视频流式读帧, 替代 FFmpeg 逐帧子进程。"""

    async def run(self, pctx: PipelineContext) -> None:
        scenes = pctx.ctx.scenes
        if not scenes:
            logger.info("[KeyframeRunner] No scenes, skipping")
            return

        summary_mode = getattr(pctx.video, "summary_mode", "native_video")
        logger.info("[KeyframeRunner] Extracting frame pool @ 1fps (mode=%s)", summary_mode)

        # 收集所有需要的整数秒时间戳 → 按场景索引分组
        total_targets = 0
        scene_targets: dict[int, set[int]] = {}
        for scene in scenes:
            tss = set(range(int(scene.start_sec), int(scene.end_sec)))
            if not tss:
                tss = {int(scene.start_sec)}
            scene_targets[scene.scene_index] = tss
            total_targets += len(tss)

        # cv2 一次流读, 按时间戳分发到对应场景
        cap = cv2.VideoCapture(pctx.ctx.file_path)
        source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_idx = 0
        collected = 0

        try:
            while collected < total_targets:
                ret, frame = cap.read()
                if not ret:
                    break
                ts = int(frame_idx / source_fps)
                # 找该秒属于哪个场景
                for scene in scenes:
                    if ts in scene_targets.get(scene.scene_index, set()):
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        if not hasattr(scene, "keyframes") or scene.keyframes is None:
                            scene.keyframes = []
                            scene.frame_timestamps = []
                        scene.keyframes.append(rgb)
                        scene.frame_timestamps.append(float(ts))
                        scene_targets[scene.scene_index].discard(ts)
                        collected += 1
                        break
                frame_idx += 1
        finally:
            cap.release()

        # 每场景后处理: 缩略图 + vlm_llm 选帧
        for i, scene in enumerate(scenes):
            if not getattr(scene, "keyframes", None):
                continue
            frames = scene.keyframes
            scene.keyframe = frames[len(frames) // 2]

            if summary_mode == "vlm_llm":
                num_cf = min(len(frames), 7)
                step = max(1, len(frames) // num_cf)
                scene.caption_frames = [frames[k * step] for k in range(num_cf)]

            # 缩略图
            try:
                from PIL import Image
                thumb_dir = os.path.join(
                    pctx.config.get("storage", {}).get("artifact_dir", "data/artifacts"),
                    "thumbnails", str(pctx.video.id),
                )
                os.makedirs(thumb_dir, exist_ok=True)
                thumb_path = os.path.join(thumb_dir, f"scene_{scene.scene_index:04d}.jpg")
                Image.fromarray(scene.keyframe).save(thumb_path, "JPEG", quality=80)
                scene.keyframe_path = thumb_path
            except Exception as e:
                logger.warning("[KeyframeRunner] Thumbnail save failed for scene %d: %s", i, e)

        total_frames = sum(len(s.keyframes) for s in scenes if hasattr(s, "keyframes") and s.keyframes)
        await pctx.tracker.update("keyframes", sub_progress=1.0)
        logger.info("[KeyframeRunner] Frame pool: %d frames @ 1fps (cv2 stream, 0 subprocesses)", total_frames)
