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

from pipeline.runners.base import OperationRunner, PipelineContext
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

        # ── 编码速度预设：逐视频 profile → 分辨率 + batch_size ──
        pipeline_cfg = pctx.config.get("pipeline", {})
        profile_name = getattr(pctx.video, "encode_profile", None)
        if not profile_name:
            profile_name = pipeline_cfg.get("default_encode_profile", "balanced")
        profiles = pipeline_cfg.get("encode_profiles", {})
        profile = profiles.get(profile_name, {})
        encode_w = profile.get("encode_width", 336)
        encode_h = profile.get("encode_height", 224)
        batch_size = profile.get("encode_batch_size", 512)
        target_size: tuple[int, int] = (encode_w, encode_h)

        await self._run_encode(
            pctx, embedder, duration, target_size, batch_size, pipeline_cfg, profile_name,
        )

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
            batch_times.append(float(frame_idx))
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
                "is_keyframe": ts == 0.0,  # 首帧标记为 keyframe（缩略图用）
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

        # 覆盖全视频的虚拟 scene
        scene = SceneData(
            scene_id=0,
            scene_index=0,
            start_sec=0.0,
            end_sec=duration,
            keyframe_path=thumb_path,
        )
        # 追加到 ctx.scenes（如果摘要路径已创建了 scenes 则不覆盖）
        if not pctx.ctx.scenes:
            pctx.ctx.scenes.append(scene)
        logger.info("[SearchEncodeRunner] Minimal scene created, thumbnail=%s", thumb_path)
