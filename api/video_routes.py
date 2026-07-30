"""
api/video_routes.py
═══════════════════════════════════════════════════════════
视频管理端点 — 上传 / 注册 / 参数 / 流式播放 / 缩略图等。
"""

import asyncio
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
    VideoCreate, VideoResponse, VideoListItem, VideoGroupResponse,
    PipelineParams, ContentType,
)
from core.models import Video, VideoGroup, VideoStatus
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
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """注册视频处理任务，初始状态为 pending。"""
    video = await create_video(db, payload)

    # 同步探测 + 异步 remux/proxy
    format_service = request.app.state.format_service
    await format_service.probe_and_save(video.id, payload.file_path)
    asyncio.create_task(format_service.process_format(video.id, payload.file_path))

    # AICheck 快检（同步等待，确保元数据请求时结果已就绪）
    await _run_ai_check_and_save(video.id, payload.file_path, request.app.state.db_session_factory)

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
    face_enabled: bool = Form(False),
    plate_enabled: bool = Form(False),
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
        face_enabled=face_enabled,
        plate_enabled=plate_enabled,
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

    # 同步探测格式（<100ms），异步执行 remux + proxy
    format_service = request.app.state.format_service
    await format_service.probe_and_save(video.id, dest_path)
    # 重操作异步执行
    asyncio.create_task(format_service.process_format(video.id, dest_path))

    # AICheck 快检（~30-60ms，同步等待，确保元数据请求时结果已就绪）
    await _run_ai_check_and_save(video.id, dest_path, request.app.state.db_session_factory)

    return APIResponse(data=VideoResponse.model_validate(video))


