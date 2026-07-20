"""
api/video_routes.py
═══════════════════════════════════════════════════════════
视频管理端点 — 上传 / 注册 / 参数 / 流式播放 / 缩略图等。
"""

import os
import uuid
import logging
import shutil

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse, VideoStatusResponse, ReuseRequest
from core.schemas import (
    VideoCreate, VideoResponse, VideoListItem, PipelineParams, ContentType,
)
from core.models import Video
from core.repository import create_video, get_video_with_relations, list_videos, delete_video
from services.video_service import VideoService

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# 视频 CRUD
# ═══════════════════════════════════════════════════════════

@router.post("/videos", status_code=201)
async def register_video(
    payload: VideoCreate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """注册视频处理任务，初始状态为 pending。"""
    video = await create_video(db, payload)
    return APIResponse(data=VideoResponse.model_validate(video))


@router.post("/videos/upload", status_code=201)
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
    content_type: str = Form("general"),
    language: str = Form("auto"),
    audio_enabled: bool = Form(False),
    vision_enabled: bool = Form(True),
    ocr_enabled: bool = Form(False),
    grounding_enabled: bool = Form(False),
    caption_enabled: bool = Form(True),
    detection_enabled: bool = Form(False),
    detection_classes: str | None = Form(None),
    summary_enabled: bool = Form(True),
    summary_mode: str = Form("native_video"),
    search_index_enabled: bool = Form(True),
    sample_fps: float = Form(1.0),
    segment_threshold: float = Form(0.5),
    caption_with_context: bool = Form(True),
    summary_detail: str = Form("standard"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """上传视频文件，创建 Video 记录（status=pending），不自动启动 Pipeline。"""
    config: dict = request.app.state.config
    video_dir = config.get("storage", {}).get("video_dir", "/home/cerno/data/videos")
    os.makedirs(video_dir, exist_ok=True)

    file_id = uuid.uuid4()
    ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    dest_path = os.path.join(video_dir, f"{file_id}{ext}")

    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = os.path.getsize(dest_path)

    # 解析 JSON 字符串 → list[str] | None
    detection_classes_list: list[str] | None = None
    if detection_classes:
        import json as _json
        try:
            parsed = _json.loads(detection_classes)
            detection_classes_list = parsed if isinstance(parsed, list) else None
        except (_json.JSONDecodeError, TypeError):
            detection_classes_list = None

    dto = VideoCreate(
        file_path=dest_path,
        file_name=file.filename or f"video_{file_id}{ext}",
        file_size=file_size,
        content_type=ContentType(content_type),
        language=language,
        audio_enabled=audio_enabled,
        vision_enabled=vision_enabled,
        ocr_enabled=ocr_enabled,
        grounding_enabled=grounding_enabled,
        caption_enabled=caption_enabled,
        detection_enabled=detection_enabled,
        detection_classes=detection_classes_list,
        summary_enabled=summary_enabled,
        summary_mode=summary_mode,
        search_index_enabled=search_index_enabled,
        sample_fps=sample_fps,
        segment_threshold=segment_threshold,
        caption_with_context=caption_with_context,
        summary_detail=summary_detail,
    )

    video = await create_video(db, dto)
    logger.info("[Upload] video=%s file=%s size=%d (pending, await params)", video.id, file.filename, file_size)
    return APIResponse(data=VideoResponse.model_validate(video))


@router.post("/videos/reuse", status_code=201)
async def reuse_video(
    payload: ReuseRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """基于已有视频的记录创建新处理任务，复用源视频文件。"""
    result = await db.execute(
        select(Video).where(Video.id == payload.source_video_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="源视频不存在")

    dto = VideoCreate(
        file_path=source.file_path,
        file_name=source.file_name,
        file_size=source.file_size,
        content_type=ContentType(payload.content_type),
        language=payload.language,
        audio_enabled=payload.audio_enabled,
        vision_enabled=payload.vision_enabled,
        ocr_enabled=payload.ocr_enabled,
        grounding_enabled=False,
        caption_enabled=payload.caption_enabled,
        detection_enabled=payload.detection_enabled,
        detection_classes=payload.detection_classes,
        summary_enabled=payload.summary_enabled,
        summary_mode=payload.summary_mode,
        search_index_enabled=payload.search_index_enabled,
        sample_fps=payload.sample_fps,
        segment_threshold=payload.segment_threshold,
        caption_with_context=payload.caption_with_context,
        summary_detail=payload.summary_detail,
    )
    video = await create_video(db, dto)

    config: dict = request.app.state.config
    db_session_factory = request.app.state.db_session_factory
    service = VideoService(
        config=config,
        db_session_factory=db_session_factory,
        embedder=request.app.state.embedder,
    )
    background_tasks.add_task(service.process_video, video.id)

    logger.info("[Reuse] video=%s sourced from %s", video.id, payload.source_video_id)
    return APIResponse(data=VideoResponse.model_validate(video))


@router.put("/videos/{video_id}/params")
async def update_video_params(
    video_id: uuid.UUID,
    payload: PipelineParams,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """设置视频处理参数并启动 Pipeline / 增量补跑。"""
    result = await db.execute(
        select(Video).where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    status_val = video.status.value if hasattr(video.status, "value") else video.status

    if status_val == "pending":
        await db.execute(
            update(Video)
            .where(Video.id == video_id)
            .values(
                content_type=payload.content_type,
                vision_enabled=payload.vision_enabled,
                audio_enabled=payload.audio_enabled,
                ocr_enabled=payload.ocr_enabled,
                caption_enabled=payload.caption_enabled,
                detection_enabled=payload.detection_enabled,
                detection_classes=payload.detection_classes,
                summary_enabled=payload.summary_enabled,
                summary_mode=payload.summary_mode,
                search_index_enabled=payload.search_index_enabled,
                language=payload.language,
                sample_fps=payload.sample_fps,
                segment_threshold=payload.segment_threshold,
                caption_with_context=payload.caption_with_context,
                summary_detail=payload.summary_detail,
            )
        )
        await db.commit()
        await db.refresh(video)

        config: dict = request.app.state.config
        db_session_factory = request.app.state.db_session_factory
        service = VideoService(
            config=config,
            db_session_factory=db_session_factory,
            embedder=request.app.state.embedder,
        )
        background_tasks.add_task(service.process_video, video.id)
        logger.info("[Params] video=%s full pipeline starting", video_id)
        return APIResponse(data=VideoResponse.model_validate(video))

    elif status_val in ("completed", "failed"):
        old = {
            "content_type": video.content_type.value if hasattr(video.content_type, "value") else video.content_type,
            "vision_enabled": video.vision_enabled,
            "audio_enabled": video.audio_enabled,
            "ocr_enabled": video.ocr_enabled,
            "caption_enabled": video.caption_enabled,
            "detection_enabled": video.detection_enabled,
            "detection_classes": video.detection_classes,
            "language": video.language,
            "sample_fps": video.sample_fps,
            "segment_threshold": video.segment_threshold,
            "caption_with_context": video.caption_with_context,
            "summary_detail": video.summary_detail,
            "summary_enabled": video.summary_enabled,
            "summary_mode": video.summary_mode,
            "search_index_enabled": video.search_index_enabled,
        }

        new = {
            "content_type": payload.content_type.value if hasattr(payload.content_type, "value") else payload.content_type,
            "vision_enabled": payload.vision_enabled,
            "audio_enabled": payload.audio_enabled,
            "ocr_enabled": payload.ocr_enabled,
            "caption_enabled": payload.caption_enabled,
            "detection_enabled": payload.detection_enabled,
            "detection_classes": payload.detection_classes,
            "language": payload.language,
            "sample_fps": payload.sample_fps,
            "segment_threshold": payload.segment_threshold,
            "caption_with_context": payload.caption_with_context,
            "summary_detail": payload.summary_detail,
            "summary_enabled": payload.summary_enabled,
            "summary_mode": payload.summary_mode,
            "search_index_enabled": payload.search_index_enabled,
        }

        non_l3_keys = {"content_type", "vision_enabled", "audio_enabled", "ocr_enabled",
                       "caption_enabled", "detection_enabled", "detection_classes",
                       "language", "sample_fps",
                       "segment_threshold", "caption_with_context", "summary_detail",
                       "summary_mode"}
        l3_keys = {"summary_enabled", "search_index_enabled"}

        non_l3_changed = {k for k in non_l3_keys if old.get(k) != new.get(k)}
        l3_changed = {k for k in l3_keys if old.get(k) != new.get(k)}
        l3_turned_on = {k for k in l3_changed if new.get(k) is True and old.get(k) is False}

        if non_l3_changed:
            raise HTTPException(
                status_code=400,
                detail=f"此修改需新建记录。已修改: {', '.join(non_l3_changed)}。仅功能开关（摘要/索引）可增量。",
            )

        if not l3_changed:
            raise HTTPException(status_code=400, detail="参数未改变")

        await db.execute(
            update(Video)
            .where(Video.id == video_id)
            .values(
                summary_enabled=payload.summary_enabled,
                search_index_enabled=payload.search_index_enabled,
            )
        )
        await db.commit()
        await db.refresh(video)

        config: dict = request.app.state.config
        db_session_factory = request.app.state.db_session_factory
        service = VideoService(
            config=config,
            db_session_factory=db_session_factory,
            embedder=request.app.state.embedder,
        )
        background_tasks.add_task(service.incremental_process, video.id, l3_turned_on)

        logger.info("[Params] video=%s incremental: %s", video_id, l3_turned_on)
        return APIResponse(data=VideoResponse.model_validate(video))

    else:
        raise HTTPException(status_code=400, detail=f"视频状态为 {status_val}，无法修改参数")


@router.get("/videos/{video_id}")
async def get_video(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """查询视频处理状态、进度及摘要制品。"""
    video = await get_video_with_relations(db, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return APIResponse(data=VideoResponse.model_validate(video))


@router.get("/videos/")
async def list_all_videos(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[VideoListItem]]:
    """查询所有视频，按创建时间降序返回简洁列表。"""
    videos = await list_videos(db)
    items = [VideoListItem.model_validate(v) for v in videos]
    return APIResponse(data=items)


@router.delete("/videos/{video_id}")
async def delete_video_endpoint(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[None]:
    """删除视频及其关联数据（scenes, transcript 通过外键 CASCADE 自动清除）。"""
    deleted = await delete_video(db, video_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Video not found")
    logger.info("[API] Video deleted: %s", video_id)
    return APIResponse(data=None)


@router.get("/videos/{video_id}/status")
async def get_video_status(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoStatusResponse]:
    """查询视频处理进度与当前阶段。"""
    result = await db.execute(
        select(
            Video.status,
            Video.progress,
            Video.error_message,
            Video.updated_at,
        ).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    return APIResponse(data=VideoStatusResponse(
        video_id=str(video_id),
        status=row.status.value if hasattr(row.status, 'value') else row.status,
        progress=row.progress,
        error_message=row.error_message,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    ))


@router.get("/videos/{video_id}/stream")
async def stream_video(
    video_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """流式传输原始视频文件，支持 HTTP Range 请求（视频拖动跳转）。"""
    result = await db.execute(
        select(Video.file_path, Video.file_name)
        .where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    file_path = row.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=row.file_name,
        content_disposition_type="inline",
    )


@router.get("/videos/{video_id}/thumbnail/{scene_index}")
async def get_thumbnail(
    video_id: uuid.UUID,
    scene_index: int,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """返回场景关键帧缩略图（搜索结果展示用）。"""
    from core.models import Scene as SceneModel
    result = await db.execute(
        select(SceneModel.keyframe_path)
        .where(
            SceneModel.video_id == video_id,
            SceneModel.scene_index == scene_index,
        )
    )
    row = result.one_or_none()
    if row is None or not row.keyframe_path:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    if not os.path.exists(row.keyframe_path):
        raise HTTPException(status_code=404, detail="Thumbnail file not found on disk")

    return FileResponse(
        path=row.keyframe_path,
        media_type="image/jpeg",
    )
