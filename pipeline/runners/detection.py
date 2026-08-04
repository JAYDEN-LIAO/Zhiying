"""
pipeline/runners/detection.py
═══════════════════════════════════════════════════════════
检测与追踪 runner — YOLO11 批量推理 + 内置 BoT-SORT 追踪。

独立帧率（默认 10fps，config.yaml 可配置），与 1fps keyframe 池完全解耦。
通过 stream_frames() 流式抽帧（NVDEC GPU 硬解优先，cv2 fallback），
帧提取在后台线程/子进程中执行，不阻塞 asyncio 事件循环。

依赖 duration runner 产出（视频时长），
与 segmentation / keyframes 同批并行执行。

产出:
  - ctx.frame_detections  → engine._persist() 写入 frame_detections 表
  - ctx.tracks             → engine._persist() 写入 tracks 表
  - ctx.track_best_frames  → track_encode 消费（全分辨率帧，延迟提取）

entity 聚合已移至 engine._persist()（等所有 op 完成后统一处理，
保证 scenes 和 detections 均已就绪，O(n+m) 双指针）。
"""

import asyncio
import logging

import cv2
import numpy as np

from pipeline.runners.base import OperationRunner, PipelineContext
from utils.video_util import stream_frames

logger = logging.getLogger(__name__)

CROP_EXPAND_RATIO = 1.3      # bbox 外扩比例 (每边 15%) — 与 track_encode 一致
CROP_INTERVAL = 2.0          # track crop 缓存间隔 (秒) — 每 track 每 2s 存一帧供 track_encode


def _expand_crop(frame: np.ndarray, bbox: dict) -> np.ndarray:
    """bbox 外扩 30% 后裁剪，clamp 到画面边界。与 track_encode 版本一致。"""
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


