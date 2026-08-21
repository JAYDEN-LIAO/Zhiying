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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse, VideoStatusResponse, ReuseRequest, AnalyzeBatchRequest, RenameFileRequest
from core.schemas import (
    VideoCreate, VideoResponse, VideoListItem, VideoGroupResponse,
    PipelineParams, ExternalVideoRegister, ContentType, ToggleSettings,
    FileItem, VersionInfo,
)
from core.config_loader import load_config
from core.models import Video, VideoGroup, VideoStatus
from core.repository import (
    create_video, get_video_with_relations, get_video_by_external_file_id,
    list_videos, delete_video,
    list_file_roots, list_file_versions, resolve_file_id,
    append_task_log,
)
from core.cancellation import mark_cancelled, unmark_cancelled
from services.video_service import VideoService, RUNNING_VIDEOS

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

    return APIResponse(data=VideoResponse.model_validate(video))


async def _ensure_group_exists(db: AsyncSession, group_id: uuid.UUID) -> None:
    """校验案例（分组）存在——不存在返回友好提示（前端可能传了已删除/陈旧的案例 id）。

    纯上传/批量上传归组时若 group_id 失效，直接 FK 报错会 500 + 一屏堆栈；
    这里提前校验给 400 文案，并作为 create_video 的兜底 catch。
    """
    row = await db.execute(select(VideoGroup).where(VideoGroup.id == group_id))
    if row.scalar_one_or_none() is None:
        raise HTTPException(status_code=400, detail="案例不存在或已被删除，请刷新案例列表后重试")


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
    summary_enabled: bool = Form(False),
    summary_mode: str = Form("vlm_llm"),
    search_index_enabled: bool = Form(True),
    sample_fps: float = Form(1.0),
    segment_threshold: float = Form(0.5),
    caption_with_context: bool = Form(True),
    summary_detail: str = Form("standard"),
    group_id: uuid.UUID | None = Form(None),  # v0.34 归入指定文件库分组
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """上传视频文件，创建 Video 记录（status=pending），不自动启动 Pipeline。"""
    config: dict = load_config()
    video_dir = config.get("storage", {}).get("video_dir", "/home/zhiying/data/videos")
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
        group_id=group_id,
    )

    if group_id is not None:
        await _ensure_group_exists(db, group_id)
    try:
        video = await create_video(db, dto)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="案例不存在或已被删除，请刷新案例列表后重试")
    logger.info("[Upload] video=%s file=%s size=%d (pending, await params)", video.id, file.filename, file_size)

    # 同步探测格式（<100ms），异步执行 remux + proxy
    format_service = request.app.state.format_service
    await format_service.probe_and_save(video.id, dest_path)
    # 重操作异步执行
    asyncio.create_task(format_service.process_format(video.id, dest_path))

    # 快速提取缩略图（异步，不阻塞上传流程）
    from utils.thumbnail_util import extract_thumbnail_on_upload, update_video_thumbnail_path
    async def _extract_and_save_thumb():
        thumb_path = await extract_thumbnail_on_upload(video.id, dest_path, config)
        if thumb_path:
            await update_video_thumbnail_path(request.app.state.db_session_factory, video.id, thumb_path)
    asyncio.create_task(_extract_and_save_thumb())

    return APIResponse(data=VideoResponse.model_validate(video))