@router.post("/videos/upload/batch", status_code=201)
async def upload_videos_batch(
    request: Request,
    files: list[UploadFile] = File(...),
    content_type: str = Form("general"),
    language: str = Form("auto"),
    audio_enabled: bool = Form(False),
    vision_enabled: bool = Form(True),
    ocr_enabled: bool = Form(False),
    grounding_enabled: bool = Form(False),
    caption_enabled: bool = Form(True),
    detection_enabled: bool = Form(False),
    detection_classes: str | None = Form(None),
    face_enabled: bool = Form(False),
    plate_enabled: bool = Form(False),
    summary_enabled: bool = Form(True),
    summary_mode: str = Form("native_video"),
    search_index_enabled: bool = Form(True),
    sample_fps: float = Form(1.0),
    segment_threshold: float = Form(0.5),
    caption_with_context: bool = Form(True),
    summary_detail: str = Form("standard"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[VideoResponse]]:
    """批量上传视频文件，创建 VideoGroup 并将所有视频关联到该组。

    每个文件使用独立的 DB session 并发处理，避免 SQLAlchemy session 并发冲突。
    """
    config: dict = request.app.state.config
    video_dir = config.get("storage", {}).get("video_dir", "/home/cerno/data/videos")
    os.makedirs(video_dir, exist_ok=True)

    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")

    # 1. 创建 VideoGroup 记录（使用主 session，需 commit 以供其他 session 可见）
    group = VideoGroup(name=None)
    db.add(group)
    await db.commit()  # commit 让独立 session 能读到 group
    await db.refresh(group)
    group_id = group.id

    # 解析 detection_classes
    detection_classes_list: list[str] | None = None
    if detection_classes:
        import json as _json
        try:
            parsed = _json.loads(detection_classes)
            detection_classes_list = parsed if isinstance(parsed, list) else None
        except (_json.JSONDecodeError, TypeError):
            detection_classes_list = None

    # 2. 并发处理所有文件（每个文件独立 session）
    sem = asyncio.Semaphore(5)
    db_factory = request.app.state.db_session_factory
    format_service = request.app.state.format_service

    async def process_one(file: UploadFile) -> VideoResponse:
        async with sem:
            file_id = uuid.uuid4()
            ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
            dest_path = os.path.join(video_dir, f"{file_id}{ext}")

            with open(dest_path, "wb") as f:
                shutil.copyfileobj(file.file, f)

            file_size = os.path.getsize(dest_path)

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
                face_enabled=face_enabled,
                plate_enabled=plate_enabled,
                summary_enabled=summary_enabled,
                summary_mode=summary_mode,
                search_index_enabled=search_index_enabled,
                sample_fps=sample_fps,
                segment_threshold=segment_threshold,
                caption_with_context=caption_with_context,
                summary_detail=summary_detail,
                group_id=group_id,
            )

            # ★ 每个文件使用独立 session，不共享主 session
            async with db_factory() as fsession:
                video = await create_video(fsession, dto)
                # 同步 probe（probe_and_save 内部使用自己的 session）
                await format_service.probe_and_save(video.id, dest_path)

            # 异步 remux/proxy + AICheck（使用独立 session factory）
            asyncio.create_task(format_service.process_format(video.id, dest_path))
            await _run_ai_check_and_save(video.id, dest_path, db_factory)

            return VideoResponse.model_validate(video)

    results = await asyncio.gather(*[process_one(f) for f in files])

    await db.refresh(group)
    logger.info("[BatchUpload] group=%s files=%d", group.id, len(results))

    return APIResponse(data=results)


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
        face_enabled=payload.face_enabled,
        plate_enabled=payload.plate_enabled,
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
        captioner=getattr(request.app.state, "captioner", None),
    )
    background_tasks.add_task(service.process_video, video.id)

    # AICheck 快检（复用源视频文件，同步等待）
    await _run_ai_check_and_save(video.id, source.file_path, request.app.state.db_session_factory)

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
                face_enabled=payload.face_enabled,
                plate_enabled=payload.plate_enabled,
                summary_enabled=payload.summary_enabled,
                summary_mode=payload.summary_mode,
                search_index_enabled=payload.search_index_enabled,
                language=payload.language,
                sample_fps=payload.sample_fps,
                segment_threshold=payload.segment_threshold,
                caption_with_context=payload.caption_with_context,
                summary_detail=payload.summary_detail,
                encode_profile=payload.encode_profile,
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
            captioner=getattr(request.app.state, "captioner", None),
        )
        background_tasks.add_task(service.process_video, video.id)
        logger.info("[Params] video=%s full pipeline starting", video_id)

        # ★ 如果是组内视频，同组其他 pending 视频也应用相同参数并启动 pipeline
        if video.group_id:
            group_result = await db.execute(
                select(Video).where(
                    Video.group_id == video.group_id,
                    Video.id != video_id,
                    Video.status == VideoStatus.PENDING,
                )
            )
            siblings = group_result.scalars().all()
            for sibling in siblings:
                await db.execute(
                    update(Video)
                    .where(Video.id == sibling.id)
                    .values(
                        content_type=payload.content_type,
                        vision_enabled=payload.vision_enabled,
                        audio_enabled=payload.audio_enabled,
                        ocr_enabled=payload.ocr_enabled,
                        caption_enabled=payload.caption_enabled,
                        detection_enabled=payload.detection_enabled,
                        detection_classes=payload.detection_classes,
                        face_enabled=payload.face_enabled,
                        plate_enabled=payload.plate_enabled,
                        summary_enabled=payload.summary_enabled,
                        summary_mode=payload.summary_mode,
                        search_index_enabled=payload.search_index_enabled,
                        language=payload.language,
                        sample_fps=payload.sample_fps,
                        segment_threshold=payload.segment_threshold,
                        caption_with_context=payload.caption_with_context,
                        summary_detail=payload.summary_detail,
                        encode_profile=payload.encode_profile,
                    )
                )
                await db.commit()
                background_tasks.add_task(service.process_video, sibling.id)
                logger.info("[Params] sibling video=%s (group=%s) pipeline starting", sibling.id, video.group_id)

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
            "face_enabled": video.face_enabled,
            "plate_enabled": video.plate_enabled,
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
            "face_enabled": payload.face_enabled,
            "plate_enabled": payload.plate_enabled,
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
            captioner=getattr(request.app.state, "captioner", None),
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
    hevc_ok: bool = False,  # 前端上报 HEVC 能力
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """流式传输视频，根据客户端能力智能选择最佳可播文件。

    - hevc_ok=false (Firefox/Chrome): HEVC 源返回 proxy，未就绪时返回 202
    - hevc_ok=true (Safari/Electron): HEVC 源直接返回 remuxed 文件
    """
    result = await db.execute(
        select(Video.file_name, Video.file_path).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    file_name = row.file_name

    # 使用 FormatService 智能路由
    format_service = request.app.state.format_service
    target = await format_service.get_stream_target(video_id, hevc_ok)

    if target is None:
        # proxy 未就绪，返回进度信息
        raise HTTPException(
            status_code=202,
            detail="Proxy transcode in progress",
            headers={"X-Proxy-Status": "processing"},
        )

    if not os.path.exists(target.file_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    return FileResponse(
        path=target.file_path,
        media_type=target.media_type,
        filename=file_name,
        content_disposition_type="inline",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-cache",
        },
    )


@router.get("/videos/{video_id}/proxy-status")
async def get_proxy_status(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """查询代理转码进度。"""
    from core.schemas import ProxyStatus as ProxyStatusSchema

    result = await db.execute(
        select(
            Video.proxy_status,
            Video.proxy_progress,
            Video.proxy_path,
        ).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    return APIResponse(data=ProxyStatusSchema(
        status=row.proxy_status or "none",
        progress=float(row.proxy_progress or 0.0),
        proxy_path=row.proxy_path,
    ).model_dump())


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


@router.get("/videos/{video_id}/metadata")
async def get_video_metadata_endpoint(
    video_id: uuid.UUID,
    request: Request,
    verbose: bool = False,
    db: AsyncSession = Depends(get_db),
) -> APIResponse:
    """获取视频文件的技术元数据（编码、分辨率、GPS、HDR、设备信息等）。

    - 首次请求实时提取（pymediainfo + exiftool），结果缓存到 DB
    - 后续请求直接返回缓存（<1ms）
    - ``?verbose=true`` 可返回原始提取数据（调试用）
    - 附带来源分析（规则引擎）和 AI 检测结果（AICheck 快检）
    """
    from utils.metadata import get_video_metadata as extract_metadata
    from api.schemas import VideoMetadataResponse, AIDetectResult

    result = await db.execute(
        select(Video.file_path, Video.metadata_json,
               Video.source_analysis, Video.ai_detect_result)
        .where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    file_path = row.file_path
    source_analysis = row.source_analysis
    ai_detect_result = row.ai_detect_result

    # ── Fast path: return cached metadata from DB ──
    from utils.metadata import _METADATA_CACHE_VERSION
    if row.metadata_json and row.metadata_json.get("_cache_version") == _METADATA_CACHE_VERSION:
        cached = dict(row.metadata_json)
        if not verbose:
            cached.pop("raw", None)
        cached["source_analysis"] = source_analysis
        cached["ai_detect"] = _build_ai_detect_response(ai_detect_result)
        return APIResponse(data=VideoMetadataResponse(**cached))

    # ── Slow path: live extraction ──
    meta = await extract_metadata(file_path, verbose=verbose)

    # ── 来源分析（规则引擎，<10ms） ──
    # 从已提取的结构化元数据构建 media_info（不依赖 raw 内部格式）
    _vs = (meta.get("video_streams") or [{}])[0]
    _as = (meta.get("audio_streams") or [{}])[0]
    _media_info = {
        "width": _vs.get("width"),
        "height": _vs.get("height"),
        "video_codec": _vs.get("codec"),
        "frame_rate": _vs.get("fps"),
        "has_audio": len(meta.get("audio_streams") or []) > 0,
        "audio_codec": _as.get("codec"),
    }
    from utils.video_source import classify_video_source
    source_analysis = classify_video_source(
        exif_data=meta.get("device"),
        file_name=os.path.basename(file_path),
        media_info=_media_info,
    )
    if source_analysis:
        asyncio.create_task(_cache_source_analysis(
            video_id, source_analysis, request.app.state.db_session_factory
        ))

    # ── Store to DB for next time (fire-and-forget) ──
    if meta.get("container") is not None:  # only cache successful extractions
        from utils.metadata import _METADATA_CACHE_VERSION
        meta["_cache_version"] = _METADATA_CACHE_VERSION
        asyncio.create_task(_cache_metadata(video_id, meta, request.app.state.db_session_factory))

    if not verbose:
        meta.pop("raw", None)

    meta["source_analysis"] = source_analysis
    meta["ai_detect"] = _build_ai_detect_response(ai_detect_result)
    return APIResponse(data=VideoMetadataResponse(**meta))


async def _cache_metadata(
    video_id: uuid.UUID,
    meta: dict,
    db_session_factory,
) -> None:
    """Store extracted metadata JSON to DB for future fast retrieval."""
    try:
        async with db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == video_id)
                .values(metadata_json=meta)
            )
            await session.commit()
        logger.debug("[Metadata] Cached to DB for video %s", video_id)
    except Exception:
        logger.warning("[Metadata] Failed to cache for %s", video_id, exc_info=True)


async def _run_ai_check_and_save(
    video_id: uuid.UUID,
    file_path: str,
    db_session_factory,
) -> None:
    """运行 AICheck 全面检测（元数据+SEI+C2PA+像素级深度分析）。

    先写 "analyzing" 状态到 DB（前端可展示"检测中"），
    实际 AICheck --deep 异步执行，完成后覆盖更新。
    """
    # 先标记 analyzing
    try:
        async with db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == video_id)
                .values(ai_detect_result={"status": "analyzing"})
            )
            await session.commit()
    except Exception as e:
        logger.warning("[AICheck] Failed to set analyzing state: %s", e)

    # 异步跑全面检测（包括 --deep 像素分析）
    asyncio.create_task(_run_ai_check_deep(video_id, file_path, db_session_factory))


