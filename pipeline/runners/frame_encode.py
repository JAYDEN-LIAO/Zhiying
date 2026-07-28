"""
pipeline/runners/frame_encode.py
═══════════════════════════════════════════════════════════
帧级编码 runner — 从 frame_queue 流式消费帧 + 批量编码 → frame_embeddings 表。

与 keyframes runner 通过 asyncio.Queue 解耦:
  keyframes (生产者) ──push──→ Queue ──pop──→ frame_encode (消费者)
  两者并发运行，GPU 不再等待全量抽帧完成。
"""

import logging

from pipeline.runners.base import OperationRunner, PipelineContext
from core.repository import bulk_insert_frames

logger = logging.getLogger(__name__)


class FrameEncodeRunner(OperationRunner):
    """帧级向量编码执行器 — 队列消费 + 批量编码。"""

    async def run(self, pctx: PipelineContext) -> None:
        embedder = pctx.shared_embedder or pctx.plugins.get("embedder")
        if embedder is None:
            logger.warning("[FrameEncodeRunner] No embedder available, skipping")
            return

        queue: object | None = getattr(pctx, "frame_queue", None)
        if queue is None:
            logger.warning("[FrameEncodeRunner] No frame_queue, skipping (search path handles encoding)")
            return

        # ── 编码速度预设 ──
        pipeline_cfg = pctx.config.get("pipeline", {})
        profile_name = getattr(pctx.video, "encode_profile", None)
        if not profile_name:
            profile_name = pipeline_cfg.get("default_encode_profile", "balanced")
        profiles = pipeline_cfg.get("encode_profiles", {})
        profile = profiles.get(profile_name, {})
        batch_size = profile.get("encode_batch_size", 512)
        target_w = profile.get("encode_width", 504)
        target_h = profile.get("encode_height", 336)
        target_size: tuple[int, int] = (target_w, target_h)

        estimated_total = max(1, int(pctx.ctx.duration or 0))

        await pctx.tracker.update("frame_encode", sub_progress=0.0)
        logger.info(
            "[FrameEncodeRunner] Consuming from frame_queue, profile=%s, %dx%d, batch=%d, ~%d frames",
            profile_name, target_w, target_h, batch_size, estimated_total,
        )

        all_frame_rows: list[dict] = []
        batch_frames: list = []
        batch_meta: list[tuple[int, float]] = []  # (scene_index, timestamp)
        total_encoded = 0

        while True:
            item = await queue.get()
            if item is None:  # sentinel — keyframes 完成
                break

            scene_idx, ts, frame = item
            batch_frames.append(frame)
            batch_meta.append((scene_idx, ts))

            if len(batch_frames) >= batch_size:
                rows = await self._encode_batch(
                    embedder, pctx, batch_frames, batch_meta, pctx.video.id, target_size,
                )
                all_frame_rows.extend(rows)
                total_encoded += len(batch_frames)
                await pctx.tracker.update(
                    "frame_encode",
                    sub_progress=min(total_encoded / estimated_total, 0.99),
                )
                batch_frames = []
                batch_meta = []

        # 最后一批
        if batch_frames:
            rows = await self._encode_batch(
                embedder, pctx, batch_frames, batch_meta, pctx.video.id, target_size,
            )
            all_frame_rows.extend(rows)

        # 持久化
        if all_frame_rows:
            async with pctx.db_session_factory() as session:
                await bulk_insert_frames(session, all_frame_rows)

        await pctx.tracker.update("frame_encode", sub_progress=1.0)
        logger.info("[FrameEncodeRunner] Done: %d frames encoded", len(all_frame_rows))

    @staticmethod
    async def _encode_batch(
        embedder,
        pctx: PipelineContext,
        frames: list,
        meta: list[tuple[int, float]],
        video_id,
        target_size: tuple[int, int] | None = None,
    ) -> list[dict]:
        """编码一批帧 → 返回 frame_embeddings 行列表。"""
        lock = getattr(pctx, "embedder_lock", None)
        if lock:
            await lock.acquire()
        try:
            embs = await embedder.encode_images_batch(frames, target_size=target_size)
        except Exception:
            logger.warning(
                "[FrameEncodeRunner] Batch encode failed, falling back to single-frame"
            )
            embs = []
            for f in frames:
                try:
                    embs.append(await embedder.encode_image(f))
                except Exception:
                    embs.append(None)
        finally:
            if lock:
                lock.release()

        rows: list[dict] = []
        for (scene_idx, ts), emb in zip(meta, embs):
            if not emb:
                continue
            rows.append({
                "video_id": video_id,
                "scene_index": scene_idx,
                "timestamp_sec": ts,
                "embedding": emb,
                "is_keyframe": False,
            })
        return rows
