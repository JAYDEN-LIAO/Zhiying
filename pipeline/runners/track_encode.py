"""
pipeline/runners/track_encode.py
═══════════════════════════════════════════════════════════
Track 语义编码 + 全局 ReID runner — v0.10 新增。

阶段 1: 对每条 track 选最佳帧 → crop(扩 15%) → 批量跨模态嵌入
阶段 2: 类内余弦比对 + 5 约束过滤 → 合并超时消失后重出现的同人/同车

依赖 detection runner 产出 (ctx.track_best_frames + ctx.tracks)
与 text_encode 同批之后执行 (Batch 5)，确保 embedder 已释放。
"""

import logging

import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)

# ── 全局 ReID 常量 ──
REID_COSINE_THRESHOLD = 0.85    # 余弦相似度 — 2048 维空间中 0.85 足以阻隔绝大多数假阳性
CROP_EXPAND_RATIO = 1.3         # bbox 外扩比例 (每边 15%)
HEAD_TAIL_CUT_RATIO = 0.15      # track 头尾淘汰比例
MAX_REID_TIME_GAP = 180.0       # 最大合并时间间隔 (秒) — 超时大概率是不同实例


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
        logger.info("[TrackEncodeRunner] Encoding %d tracks + global ReID", track_count)

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
                frame = self._fallback_frame(pctx.ctx.file_path, trk)
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
                "first_bbox": _last_bbox(pctx.ctx.frame_detections, tid, side="first"),
                "last_bbox": _last_bbox(pctx.ctx.frame_detections, tid, side="last"),
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

        # ── Phase 2: 全局 ReID 合并 ──
        # 利用 Qwen3-VL-Embedding-2B 的跨模态语义做离线 ReID：
        # 同类别 + 时间不重叠 + cos≥0.85 + 空间门 + 时间间隔≤3min
        # → 合并穿越遮挡/短暂出画后重出现的同人/同车
        embeddings_out, merged_tracks, merged_dets = _global_reid_merge(
            emb_metas, pctx.ctx.tracks, pctx.ctx.frame_detections or [],
        )

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

        merge_count = len(emb_metas) - len(embeddings_out)
        if merge_count > 0:
            logger.info(
                "[TrackEncodeRunner] Done: %d embeddings (%d tracks merged via global ReID)",
                len(track_embeddings), merge_count,
            )
        else:
            logger.info(
                "[TrackEncodeRunner] Done: %d embeddings (no ReID merges)",
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
    def _fallback_frame(file_path: str, trk: dict) -> np.ndarray | None:
        """头尾帧回退 → cv2 seek 到 track 中间时间点。"""
        import cv2
        from utils.video_util import suppress_ffmpeg_stderr

        mid = trk["first_seen"] + (trk["last_seen"] - trk["first_seen"]) * 0.5
        with suppress_ffmpeg_stderr():
            cap = cv2.VideoCapture(file_path)
            try:
                cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000)
                ret, frame = cap.read()
                if ret:
                    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            finally:
                cap.release()
        return None


# ═══════════════════════════════════════════════════════════
# 全局 ReID 合并 (手搓, 零新依赖)
# ═══════════════════════════════════════════════════════════

def _cosine_sim_matrix(embs: np.ndarray) -> np.ndarray:
    """(n, 2048) → (n, n) 余弦相似度矩阵。一行矢量化。"""
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs = embs / np.maximum(norms, 1e-8)
    return embs @ embs.T


def _time_overlap(t1: dict, t2: dict) -> bool:
    """含 1s 缓冲的时间重叠检测。"""
    return not (
        t1["last_seen"] + 1.0 < t2["first_seen"]
        or t2["last_seen"] + 1.0 < t1["first_seen"]
    )


