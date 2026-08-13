"""
pipeline/runners/face.py
═══════════════════════════════════════════════════════════
人脸识别 runner — SCRFD 检测 + ArcFace R50 嵌入 + 身份聚类。

依赖 detection runner 产出 (ctx.track_best_frames + ctx.tracks)。

v0.30 重构（整体人物建模）:
  1. 多帧采样：短 track 用 best 帧；长 track 按时间范围补采 2~3 帧全分辨率
     → 提高提到清晰脸的概率（单帧 best 帧可能选到糊脸/侧脸）。
  2. 两阶段身份聚类：
     Phase A【同 track 软先验】 同 track 内的人脸先两两比相似度，
       高的并（同一人不同角度），低的留（框住多人，自然分开）。
     Phase B【全局凝聚聚类】 所有 track 的所有脸按人脸相似度凝聚合并，
       跨镜头/跨换装的同一个人合并成一个身份（修复碎片化主战场）。
     → 脸是唯一身份依据；track 只做时空索引（best_track_id + 时间段）。
  3. 检索锚点：身份存最高质量单脸的 embedding（best_face_embedding）为主锚，
     face_embedding（均值）保留兜底兼容旧数据。

产出:
  - ctx.face_identities → 聚类后的人脸身份列表
  - ctx.face_detections  → 逐次人脸检出记录列表（identity_id 对齐 track）
"""

import asyncio
import logging

import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext
from utils.video_util import extract_keyframe_to_memory

logger = logging.getLogger(__name__)

# ── 身份聚类阈值（护栏式：同 track 宽松合并、跨 track 保守合并） ──
# v0.30 实测教训（综艺人脸1.mp4）:
#   - 单一 0.60 阈值 → 同一人跨出镜碎片化（386 身份，76% 单脸）
#   - 单一 0.40 阈值 → 不同人被错误合并（"人物B"=125 张脸/KMeans 4 簇，
#     代表性 embedding 稀释成噪声 → 搜索搜不到原能搜到的人脸）
# 正确策略:
#   - 同 track 内（同一人时间连续，强先验）: 相似度 ≥ SAME_TRACK_SIM 即合并（0.30 宽松）
#   - 跨 track（不同时空，必须高相似才敢并）: 相似度 ≥ CROSS_TRACK_SIM 才合并（0.58 保守）
# 实测 CROSS=0.58: dc.png 身份 36 张/代表 sim 0.634（0.40 下是 0.14 噪声、搜不到）
SAME_TRACK_SIM = 0.30            # 同 track 内合并阈值（同一人不同角度）
CROSS_TRACK_SIM = 0.58           # 跨 track 合并阈值（防并错不同人）
# 搜索命中阈值 FACE_SEARCH_MIN_SIM=0.45 见 core/search.py（略低于 CROSS_TRACK_SIM，
# 容忍查询图与代表脸的小差异；搜索只取 top-k 无合并副作用，不会引入误并）。
IDENTITY_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# ── 多帧采样参数 ──
SHORT_TRACK_SEC = 5.0      # 短 track 阈值：< 此秒数只用 best 帧
LONG_TRACK_SAMPLES = 3     # 长 track 采样帧数（含 best 帧）
MAX_SEEK_CONCURRENCY = 4   # ffmpeg 补采并发上限


def _normalize(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-8)


def _label_for(iid: int) -> str:
    """身份标签：前 26 位 A~Z，超出用 AA/AB... 保持一致。"""
    if iid <= len(IDENTITY_LABELS):
        return f"人物 {IDENTITY_LABELS[iid - 1]}"
    n = iid - 1
    letters = ""
    while n >= 0:
        letters = IDENTITY_LABELS[n % 26] + letters
        n = n // 26 - 1
    return f"人物 {letters}"