@router.post("/videos/register-external", status_code=201)
async def register_external_video(
    payload: ExternalVideoRegister,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """注册平台共享路径的视频 — 绝对路径就地引用，不上传字节（云智集成）。

    源文件归平台所有（source_owned=False），删除视频时 Zhiying 不 unlink 源文件
    （StorageManager 跳过外部源文件清理）。其余流程与上传一致：
    建 pending 记录 → 同步 probe → 异步 remux/proxy → 前端配置参数后启动 Pipeline。
    """
    config: dict = load_config()
    file_path = os.path.abspath(payload.file_path)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"共享文件不存在: {file_path}")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=400, detail=f"共享路径不是文件: {file_path}")
    file_size = os.path.getsize(file_path)
    if file_size <= 0:
        raise HTTPException(status_code=400, detail=f"共享文件为空: {file_path}")
    file_name = payload.file_name or os.path.basename(file_path)

    dto = VideoCreate(
        file_path=file_path,
        file_name=file_name,
        file_size=file_size,
        source_owned=False,  # 平台共享文件归平台所有
        content_type=payload.content_type,
        language=payload.language,
        audio_enabled=payload.audio_enabled,
        vision_enabled=payload.vision_enabled,
        ocr_enabled=payload.ocr_enabled,
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
        external_file_id=payload.external_file_id,
    )

    video = await create_video(db, dto)
    logger.info(
        "[RegisterExternal] video=%s file=%s source_owned=False external_file_id=%s (platform shared)",
        video.id, file_name, payload.external_file_id,
    )

    # 同步探测格式（<100ms），异步执行 remux + proxy
    format_service = request.app.state.format_service
    await format_service.probe_and_save(video.id, file_path)
    asyncio.create_task(format_service.process_format(video.id, file_path))

    # 快速提取缩略图（异步，不阻塞注册流程）
    from utils.thumbnail_util import extract_thumbnail_on_upload, update_video_thumbnail_path
    async def _extract_and_save_thumb():
        thumb_path = await extract_thumbnail_on_upload(video.id, file_path, config)
        if thumb_path:
            await update_video_thumbnail_path(request.app.state.db_session_factory, video.id, thumb_path)
    asyncio.create_task(_extract_and_save_thumb())

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
    summary_enabled: bool = Form(False),
    summary_mode: str = Form("vlm_llm"),
    search_index_enabled: bool = Form(True),
    sample_fps: float = Form(1.0),
    segment_threshold: float = Form(0.5),
    caption_with_context: bool = Form(True),
    summary_detail: str = Form("standard"),
    group_id: uuid.UUID | None = Form(None),  # v0.34 归入指定文件库分组（否则自动建组）
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[VideoResponse]]:
    """批量上传视频文件，创建 VideoGroup 并将所有视频关联到该组。

    每个文件使用独立的 DB session 并发处理，避免 SQLAlchemy session 并发冲突。
    """
    config: dict = load_config()
    video_dir = config.get("storage", {}).get("video_dir", "/home/zhiying/data/videos")
    os.makedirs(video_dir, exist_ok=True)

    if not files:
        raise HTTPException(status_code=400, detail="请至少上传一个文件")

    # 1. 创建 VideoGroup 记录（使用主 session，需 commit 以供其他 session 可见）
    #    v0.34：若指定 group_id 则复用该组（文件库新建文件后上传归组），否则自动建组
    created_group: VideoGroup | None = None
    if group_id is None:
        created_group = VideoGroup(name=None)
        db.add(created_group)
        await db.commit()  # commit 让独立 session 能读到 group
        await db.refresh(created_group)
        group_id = created_group.id
    else:
        # 复用指定案例：先校验存在，避免并发创建时 FK 报错
        await _ensure_group_exists(db, group_id)

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
                try:
                    video = await create_video(fsession, dto)
                except IntegrityError:
                    await fsession.rollback()
                    raise HTTPException(status_code=400, detail="案例不存在或已被删除，请刷新案例列表后重试")
                # 同步 probe（probe_and_save 内部使用自己的 session）
                await format_service.probe_and_save(video.id, dest_path)

            # 异步 remux/proxy（使用独立 session factory）
            asyncio.create_task(format_service.process_format(video.id, dest_path))

            # 快速提取缩略图（异步，不阻塞上传流程）
            from utils.thumbnail_util import extract_thumbnail_on_upload, update_video_thumbnail_path
            async def _extract_and_save_thumb():
                thumb_path = await extract_thumbnail_on_upload(video.id, dest_path, config)
                if thumb_path:
                    await update_video_thumbnail_path(db_factory, video.id, thumb_path)
            asyncio.create_task(_extract_and_save_thumb())

            return VideoResponse.model_validate(video)

    results = await asyncio.gather(*[process_one(f) for f in files])

    if created_group is not None:
        await db.refresh(created_group)
        logger.info("[BatchUpload] group=%s files=%d", created_group.id, len(results))
    else:
        logger.info("[BatchUpload] group=%s (existing) files=%d", group_id, len(results))

    return APIResponse(data=results)


