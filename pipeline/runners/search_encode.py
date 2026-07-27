"""
pipeline/runners/search_encode.py
═══════════════════════════════════════════════════════════
纯搜索索引构建 runner — 流式抽帧 + 批量编码。

不依赖 segmentation / keyframes / scene。
摘要启用时此 runner 被 gate 关闭，走原有的 keyframes→frame_encode 路径。

解码：优先 NVDEC 硬解（GPU），自动 fallback 到 cv2（CPU）。
"""

import logging
import os

from pipeline.runners.base import OperationRunner, PipelineContext
from core.interfaces import Scene as SceneData
from core.repository import bulk_insert_frames
from utils.video_util import stream_frames

logger = logging.getLogger(__name__)


class SearchEncodeRunner(OperationRunner):
    """纯搜索索引构建 — 流式抽帧 + 批量编码 → 入库。

    仅在 summary_enabled=False 时激活。与 detection 真正并行
    （两者都只依赖 duration），消灭了 segmentation + keyframes 的串行开销。

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

        video_path = pctx.ctx.file_path
        pipeline_cfg = pctx.config.get("pipeline", {})
        batch_size = pipeline_cfg.get("encode_batch_size", 64)
        use_nvdec = pipeline_cfg.get("use_nvdec", False)
        total_frames = max(1, int(duration))

        await pctx.tracker.update("search_encode", sub_progress=0.0)
        logger.info(
            "[SearchEncodeRunner] ~%d frames @ 1fps, batch=%d, nvdec=%s",
            total_frames, batch_size, use_nvdec,
        )

        # ── 流式抽帧 + 攒批编码 ──
        all_frame_rows: list[dict] = []
        video_id = pctx.video.id
        batch_frames: list = []
        batch_times: list[float] = []
        frame_idx = 0
        thumbnail_frame = None  # 首帧用作缩略图

        async for frame in stream_frames(
            video_path, fps=1.0, use_nvdec=use_nvdec,
            total_frames=total_frames,
        ):
            # 首帧保存为缩略图
            if thumbnail_frame is None:
                thumbnail_frame = frame

            batch_frames.append(frame)
            batch_times.append(float(frame_idx))
            frame_idx += 1

            if len(batch_frames) >= batch_size:
                rows = await self._encode_batch(
                    embedder, pctx, batch_frames, batch_times, video_id,
                )
                all_frame_rows.extend(rows)
                await pctx.tracker.update(
                    "search_encode",
                    sub_progress=min(frame_idx / total_frames, 0.99),
                )
                batch_frames = []
                batch_times = []

        # 最后一批
        if batch_frames:
            rows = await self._encode_batch(
                embedder, pctx, batch_frames, batch_times, video_id,
            )
            all_frame_rows.extend(rows)

        # ── 缩略图：创建一个覆盖全视频的最小 scene ──
        if thumbnail_frame is not None:
            self._create_minimal_scene(
                pctx, video_path, duration, thumbnail_frame,
            )

        # ── 持久化帧嵌入 ──
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
    ) -> list[dict]:
        """编码一批帧 → 返回 frame_embeddings 行列表。"""
        lock = getattr(pctx, "embedder_lock", None)
        if lock:
            await lock.acquire()
        try:
            embs = await embedder.encode_images_batch(frames)
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
