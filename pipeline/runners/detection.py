"""
pipeline/runners/detection.py
═══════════════════════════════════════════════════════════
检测与追踪 runner — YOLO11 批量推理 + 内置 BoT-SORT 追踪。

独立帧率（默认 10fps，可配置），与 1fps keyframe 池完全解耦。
cv2 流式抽帧 → detector.detect()（内部 model.track）→ 直接消费 track_id。

依赖 segmentation runner 产出（scene 时间边界），
与 keyframes / alignment 同批并行执行。

产出:
  - ctx.frame_detections → engine._persist() 写入 frame_detections 表
  - ctx.tracks           → engine._persist() 写入 tracks 表
  - scene.entities       → engine._persist() 通过已有 bulk_insert_scenes 写入
"""

import logging

import cv2
import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class DetectionRunner(OperationRunner):
    """检测与追踪执行器 — 独立帧率抽帧 → YOLO11 track() → 场景聚合。"""

    async def run(self, pctx: PipelineContext) -> None:
        detector = pctx.plugins.get("detector")
        scenes = pctx.ctx.scenes

        if detector is None or not scenes:
            logger.info("[DetectionRunner] Detector disabled or no scenes, skipping")
            pctx.ctx.frame_detections = []
            pctx.ctx.tracks = []
            return

        # ── 独立检测帧率（与 1fps keyframe 池解耦）──
        det_cfg = pctx.config.get("plugins", {}).get("detector", {})
        detection_fps: float = det_cfg.get("detection_fps", 10)
        batch_size: int = det_cfg.get("batch_size", 8)
        duration = pctx.ctx.duration

        if duration is None or duration <= 0:
            logger.warning("[DetectionRunner] No valid duration, skipping")
            pctx.ctx.frame_detections = []
            pctx.ctx.tracks = []
            return

        total_samples = max(1, int(duration * detection_fps))
        logger.info(
            "[DetectionRunner] Processing @ %.1f fps, duration=%.1fs, ~%d frames, batch_size=%d",
            detection_fps, duration, total_samples, batch_size,
        )

        # ── 设置目标类别过滤（per-video config）──
        target_classes = getattr(pctx.video, "detection_classes", None)
        if hasattr(detector, "set_target_classes"):
            detector.set_target_classes(target_classes)
        if target_classes:
            logger.info("[DetectionRunner] Filtering to classes: %s", target_classes)

        # ── 重置追踪器（新视频 = 新 tracker 状态）──
        if hasattr(detector, "reset_tracker"):
            detector.reset_tracker()

        # ── 流式抽帧 + 批量检测 + 累加结果 ──
        video_path = pctx.ctx.file_path
        frame_detections: list[dict] = []
        tracks_map: dict[int, dict] = {}
        best_cache: dict[int, dict] = {}  # track_id → {frame, bbox, timestamp, conf}

        batch_frames: list[np.ndarray] = []
        batch_timestamps: list[float] = []
        processed = 0

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error("[DetectionRunner] Cannot open video: %s", video_path)
            pctx.ctx.frame_detections = []
            pctx.ctx.tracks = []
            return

        try:
            source_fps = cap.get(cv2.CAP_PROP_FPS)
            if source_fps <= 0:
                source_fps = 30.0
            frame_interval = 1.0 / detection_fps
            frame_idx = 0
            next_ts = 0.0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                timestamp = frame_idx / source_fps
                if timestamp >= next_ts - 0.001 and timestamp <= duration:
                        next_ts += frame_interval
                        # BGR→RGB（cv2 读取 BGR，YOLO 需要 RGB）
                        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        batch_frames.append(rgb)
                        batch_timestamps.append(timestamp)

                        if len(batch_frames) >= batch_size:
                            await self._process_batch(
                                detector, batch_frames, batch_timestamps,
                                pctx, frame_detections, tracks_map, best_cache,
                            )
                            processed += len(batch_frames)
                            await pctx.tracker.update(
                                "detection",
                                sub_progress=min(processed / total_samples, 0.98),
                                description=f"检测追踪 {processed}/{total_samples} 帧",
                            )
                            batch_frames = []
                            batch_timestamps = []
                frame_idx += 1

            # 处理最后一批
            if batch_frames:
                await self._process_batch(
                    detector, batch_frames, batch_timestamps,
                    pctx, frame_detections, tracks_map,
                )
                processed += len(batch_frames)
        finally:
            cap.release()

        if processed == 0:
            logger.warning("[DetectionRunner] No frames extracted")
            pctx.ctx.frame_detections = []
            pctx.ctx.tracks = []
            return

        ctx_tracks = list(tracks_map.values())
        ctx_tracks.sort(key=lambda x: x["first_seen"])

        pctx.ctx.frame_detections = frame_detections
        pctx.ctx.tracks = ctx_tracks
        pctx.ctx.track_best_frames = best_cache

        # ── 按场景聚合 entities（给 label search 用）──
        self._aggregate_scene_entities(scenes, frame_detections)

        await pctx.tracker.update("detection", sub_progress=1.0)

        unique_tracks = len(tracks_map)
        logger.info(
            "[DetectionRunner] Done: %d detections, %d tracks across %d frames @ %.1f fps",
            len(frame_detections), unique_tracks, processed, detection_fps,
        )

    # ── 内部方法 ──

    @staticmethod
    async def _process_batch(
        detector,
        frames: list[np.ndarray],
        timestamps: list[float],
        pctx: PipelineContext,
        frame_detections: list[dict],
        tracks_map: dict[int, dict],
        best_cache: dict[int, dict] | None = None,
    ) -> None:
        """处理一批帧：检测+追踪 → 累加到 frame_detections + tracks_map + best_cache。"""
        batch_dets = await detector.detect(frames)

        for i, (timestamp, dets) in enumerate(zip(timestamps, batch_dets)):
            frame = frames[i]
            for t in dets:
                tid = t.get("track_id")
                if tid is None or tid < 0:
                    continue

                video_id = pctx.video.id

                frame_detections.append({
                    "video_id": video_id,
                    "track_id": tid,
                    "timestamp_sec": float(timestamp),
                    "class_name": t["class_name"],
                    "confidence": t["confidence"],
                    "bbox": t["bbox"],
                })

                if tid not in tracks_map:
                    tracks_map[tid] = {
                        "video_id": video_id,
                        "track_id": tid,
                        "class_name": t["class_name"],
                        "first_seen": float(timestamp),
                        "last_seen": float(timestamp),
                        "frame_count": 1,
                    }
                else:
                    trk = tracks_map[tid]
                    trk["last_seen"] = float(timestamp)
                    trk["frame_count"] += 1

                # 维护最佳帧缓存 (track_encode runner 复用)
                if best_cache is not None:
                    conf = t["confidence"]
                    if tid not in best_cache or conf > best_cache[tid]["conf"]:
                        best_cache[tid] = {
                            "frame": frame,
                            "bbox": t["bbox"],
                            "timestamp": float(timestamp),
                            "conf": conf,
                        }

    @staticmethod
    def _aggregate_scene_entities(scenes, frame_detections: list[dict]) -> None:
        """将逐帧检测结果按场景聚合去重，写入 scene.entities。

        每个 track_id 在单个场景中只出现一次（首次检测），
        与 scenes.entities 的 JSONB 注释格式完全一致。
        """
        if not frame_detections:
            return

        for scene in scenes:
            seen_tracks: set[int] = set()
            entities: list[dict] = []
            for fd in frame_detections:
                ts = fd["timestamp_sec"]
                if scene.start_sec <= ts <= scene.end_sec:
                    tid = fd["track_id"]
                    if tid not in seen_tracks:
                        seen_tracks.add(tid)
                        entities.append({
                            "label": fd["class_name"],
                            "bbox": [fd["bbox"]["x1"], fd["bbox"]["y1"],
                                     fd["bbox"]["x2"], fd["bbox"]["y2"]],
                            "confidence": fd["confidence"],
                            "start_sec": ts,
                            "end_sec": ts,
                            "track_id": tid,
                        })
            scene.entities = entities if entities else []
