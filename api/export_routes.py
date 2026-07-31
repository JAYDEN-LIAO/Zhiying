"""
api/export_routes.py
═══════════════════════════════════════════════════════════
导出 API — 视频片段 / 帧序列 / 追踪轨迹 / 缩略图。

同时提供 POST (JSON body) 和 GET (query params) 两种入口。
前端浏览器使用 GET 直接导航下载，避免 async 后浏览器屏蔽自动下载。
"""

import os
import uuid
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import (
    ExportClipRequest,
    ExportFramesRequest,
    ExportTrackRequest,
    ExportThumbnailsRequest,
)
from core.models import FrameDetection, Scene, Track, Video
from services.export_service import ExportService, format_ts, sanitize_filename

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# 视频片段导出 — POST (JSON) + GET (query params)
# ═══════════════════════════════════════════════════════════

@router.post("/{video_id}/export/clip")
async def export_clip(
    video_id: uuid.UUID,
    payload: ExportClipRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """POST 版 — JSON body: {"start_sec":0, "end_sec":10}"""
    return await _handle_clip_export(video_id, payload.start_sec, payload.end_sec, request, background_tasks, db)


@router.get("/{video_id}/export/clip")
async def export_clip_get(
    video_id: uuid.UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    start_sec: float = Query(..., ge=0.0),
    end_sec: float = Query(..., ge=0.0),
) -> FileResponse:
    """GET 版 — 浏览器直接导航下载用。"""
    return await _handle_clip_export(video_id, start_sec, end_sec, request, background_tasks, db)


async def _handle_clip_export(
    video_id: uuid.UUID, start_sec: float, end_sec: float,
    request: Request, background_tasks: BackgroundTasks, db: AsyncSession,
) -> FileResponse:
    result = await db.execute(
        select(Video.file_path, Video.duration, Video.file_name).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    file_path: str = row.file_path
    duration: float | None = row.duration
    file_name: str = row.file_name
    base_name = os.path.splitext(file_name)[0]

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    config: dict = request.app.state.config
    service = ExportService(config)

    if start_sec == end_sec:
        if start_sec < 0 or (duration and duration > 0 and start_sec > duration):
            raise HTTPException(status_code=400, detail=f"Invalid timestamp: {start_sec}")
        out_path = await service.export_single_frame(video_path=file_path, timestamp=start_sec)
        background_tasks.add_task(_cleanup_file, out_path)
        return _file_response(out_path, f"{sanitize_filename(base_name)}_{format_ts(start_sec)}.jpg", "image/jpeg")

    if start_sec >= end_sec:
        raise HTTPException(status_code=400, detail="start_sec must be less than end_sec for clip")

    if duration and duration > 0:
        if start_sec >= duration:
            raise HTTPException(status_code=400, detail="start_sec exceeds video duration")
        if end_sec > duration:
            end_sec = duration

    output_path = await service.export_clip(video_path=file_path, start_sec=start_sec, end_sec=end_sec)
    background_tasks.add_task(_cleanup_file, output_path)
    ts_start = format_ts(start_sec)
    ts_end = format_ts(end_sec)
    return _file_response(output_path, f"{sanitize_filename(base_name)}_{ts_start}_{ts_end}.mp4")


# ═══════════════════════════════════════════════════════════
# 追踪轨迹导出 → zip — POST (JSON) + GET (query params)
# ═══════════════════════════════════════════════════════════

@router.post("/{video_id}/export/track/{track_id}")
async def export_track_zip(
    video_id: uuid.UUID, track_id: int,
    payload: ExportTrackRequest,
    request: Request, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """POST 版 — JSON body: {"draw_bbox": true}"""
    return await _handle_track_export(video_id, track_id, payload.draw_bbox, request, background_tasks, db)


@router.get("/{video_id}/export/track/{track_id}")
async def export_track_zip_get(
    video_id: uuid.UUID, track_id: int,
    request: Request, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    draw_bbox: bool = Query(default=True),
    display_id: int = Query(default=None, description="前端类内序号，用于文件名"),
) -> FileResponse:
    """GET 版 — 浏览器直接导航下载用。"""
    return await _handle_track_export(video_id, track_id, draw_bbox, request, background_tasks, db, display_id=display_id)


async def _handle_track_export(
    video_id: uuid.UUID, track_id: int, draw_bbox: bool,
    request: Request, background_tasks: BackgroundTasks, db: AsyncSession,
    display_id: int | None = None,
) -> FileResponse:
    result = await db.execute(
        select(Video.file_path, Video.file_name).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    file_path: str = row.file_path
    file_name: str = row.file_name
    base_name = os.path.splitext(file_name)[0]

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    track_result = await db.execute(
        select(Track).where(Track.video_id == video_id, Track.track_id == track_id)
    )
    track = track_result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")

    segments = track.segments or [{"start": track.first_seen, "end": track.last_seen}]

    all_dets_result = await db.execute(
        select(FrameDetection).where(
            FrameDetection.video_id == video_id,
            FrameDetection.track_id == track_id,
        ).order_by(FrameDetection.timestamp_sec)
    )
    all_dets = list(all_dets_result.scalars().all())

    per_seg_dets: list[list[dict]] = []
    for seg in segments:
        seg_start, seg_end = seg["start"], seg["end"]
        filtered = [
            {"timestamp_sec": d.timestamp_sec, "bbox": d.bbox}
            for d in all_dets if seg_start - 0.5 <= d.timestamp_sec <= seg_end + 0.5
        ]
        per_seg_dets.append(filtered)

    from utils.metadata import get_video_metadata
    meta = await get_video_metadata(file_path)
    video_streams = meta.get("video_streams", [])
    if video_streams and video_streams[0].get("width") and video_streams[0].get("height"):
        resolution = (video_streams[0]["width"], video_streams[0]["height"])
    else:
        resolution = (1920, 1080)

    config: dict = request.app.state.config
    service = ExportService(config)
    zip_path = await service.export_track_segments_zip(
        video_path=file_path, video_name=base_name, track_id=track.track_id,
        segments=segments, class_name=track.class_name,
        per_segment_detections=per_seg_dets if draw_bbox else None,
        video_resolution=resolution, draw_bbox=draw_bbox,
    )

    background_tasks.add_task(_cleanup_file, zip_path)
    label = display_id or track_id
    cls = track.class_name
    return _file_response(zip_path, f"{sanitize_filename(base_name)}_{cls}_{label}.zip", "application/zip")


# ═══════════════════════════════════════════════════════════
# 全部场景缩略图导出 — POST (JSON) + GET (直接下载)
# ═══════════════════════════════════════════════════════════

@router.post("/{video_id}/export/thumbnails")
async def export_thumbnails(
    video_id: uuid.UUID, payload: ExportThumbnailsRequest,
    request: Request, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """POST 版 — JSON body: {} 或 {"scene_indices": [0,2,5]}"""
    return await _handle_thumbnail_export(video_id, payload.scene_indices, request, background_tasks, db)


@router.get("/{video_id}/export/thumbnails")
async def export_thumbnails_get(
    video_id: uuid.UUID,
    request: Request, background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """GET 版 — 浏览器直接导航下载全部场景缩略图。"""
    return await _handle_thumbnail_export(video_id, None, request, background_tasks, db)


async def _handle_thumbnail_export(
    video_id: uuid.UUID, scene_indices: list[int] | None,
    request: Request, background_tasks: BackgroundTasks, db: AsyncSession,
) -> FileResponse:
    result = await db.execute(select(Video.file_name).where(Video.id == video_id))
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    file_name: str = row.file_name
    base_name = os.path.splitext(file_name)[0]

    stmt = select(Scene.keyframe_path).where(Scene.video_id == video_id)
    if scene_indices is not None:
        stmt = stmt.where(Scene.scene_index.in_(scene_indices))
    stmt = stmt.order_by(Scene.scene_index)

    result = await db.execute(stmt)
    paths = [row.keyframe_path for row in result.all() if row.keyframe_path]
    if not paths:
        raise HTTPException(status_code=404, detail="No thumbnails found")

    config: dict = request.app.state.config
    service = ExportService(config)
    zip_path = await service.export_thumbnails(paths, video_name=base_name)
    background_tasks.add_task(_cleanup_file, zip_path)
    return _file_response(zip_path, f"{sanitize_filename(base_name)}_thumbnails.zip", "application/zip")


# ═══════════════════════════════════════════════════════════
# Track 物体缩略图导出（原本就是 GET，无需改动）
# ═══════════════════════════════════════════════════════════

@router.get("/{video_id}/export/track/{track_id}/thumbnail")
async def export_track_thumbnail(
    video_id: uuid.UUID, track_id: int,
    request: Request, db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = None,
    display_id: int = Query(default=None, description="前端类内序号，用于文件名"),
) -> FileResponse:
    """导出 track 物体的全尺寸裁剪图（JPEG 下载）。"""
    result = await db.execute(
        select(Video.file_path, Video.file_name).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    file_path: str = row.file_path
    file_name: str = row.file_name

    track_result = await db.execute(
        select(Track).where(Track.video_id == video_id, Track.track_id == track_id)
    )
    track = track_result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")

    thumb_ts = min(track.first_seen + 0.5, track.last_seen)
    det_result = await db.execute(
        select(FrameDetection).where(
            FrameDetection.video_id == video_id,
            FrameDetection.track_id == track_id,
            FrameDetection.timestamp_sec.between(thumb_ts - 0.5, thumb_ts + 0.5),
        ).order_by(FrameDetection.timestamp_sec).limit(1)
    )
    det = det_result.scalar_one_or_none()
    if det is None:
        raise HTTPException(status_code=404, detail="No detection data for thumbnail")

    config: dict = request.app.state.config
    service = ExportService(config)
    out_path = await service.export_track_thumbnail(
        video_path=file_path, timestamp=thumb_ts, bbox=det.bbox,
    )
    safe_name = sanitize_filename(os.path.splitext(file_name)[0])
    label = display_id or track_id
    cls = track.class_name
    if background_tasks is not None:
        background_tasks.add_task(_cleanup_file, out_path)
    return _file_response(out_path, f"{safe_name}_{cls}_{label}_{format_ts(thumb_ts)}.jpg", "image/jpeg")


# ═══════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════

def _file_response(path: str, filename: str, media_type: str = "video/mp4") -> FileResponse:
    return FileResponse(path=path, media_type=media_type, filename=filename)


async def _cleanup_file(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug("[Export] Cleaned up: %s", path)
    except OSError:
        logger.warning("[Export] Failed to clean up: %s", path)
