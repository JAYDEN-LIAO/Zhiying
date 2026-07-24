"""
pipeline/runners/face.py
═══════════════════════════════════════════════════════════
人脸识别 runner — SCRFD 检测 + ArcFace R50 嵌入 + 身份聚类。

依赖 detection runner 产出 (ctx.track_best_frames + ctx.tracks)。
对 person tracks 的最佳帧提取人脸 → ArcFace 512-dim 嵌入 → 贪心聚类。

产出:
  - ctx.face_identities → 聚类后的人脸身份列表
  - ctx.face_detections  → 逐次人脸检出记录列表
"""

import logging

import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)

# ── 身份聚类阈值 ──
IDENTITY_COSINE_THRESHOLD = 0.65   # ArcFace 512 维空间中的余弦阈值
IDENTITY_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


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

        # ── Phase 1: 收集 person crops + 批量人脸提取 ──
        person_metas: list[dict] = []      # {track_id, timestamp, bbox, crop}
        crops: list[np.ndarray] = []

        for trk in person_tracks:
            tid = trk["track_id"]
            cache = best_cache.get(tid)
            if not cache:
                continue
            frame = cache["frame"]
            ts = cache["timestamp"]

            # 从全帧中 crop person bbox（扩 10% 给头部/脸部留空间）
            h, w = frame.shape[:2]
            b = cache["bbox"]
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
                "crop_offset": (px1, py1, w, h),  # for converting face bbox back to frame coords
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
            px1, py1, fw, fh = meta["crop_offset"]
            for face in face_list:
                fb = face["bbox"]
                # 人脸 bbox 从 person crop 坐标 → 全帧归一化坐标
                frame_bbox = {
                    "x1": (px1 + fb["x1"] * (meta["person_bbox"]["x2"] - meta["person_bbox"]["x1"]) * fw) / fw,
                    "y1": (py1 + fb["y1"] * (meta["person_bbox"]["y2"] - meta["person_bbox"]["y1"]) * fh) / fh,
                    "x2": (px1 + fb["x2"] * (meta["person_bbox"]["x2"] - meta["person_bbox"]["x1"]) * fw) / fw,
                    "y2": (py1 + fb["y2"] * (meta["person_bbox"]["y2"] - meta["person_bbox"]["y1"]) * fh) / fh,
                }
                # clamp
                for k in frame_bbox:
                    frame_bbox[k] = max(0.0, min(1.0, frame_bbox[k]))

                face_records.append({
                    "track_id": meta["track_id"],
                    "timestamp": meta["timestamp"],
                    "bbox": frame_bbox,
                    "quality": face["quality"],
                    "embedding": face["embedding"],
                })

        if not face_records:
            logger.info("[FaceRunner] No faces detected in person crops, skipping")
            return

        await pctx.tracker.update(
            "face", sub_progress=0.5,
            description=f"聚类 {len(face_records)} 张人脸",
        )

        # ── Phase 4: 贪心身份聚类 ──
        # 按时间排序 → 首个人脸创建新身份 → 后续与已有身份均值比对
        face_records.sort(key=lambda x: x["timestamp"])
        identity_embeddings: dict[int, list[np.ndarray]] = {}
        identity_metas: dict[int, dict] = {}
        next_id = 1
        id_to_label: dict[int, str] = {}

        for fr in face_records:
            emb = np.array(fr["embedding"], dtype=np.float64)
            emb = emb / (np.linalg.norm(emb) + 1e-8)

            matched_iid: int | None = None
            best_sim = 0.0
            for iid, id_embs in identity_embeddings.items():
                mean_emb = np.mean(np.stack(id_embs), axis=0)
                mean_emb = mean_emb / (np.linalg.norm(mean_emb) + 1e-8)
                cos_sim = float(np.dot(emb, mean_emb))
                if cos_sim >= IDENTITY_COSINE_THRESHOLD and cos_sim > best_sim:
                    best_sim = cos_sim
                    matched_iid = iid

            if matched_iid is not None:
                identity_embeddings[matched_iid].append(emb)
                fr["identity_id"] = matched_iid
                meta = identity_metas[matched_iid]
            else:
                iid = next_id
                next_id += 1
                identity_embeddings[iid] = [emb]
                label = f"人物 {IDENTITY_LABELS[iid - 1]}" if iid <= len(IDENTITY_LABELS) else f"人物 {iid}"
                id_to_label[iid] = label
                meta = {
                    "video_id": video_id,
                    "identity_label": label,
                    "face_count": 0,
                    "first_seen": fr["timestamp"],
                    "last_seen": fr["timestamp"],
                    "total_quality": 0.0,
                    "best_quality": -1.0,
                    "best_face_timestamp": fr["timestamp"],
                    "best_face_bbox": fr["bbox"],
                }
                identity_metas[iid] = meta
                fr["identity_id"] = iid

            meta["last_seen"] = max(meta["last_seen"], fr["timestamp"])
            meta["face_count"] += 1
            meta["total_quality"] += fr["quality"]
            if fr["quality"] > meta["best_quality"]:
                meta["best_quality"] = fr["quality"]
                meta["best_face_timestamp"] = fr["timestamp"]
                meta["best_face_bbox"] = fr["bbox"]

        # ── Phase 5: 写入 ctx ──
        pctx.ctx.face_identities = []
        for iid in sorted(identity_metas.keys()):
            meta = identity_metas[iid]
            id_embs = identity_embeddings[iid]
            mean_emb = np.mean(np.stack(id_embs), axis=0).tolist()
            pctx.ctx.face_identities.append({
                "video_id": video_id,
                "identity_label": meta["identity_label"],
                "face_count": meta["face_count"],
                "first_seen": meta["first_seen"],
                "last_seen": meta["last_seen"],
                "avg_quality": round(meta["total_quality"] / max(meta["face_count"], 1), 4),
                "face_embedding": mean_emb,
                "best_face_timestamp": meta["best_face_timestamp"],
                "best_face_bbox": meta["best_face_bbox"],
                "best_face_path": meta.get("best_face_path"),
            })

        pctx.ctx.face_detections = [
            {
                "video_id": video_id,
                "track_id": fr["track_id"],
                "identity_id": fr["identity_id"],
                "timestamp_sec": fr["timestamp"],
                "bbox": fr["bbox"],
                "quality_score": fr["quality"],
                "face_embedding": fr["embedding"],
            }
            for fr in face_records
        ]

        await pctx.tracker.update("face", sub_progress=1.0)

        unique_ids = len(identity_metas)
        logger.info(
            "[FaceRunner] Done: %d faces → %d identities",
            len(face_records), unique_ids,
        )
