"""
pipeline/runners/plate.py
═══════════════════════════════════════════════════════════
车牌识别 runner — HyperLPR3 车牌检测 + 文字识别。

依赖 detection runner 产出 (ctx.track_best_frames + ctx.tracks)。
对 vehicle tracks (car/truck/bus/motorcycle) 识别车牌。

车牌召回优化:
  - crop 外扩 25%（车牌贴保险杠边缘，YOLO 紧框常把车牌切掉）
  - 多候选帧：best 帧识别失败时，沿 track 出入口采样 ≤3 帧（车头/车尾朝相机、
    车牌可见概率最高），按各时刻实际 bbox 全分辨率重抽 + 外扩裁剪，
    批量识别，取最高置信度。仅失败 track 才补抽，正常视频零额外成本。

产出:
  - ctx.plate_detections → 车牌识别结果列表
"""

import asyncio
import logging

import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext
from utils.video_util import extract_keyframe_to_memory

logger = logging.getLogger(__name__)

VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle"}

CROP_EXPAND_RATIO = 0.25      # vehicle crop 外扩比例（每边 25%，clamp 到画面）
MAX_CANDIDATE_FRAMES = 3      # best 帧失败后的补充采样帧数上限（控制抽帧压力）
_MAX_CAND_TS_GAP = 0.5        # 候选时刻与最近检测的时间差上限（超出视为 track 空洞，跳过）


def _expand_bbox(bbox: dict, ratio: float = CROP_EXPAND_RATIO) -> dict:
    """bbox 归一化外扩 ratio（每边），clamp 到 [0,1]。

    车牌贴在保险杠边缘，YOLO 紧框常把车牌切掉；外扩给识别器留出车牌空间。
    """
    bw = bbox["x2"] - bbox["x1"]
    bh = bbox["y2"] - bbox["y1"]
    return {
        "x1": max(0.0, bbox["x1"] - bw * ratio),
        "y1": max(0.0, bbox["y1"] - bh * ratio),
        "x2": min(1.0, bbox["x2"] + bw * ratio),
        "y2": min(1.0, bbox["y2"] + bh * ratio),
    }


def _crop_frame(frame: np.ndarray, region: dict) -> np.ndarray | None:
    """按归一化 region 裁剪帧；无效/过小返回 None。"""
    h, w = frame.shape[:2]
    px1 = max(0, int(region["x1"] * w))
    py1 = max(0, int(region["y1"] * h))
    px2 = min(w, int(region["x2"] * w))
    py2 = min(h, int(region["y2"] * h))
    if px2 <= px1 or py2 <= py1:
        return None
    crop = frame[py1:py2, px1:px2]
    if crop.size == 0 or min(crop.shape[:2]) < 20:
        return None
    return crop


def _candidate_times(meta: dict) -> list[float]:
    """best 帧识别失败后的补充采样时间点（≤MAX_CANDIDATE_FRAMES）。

    选 track 出入口（车进入/驶离时车头/车尾朝相机，车牌可见概率最高）+ 长 track 中点。
    避开已试过的 best 帧时间，避免重复抽同一时刻。
    """
    first, last = float(meta["first_seen"]), float(meta["last_seen"])
    best = float(meta["timestamp"])
    out: list[float] = []
    for t in (first + 0.1, last - 0.1):
        if t >= first and t <= last and abs(t - best) > 0.3:
            out.append(t)
    # 长 track 补中点（与 best 帧拉开距离才有意义）
    if last - first > 4.0:
        mid = (first + last) / 2
        if abs(mid - best) > 1.0 and all(abs(mid - t) > 0.3 for t in out):
            out.append(mid)
    return out[:MAX_CANDIDATE_FRAMES]