@router.post("/videos/analyze-batch")
async def analyze_videos_batch(
    payload: AnalyzeBatchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """批量解析：精确启动指定视频的管道（仅 pending），不触发组同步。

    用于案例库「批量解析」——勾选谁就启动谁，同组其余 pending 兄弟保持不动
    （区别于 PUT /params 的组同步行为）。params 可选：提供则整批应用该参数集。
    """
    params = payload.params
    started = 0
    skipped = 0
    for vid in payload.video_ids:
        result = await db.execute(select(Video).where(Video.id == vid))
        video = result.scalar_one_or_none()
        if video is None:
            skipped += 1
            continue
        status_val = video.status.value if hasattr(video.status, "value") else video.status
        if status_val != "pending":
            skipped += 1
            continue
        if params is not None:
            await db.execute(
                update(Video).where(Video.id == video.id).values(
                    content_type=params.content_type,
                    vision_enabled=params.vision_enabled,
                    audio_enabled=params.audio_enabled,
                    ocr_enabled=params.ocr_enabled,
                    caption_enabled=params.caption_enabled,
                    detection_enabled=params.detection_enabled,
                    detection_classes=params.detection_classes,
                    face_enabled=params.face_enabled,
                    plate_enabled=params.plate_enabled,
                    summary_enabled=params.summary_enabled,
                    summary_mode=params.summary_mode,
                    search_index_enabled=params.search_index_enabled,
                    language=params.language,
                    sample_fps=params.sample_fps,
                    segment_threshold=params.segment_threshold,
                    caption_with_context=params.caption_with_context,
                    summary_detail=params.summary_detail,
                    encode_profile=params.encode_profile,
                )
            )
        await request.app.state.pipeline_queue.enqueue("pipeline", {"video_id": str(video.id)})
        await append_task_log(db, video.id, "批量解析：任务入队")
        started += 1

    logger.info("[AnalyzeBatch] requested=%d started=%d skipped=%d", len(payload.video_ids), started, skipped)
    return APIResponse(data={"started": started, "skipped": skipped})


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

    config: dict = load_config()
    db_session_factory = request.app.state.db_session_factory
    service = VideoService(
        config=config,
        db_session_factory=db_session_factory,
        embedder=request.app.state.embedder,
        captioner=getattr(request.app.state, "captioner", None),
    )
    await request.app.state.pipeline_queue.enqueue("pipeline", {"video_id": str(video.id)})

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

        config: dict = load_config()
        db_session_factory = request.app.state.db_session_factory
        service = VideoService(
            config=config,
            db_session_factory=db_session_factory,
            embedder=request.app.state.embedder,
            captioner=getattr(request.app.state, "captioner", None),
            detector=getattr(request.app.state, "detector", None),
        )
        await request.app.state.pipeline_queue.enqueue("pipeline", {"video_id": str(video.id)})
        await append_task_log(db, video.id, "参数已提交，任务入队")
        logger.info("[Params] video=%s full pipeline starting", video_id)

        # ★ 如果是组内视频且 apply_to_group=true，同组其他 pending 视频也应用相同参数并启动 pipeline
        if payload.apply_to_group and video.group_id:
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
                await request.app.state.pipeline_queue.enqueue("pipeline", {"video_id": str(sibling.id)})
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
                       "segment_threshold", "caption_with_context", "summary_detail", "summary_mode"}
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

        config: dict = load_config()
        db_session_factory = request.app.state.db_session_factory
        service = VideoService(
            config=config,
            db_session_factory=db_session_factory,
            embedder=request.app.state.embedder,
            captioner=getattr(request.app.state, "captioner", None),
            detector=getattr(request.app.state, "detector", None),
        )
        await request.app.state.pipeline_queue.enqueue(
            "incremental",
            {"video_id": str(video.id), "added_modalities": list(l3_turned_on)},
        )

        logger.info("[Params] video=%s incremental: %s", video_id, l3_turned_on)
        return APIResponse(data=VideoResponse.model_validate(video))

    else:
        raise HTTPException(status_code=400, detail=f"视频状态为 {status_val}，无法修改参数")


