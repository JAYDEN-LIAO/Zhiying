"""
pipeline/runners/plate.py
═══════════════════════════════════════════════════════════
车牌识别 runner — PaddleOCR 车牌检测 + 文字识别。

依赖 detection runner 产出 (ctx.track_best_frames + ctx.tracks)。
对 vehicle tracks (car/truck/bus/motorcycle) 的最佳帧提取车牌。

产出:
  - ctx.plate_detections → 车牌识别结果列表
"""

import logging

import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)

VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle"}


class PlateRunner(OperationRunner):
    """车牌检测 + OCR 执行器。"""

    async def run(self, pctx: PipelineContext) -> None:
        plate_recognizer = pctx.plugins.get("plate")
        if plate_recognizer is None:
            logger.info("[PlateRunner] No plate plugin, skipping")
            return

        tracks = pctx.ctx.tracks or []
        best_cache = pctx.ctx.track_best_frames or {}
        vehicle_tracks = [
            t for t in tracks
            if t["class_name"] in VEHICLE_CLASSES
        ]

        if not vehicle_tracks:
            logger.info("[PlateRunner] No vehicle tracks found, skipping")
            return

        video_id = str(pctx.video.id)

        # ── Phase 1: 收集 vehicle crops ──
        vehicle_metas: list[dict] = []
        crops: list[np.ndarray] = []

        for trk in vehicle_tracks:
            tid = trk["track_id"]
            cache = best_cache.get(tid)
            if not cache:
                continue
            frame = cache["frame"]
            ts = cache["timestamp"]

            h, w = frame.shape[:2]
            b = cache["bbox"]
            px1 = max(0, int(b["x1"] * w))
            py1 = max(0, int(b["y1"] * h))
            px2 = min(w, int(b["x2"] * w))
            py2 = min(h, int(b["y2"] * h))

            if px2 <= px1 or py2 <= py1:
                continue

            vehicle_crop = frame[py1:py2, px1:px2]
            if vehicle_crop.size == 0 or min(vehicle_crop.shape[:2]) < 20:
                continue

            vehicle_metas.append({
                "track_id": tid,
                "class_name": trk["class_name"],
                "timestamp": ts,
                "vehicle_bbox": b,
            })
            crops.append(vehicle_crop)

        if not crops:
            logger.info("[PlateRunner] No valid vehicle crops, skipping")
            return

        await pctx.tracker.update(
            "plate", sub_progress=0.1,
            description=f"车牌识别 {len(crops)} 个车辆 crops",
        )

        # ── Phase 2: 批量识别 ──
        all_plate_results = await plate_recognizer.recognize(crops)

        # ── Phase 3: 组装产出 ──
        plate_detections: list[dict] = []
        for meta, plate_list in zip(vehicle_metas, all_plate_results):
            for plate in plate_list:
                # 车牌 bbox 从 vehicle crop 坐标 → 全帧归一化坐标
                vb = meta["vehicle_bbox"]
                pb = plate["bbox"]
                frame_bbox = {
                    "x1": vb["x1"] + pb["x1"] * (vb["x2"] - vb["x1"]),
                    "y1": vb["y1"] + pb["y1"] * (vb["y2"] - vb["y1"]),
                    "x2": vb["x1"] + pb["x2"] * (vb["x2"] - vb["x1"]),
                    "y2": vb["y1"] + pb["y2"] * (vb["y2"] - vb["y1"]),
                }
                for k in frame_bbox:
                    frame_bbox[k] = max(0.0, min(1.0, frame_bbox[k]))

                plate_detections.append({
                    "video_id": video_id,
                    "track_id": meta["track_id"],
                    "class_name": meta["class_name"],
                    "timestamp_sec": meta["timestamp"],
                    "plate_text": plate["plate_text"],
                    "plate_type": plate.get("plate_type", "blue"),
                    "char_confidences": plate.get("char_confidences", []),
                    "bbox": frame_bbox,
                    "detection_confidence": plate["confidence"],
                    "thumbnail_path": None,
                })

        pctx.ctx.plate_detections = plate_detections

        await pctx.tracker.update("plate", sub_progress=1.0)

        logger.info(
            "[PlateRunner] Done: %d plates from %d vehicle tracks",
            len(plate_detections), len(vehicle_tracks),
        )
