"""
pipeline/runners/search_encode.py
═══════════════════════════════════════════════════════════
纯搜索索引构建 runner — 独立 NVDEC 流抽帧 + 批量编码。

与 detection 的 NVDEC 流完全独立，两路并行互不干扰。
不依赖 segmentation / keyframes / scene。
摘要启用时此 runner 被 gate 关闭，走原有的 keyframes→frame_encode 路径。
"""

import logging
import os

from pipeline.runners.base import OperationRunner, PipelineContext, resolve_encode_profile
from core.interfaces import Scene as SceneData
from core.repository import bulk_insert_frames
from utils.video_util import stream_frames

logger = logging.getLogger(__name__)


class SearchEncodeRunner(OperationRunner):
    """纯搜索索引构建 — 独立 NVDEC 流抽帧 + 批量编码 → 入库。

    仅在 summary_enabled=False 时激活。
    与 detection 使用独立 NVDEC 解码流，互不干扰。

    同时创建一个覆盖全视频的最小 scene（缩略图用）。
    """

    async def run(self, pctx: PipelineContext) -> None:
        embedder = pctx.shared_embedder or pctx.plugins.get("embedder")
        if embedder is None:
            logger.warning("[SearchEncodeRunner] No embedder available, skipping")
            return

        duration = pctx.ctx.duration
        if not duration or duration <= 0:
            logger.warning("[SearchEncodeRunner] No valid duration, skipping")
            return

        # ── 编码速度预设（统一解析，见 base.resolve_encode_profile）──
        pipeline_cfg = pctx.config.get("pipeline", {})
        profile = resolve_encode_profile(pctx.config, pctx.video)
        batch_size = profile.encode_batch_size
        target_size = profile.target_size

        # ── 队列模式（优先）：从 detection 共享 NVDEC 流消费帧 ──
        search_queue: object | None = getattr(pctx, "search_frame_queue", None)
        if search_queue is not None:
            await self._run_from_queue(
                pctx, embedder, search_queue, duration, target_size, profile.name,
            )
        else:
            await self._run_encode(
                pctx, embedder, duration, target_size, batch_size, pipeline_cfg, profile.name,
            )

    async def _run_from_queue(
        self,
        pctx: PipelineContext,
        embedder: object,
        queue: object,
        duration: float,
        target_size: tuple[int, int],
        profile_name: str,
    ) -> None:
        """队列模式：消费 detection 共享流推送的帧，不独立开 NVDEC 流。

        使用 QUEUE_BATCH=64 提前开始编码，与帧提取重叠，
        避免等齐全部帧再编（否则 decode 和 encode 完全串行）。
        帧已由 detection 端 resize 到 target_size。
        """
        video_id = pctx.video.id
        total_frames = max(1, int(duration))
        QUEUE_BATCH = 64
        total_batches = (total_frames + QUEUE_BATCH - 1) // QUEUE_BATCH

        logger.info(
            "[SearchEncodeRunner] Queue mode: consuming from shared detection stream, "
            "profile=%s %dx%d queue_batch=%d ~%d frames → %d batch(s)",
            profile_name, target_size[0], target_size[1],
            QUEUE_BATCH, total_frames, total_batches,
        )

        await pctx.tracker.update("search_encode", sub_progress=0.0)

        all_frame_rows: list[dict] = []
        batch_frames: list = []
        batch_times: list[float] = []
        frame_idx = 0
        thumbnail_frame = None

        while True:
            item = await queue.get()  # type: ignore[union-attr]
            if item is None:
                break
            frame, ts = item

            if thumbnail_frame is None:
                thumbnail_frame = frame

            batch_frames.append(frame)
            batch_times.append(ts)
            frame_idx += 1

            if len(batch_frames) >= QUEUE_BATCH:
                rows = await self._encode_batch(
                    embedder, pctx, batch_frames, batch_times, video_id, target_size,
                )
                all_frame_rows.extend(rows)
                current_batch = frame_idx // QUEUE_BATCH
                pct = min(frame_idx / total_frames * 100, 99.0)
                msg = f"编码 {frame_idx}/{total_frames}帧 ({pct:.0f}%) | batch {current_batch}/{total_batches}"
                logger.info("[search_encode] %s", msg)
                await pctx.tracker.update(
                    "search_encode",
                    sub_progress=min(frame_idx / total_frames, 0.99),
                    description=msg,
                )
                batch_frames = []
                batch_times = []

        # 最后一批
        if batch_frames:
            rows = await self._encode_batch(
                embedder, pctx, batch_frames, batch_times, video_id, target_size,
            )
            all_frame_rows.extend(rows)

        # ── 缩略图 + 最小 scene ──
        if thumbnail_frame is not None:
            self._create_minimal_scene(pctx, pctx.ctx.file_path, duration, thumbnail_frame)

        # ── 持久化帧嵌入 ──
        if all_frame_rows:
            async with pctx.db_session_factory() as session:
                await bulk_insert_frames(session, all_frame_rows)

        await pctx.tracker.update("search_encode", sub_progress=1.0)
        logger.info("[SearchEncodeRunner] Queue mode done: %d frames encoded", len(all_frame_rows))
        if pctx.log:
            await pctx.log(f"搜索索引构建完成：{len(all_frame_rows)} 帧编码")

    async def _run_encode(
        self,
        pctx: PipelineContext,
        embedder: object,
        duration: float,
        target_size: tuple[int, int],
        batch_size: int,
        pipeline_cfg: dict,
        profile_name: str,
    ) -> None:
        """独立 NVDEC 流抽帧 + 批量编码。"""
        video_path = pctx.ctx.file_path
        use_nvdec = pipeline_cfg.get("use_nvdec", False)
        total_frames = max(1, int(duration))
        total_batches = (total_frames + batch_size - 1) // batch_size

        logger.info(
            "[SearchEncodeRunner] ~%d frames @1fps "
            "profile=%s %dx%d batch=%d nvdec=%s → %d batch(s)",
            total_frames, profile_name,
            target_size[0], target_size[1],
            batch_size, use_nvdec, total_batches,
        )

        await pctx.tracker.update("search_encode", sub_progress=0.0)

        all_frame_rows: list[dict] = []
        video_id = pctx.video.id
        batch_frames: list = []
        batch_times: list[float] = []
        frame_idx = 0
        thumbnail_frame = None

        async for frame in stream_frames(
            video_path, fps=1.0, use_nvdec=use_nvdec,
            output_width=target_size[0], output_height=target_size[1],
            total_frames=total_frames,
        ):
            if thumbnail_frame is None:
                thumbnail_frame = frame

            batch_frames.append(frame)
            batch_times.append(pctx.ctx.start_time + float(frame_idx))
            frame_idx += 1

            if len(batch_frames) >= batch_size:
                rows = await self._encode_batch(
                    embedder, pctx, batch_frames, batch_times, video_id, target_size,
                )
                all_frame_rows.extend(rows)
                current_batch = frame_idx // batch_size
                pct = min(frame_idx / total_frames * 100, 99.0)
                msg = f"编码 {frame_idx}/{total_frames}帧 ({pct:.0f}%) | batch {current_batch}/{total_batches}"
                logger.info("[search_encode] %s", msg)
                await pctx.tracker.update(
                    "search_encode",
                    sub_progress=min(frame_idx / total_frames, 0.99),
                    description=msg,
                )
                batch_frames = []
                batch_times = []

        if batch_frames:
            rows = await self._encode_batch(
                embedder, pctx, batch_frames, batch_times, video_id, target_size,
            )
            all_frame_rows.extend(rows)

        if thumbnail_frame is not None:
            self._create_minimal_scene(pctx, video_path, duration, thumbnail_frame)

        if all_frame_rows:
            async with pctx.db_session_factory() as session:
                await bulk_insert_frames(session, all_frame_rows)

        await pctx.tracker.update("search_encode", sub_progress=1.0)
        logger.info("[SearchEncodeRunner] Done: %d frames encoded", len(all_frame_rows))
        if pctx.log:
            await pctx.log(f"搜索索引构建完成：{len(all_frame_rows)} 帧编码")

    @staticmethod
    async def _encode_batch(
        embedder,
        pctx: PipelineContext,
        frames: list,
        timestamps: list[float],
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
                "[SearchEncodeRunner] Batch encode failed, falling back to single-frame"
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
        for ts, emb in zip(timestamps, embs):
            if not emb:
                continue
            rows.append({
                "video_id": video_id,
                "scene_index": 0,  # 纯搜索无 scene 上下文，统一归到全视频 scene
                "timestamp_sec": ts,
                "embedding": emb,
                "is_keyframe": ts == pctx.ctx.start_time,  # 首帧（媒体时间轴起点）标记为 keyframe（缩略图用）
            })
        return rows

    @staticmethod
    def _create_minimal_scene(
        pctx: PipelineContext,
        video_path: str,
        duration: float,
        thumbnail_frame,
    ) -> None:
        """创建一个覆盖全视频的最小 scene，含缩略图。"""
        import asyncio
        from PIL import Image

        artifact_dir = pctx.config.get("storage", {}).get(
            "artifact_dir", "data/artifacts",
        )
        thumb_dir = os.path.join(
            artifact_dir, "thumbnails", str(pctx.video.id),
        )
        os.makedirs(thumb_dir, exist_ok=True)
        thumb_path = os.path.join(thumb_dir, "scene_0000.jpg")
        try:
            Image.fromarray(thumbnail_frame).save(thumb_path, "JPEG", quality=80)
        except Exception as e:
            logger.warning("[SearchEncodeRunner] Thumbnail save failed: %s", e)
            thumb_path = None

        # 覆盖全视频的虚拟 scene（媒体时间轴，含 start_time 偏移）
        scene = SceneData(
            scene_id=0,
            scene_index=0,
            start_sec=pctx.ctx.start_time,
            end_sec=pctx.ctx.start_time + duration,
            keyframe_path=thumb_path,
        )
        # 追加到 ctx.scenes（如果摘要路径已创建了 scenes 则不覆盖）
        if not pctx.ctx.scenes:
            pctx.ctx.scenes.append(scene)
        logger.info("[SearchEncodeRunner] Minimal scene created, thumbnail=%s", thumb_path)