class DetectionRunner(OperationRunner):
    """检测与追踪执行器 — 流式抽帧 → YOLO11 track() → 结果累加。

    v0.16 优化:
      - 生产者-消费者并发: 帧提取（NVDEC pipe）与 YOLO 推理重叠
      - 检测帧率 configurable (默认 10fps)
      - 两路独立 NVDEC 流（detection + search_encode），互不干扰
    """

    async def run(self, pctx: PipelineContext) -> None:
        detector = pctx.plugins.get("detector")

        if detector is None:
            logger.info("[DetectionRunner] Detector disabled, skipping")
            pctx.ctx.frame_detections = []
            pctx.ctx.tracks = []
            return

        # ── 独立检测帧率（与 1fps keyframe 池解耦）──
        det_cfg = pctx.config.get("plugins", {}).get("detector", {})
        detection_fps: float = det_cfg.get("detection_fps", 15)
        # 攒批大小。⚠️ 全局 GPU 锁串行化后不能用 1024：
        #   - YOLO 持锁整批前向 ~20s，embedder 全程饿死、共享流解码被连带卡死 → 管道病态慢
        #   - 1024 帧全量缓冲进显存（~5GB+）→ 显存撑满接近 OOM
        #   128 帧 ≈ 2-4s 持锁，embedder 每隔几秒就能插进来，管道顺畅，显存压力大降
        _BATCH_SIZE = 128
        duration = pctx.ctx.duration

        if duration is None or duration <= 0:
            logger.warning("[DetectionRunner] No valid duration, skipping")
            pctx.ctx.frame_detections = []
            pctx.ctx.tracks = []
            return

        total_samples = max(1, int(duration * detection_fps))
        total_batches = (total_samples + _BATCH_SIZE - 1) // _BATCH_SIZE
        logger.info(
            "[DetectionRunner] @%.1ffps dur=%.0fs ~%dframes → %d batch(s) @%d frames/batch",
            detection_fps, duration, total_samples, total_batches, _BATCH_SIZE,
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

        # ── 生产者-消费者并发：帧提取（NVDEC raw pipe）与 YOLO 推理重叠 ──
        video_path = pctx.ctx.file_path
        pipeline_cfg = pctx.config.get("pipeline", {})
        use_nvdec = pipeline_cfg.get("use_nvdec", False)

        # 搜索帧共享队列 + 搜索目标分辨率（从 encode_profile 读取）
        search_queue: asyncio.Queue | None = getattr(pctx, "search_frame_queue", None)
        frames_per_search = max(1, int(detection_fps))
        search_target_w, search_target_h = _get_search_target(pctx, pipeline_cfg)

        # 内部帧队列：生产者-消费者通道
        inner_queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        extract_error: Exception | None = None
        extract_frame_count = 0

        async def _extract() -> None:
            """后台任务：NVDEC raw pipe 读帧 → 推送 inner_queue + 搜索帧队列。

            单 NVDEC session，输出 raw NV12（无 MJPEG 编解码）。
            每 10 帧（1fps 采样）resize 后推送给 search_encode 消费。
            """
            nonlocal extract_error, extract_frame_count
            frame_idx = 0
            try:
                async for frame in stream_frames(
                    video_path,
                    fps=detection_fps,
                    use_nvdec=use_nvdec,
                    output_width=640,
                    output_height=384,
                    total_frames=total_samples,
                ):
                    timestamp = float(frame_idx) / detection_fps
                    # 推入内部队列供 YOLO 消费
                    await inner_queue.put((frame, timestamp))
                    # 1fps 采样推入搜索队列（共享 NVDEC 流，单 session）
                    if search_queue is not None and frame_idx % frames_per_search == 0:
                        small = cv2.resize(frame, (search_target_w, search_target_h))
                        await search_queue.put((small, timestamp))
                    frame_idx += 1
            except Exception as e:
                logger.error("[DetectionRunner] Frame extraction failed: %s", e)
                extract_error = e
            finally:
                await inner_queue.put(None)
            extract_frame_count = frame_idx

        extract_task = asyncio.create_task(_extract())

        # ── 消费循环：从队列取帧 → 攒批 → 推理 → 累加结果 ──
        frame_detections: list[dict] = []
        tracks_map: dict[int, dict] = {}
        best_cache: dict[int, dict] = {}  # track_id → {frame, bbox, timestamp, conf}
        batch_frames: list[np.ndarray] = []
        batch_timestamps: list[float] = []
        processed = 0

        await pctx.tracker.update("detection", sub_progress=0.0)

        try:
            while True:
                item = await inner_queue.get()
                if item is None:
                    break
                frame, timestamp = item
                batch_frames.append(frame)
                batch_timestamps.append(timestamp)

                if len(batch_frames) >= _BATCH_SIZE:
                    await self._process_batch(
                        detector, batch_frames, batch_timestamps,
                        pctx, frame_detections, tracks_map, best_cache,
                    )
                    processed += len(batch_frames)
                    current_batch = processed // _BATCH_SIZE
                    pct = min(processed / total_samples * 100, 99.0)
                    # 每 2 批输出进度 + 写 DB
                    if current_batch % 2 == 0 or current_batch == total_batches:
                        det_so_far = len(frame_detections)
                        trk_so_far = len(tracks_map)
                        msg = (
                            f"检测 {processed}/{total_samples}帧 ({pct:.0f}%) | "
                            f"batch {current_batch}/{total_batches} | "
                            f"{det_so_far}det {trk_so_far}trk"
                        )
                        logger.info("[detect] %s", msg)
                        await pctx.tracker.update(
                            "detection",
                            sub_progress=min(processed / total_samples, 0.98),
                            description=msg,
                        )
                    batch_frames = []
                    batch_timestamps = []

            # 处理最后一批
            if batch_frames:
                await self._process_batch(
                    detector, batch_frames, batch_timestamps,
                    pctx, frame_detections, tracks_map, best_cache,
                )
                processed += len(batch_frames)
        finally:
            # 通知 search_encode 流结束
            if search_queue is not None:
                await search_queue.put(None)
            # 停止帧提取后台任务
            extract_task.cancel()
            try:
                await extract_task
            except asyncio.CancelledError:
                pass

        if extract_error:
            raise extract_error  # type: ignore[misc]

        if processed == 0:
            logger.warning("[DetectionRunner] No frames extracted")
            pctx.ctx.frame_detections = []
            pctx.ctx.tracks = []
            return

        ctx_tracks = list(tracks_map.values())
        ctx_tracks.sort(key=lambda x: x["first_seen"])

        pctx.ctx.frame_detections = frame_detections
        pctx.ctx.tracks = ctx_tracks
        pctx.ctx.track_best_frames = best_cache  # 640×384 检测帧，track_encode 裁剪质量足够

        # 注意：entity 聚合已移至 engine._persist() —
        # 此时 scenes 可能尚未就绪（detection 不依赖 segmentation），
        # 在所有 op 完成后的 persist 阶段统一处理。

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
        best_cache: dict[int, dict],
    ) -> None:
        """处理一批帧：检测+追踪 → 累加到 frame_detections + tracks_map + best_cache。

        frames: 640×384 RGB 检测帧（stream_frames 输出，已缩放+BGR→RGB 转换）。
        best_cache 存储检测分辨率帧占位，后续由 _upgrade_best_frames 替换为全分辨率。
        """
        batch_dets = await detector.detect(frames)

        for i, (timestamp, dets) in enumerate(zip(timestamps, batch_dets)):
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
                        "segments": [{"start": float(timestamp), "end": float(timestamp)}],
                    }
                else:
                    trk = tracks_map[tid]
                    trk["last_seen"] = float(timestamp)
                    trk["frame_count"] += 1
                    # 延长最后一段
                    if trk["segments"]:
                        trk["segments"][-1]["end"] = float(timestamp)

                # 维护最佳帧缓存（检测分辨率 640×384，track_encode 裁剪质量足够）
                conf = t["confidence"]
                if tid not in best_cache or conf > best_cache[tid]["conf"]:
                    best_cache[tid] = {
                        "frame": frames[i],
                        "bbox": t["bbox"],
                        "timestamp": float(timestamp),
                        "conf": conf,
                    }

                # 维护 track crop 缓存（每 CROP_INTERVAL 秒一帧，track_encode 零 seek 读取）
                buf = pctx.ctx.track_crop_cache.get(tid)
                if buf is None:
                    buf = []
                    pctx.ctx.track_crop_cache[tid] = buf
                last_ts = buf[-1][0] if buf else -1e9
                if timestamp - last_ts >= CROP_INTERVAL:
                    crop = _expand_crop(frames[i], t["bbox"])
                    if crop.size > 0 and crop.shape[0] > 4 and crop.shape[1] > 4:
                        buf.append((float(timestamp), crop))


def _get_search_target(pctx, pipeline_cfg: dict) -> tuple[int, int]:
    """从视频 encode_profile 或 config 默认值获取搜索帧目标分辨率。"""
    profile_name = getattr(pctx.video, "encode_profile", None)
    if not profile_name:
        profile_name = pipeline_cfg.get("default_encode_profile", "balanced")
    profiles = pipeline_cfg.get("encode_profiles", {})
    profile = profiles.get(profile_name, {})
    w = profile.get("encode_width", 336)
    h = profile.get("encode_height", 224)
    return (w, h)
