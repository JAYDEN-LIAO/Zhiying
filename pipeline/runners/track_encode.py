"""
pipeline/runners/track_encode.py
═══════════════════════════════════════════════════════════
Track 语义编码 runner — v0.10 新增。

阶段 1: 对每条 track 选最佳帧 → crop(扩 15%) → 批量跨模态嵌入
阶段 2: 无全局 ReID（跨遮挡重识别由 BoT-SORT 保活机制处理）

依赖 detection runner 产出 (ctx.track_best_frames + ctx.tracks)
与 text_encode 同批之后执行 (Batch 5)，确保 embedder 已释放。
"""

import logging

import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)

CROP_EXPAND_RATIO = 1.3         # bbox 外扩比例 (每边 15%)
HEAD_TAIL_CUT_RATIO = 0.15      # track 头尾淘汰比例


class TrackEncodeRunner(OperationRunner):
    """Track 嵌入 + 全局 ReID 合并执行器。"""

    async def run(self, pctx: PipelineContext) -> None:
        embedder = pctx.shared_embedder or pctx.plugins.get("embedder")
        if embedder is None:
            logger.info("[TrackEncodeRunner] No embedder, skipping")
            return
        if not pctx.ctx.tracks:
            logger.info("[TrackEncodeRunner] No tracks to encode")
            return

        best_cache = pctx.ctx.track_best_frames or {}
        if not best_cache:
            logger.warning("[TrackEncodeRunner] No best frames cached, skipping")
            return

        tracks = pctx.ctx.tracks
        track_count = len(tracks)
        logger.info("[TrackEncodeRunner] Encoding %d tracks", track_count)

        # ── Phase 1: crop + 批量嵌入 ──
        crops: list[np.ndarray] = []
        emb_metas: list[dict] = []
        track_by_id = {t["track_id"]: t for t in tracks}

        for trk in tracks:
            tid = trk["track_id"]
            cache = best_cache.get(tid)
            if not cache:
                continue

            # 头尾过滤
            frame = cache["frame"]
            ts = cache["timestamp"]
            if not self._is_mid_frame(trk, ts):
                frame = await self._fallback_frame(pctx.ctx.file_path, trk)
                if frame is None:
                    continue
                ts = trk["first_seen"] + (trk["last_seen"] - trk["first_seen"]) * 0.5

            crop = self._expand_crop(frame, cache["bbox"])
            crops.append(crop)
            emb_metas.append({
                "track_id": tid,
                "class_name": trk["class_name"],
                "timestamp_sec": ts,
                "bbox": cache["bbox"],
            })

        if not crops:
            logger.warning("[TrackEncodeRunner] No valid crops after filtering")
            return

        # 分批次编码 — 272 个 crop 一次性 batch 会撑爆显存
        TRACK_BATCH = 64  # GB10 128GB 统一内存
        emb_vectors: list = []
        lock = getattr(pctx, "embedder_lock", None)
        for bi in range(0, len(crops), TRACK_BATCH):
            batch_crops = crops[bi:bi + TRACK_BATCH]
            if lock: await lock.acquire()
            try:
                if hasattr(embedder, "encode_images_batch"):
                    emb_vectors.extend(await embedder.encode_images_batch(batch_crops))
                else:
                    for c in batch_crops:
                        emb_vectors.append(await embedder.encode_image(c))
            finally:
                if lock: lock.release()

        for meta, vec in zip(emb_metas, emb_vectors):
            meta["embedding"] = np.array(vec, dtype=np.float64)

        # ── Phase 2: 无全局 ReID 合并（跨遮挡重识别由 BoT-SORT 保活机制处理）──
        embeddings_out = emb_metas
        merged_tracks = pctx.ctx.tracks
        merged_dets = pctx.ctx.frame_detections

        # 用合并后的数据构建 track_embeddings
        track_embeddings = []
        for meta in embeddings_out:
            emb = meta["embedding"]
            if isinstance(emb, np.ndarray):
                emb = emb.tolist()
            track_embeddings.append({
                "track_id": meta["track_id"],
                "class_name": meta["class_name"],
                "embedding": emb,
                "timestamp_sec": meta["timestamp_sec"],
                "bbox": meta["bbox"],
            })

        pctx.ctx.track_embeddings = track_embeddings
        pctx.ctx.tracks = merged_tracks
        pctx.ctx.frame_detections = merged_dets

        logger.info(
            "[TrackEncodeRunner] Done: %d embeddings",
            len(track_embeddings),
        )

    # ── 内部方法 ──

    @staticmethod
    def _expand_crop(frame: np.ndarray, bbox: dict) -> np.ndarray:
        """bbox 外扩 15% 后裁剪，clamp 到画面边界。"""
        h, w = frame.shape[:2]
        x1, y1 = bbox["x1"], bbox["y1"]
        x2, y2 = bbox["x2"], bbox["y2"]

        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        bw, bh = (x2 - x1) * CROP_EXPAND_RATIO, (y2 - y1) * CROP_EXPAND_RATIO

        nx1 = max(0, int((cx - bw / 2) * w))
        nx2 = min(w, int((cx + bw / 2) * w))
        ny1 = max(0, int((cy - bh / 2) * h))
        ny2 = min(h, int((cy + bh / 2) * h))

        return frame[ny1:ny2, nx1:nx2]

    @staticmethod
    def _is_mid_frame(trk: dict, ts: float) -> bool:
        """检查时间戳是否在 track 的中间 70% 区间 (避开头尾 15%)。"""
        dur = trk["last_seen"] - trk["first_seen"]
        if dur <= 0:
            return True
        head = trk["first_seen"] + dur * HEAD_TAIL_CUT_RATIO
        tail = trk["last_seen"] - dur * HEAD_TAIL_CUT_RATIO
        return head <= ts <= tail

    @staticmethod
    async def _fallback_frame(file_path: str, trk: dict) -> np.ndarray | None:
        """头尾帧回退 → FFmpeg pipe 异步提取 track 中间时间点。

        使用 extract_keyframe_to_memory（FFmpeg subprocess + asyncio），
        不阻塞事件循环。替代旧 cv2.VideoCapture 同步 seek 方案。
        """
        from utils.video_util import extract_keyframe_to_memory

        mid = trk["first_seen"] + (trk["last_seen"] - trk["first_seen"]) * 0.5
        try:
            return await extract_keyframe_to_memory(file_path, mid)
        except Exception:
            return None