class FaceRunner(OperationRunner):
    """人脸检测 + 识别 + 身份聚类执行器。"""

    async def run(self, pctx: PipelineContext) -> None:
        face_recognizer = pctx.plugins.get("face")
        if face_recognizer is None:
            logger.info("[FaceRunner] No face plugin, skipping")
            return

        tracks = pctx.ctx.tracks or []
        best_cache = pctx.ctx.track_best_frames or {}
        person_tracks = [t for t in tracks if t["class_name"] == "person"]

        if not person_tracks:
            logger.info("[FaceRunner] No person tracks found, skipping")
            return

        video_id = str(pctx.video.id)
        video_path = pctx.ctx.file_path

        # ── Phase 1: 收集 person crops（多帧采样）──
        person_metas: list[dict] = []      # {track_id, timestamp, bbox, crop}
        crops: list[np.ndarray] = []

        for trk in person_tracks:
            tid = trk["track_id"]
            cache = best_cache.get(tid)
            # 采样时间点：best 帧 + 长 track 补采 [first_seen, last_seen] 内均匀点
            ts_points: list[float] = []
            if cache:
                ts_points.append(cache["timestamp"])
            duration = float(trk.get("last_seen", 0)) - float(trk.get("first_seen", 0))
            if cache and duration >= SHORT_TRACK_SEC:
                start, end = float(trk["first_seen"]), float(trk["last_seen"])
                for k in range(1, LONG_TRACK_SAMPLES):
                    frac = k / LONG_TRACK_SAMPLES
                    t = start + (end - start) * frac
                    # 避免与 best 帧时间重叠
                    if not cache or abs(t - cache["timestamp"]) > 1.0:
                        ts_points.append(t)

            # 逐采样点提取帧 → crop person
            frames_for_track: list[np.ndarray] = []
            for ts in ts_points:
                if cache and ts == cache["timestamp"]:
                    frames_for_track.append(cache["frame"])
                else:
                    try:
                        frame = await extract_keyframe_to_memory(video_path, ts)
                        frames_for_track.append(frame)
                    except Exception as e:
                        logger.warning(
                            "[FaceRunner] Seek failed @%.1fs track %d: %s", ts, tid, e,
                        )

            for frame in frames_for_track:
                h, w = frame.shape[:2]
                b = cache["bbox"] if cache else trk.get("bbox", {})
                if not b or "x1" not in b:
                    continue
                # 从全帧中 crop person bbox（扩 10% 给头部/脸部留空间）
                px1 = max(0, int((b["x1"] - 0.05) * w))
                py1 = max(0, int((b["y1"] - 0.15) * h))  # 上边缘多扩（头部在上面）
                px2 = min(w, int((b["x2"] + 0.05) * w))
                py2 = min(h, int((b["y2"] + 0.05) * h))

                if px2 <= px1 or py2 <= py1:
                    continue

                person_crop = frame[py1:py2, px1:px2]
                if person_crop.size == 0 or min(person_crop.shape[:2]) < 30:
                    continue

                person_metas.append({
                    "track_id": tid,
                    "timestamp": ts,
                    "person_bbox": b,
                    "crop_offset": (px1, py1, px2, py2, w, h),  # crop pixel coords + full-frame dims
                })
                crops.append(person_crop)

        if not crops:
            logger.info("[FaceRunner] No valid person crops, skipping")
            return

        await pctx.tracker.update(
            "face", sub_progress=0.1,
            description=f"人脸检测+识别 {len(crops)} 个 person crops",
        )

        # ── Phase 2: 批量提取人脸 ──
        all_face_dets = await face_recognizer.extract(crops)

        # ── Phase 3: 转换到帧坐标 + 收集 embedding ──
        face_records: list[dict] = []  # [{track_id, timestamp, bbox(frame), quality, embedding}, ...]
        for meta, face_list in zip(person_metas, all_face_dets):
            px1, py1, px2, py2, fw, fh = meta["crop_offset"]
            crop_w = px2 - px1
            crop_h = py2 - py1
            for face in face_list:
                fb = face["bbox"]
                # 人脸 bbox 从 person crop 归一化坐标 → 全帧归一化坐标
                frame_bbox = {
                    "x1": (px1 + fb["x1"] * crop_w) / fw,
                    "y1": (py1 + fb["y1"] * crop_h) / fh,
                    "x2": (px1 + fb["x2"] * crop_w) / fw,
                    "y2": (py1 + fb["y2"] * crop_h) / fh,
                }
                # clamp
                for k in frame_bbox:
                    frame_bbox[k] = max(0.0, min(1.0, frame_bbox[k]))

                face_records.append({
                    "track_id": meta["track_id"],
                    "timestamp": meta["timestamp"],
                    "bbox": frame_bbox,
                    "quality": face["quality"],
                    "embedding": np.asarray(face["embedding"], dtype=np.float64),
                })

        if not face_records:
            logger.info("[FaceRunner] No faces detected in person crops, skipping")
            return

        await pctx.tracker.update(
            "face", sub_progress=0.5,
            description=f"聚类 {len(face_records)} 张人脸",
        )

        # ── Phase 4: 两阶段身份聚类（护栏式：同 track 宽松、跨 track 保守） ──
        # 归一化 embedding 矩阵 (N, 512)
        emb_matrix = np.stack([_normalize(fr["embedding"]) for fr in face_records])

        # 实现：并查集。
        #   Phase A【同 track】: sim >= SAME_TRACK_SIM 即合并（同一人不同角度，强先验）
        #   Phase B【跨 track】: sim >= CROSS_TRACK_SIM 才合并（不同时空，防并错不同人）
        # 实测单一 0.40 会把不同人并错（代表 embedding 稀释成噪声 → 搜索搜不到），
        # 单一 0.60 会碎片化。护栏式两个阈值分别应对两个方向的错误。
        n_faces = len(face_records)
        parent = list(range(n_faces))

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(a: int, b: int) -> None:
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[ra] = rb

        # 先做全量相似度矩阵（N×N, 归一化后点积即余弦）
        sim = emb_matrix @ emb_matrix.T
        track_ids = [fr["track_id"] for fr in face_records]

        # Phase A: 同 track 内合并（低阈值，同一人不同角度）
        for i in range(n_faces):
            for j in range(i + 1, n_faces):
                if track_ids[i] == track_ids[j] and sim[i, j] >= SAME_TRACK_SIM:
                    _union(i, j)

        # Phase B: 跨 track 凝聚（高阈值，按相似度从高到低合并）
        pairs = []
        for i in range(n_faces):
            for j in range(i + 1, n_faces):
                s = sim[i, j]
                if track_ids[i] != track_ids[j] and s >= CROSS_TRACK_SIM:
                    pairs.append((s, i, j))
        pairs.sort(reverse=True, key=lambda x: x[0])
        for s, i, j in pairs:
            _union(i, j)

        # 收集身份（按并查集根分组）
        comp_to_idx: dict[int, int] = {}
        iid_by_face: list[int] = [0] * n_faces
        n_identities = 0
        for i in range(n_faces):
            root = _find(i)
            if root not in comp_to_idx:
                comp_to_idx[root] = n_identities
                n_identities += 1
            iid_by_face[i] = comp_to_idx[root]

        # ── Phase 5: 汇总身份 + 写 ctx ──
        id_to_label: dict[int, str] = {i + 1: _label_for(i + 1) for i in range(n_identities)}
        face_records_sorted = sorted(
            enumerate(face_records), key=lambda x: x[1]["timestamp"],
        )

        identity_metas: dict[int, dict] = {}
        identity_emb_sets: dict[int, list[np.ndarray]] = {
            i + 1: [] for i in range(n_identities)
        }
        identity_best: dict[int, dict] = {}  # iid -> {embedding, track_id, timestamp, bbox, quality}

        for face_i, fr in face_records_sorted:
            iid = iid_by_face[face_i] + 1  # 1-based internal
            fr["identity_id"] = iid
            fr["_label"] = id_to_label[iid]

            meta = identity_metas.get(iid)
            if meta is None:
                meta = {
                    "video_id": video_id,
                    "identity_label": id_to_label[iid],
                    "face_count": 0,
                    "first_seen": fr["timestamp"],
                    "last_seen": fr["timestamp"],
                    "total_quality": 0.0,
                    "best_quality": -1.0,
                    "best_face_timestamp": fr["timestamp"],
                    "best_face_bbox": fr["bbox"],
                    "best_track_id": fr["track_id"],
                    "best_face_embedding": None,
                }
                identity_metas[iid] = meta

            meta["last_seen"] = max(meta["last_seen"], fr["timestamp"])
            meta["face_count"] += 1
            meta["total_quality"] += float(fr["quality"])
            identity_emb_sets[iid].append(_normalize(fr["embedding"]))

        # 写 ctx — best_face_embedding 选"与均值最接近的脸"（最典型脸），而非质量分最高。
        # 实测教训（v0.30）: 质量分最高的单脸可能是偏角度/特殊光照 → 对查询图相似度反而低
        # （人物N: 质量分脸 sim=0.38 搜不到，均值 0.634 / 最典型脸 0.600 能搜到）。
        # 最典型脸 = 与均值余弦最接近的单张，兼顾单脸锐度 + 身份代表性。
        pctx.ctx.face_identities = []
        for iid in sorted(identity_metas.keys()):
            meta = identity_metas[iid]
            id_embs = identity_emb_sets[iid]
            mean_emb = np.mean(np.stack(id_embs), axis=0)
            mean_emb_n = mean_emb / (np.linalg.norm(mean_emb) + 1e-8)

            # 最典型脸：与均值最接近的成员（track/timestamp/bbox/embedding 取自它）
            best_member: dict | None = None
            best_sim_to_mean = -1.0
            for fr in face_records:
                if fr["identity_id"] != iid:
                    continue
                emb_n = _normalize(fr["embedding"])
                s = float(emb_n @ mean_emb_n)
                if s > best_sim_to_mean:
                    best_sim_to_mean = s
                    best_member = fr
            best_face_embedding = best_member["embedding"] if best_member else mean_emb
            best_face_timestamp = best_member["timestamp"] if best_member else meta["best_face_timestamp"]
            best_face_bbox = best_member["bbox"] if best_member else meta["best_face_bbox"]
            best_track_id = best_member["track_id"] if best_member else meta["best_track_id"]

            pctx.ctx.face_identities.append({
                "video_id": video_id,
                "identity_label": meta["identity_label"],
                "face_count": meta["face_count"],
                "first_seen": meta["first_seen"],
                "last_seen": meta["last_seen"],
                "avg_quality": round(meta["total_quality"] / max(meta["face_count"], 1), 4),
                "face_embedding": mean_emb.tolist(),                    # 均值（兜底）
                "best_face_embedding": best_face_embedding,  # 最典型单脸（主锚）
                "best_track_id": best_track_id,
                "best_face_timestamp": best_face_timestamp,
                "best_face_bbox": best_face_bbox,
                "best_face_path": meta.get("best_face_path"),
            })

        pctx.ctx.face_detections = [
            {
                "video_id": video_id,
                "track_id": fr["track_id"],
                "identity_id": fr["identity_id"],  # runner internal ID, engine 会用 _label 映射到 DB ID
                "_label": fr["_label"],  # 供 engine 映射用
                "timestamp_sec": fr["timestamp"],
                "bbox": fr["bbox"],
                "quality_score": fr["quality"],
                "face_embedding": fr["embedding"].tolist(),
            }
            for fr in face_records
        ]

        await pctx.tracker.update("face", sub_progress=1.0)

        logger.info(
            "[FaceRunner] Done: %d faces → %d identities",
            len(face_records), n_identities,
        )
        if pctx.log:
            await pctx.log(f"人脸识别完成：{len(face_records)} 张人脸 → {n_identities} 个身份")
