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
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import (
    ExportClipRequest,
    ExportFramesRequest,
    ExportTrackRequest,
    ExportThumbnailsRequest,
)
from core.models import FrameDetection, OCRDetection, PlateDetection, Scene, Track, Video
from services.export_service import ExportService, condense_ocr, fmt_clock, format_ts, sanitize_filename

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
# 摘要 / OCR 画面文字导出 — txt（GET 直接导航下载，同 clip 模式）
# ═══════════════════════════════════════════════════════════

def _txt_response(text: str, filename: str) -> Response:
    """txt 下载响应：UTF-8 加 BOM + CRLF（Windows 记事本旧默认 ANSI/无换行会乱）；
    中文文件名走 RFC 5987 filename*（HTTP header 仅 latin-1）。"""
    import urllib.parse
    ascii_name = urllib.parse.quote(filename)
    return Response(
        content=text.replace("\n", "\r\n").encode("utf-8-sig"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{ascii_name}',
        },
    )


@router.get("/{video_id}/export/summary")
async def export_summary_txt(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """导出视频摘要为 txt（未生成摘要时 404）。"""
    result = await db.execute(
        select(Video.file_name, Video.summary).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    summary: dict | None = row.summary
    if not summary:
        raise HTTPException(status_code=404, detail="该视频未生成摘要")

    base_name = os.path.splitext(row.file_name or str(video_id))[0]
    lines: list[str] = [f"视频摘要 — {row.file_name}", ""]

    one_liner = (summary.get("one_liner") or "").strip()
    if one_liner:
        lines += ["【一句话概述】", one_liner, ""]

    for label, key in (("标签", "tags"), ("主题", "main_topics"), ("实体", "main_entities")):
        items = [str(t) for t in (summary.get(key) or []) if str(t).strip()]
        if items:
            lines.append(f"【{label}】{'、'.join(items)}")
    if lines[-1] != "":
        lines.append("")

    scenes = summary.get("scenes_summary") or []
    if scenes:
        lines += ["【分场景摘要】"]
        for sc in scenes:
            ts = f"{fmt_clock(sc.get('start_sec', 0))} - {fmt_clock(sc.get('end_sec', 0))}"
            desc = (sc.get("description") or "").strip()
            lines.append(f"[{ts}] {desc}")

    return _txt_response("\n".join(lines), f"{sanitize_filename(base_name)}_摘要.txt")


@router.get("/{video_id}/export/ocr")
async def export_ocr_txt(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """导出画面文字识别（OCR）清单为 txt（无识别数据时 404）。"""
    video_result = await db.execute(select(Video.file_name).where(Video.id == video_id))
    v_row = video_result.one_or_none()
    if v_row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    det_result = await db.execute(
        select(OCRDetection)
        .where(OCRDetection.video_id == video_id)
        .order_by(OCRDetection.timestamp_sec)
    )
    dets = list(det_result.scalars().all())
    if not dets:
        raise HTTPException(status_code=404, detail="该视频未开启画面文字识别或暂无识别数据")

    base_name = os.path.splitext(v_row.file_name or str(video_id))[0]
    condensed = condense_ocr(dets)
    lines: list[str] = [f"画面文字识别 — {v_row.file_name}", ""]
    for ts, text in condensed:
        lines.append(f"[{fmt_clock(ts)}] {text}")
    lines.append("")
    lines.append(f"共识别文字行：{len(condensed)} 行")

    return _txt_response("\n".join(lines), f"{sanitize_filename(base_name)}_画面文字.txt")


@router.get("/{video_id}/export/plates")
async def export_plates_txt(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """导出视频中识别到的全部车牌为 txt（与任务报告同一去重逻辑，无数据时 404）。"""
    video_result = await db.execute(select(Video.file_name).where(Video.id == video_id))
    v_row = video_result.one_or_none()
    if v_row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    rows = await db.execute(
        select(PlateDetection.plate_text).where(
            PlateDetection.video_id == video_id,
            PlateDetection.plate_text.isnot(None),
        )
    )
    plate_texts = list(dict.fromkeys(rows.scalars().all()))
    if not plate_texts:
        raise HTTPException(status_code=404, detail="该视频未开启车牌识别或暂无识别数据")

    base_name = os.path.splitext(v_row.file_name or str(video_id))[0]
    lines = [
        f"车牌识别清单 — {v_row.file_name}",
        f"去重后共 {len(plate_texts)} 个：",
        "",
        *plate_texts,
    ]
    return _txt_response("\n".join(lines), f"{sanitize_filename(base_name)}_车牌.txt")


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