def _spatial_gate(t1: dict, t2: dict) -> bool:
    """宽松空间门——只拦物理上不可能的瞬移。

    允许:
      ≤ 50% 画面位移 (正常走动)
      ≤ 1.5 画面/秒 速度 (快跑/车辆)
    拦截:
      人在最左消失, 0.5s 后瞬移到最右。
    """
    b1 = t1.get("last_bbox") or t1.get("bbox")
    b2 = t2.get("first_bbox") or t2.get("bbox")
    if not b1 or not b2:
        return True  # 缺数据不拦

    cx1 = (b1["x1"] + b1["x2"]) / 2
    cy1 = (b1["y1"] + b1["y2"]) / 2
    cx2 = (b2["x1"] + b2["x2"]) / 2
    cy2 = (b2["y1"] + b2["y2"]) / 2

    distance = np.sqrt((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2)
    time_gap = max(t2["first_seen"] - t1["last_seen"], 0.01)

    # 基础距离上限
    max_allowed = min(0.5, 2.0 / max(time_gap, 1.0))

    # 相机缩放容错: 中心很近 + bbox 尺寸变化大 → 很可能是缩放, 放宽
    w1, h1 = b1["x2"] - b1["x1"], b1["y2"] - b1["y1"]
    w2, h2 = b2["x2"] - b2["x1"], b2["y2"] - b2["y1"]
    size_ratio = max(w1 * h1, w2 * h2) / max(min(w1 * h1, w2 * h2), 1e-6)
    if distance < 0.15 and size_ratio > 2.0:
        max_allowed = max(max_allowed, 0.4)  # 缩放场景放宽到 40% 画面

    return distance <= max_allowed


def _last_bbox(dets: list[dict] | None, track_id: int, side: str = "last") -> dict | None:
    """从 frame_detections 中取某 track 的最后一帧(或首帧) bbox。"""
    if not dets:
        return None
    matches = [d for d in dets if d["track_id"] == track_id]
    if not matches:
        return None
    matches.sort(key=lambda d: d["timestamp_sec"])
    return matches[-1]["bbox"] if side == "last" else matches[0]["bbox"]


def _global_reid_merge(
    emb_metas: list[dict],
    tracks: list[dict],
    frame_detections: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """全局 ReID —— 类内余弦比对 + 5 约束 → 合并穿越遮挡的同人/同车。

    约束:
      1. 同类别
      2. 时间不重叠
      3. 时间间隔 ≤ MAX_REID_TIME_GAP (3 min)
      4. 余弦相似度 ≥ REID_COSINE_THRESHOLD (0.85)
      5. 宽松空间门 (不瞬移)
    """
    n = len(emb_metas)
    if n < 2:
        return emb_metas, list(tracks), list(frame_detections)

    # 余弦矩阵
    embs = np.stack([m["embedding"] for m in emb_metas])
    sim = _cosine_sim_matrix(embs)

    # 匹配：类 + 时间 + 余弦 + 空间
    best_match: dict[int, tuple[int, float]] = {}  # child_track_id → (parent_track_id, sim)
    for i in range(n):
        for j in range(i + 1, n):
            tid_i = emb_metas[i]["track_id"]
            tid_j = emb_metas[j]["track_id"]
            if emb_metas[i]["class_name"] != emb_metas[j]["class_name"]:  # 1
                continue
            t_i = _find_track(tracks, tid_i)
            t_j = _find_track(tracks, tid_j)
            if not t_i or not t_j:
                continue
            if _time_overlap(t_i, t_j):                                    # 2
                continue

            # 时间间隔门 — 太长间隔大概率不是同一物体                     # 3
            gap = max(
                t_j["first_seen"] - t_i["last_seen"],
                t_i["first_seen"] - t_j["last_seen"],
            )
            if gap > MAX_REID_TIME_GAP:
                continue

            if sim[i][j] < REID_COSINE_THRESHOLD:                          # 4
                continue
            if not _spatial_gate(
                {"bbox": emb_metas[i]["bbox"], "last_bbox": emb_metas[i].get("last_bbox"),
                 "first_seen": t_i["first_seen"], "last_seen": t_i["last_seen"]},
                {"bbox": emb_metas[j]["bbox"], "first_bbox": emb_metas[j].get("first_bbox"),
                 "first_seen": t_j["first_seen"], "last_seen": t_j["last_seen"]},
            ):                                                               # 5
                continue
            if tid_j not in best_match or sim[i][j] > best_match[tid_j][1]:
                best_match[tid_j] = (tid_i, float(sim[i][j]))

    # 贪心合并 (用真实 track_id)
    merged_ids: set[int] = set()
    merge_map: dict[int, int] = {}  # old_track_id → new_track_id
    for child_id, (parent_id, _) in best_match.items():
        root = parent_id
        while root in merge_map:
            root = merge_map[root]
        merge_map[child_id] = root
        merged_ids.add(child_id)

    merged_dets = list(frame_detections)
    merged_tracks = [dict(t) for t in tracks]

    for old_id, new_id in merge_map.items():
        for det in merged_dets:
            if det.get("track_id") == old_id:
                det["track_id"] = new_id
        for trk in merged_tracks:
            if trk["track_id"] == old_id:
                trk["merged_into"] = new_id

    for trk in merged_tracks:
        if trk["track_id"] in merge_map.values() or trk["track_id"] not in merged_ids:
            # 收集该 track 的所有出现片段
            pieces = [(trk["first_seen"], trk["last_seen"])]
            absorbed = [
                t for t in merged_tracks
                if t.get("merged_into") == trk["track_id"]
            ]
            for a in absorbed:
                pieces.append((a["first_seen"], a["last_seen"]))
                trk["frame_count"] += a.get("frame_count", 0)
            # 排序 + 合并相邻片段 (间隙 ≤ 0.5s 视为连续)
            pieces.sort()
            merged_pieces: list[dict] = []
            for s, e in pieces:
                if merged_pieces and s - merged_pieces[-1]["end"] <= 0.5:
                    merged_pieces[-1]["end"] = max(merged_pieces[-1]["end"], e)
                else:
                    merged_pieces.append({"start": round(s, 1), "end": round(e, 1)})
            trk["segments"] = merged_pieces
            trk["first_seen"] = merged_pieces[0]["start"]
            trk["last_seen"] = merged_pieces[-1]["end"]

    remaining = [
        emb_metas[i] for i in range(n)
        if emb_metas[i]["track_id"] not in merged_ids
    ]

    # 删除被合并的 child track（时间/帧数据已吸收到 parent）
    merged_tracks = [t for t in merged_tracks if not t.get("merged_into")]

    return remaining, merged_tracks, merged_dets


def _find_track(tracks: list[dict], track_id: int) -> dict | None:
    for t in tracks:
        if t["track_id"] == track_id:
            return t
    return None
