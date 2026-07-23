"""
api/export_routes.py
═══════════════════════════════════════════════════════════
导出 API — 视频片段 / 帧序列 / 追踪轨迹 / 缩略图。

所有导出端点挂在 /api/v1/videos/{video_id}/export/... 下。
"""

import os
import uuid
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import (
    APIResponse,
    ExportClipRequest,
    ExportFramesRequest,
    ExportTrackRequest,
    ExportThumbnailsRequest,
)
from core.models import FrameDetection, Scene, Track, Video
from services.export_service import ExportService

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# 片段导出
# ═══════════════════════════════════════════════════════════

@router.post("/{video_id}/export/clip")
async def export_clip(
    video_id: uuid.UUID,
    payload: ExportClipRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """导出视频片段 — ffmpeg 流复制，不重编码，极速。

    请求体::

        {"start_sec": 0.0, "end_sec": 10.0}
    """
    result = await db.execute(
        select(Video.file_path, Video.duration).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    file_path: str = row.file_path
    duration: float | None = row.duration

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    # 边界校验
    if payload.start_sec >= payload.end_sec:
        raise HTTPException(status_code=400, detail="start_sec must be less than end_sec")

    if duration and duration > 0:
        if payload.start_sec >= duration:
            raise HTTPException(status_code=400, detail="start_sec exceeds video duration")
        if payload.end_sec > duration:
            payload.end_sec = duration

    config: dict = request.app.state.config
    service = ExportService(config)
    output_path = await service.export_clip(
        video_path=file_path,
        start_sec=payload.start_sec,
        end_sec=payload.end_sec,
        output_format=payload.output_format,
    )

    background_tasks.add_task(_cleanup_file, output_path)
    return _file_response(output_path, f"clip_{video_id}_{payload.start_sec}-{payload.end_sec}.mp4")


# ═══════════════════════════════════════════════════════════
# 帧导出
# ═══════════════════════════════════════════════════════════

@router.post("/{video_id}/export/frames")
async def export_frames(
    video_id: uuid.UUID,
    payload: ExportFramesRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """导出指定时间点的帧图片（zip 打包）。

    请求体::

        {"timestamps": [1.0, 5.0, 10.0], "format": "jpg"}
    """
    result = await db.execute(
        select(Video.file_path, Video.duration).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    file_path: str = row.file_path
    duration: float | None = row.duration

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    # 边界校验
    for ts in payload.timestamps:
        if ts < 0:
            raise HTTPException(status_code=400, detail=f"Negative timestamp: {ts}")
        if duration and duration > 0 and ts > duration:
            raise HTTPException(status_code=400, detail=f"Timestamp exceeds duration: {ts}s > {duration}s")

    config: dict = request.app.state.config
    service = ExportService(config)
    zip_path = await service.export_frames(
        video_path=file_path,
        timestamps=payload.timestamps,
        output_format=payload.format,
    )

    background_tasks.add_task(_cleanup_file, zip_path)
    return _file_response(zip_path, f"frames_{video_id}.zip", "application/zip")


# ═══════════════════════════════════════════════════════════
# 追踪轨迹导出
# ═══════════════════════════════════════════════════════════

@router.post("/{video_id}/export/track/{track_id}")
async def export_track_clip(
    video_id: uuid.UUID,
    track_id: int,
    payload: ExportTrackRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """导出追踪轨迹的视频片段，可选 bbox 叠加。

    请求体::

        {"draw_bbox": true}
    """
    # 1. 查询视频文件路径
    result = await db.execute(
        select(Video.file_path).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    file_path: str = row.file_path

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    # 2. 查询 track
    track_result = await db.execute(
        select(Track).where(
            Track.video_id == video_id,
            Track.track_id == track_id,
        )
    )
    track = track_result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail=f"Track {track_id} not found")

    # 3. 查询 detections
    dets_result = await db.execute(
        select(FrameDetection).where(
            FrameDetection.video_id == video_id,
            FrameDetection.track_id == track_id,
        ).order_by(FrameDetection.timestamp_sec)
    )
    db_dets = list(dets_result.scalars().all())

    # 4. 获取视频分辨率（通过 metadata 模块）
    from utils.metadata import get_video_metadata
    meta = await get_video_metadata(file_path)
    video_streams = meta.get("video_streams", [])
    if video_streams and video_streams[0].get("width") and video_streams[0].get("height"):
        resolution = (video_streams[0]["width"], video_streams[0]["height"])
    else:
        resolution = (1920, 1080)  # fallback

    # 5. 导出
    config: dict = request.app.state.config
    service = ExportService(config)

    track_data = {
        "track_id": track.track_id,
        "class_name": track.class_name,
        "first_seen": track.first_seen,
        "last_seen": track.last_seen,
        "frame_count": track.frame_count,
    }
    detections_data = [
        {
            "timestamp_sec": d.timestamp_sec,
            "bbox": d.bbox,
        }
        for d in db_dets
    ]

    output_path = await service.export_track_clip(
        video_path=file_path,
        track_data=track_data,
        detections=detections_data,
        video_resolution=resolution,
        draw_bbox=payload.draw_bbox,
    )

    background_tasks.add_task(_cleanup_file, output_path)
    filename = f"track_{track.class_name}_{track_id}_{video_id}.mp4"
    return _file_response(output_path, filename)


# ═══════════════════════════════════════════════════════════
# 缩略图导出
# ═══════════════════════════════════════════════════════════

@router.post("/{video_id}/export/thumbnails")
async def export_thumbnails(
    video_id: uuid.UUID,
    payload: ExportThumbnailsRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """导出场景缩略图（zip 打包）。

    请求体::

        {}              # 导出全部场景
        {"scene_indices": [0, 2, 5]}  # 仅导出指定场景
    """
    # 查询缩略图路径
    stmt = select(Scene.keyframe_path).where(Scene.video_id == video_id)

    if payload.scene_indices is not None:
        stmt = stmt.where(Scene.scene_index.in_(payload.scene_indices))

    stmt = stmt.order_by(Scene.scene_index)

    result = await db.execute(stmt)
    paths = [row.keyframe_path for row in result.all() if row.keyframe_path]

    if not paths:
        raise HTTPException(status_code=404, detail="No thumbnails found for this video")

    config: dict = request.app.state.config
    service = ExportService(config)
    zip_path = await service.export_thumbnails(paths)

    background_tasks.add_task(_cleanup_file, zip_path)
    return _file_response(zip_path, f"thumbnails_{video_id}.zip", "application/zip")


# ═══════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════

def _file_response(path: str, filename: str, media_type: str = "video/mp4") -> FileResponse:
    """构建 FileResponse，统一文件名与媒体类型。"""
    return FileResponse(
        path=path,
        media_type=media_type,
        filename=filename,
    )


async def _cleanup_file(path: str) -> None:
    """后台任务：清理导出临时文件。"""
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug("[Export] Cleaned up: %s", path)
    except OSError:
        logger.warning("[Export] Failed to clean up: %s", path)