async def _run_ai_check_deep(
    video_id: uuid.UUID,
    file_path: str,
    db_session_factory,
) -> None:
    """后台任务：执行 AICheck --deep 全面检测并写入 DB。"""
    try:
        from services.ai_detect_service import run_ai_check
        result = await run_ai_check(file_path, deep=True)
        if result.get("status") == "error":
            logger.info("[AICheck] Skipped save — error: %s",
                         result.get("error_message", "")[:100])
            # 出错时写入 error 状态，前端可展示
            async with db_session_factory() as session:
                await session.execute(
                    update(Video)
                    .where(Video.id == video_id)
                    .values(ai_detect_result=result)
                )
                await session.commit()
            return
        async with db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == video_id)
                .values(ai_detect_result=result)
            )
            await session.commit()
        logger.info("[AICheck] Deep check done for video=%s verdict=%s",
                     video_id, result.get("verdict"))
    except Exception as e:
        logger.warning("[AICheck] Deep check failed for %s: %s", video_id, e)
        try:
            async with db_session_factory() as session:
                await session.execute(
                    update(Video)
                    .where(Video.id == video_id)
                    .values(ai_detect_result={
                        "status": "error",
                        "error_message": str(e)[:200],
                    })
                )
                await session.commit()
        except Exception:
            pass


async def _cache_source_analysis(
    video_id: uuid.UUID,
    source_analysis: dict,
    db_session_factory,
) -> None:
    """缓存来源分析结果到 DB。"""
    try:
        async with db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == video_id)
                .values(source_analysis=source_analysis)
            )
            await session.commit()
        logger.debug("[SourceAnalysis] Cached for video %s", video_id)
    except Exception as e:
        logger.warning("[SourceAnalysis] Failed to cache for %s: %s", video_id, e)


def _build_ai_detect_response(
    ai_detect_result: dict | None,
) -> dict | None:
    """构建 AI 检测响应 dict。

    返回 None（旧视频尚未检测）或 AICheck 结果（包括 analyzing/completed/error 状态）。
    """
    if ai_detect_result is None:
        return None
    return dict(ai_detect_result)


