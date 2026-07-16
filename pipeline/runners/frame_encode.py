"""
pipeline/runners/frame_encode.py
═══════════════════════════════════════════════════════════
帧级编码 runner — 1fps 逐帧 encode_image → frame_embeddings 表。
"""

import logging

from pipeline.runners.base import OperationRunner, PipelineContext
from core.repository import bulk_insert_frames

logger = logging.getLogger(__name__)


class FrameEncodeRunner(OperationRunner):
    """帧级向量编码执行器 — batch encode 4 帧一批。"""

    async def run(self, pctx: PipelineContext) -> None:
        embedder = pctx.shared_embedder or pctx.plugins.get("embedder")
        if embedder is None:
            logger.warning("[FrameEncodeRunner] No embedder available, skipping")
            return

        scenes = pctx.ctx.scenes
        if not scenes:
            return

        scene_count = len(scenes)
        await pctx.tracker.update("frame_encode", sub_progress=0.0)
        logger.info("[FrameEncodeRunner] Encoding frame embeddings ...")

        _BATCH_SIZE = 4

        for si, scene in enumerate(scenes):
            if not scene.keyframes or not scene.frame_timestamps:
                await pctx.tracker.update("frame_encode", sub_progress=(si + 1) / scene_count)
                continue

            frame_rows: list[dict] = []
            frame_items = list(zip(scene.frame_timestamps, scene.keyframes))

            for i in range(0, len(frame_items), _BATCH_SIZE):
                batch = frame_items[i:i + _BATCH_SIZE]
                batch_frames = [b[1] for b in batch]
                batch_times = [b[0] for b in batch]

                try:
                    embs = await embedder.encode_images_batch(batch_frames)
                except Exception:
                    logger.warning("[FrameEncodeRunner] Batch encode failed, falling back to single-frame")
                    embs = []
                    for f in batch_frames:
                        try:
                            embs.append(await embedder.encode_image(f))
                        except Exception:
                            embs.append(None)

                for j, (t, emb) in enumerate(zip(batch_times, embs)):
                    if not emb:
                        continue
                    frame_rows.append({
                        "video_id": pctx.video.id,
                        "scene_index": scene.scene_index,
                        "timestamp_sec": t,
                        "embedding": emb,
                        "is_keyframe": False,
                    })

            if frame_rows:
                async with pctx.db_session_factory() as session:
                    await bulk_insert_frames(session, frame_rows)

            await pctx.tracker.update("frame_encode", sub_progress=(si + 1) / scene_count)

        logger.info("[FrameEncodeRunner] Done")
