"""
pipeline/runners/keyframe.py
═══════════════════════════════════════════════════════════
关键帧抽取 runner — cv2 流式读帧 (asyncio.to_thread), 1fps 帧池 + 缩略图。

cv2 读帧是同步 C 调用，通过 asyncio.to_thread 投递到线程池，
不阻塞事件循环 — detection 等操作可以真正并行运行。
"""

import asyncio
import logging
import os

import cv2
import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class KeyframeRunner(OperationRunner):
    """关键帧抽取 — cv2 在线程池中流式读帧, 事件循环不被阻塞。"""

    async def run(self, pctx: PipelineContext) -> None:
        scenes = pctx.ctx.scenes
        if not scenes:
            logger.info("[KeyframeRunner] No scenes, skipping")
            return

        summary_mode = getattr(pctx.video, "summary_mode", "native_video")
        logger.info("[KeyframeRunner] Extracting frame pool @ 1fps (cv2, mode=%s)", summary_mode)

        # 收集需要的整数秒时间戳 → 按场景索引分组
        total_targets = 0
        scene_targets: dict[int, set[int]] = {}
        for scene in scenes:
            tss = set(range(int(scene.start_sec), int(scene.end_sec)))
            if not tss:
                tss = {int(scene.start_sec)}
            scene_targets[scene.scene_index] = tss
            total_targets += len(tss)

        # cv2 同步读帧 → asyncio.to_thread 投递线程池，事件循环继续跑
        video_path = pctx.ctx.file_path
        collected, scene_keyframes, scene_timestamps = await asyncio.to_thread(
            self._read_frames, video_path, scenes, scene_targets, total_targets,
        )

        # 将抽到的帧写回 scene 对象
        for scene in scenes:
            idx = scene.scene_index
            if idx in scene_keyframes:
                scene.keyframes = scene_keyframes[idx]
                scene.frame_timestamps = scene_timestamps[idx]

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
        logger.info("[KeyframeRunner] Frame pool: %d frames @ 1fps (cv2)", total_frames)

    @staticmethod
    def _read_frames(
        video_path: str,
        scenes: list,
        scene_targets: dict[int, set[int]],
        total_targets: int,
    ) -> tuple[int, dict[int, list[np.ndarray]], dict[int, list[float]]]:
        """同步读帧循环 — 在线程池中执行，不阻塞事件循环。"""
        cap = cv2.VideoCapture(video_path)
        source_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

        scene_frames: dict[int, list[np.ndarray]] = {}
        scene_tss: dict[int, list[float]] = {}
        frame_idx = 0
        collected = 0

        try:
            while collected < total_targets:
                ret, frame = cap.read()
                if not ret:
                    break
                ts = int(frame_idx / source_fps)
                for scene in scenes:
                    targets = scene_targets.get(scene.scene_index, set())
                    if ts in targets:
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        idx = scene.scene_index
                        if idx not in scene_frames:
                            scene_frames[idx] = []
                            scene_tss[idx] = []
                        scene_frames[idx].append(rgb)
                        scene_tss[idx].append(float(ts))
                        targets.discard(ts)
                        collected += 1
                        break
                frame_idx += 1
        finally:
            cap.release()

        return collected, scene_frames, scene_tss