@router.patch("/videos/{video_id}/toggles")
async def patch_video_toggles(
    video_id: uuid.UUID,
    payload: ToggleSettings,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """抽屉「处理参数设置」小面板的轻量持久化端点（v0.37）。

    仅写入传入的非 None 字段，**不入队管道、不动版本、不联动组**，纯粹把 5 个
    核心开关落到 video 行；用户随后点底部「视频解析」按钮才走完整 PUT /params 流程。
    """
    updates: dict = {}
    if payload.detection_enabled is not None:
        updates["detection_enabled"] = payload.detection_enabled
    if payload.face_enabled is not None:
        updates["face_enabled"] = payload.face_enabled
    if payload.plate_enabled is not None:
        updates["plate_enabled"] = payload.plate_enabled
    if payload.ocr_enabled is not None:
        updates["ocr_enabled"] = payload.ocr_enabled
    if payload.search_index_enabled is not None:
        updates["search_index_enabled"] = payload.search_index_enabled
    if payload.summary_enabled is not None:
        updates["summary_enabled"] = payload.summary_enabled

    if not updates:
        raise HTTPException(status_code=400, detail="至少传入一个开关字段")

    cur = (await db.execute(select(Video).where(Video.id == video_id))).scalar_one_or_none()
    if cur is None:
        raise HTTPException(status_code=404, detail="Video not found")

    # 链式校验：detection 关闭 → face/plate 强制关闭（保证 DB 不会出现非法组合）
    effective_detection = updates.get("detection_enabled", cur.detection_enabled)
    if updates.get("face_enabled", cur.face_enabled) and not effective_detection:
        updates["face_enabled"] = False
    if updates.get("plate_enabled", cur.plate_enabled) and not effective_detection:
        updates["plate_enabled"] = False

    # ORM-level 写入：走 session identity map，commit 后强制 expire → refresh 取到最新行
    for key, value in updates.items():
        setattr(cur, key, value)
    await db.commit()
    await db.refresh(cur)
    logger.info("[Toggles] video=%s updated: %s", video_id, updates)
    return APIResponse(data=VideoResponse.model_validate(cur))


@router.get("/videos/{video_id}")
async def get_video(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """查询视频处理状态、进度及摘要制品。"""
    video = await get_video_with_relations(db, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    # v0.34 版本行缺格式 → 从同文件其它版本回退并回写（共享同一物理文件）
    if video.video_codec is None and video.file_id is not None:
        from sqlalchemy import select as sa_select
        sibling = (await db.execute(
            sa_select(Video.container_format, Video.video_codec, Video.audio_codec,
                      Video.has_audio, Video.duration, Video.remuxed_path,
                      Video.proxy_path, Video.proxy_status, Video.proxy_progress,
                      Video.metadata_json)
            .where(Video.file_id == video.file_id, Video.container_format.isnot(None))
            .order_by(Video.version_no.asc()).limit(1)
        )).one_or_none()
        if sibling is not None:
            video.container_format = sibling.container_format
            video.video_codec = sibling.video_codec
            video.audio_codec = sibling.audio_codec
            video.has_audio = sibling.has_audio
            if video.duration is None:
                video.duration = sibling.duration
            video.remuxed_path = sibling.remuxed_path
            video.proxy_path = sibling.proxy_path
            video.proxy_status = sibling.proxy_status
            video.proxy_progress = sibling.proxy_progress
            if video.metadata_json is None:
                video.metadata_json = sibling.metadata_json
            await db.commit()  # 回写，后续请求直接命中
    return APIResponse(data=VideoResponse.model_validate(video))


@router.get("/videos/external/{file_id}")
async def get_video_by_external_file_id_endpoint(
    file_id: int,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """按云智平台文件库资源 ID 查找视频（Bridge context.resource.id → 自动跳转目标）。"""
    video = await get_video_by_external_file_id(db, file_id)
    if video is None:
        raise HTTPException(status_code=404, detail="未找到该平台文件对应的视频")
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
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """删除视频记录 + 关联 DB 数据（级联）+ 磁盘产物，返回释放字节数。

    - DB: 批量 DELETE videos 行，子表由 ON DELETE CASCADE 级联清除，
      同事务内完成空组清理。
    - 磁盘: StorageManager 按 videos 表剩余引用判定清理
      （reuse 共享文件只在最后一个引用删除时才真正 unlink）。
    - 处理中视频：允许删除。删除前登记 core.cancellation，后台管道在
      persist 前检查到即中止（跳过写入，避免 FK 异常）。文件清理失败
      非致命（storage_manager 逐项 try/except，DB 已删即返回成功，
      残留文件由孤儿清扫兜底）。
    """
    result = await db.execute(select(Video).where(Video.id == video_id))
    video = result.scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    # 仅在「管道在跑」时登记取消（DB 删除前），管道检查到即中止；
    # 已完成/待处理视频无后台管道，不登记（避免集合无界增长）
    was_running = video.status == VideoStatus.PROCESSING or video_id in RUNNING_VIDEOS
    if was_running:
        mark_cancelled(video_id)
    storage_manager = getattr(request.app.state, "storage_manager", None)
    try:
        freed_bytes = await delete_video(db, video, storage_manager)
    except Exception:
        if was_running:
            unmark_cancelled(video_id)
        raise
    logger.info("[API] Video deleted: %s (freed %.1f MB)", video_id, freed_bytes / 1e6)
    return APIResponse(data={"freed_bytes": freed_bytes})


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
    - 附带来源分析（规则引擎）
    """
    from api.schemas import VideoMetadataResponse
    from utils.metadata import get_video_metadata as extract_metadata

    result = await db.execute(
        select(Video.file_path, Video.file_name, Video.metadata_json,
               Video.source_analysis, Video.ai_detect_result)
        .where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    file_path = row.file_path
    source_analysis = row.source_analysis
    # Mock: 新视频返回 not_run，旧视频保留已有数据
    ai_detect_result = row.ai_detect_result or {"status": "not_run"}

    # ── Fast path: return cached metadata from DB ──
    from utils.metadata import _METADATA_CACHE_VERSION
    if row.metadata_json and row.metadata_json.get("_cache_version") == _METADATA_CACHE_VERSION:
        cached = dict(row.metadata_json)
        if not verbose:
            cached.pop("raw", None)
        cached["source_analysis"] = source_analysis
        cached["ai_detect"] = ai_detect_result
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
    from utils.video_source import classify_video_source, read_video_header
    # file_name 用原始上传名（row.file_name），而非存储路径 basename（UUID 重命名后
    # 会丢失 ch01_20260721000000.mp4 这类监控命名模式 → 品牌判断失效）。
    # file_header 用魔数嗅探品牌（内容级签名，改名后依然可靠）。
    source_analysis = classify_video_source(
        exif_data=meta.get("device"),
        file_name=row.file_name,
        media_info=_media_info,
        file_header=read_video_header(file_path),
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
    meta["ai_detect"] = ai_detect_result
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



# ═══════════════════════════════════════════════════════════
# v0.34 文件库 / 多版本解析
# ═══════════════════════════════════════════════════════════

@router.put("/files/{file_id}", response_model=APIResponse[dict])
async def rename_file(
    file_id: uuid.UUID,
    payload: RenameFileRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """重命名文件：更新该文件全部版本行的 file_name（含遗留 NULL file_id 独立文件）。

    传入任一版本行 id 或逻辑 file_id 均可（与 delete_file 一致）：
      行 id → 解析 file_id → 更新链上全部版本行；遗留独立文件（file_id NULL）只更新自身。
    新名字未带扩展名时自动补回磁盘真实后缀（下载导出用 file_name 作文件名，缺后缀会打不开）。
    """
    from sqlalchemy import and_, or_
    video = await db.get(Video, file_id)
    if video is None:
        # 兼容直接传逻辑 file_id（链上某行的 file_id 列）
        video = (await db.execute(
            select(Video).where(Video.file_id == file_id).order_by(Video.created_at).limit(1)
        )).scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    fid = video.file_id or video.id
    ext = os.path.splitext(video.file_path or "")[1] or ""
    new_name = payload.name if (not ext or "." in payload.name) else f"{payload.name}{ext}"
    result = await db.execute(
        update(Video).where(or_(
            Video.file_id == fid,
            and_(Video.file_id.is_(None), Video.id == fid),
        )).values(file_name=new_name)
    )
    await db.commit()
    renamed = result.rowcount or 0
    logger.info("[RenameFile] file=%s name=%s rows=%d", file_id, new_name, renamed)
    return APIResponse(data={"ok": True, "renamed": renamed})


@router.get("/files", response_model=APIResponse[list[FileItem]])
async def list_files(db: AsyncSession = Depends(get_db)) -> APIResponse[list[FileItem]]:
    """文件库列表 — 每个文件一行（根行信息 + 当前版本状态/进度/摘要）。"""
    rows = await list_file_roots(db)
    # 批量查询排队中 video_id（pipeline_tasks status='queued'）
    from sqlalchemy import text as sa_text
    qrows = await db.execute(sa_text(
        "SELECT DISTINCT video_id FROM pipeline_tasks WHERE status = 'queued'"
    ))
    queued_ids = {r[0] for r in qrows if r[0] is not None}
    items = [FileItem(
        id=r["id"],                          # 根 videos 行 id（前端打开用，Workbench 再解析当前版本）
        name=r["file_name"],
        file_ext=os.path.splitext(r.get("file_path") or "")[1],
        group_id=r.get("group_id"),
        duration=r.get("duration"),
        file_size=r.get("file_size"),
        created_at=r.get("created_at"),
        current_version_no=r.get("current_version_no"),
        current_status=r.get("current_status"),
        current_progress=float(r.get("current_progress") or 0.0),
        current_summary=r.get("current_summary"),
        versions_count=int(r.get("versions_count") or 1),
        queued=r["id"] in queued_ids,
    ) for r in rows]
    return APIResponse(data=items)


@router.get("/videos/{video_id}/versions", response_model=APIResponse[list[VersionInfo]])
async def list_versions(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[VersionInfo]]:
    """某文件的全部解析版本（版本链）— 输入任一版本行 id 即可。"""
    video = await db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")
    # 单版本（file_id NULL）→ 返回自身；版本化 → 返回整链
    if video.file_id is None:
        versions = [video]
    else:
        versions = await list_file_versions(db, video.file_id)
    items = [VersionInfo.model_validate(v) for v in versions]
    return APIResponse(data=items)


@router.post("/videos/{video_id}/reanalyze", response_model=APIResponse[VideoResponse])
async def reanalyze_video(
    video_id: uuid.UUID,
    payload: PipelineParams,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """重解析 — 为已有视频创建新版本行（复制文件信息 + 版本链）并入队管道。"""
    video = await db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="视频不存在")

    service = VideoService(
        config=load_config(),
        db_session_factory=request.app.state.db_session_factory,
        embedder=getattr(request.app.state, "embedder", None),
        captioner=getattr(request.app.state, "captioner", None),
        detector=getattr(request.app.state, "detector", None),
    )
    new_video = await service.create_reanalyze_version(video_id, payload)
    # 日志生命周期：新版本行（不经过 create_video/PUT params，这里补写）
    await append_task_log(db, new_video.id, "任务已创建（重新解析新版本）")
    await append_task_log(db, new_video.id, "参数已提交，任务入队")

    queue = getattr(request.app.state, "pipeline_queue", None)
    if queue is not None:
        await queue.enqueue("pipeline", {"video_id": str(new_video.id)})
    return APIResponse(data=VideoResponse.model_validate(new_video))


@router.delete("/files/{file_id}", response_model=APIResponse[dict])
async def delete_file(
    file_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """删除文件库中的一个文件（整个版本链）— 删该 file_id 全部 videos 行（级联产物）。

    file_id 传入任一版本行 id 均可：解析其 file_id 后删链上全部版本行。
    磁盘清理走 StorageManager（repository.delete_video 内部按引用判定）。
    """
    video = await db.get(Video, file_id)
    if video is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    # 独立视频（file_id NULL，未重解析过）：直接删自身
    # 版本化文件：删该 file_id 链上全部版本行
    if video.file_id is None:
        versions = [video]
    else:
        versions = await list_file_versions(db, video.file_id)
    freed = 0
    sm = getattr(request.app.state, "storage_manager", None)
    for v in versions:
        freed += await delete_video(db, v, storage_manager=sm)
    return APIResponse(data={"ok": True, "freed_bytes": freed})


@router.post("/videos/suggest-params", response_model=APIResponse[dict])
async def suggest_params(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[dict]:
    """智能参数推荐：基于 embedder zero-shot 视频场景分类（无需联网/新模型）。

    Body: { "video_ids": [uuid, ...] }
    Returns: { suggestions: [{ video_id, scene_key, scene_label, confidence, params|null, all_scores }] }
    """
    from services.smart_suggest import suggest_params_batch
    from core.models import Video as VideoModel

    video_ids = payload.get("video_ids") or []
    if not video_ids:
        return APIResponse(data={"suggestions": []})

    # 批量取视频行（file_path + duration）
    str_ids = [str(vid) for vid in video_ids]
    rows = await db.execute(
        select(VideoModel.id, VideoModel.file_path, VideoModel.duration).where(VideoModel.id.in_(str_ids))
    )
    items = [{"video_id": str(r[0]), "video_path": r[1] or "", "duration": r[2] or 0.0} for r in rows.all()]
    if not items:
        return APIResponse(data={"suggestions": []})

    embedder = getattr(request.app.state, "embedder", None)
    try:
        # 整体超时：5 视频 × 3 帧 × 编码 + 批场景文本 ≈ 90s 富裕
        suggestions = await asyncio.wait_for(
            suggest_params_batch(embedder, items),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        logger.warning("[SuggestParams] timeout, returning empty suggestions")
        suggestions = [
            {"video_id": it["video_id"], "scene_key": None, "scene_label": None,
             "confidence": 0.0, "params": None, "all_scores": {}, "reason": "timeout"}
            for it in items
        ]
    except Exception as e:
        logger.exception("[SuggestParams] batch failed: %s", e)
        suggestions = [
            {"video_id": it["video_id"], "scene_key": None, "scene_label": None,
             "confidence": 0.0, "params": None, "all_scores": {}, "reason": f"error: {e}"}
            for it in items
        ]

    # ── 持久化推荐结果到 video 行（v0.37）：关闭弹窗也不丢，抽屉小面板回填用 ──
    # 同时把推荐参数直接落库到 6 开关列（confidence ≥ 0.30）—— 让抽屉「智能推荐」按钮语义自动生效，
    # 后续「按各视频参数」批量解析 / Workbench 直接使用这些参数而不用再弹确认。
    try:
        LOW_CONF_FOR_APPLY = 0.30
        for s in suggestions:
            vid = s.get("video_id")
            if not vid:
                continue
            params_snapshot = s.get("params") if isinstance(s.get("params"), dict) else None
            confidence = float(s.get("confidence") or 0.0)
            update_values: dict = {
                "suggested_scene_key": s.get("scene_key"),
                "suggested_scene_label": s.get("scene_label"),
                "suggested_confidence": confidence,
                "suggested_params": params_snapshot,
            }
            # 高置信度推荐：直接把 6 开关列落库（用户可在抽屉手动覆盖）
            if params_snapshot and confidence >= LOW_CONF_FOR_APPLY:
                update_values.update({
                    "detection_enabled": bool(params_snapshot.get("detection_enabled", False)),
                    "face_enabled":      bool(params_snapshot.get("face_enabled", False)),
                    "plate_enabled":     bool(params_snapshot.get("plate_enabled", False)),
                    "ocr_enabled":       bool(params_snapshot.get("ocr_enabled", False)),
                    "search_index_enabled": bool(params_snapshot.get("search_index_enabled", True)),
                    # 摘要默认关（v0.37，与 presets 对齐；smart_suggest 也始终不推荐开启）
                    "summary_enabled":   False,
                })
            await db.execute(
                update(VideoModel)
                .where(VideoModel.id == uuid.UUID(vid))
                .values(**update_values)
            )
        await db.commit()
    except Exception as e:
        logger.warning("[SuggestParams] persist suggestions failed: %s", e)
        await db.rollback()

    return APIResponse(data={"suggestions": suggestions})
