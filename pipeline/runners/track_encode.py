"""
pipeline/runners/track_encode.py
═══════════════════════════════════════════════════════════
Track 语义编码 runner — v0.21：检测缓存多帧 + 全局 tracklet 缝合。

阶段 1: 读取 detection 缓存的多帧 crop（640×384，零 FFmpeg seek）
         → 每 track 挑 20%/50%/80% 附近 3 帧 → Qwen3-VL-Embedding → mean pool
阶段 2: 全局 tracklet 缝合：cosine similarity + 时序不重叠约束
         → 合并属于同一身份但被遮挡分开的 tracklet
"""

import logging
from collections import defaultdict

import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.85     # tracklet 合并 cosine 阈值（640×384 特征较粗，调高防误合并）
MAX_OVERLAP_SEC = 1.0           # 允许的最大真实检测重叠时长（超过视为不同物体）
HIGH_SIM_OVERRIDE = 0.90        # 小重叠时要求的外观超高阈值（判定为双跟踪伪影）


class TrackEncodeRunner(OperationRunner):
    """Track 嵌入 + 全局 ReID tracklet 缝合执行器。

    v0.21 变更:
      - 帧源: FFmpeg 重新 seek 原视频 → detection 缓存的 640×384 crop（零 seek，长视频友好）
      - 多帧: 从缓存挑 20%/50%/80% 附近 3 帧 → mean pool
      - 阈值: 0.80 → 0.85（低分辨率特征较粗，防误合并）
    """

    async def run(self, pctx: PipelineContext) -> None:
        embedder = pctx.shared_embedder or pctx.plugins.get("embedder")
        if embedder is None:
            logger.info("[TrackEncodeRunner] No embedder, skipping")
            return
        if not pctx.ctx.tracks:
            logger.info("[TrackEncodeRunner] No tracks to encode")
            return

        tracks = pctx.ctx.tracks
        duration = pctx.ctx.duration or 0
        crop_cache = pctx.ctx.track_crop_cache or {}

        # ── Phase 1: 读取检测缓存的多帧 crop（零 seek）──
        crops: list[np.ndarray] = []
        metas: list[dict] = []
        for trk in tracks:
            tid = trk["track_id"]
            entries = crop_cache.get(tid)
            if not entries:
                logger.debug("[TrackEncode] track %d has no cached crops, skipping", tid)
                continue

            first = max(0.0, trk["first_seen"])
            last = min(trk["last_seen"], duration) if duration > 0 else trk["last_seen"]
            dur = max(0.5, last - first)

            # 按 track 时长决定帧数
            if dur < 1.0:
                fracs = [0.5]
            elif dur < 3.0:
                fracs = [0.25, 0.75]
            else:
                fracs = [0.2, 0.5, 0.8]

            # 从缓存挑最接近目标分位的 crop（去重，避免同一帧重复编码）
            chosen: list[tuple[float, np.ndarray]] = []
            for frac in fracs:
                target_ts = first + dur * frac
                best_entry = min(entries, key=lambda e: abs(e[0] - target_ts))
                if chosen and abs(best_entry[0] - chosen[-1][0]) < 0.1:
                    continue
                chosen.append(best_entry)

            for ts, crop in chosen:
                crops.append(crop)
                metas.append({"track_id": tid, "timestamp_sec": ts, "bbox": None})

        if not crops:
            logger.warning("[TrackEncode] No valid crops from cache, skipping")
            return

        logger.info(
            "[TrackEncode] Read %d crops from cache for %d tracks (%.1f/track)",
            len(crops), len(tracks), len(crops) / max(1, len(tracks)),
        )

        # ── 批量编码 ──
        TRACK_BATCH = 64
        raw_vectors: list[list[float]] = []
        lock = getattr(pctx, "embedder_lock", None)
        for bi in range(0, len(crops), TRACK_BATCH):
            batch = crops[bi:bi + TRACK_BATCH]
            if lock:
                await lock.acquire()
            try:
                if hasattr(embedder, "encode_images_batch"):
                    vecs = await embedder.encode_images_batch(batch)
                else:
                    vecs = [await embedder.encode_image(c) for c in batch]
                for v in vecs:
                    arr = v.tolist() if hasattr(v, "tolist") else v
                    raw_vectors.append(arr)
            finally:
                if lock:
                    lock.release()

        # ── Per-track mean pool ──
        track_feats: dict[int, list[np.ndarray]] = defaultdict(list)
        for meta, vec in zip(metas, raw_vectors):
            track_feats[meta["track_id"]].append(np.array(vec, dtype=np.float32))

        pooled: dict[int, list[float]] = {}
        for tid, vecs in track_feats.items():
            pooled[tid] = np.mean(vecs, axis=0).tolist()

        # ── Phase 2: 全局 tracklet 缝合（固定开启）──
        frame_dets = pctx.ctx.frame_detections or []
        new_tracks, new_frame_dets = self._stitch_tracks(tracks, frame_dets, pooled)
        logger.info("[TrackEncode] Track stitching enabled")

        # ── Phase 2.5: 每视频每类别 display_seq（类内 1..N；track_id 不变保持全局唯一）──
        new_tracks, new_frame_dets = self._assign_display_seq(new_tracks, new_frame_dets)

        # ── 构建最终的 track_embeddings（bbox/timestamp 取自最佳帧，供搜索缩略图裁剪）──
        best_frames = pctx.ctx.track_best_frames or {}
        track_embeddings: list[dict] = []
        for t in new_tracks:
            tid = t["track_id"]
            emb = pooled.get(tid)
            best = best_frames.get(tid) or {}
            if emb is not None:
                track_embeddings.append({
                    "track_id": tid,
                    "class_name": t["class_name"],
                    "display_seq": t.get("display_seq"),
                    "embedding": emb,
                    "timestamp_sec": best.get("timestamp", t["first_seen"]),
                    "bbox": best.get("bbox"),
                })

        pctx.ctx.track_embeddings = track_embeddings
        pctx.ctx.tracks = new_tracks
        pctx.ctx.frame_detections = new_frame_dets

        n_before = len(set(t["track_id"] for t in tracks))
        n_after = len(set(t["track_id"] for t in new_tracks))
        logger.info(
            "[TrackEncode] Done: %d embeddings, %d tracks (merged %d)",
            len(track_embeddings), n_after, n_before - n_after,
        )

    # ── 静态方法 ──

    @staticmethod
    def _assign_display_seq(
        tracks: list[dict],
        frame_dets: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """每视频每类别 display_seq：按 class 分组 → (first_seen, track_id) 排序 → 1..N。

        **track_id 不变**（保持全局唯一，face/plate/导出/选中态零影响）；
        display_seq 是纯展示字段，赋值到 tracks + frame_dets（同一映射），
        track_embeddings 在调用方从 tracks 构建时自动带上。
        """
        from collections import defaultdict

        by_class: dict[str, list[dict]] = defaultdict(list)
        for t in tracks:
            by_class[t["class_name"]].append(t)

        seq_by_tid: dict[int, int] = {}
        for cls, lst in by_class.items():
            lst.sort(key=lambda t: (t.get("first_seen", 0), t.get("track_id", 0)))
            for i, t in enumerate(lst, 1):
                seq_by_tid[t["track_id"]] = i

        for t in tracks:
            t["display_seq"] = seq_by_tid.get(t["track_id"])
        for d in frame_dets:
            d["display_seq"] = seq_by_tid.get(d["track_id"])
        return tracks, frame_dets

    @staticmethod
    def _stitch_tracks(
        tracks: list[dict],
        frame_dets: list[dict],
        pooled: dict[int, list[float]],
    ) -> tuple[list[dict], list[dict]]:
        """全局 tracklet 缝合。

        条件: 同类 + cosine ≥ 阈值 + 时序不重叠 → 合并。
        返回 (new_tracks, new_frame_dets)。
        """
        n = len(tracks)
        if n < 2:
            return tracks, frame_dets

        # 构建特征矩阵
        emb_matrix = []
        valid_idx: list[int] = []
        for i, t in enumerate(tracks):
            if t["track_id"] in pooled:
                emb_matrix.append(pooled[t["track_id"]])
                valid_idx.append(i)

        if len(valid_idx) < 2:
            return tracks, frame_dets

        emb_matrix = np.array(emb_matrix, dtype=np.float32)
        norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
        norms[norms < 1e-12] = 1.0
        emb_matrix = emb_matrix / norms

        # Cosine similarity
        sim = emb_matrix @ emb_matrix.T

        # 构建合并映射: old_tid → new_tid
        merge_map: dict[int, int] = {}
        merged_into: set[int] = set()

        for i in range(len(valid_idx)):
            ai = valid_idx[i]
            for j in range(i + 1, len(valid_idx)):
                aj = valid_idx[j]
                if sim[i, j] < SIMILARITY_THRESHOLD:
                    continue

                ti, tj = tracks[ai], tracks[aj]
                if ti["class_name"] != tj["class_name"]:
                    continue

                # 时序检查：真实重叠 + 外观分级容忍（双跟踪伪影）
                overlap = _real_overlap_seconds(ti, tj)
                if overlap > MAX_OVERLAP_SEC:
                    continue  # 重叠太久 → 真两个人
                if overlap > 0 and sim[i, j] < HIGH_SIM_OVERRIDE:
                    continue  # 小重叠但外观不够高 → 仍是两个人
                # 小重叠 + 外观极高 → 双跟踪伪影，放行合并

                # 合并: tj → ti
                old_id = tj["track_id"]
                new_id = ti["track_id"]
                if old_id in merged_into:
                    continue

                merge_map[old_id] = new_id
                merged_into.add(old_id)
                logger.info(
                    "[TrackEncode] ✂ Merge track %d → %d (sim=%.3f, '%s')",
                    old_id, new_id, sim[i, j], ti["class_name"],
                )

        if not merge_map:
            return tracks, frame_dets

        # 解析链式合并: A→B→C → A→C
        for old_id in list(merge_map.keys()):
            current = merge_map[old_id]
            visited = {old_id}
            while current in merge_map and current not in visited:
                visited.add(current)
                current = merge_map[current]
            merge_map[old_id] = current

        # 应用到 tracks
        seen_ids: set[int] = set()
        new_tracks: list[dict] = []
        for t in tracks:
            tid = t["track_id"]
            new_tid = merge_map.get(tid, tid)
            if new_tid in seen_ids:
                # 合并到已有 track，延长生命周期
                for nt in new_tracks:
                    if nt["track_id"] == new_tid:
                        nt["last_seen"] = max(nt["last_seen"], t["last_seen"])
                        nt["frame_count"] += t["frame_count"]
                        segs = t.get("segments")
                        if segs:
                            nt.setdefault("segments", []).extend(segs)
                        break
            else:
                t = dict(t)
                t["track_id"] = new_tid
                if t.get("segments") is None:
                    t["segments"] = []
                new_tracks.append(t)
                seen_ids.add(new_tid)

        # 应用到 frame_detections
        new_dets: list[dict] = []
        for d in frame_dets:
            d = dict(d)
            d["track_id"] = merge_map.get(d["track_id"], d["track_id"])
            new_dets.append(d)

        # 迁移 pool embedding key
        for old_id, new_id in merge_map.items():
            if old_id in pooled and new_id != old_id:
                if new_id in pooled:
                    pooled[new_id] = np.mean(
                        [np.array(pooled[new_id]), np.array(pooled[old_id])],
                        axis=0,
                    ).tolist()

        logger.info("[TrackEncode] ✅ Stitch: %d track pairs merged", len(merge_map))
        return new_tracks, new_dets


def _track_segments(trk: dict) -> list[dict]:
    """获取 track 的真实检测片段（segments 缺失时退化为整个生命周期）。"""
    segs = trk.get("segments")
    if segs:
        return segs
    return [{"start": trk["first_seen"], "end": trk["last_seen"]}]


def _real_overlap_seconds(a: dict, b: dict) -> float:
    """两条 track 的真实检测重叠时长（秒）。

    用 segments（实际检测片段）而非 first_seen/last_seen（含 tracker lost 缓冲）。
    镜头切换/缩放/遮挡边缘时 tracker 会短暂双跟踪同一物体，造成 0.3-1s 真实重叠，
    此时若外观极高（同一个人）应允许合并。
    """
    total = 0.0
    for sa in _track_segments(a):
        for sb in _track_segments(b):
            overlap = min(sa["end"], sb["end"]) - max(sa["start"], sb["start"])
            if overlap > 0:
                total += overlap
    return total
