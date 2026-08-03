"""
pipeline/runners/keyframe.py
═══════════════════════════════════════════════════════════
关键帧抽取 runner — stream_frames() 异步生成器 + frame_queue 生产者。

帧通过 asyncio.Queue 流式推送给 frame_encode runner，
抽取和编码并发执行，消除 GPU 空闲等待。

原始帧仍存入 scene.keyframes 供 caption 等下游消费。
"""

import logging
import os

from pipeline.runners.base import OperationRunner, PipelineContext
from utils.video_util import stream_frames

logger = logging.getLogger(__name__)


class KeyframeRunner(OperationRunner):
    """关键帧抽取 — 流式抽帧 + 队列推送给 frame_encode 并发编码。"""

    async def run(self, pctx: PipelineContext) -> None:
        scenes = pctx.ctx.scenes
        if not scenes:
            logger.info("[KeyframeRunner] No scenes, skipping")
            frame_queue = getattr(pctx, "frame_queue", None)
            if frame_queue is not None:
                await frame_queue.put(None)
            return

        duration = pctx.ctx.duration
        if not duration or duration <= 0:
            logger.warning("[KeyframeRunner] No valid duration, skipping")
            frame_queue = getattr(pctx, "frame_queue", None)
            if frame_queue is not None:
                await frame_queue.put(None)
            return

        summary_mode = getattr(pctx.video, "summary_mode", "native_video")
        total_seconds = int(duration)
        pipeline_cfg = pctx.config.get("pipeline", {})
        use_nvdec = pipeline_cfg.get("use_nvdec", False)

        logger.info(
            "[KeyframeRunner] Extracting frame pool @ 1fps (stream, mode=%s, ~%d frames, nvdec=%s)",
            summary_mode, total_seconds, use_nvdec,
        )

        # ── 预计算 second → scene_index 映射 (O(1) 查找) ──
        second_to_scene: list[int | None] = [None] * total_seconds
        scene_lookup: dict[int, object] = {}
        for scene in scenes:
            si = scene.scene_index
            scene_lookup[si] = scene
            scene.keyframes = []
            scene.frame_timestamps = []
            for t in range(int(scene.start_sec), int(scene.end_sec)):
                if t < total_seconds and second_to_scene[t] is None:
                    second_to_scene[t] = si

        # ── 流式抽帧 + 分发到 scene 对象和 frame_queue ──
        video_path = pctx.ctx.file_path
        frame_queue: object | None = getattr(pctx, "frame_queue", None)
        expected_frames = sum(scene_idx is not None for scene_idx in second_to_scene)
        if frame_queue is not None:
            # 先发送准确总量，消费者据此计算实际编码进度。
            await frame_queue.put(("__total__", expected_frames))
        frame_idx = 0
        extracted = 0
        progress_stride = max(1, total_seconds // 100)


        try:
            async for frame in stream_frames(
                video_path, fps=1.0,
                use_nvdec=use_nvdec,
                total_frames=total_seconds,  # cv2 路径用；NVDEC 忽略
            ):
                if frame_idx >= total_seconds:
                    break

                scene_idx = second_to_scene[frame_idx]
                if scene_idx is not None:
                    ts = float(frame_idx)
                    scene = scene_lookup[scene_idx]
                    scene.keyframes.append(frame)
                    scene.frame_timestamps.append(ts)
                    extracted += 1

                    # 推送到消费者队列（frame_encode 并发消费）
                    if frame_queue is not None:
                        await frame_queue.put((scene_idx, ts, frame))

                frame_idx += 1
                if frame_idx % progress_stride == 0:
                    await pctx.tracker.update(
                        "keyframes",
                        sub_progress=min(frame_idx / max(1, total_seconds), 0.99),
                    )
        finally:
            # 确保消费者收到结束信号（即使异常也会发送）
            if frame_queue is not None:
                await frame_queue.put(None)

        # ── 每场景后处理: 缩略图 + vlm_llm 选帧 ──
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
        logger.info("[KeyframeRunner] Frame pool: %d frames @ 1fps (stream)", total_frames)