def _pick_best(plates: list[dict]) -> dict | None:
    """同 track 多个候选结果里取置信度最高者。"""
    if not plates:
        return None
    return max(plates, key=lambda p: p.get("confidence", 0.0))


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

        # track → 该 track 全部逐帧检测（候选帧按实际时刻 bbox 定位用）
        det_by_track: dict[int, list[dict]] = {}
        for d in pctx.ctx.frame_detections or []:
            det_by_track.setdefault(d["track_id"], []).append(d)

        def _nearest_bbox(tid: int, ts: float) -> dict | None:
            dets = det_by_track.get(tid)
            if not dets:
                return None
            best = min(dets, key=lambda d: abs(d["timestamp_sec"] - ts))
            if abs(best["timestamp_sec"] - ts) > _MAX_CAND_TS_GAP:
                return None  # track 空洞，该时刻无检测可用
            return best["bbox"]

        # ── Phase 1: 收集 vehicle crops（best 帧，外扩裁剪）──
        vehicle_metas: list[dict] = []
        crops: list[np.ndarray] = []

        for trk in vehicle_tracks:
            tid = trk["track_id"]
            cache = best_cache.get(tid)
            if not cache:
                continue
            frame = cache["frame"]
            ts = cache["timestamp"]

            region = _expand_bbox(cache["bbox"])
            vehicle_crop = _crop_frame(frame, region)
            if vehicle_crop is None:
                continue

            vehicle_metas.append({
                "track_id": tid,
                "class_name": trk["class_name"],
                "timestamp": ts,
                "first_seen": trk["first_seen"],
                "last_seen": trk["last_seen"],
                "crop_region": region,
            })
            crops.append(vehicle_crop)

        if not crops:
            logger.info("[PlateRunner] No valid vehicle crops, skipping")
            return

        await pctx.tracker.update(
            "plate", sub_progress=0.1,
            description=f"车牌识别 {len(crops)} 个车辆 crops",
        )

        # ── Phase 2: best 帧批量识别 ──
        primary_results = await plate_recognizer.recognize(crops)

        # ── Phase 3: best 帧失败的 track 补充采样（≤3 帧/track）──
        fail_metas = [
            m for m, pl in zip(vehicle_metas, primary_results) if not pl
        ]
        extra_crops: list[np.ndarray] = []
        extra_regions: list[dict] = []   # 每个 extra crop 的实际裁剪区域（frame→bbox 映射用）
        extra_track_ids: list[int] = []
        cand_ts_for_extras: list[float] = []

        if fail_metas:
            cand_tasks: list[tuple[int, float]] = []  # (track_id, ts)
            for m in fail_metas:
                for ts in _candidate_times(m):
                    cand_tasks.append((m["track_id"], ts))

            sem = asyncio.Semaphore(4)  # 限制并发 ffmpeg 抽帧

            async def _grab(tid: int, ts: float) -> tuple[np.ndarray | None, dict | None, int | None, float | None]:
                bbox = _nearest_bbox(tid, ts)
                if bbox is None:
                    return None, None, None, None
                region = _expand_bbox(bbox)
                try:
                    async with sem:
                        f = await extract_keyframe_to_memory(pctx.ctx.file_path, ts)
                except Exception as e:
                    logger.warning(
                        "[PlateRunner] Candidate frame @%.2fs for track %d failed: %s",
                        ts, tid, e,
                    )
                    return None, None, None, None
                crop = _crop_frame(f, region)
                if crop is None:
                    return None, None, None, None
                return crop, region, tid, ts

            grabbed = await asyncio.gather(*[_grab(tid, ts) for tid, ts in cand_tasks])
            for crop, region, tid, ts in grabbed:
                if crop is not None:
                    extra_crops.append(crop)
                    extra_regions.append(region)
                    extra_track_ids.append(tid)
                    cand_ts_for_extras.append(ts)

            if extra_crops:
                extra_results = await plate_recognizer.recognize(extra_crops)
                logger.info(
                    "[PlateRunner] %d/%d tracks best-frame failed, %d candidate crops tried",
                    len(fail_metas), len(vehicle_metas), len(extra_crops),
                )
            else:
                extra_results = []

        # ── Phase 4: 每 track 合并最佳结果 + 组装 ──
        best_per_track: dict[int, tuple[dict, dict, float]] = {}  # track_id → (plate, crop_region, timestamp)

        for meta, pl_list in zip(vehicle_metas, primary_results):
            best = _pick_best(pl_list)
            if best is not None:
                best_per_track.setdefault(meta["track_id"], (best, meta["crop_region"], meta["timestamp"]))

        if extra_crops:
            for tid, region, ts, pl_list in zip(extra_track_ids, extra_regions, cand_ts_for_extras, extra_results):
                best = _pick_best(pl_list)
                if best is not None:
                    cur = best_per_track.get(tid)
                    if cur is None or best["confidence"] > cur[0]["confidence"]:
                        best_per_track[tid] = (best, region, ts)

        plate_detections: list[dict] = []
        for trk in vehicle_tracks:
            entry = best_per_track.get(trk["track_id"])
            if not entry:
                continue
            plate, region, ts = entry

            # 车牌 bbox 从 crop 坐标 → 全帧归一化坐标（经实际裁剪区域 crop_region 映射）
            pb = plate["bbox"]
            frame_bbox = {
                "x1": region["x1"] + pb["x1"] * (region["x2"] - region["x1"]),
                "y1": region["y1"] + pb["y1"] * (region["y2"] - region["y1"]),
                "x2": region["x1"] + pb["x2"] * (region["x2"] - region["x1"]),
                "y2": region["y1"] + pb["y2"] * (region["y2"] - region["y1"]),
            }
            for k in frame_bbox:
                frame_bbox[k] = max(0.0, min(1.0, frame_bbox[k]))

            plate_detections.append({
                "video_id": video_id,
                "track_id": trk["track_id"],
                "class_name": trk["class_name"],
                "timestamp_sec": ts,
                "plate_text": plate["plate_text"],
                "plate_type": plate.get("plate_type", "blue"),
                "char_confidences": [0.0 if (isinstance(c, float) and np.isnan(c)) else c for c in plate.get("char_confidences", [])],
                "bbox": frame_bbox,
                "detection_confidence": 0.0 if np.isnan(float(plate["confidence"])) else float(plate["confidence"]),
                "thumbnail_path": None,
            })

        pctx.ctx.plate_detections = plate_detections

        await pctx.tracker.update("plate", sub_progress=1.0)

        logger.info(
            "[PlateRunner] Done: %d plates from %d vehicle tracks",
            len(plate_detections), len(vehicle_tracks),
        )
        if pctx.log:
            await pctx.log(f"车牌识别完成：{len(plate_detections)} 个车牌（来自 {len(vehicle_tracks)} 条车辆轨迹）")
