"""
api/routes.py
═══════════════════════════════════════════════════════════
FastAPI 路由定义 — 视频管理 / 搜索 / 混合检索 / 上传。

响应信封统一为：
  {"code": 0, "message": "ok", "data": { ... }}
"""

import os
import uuid
import time
import logging
import shutil
from typing import Generic, TypeVar

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from api.deps import get_db
from core.schemas import (
    VideoCreate, VideoResponse, VideoListItem, SceneResponse, PipelineParams,
    ContentType,
)
from core.models import Video
from core.repository import create_video, get_video_with_relations, list_videos, delete_video
from core.config_loader import load_config
from services.video_service import VideoService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


# ═══════════════════════════════════════════════════════════
# 通用响应信封
# ═══════════════════════════════════════════════════════════

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """统一响应体。"""
    code: int = Field(default=0)
    message: str = Field(default="ok")
    data: T | None = Field(default=None)


# ═══════════════════════════════════════════════════════════
# 搜索专用 DTO
# ═══════════════════════════════════════════════════════════

class SemanticSearchRequest(BaseModel):
    """语义搜索请求 — 用户只需传入文本，向量编码由服务端自动完成。"""
    query: str = Field(..., min_length=1, description="自然语言搜索文本")
    video_ids: list[str] | None = Field(
        default=None,
        description="限定搜索的视频范围，为空则全库搜索",
    )
    search_types: list[str] | None = Field(
        default=None,
        description="检索路: frame / chunk / text / label，默认全部启用",
    )
    top_k: int = Field(default=20, ge=1, le=100)
    min_similarity: float = Field(default=0.3, ge=0.0, le=1.0)


class SearchResultItem(BaseModel):
    scene_id: int = 0
    video_id: str
    scene_index: int
    scene_range_start: float = 0.0
    scene_range_end: float = 0.0
    precise_start: float | None = None
    precise_end: float | None = None
    precision_level: str = "scene"
    match_paths: list[str] = Field(default_factory=list)
    caption: str | None = None
    ocr_text: str | None = None
    aligned_transcript: str | None = None
    similarity: float | None = None
    thumbnail_url: str | None = None


class SearchResults(BaseModel):
    results: list[SearchResultItem]
    total: int
    query_time_ms: float


# ═══════════════════════════════════════════════════════════
# 上传辅助
# ═══════════════════════════════════════════════════════════

class VideoStatusResponse(BaseModel):
    """轻量状态响应。"""
    video_id: str
    status: str
    progress: float
    current_phase: str | None = None
    phase_description: str | None = None
    error_message: str | None = None
    updated_at: str | None = None


# ═══════════════════════════════════════════════════════════
# 视频管理
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
    summary_enabled: bool = Form(True),
    summary_mode: str = Form("native_video"),
    search_index_enabled: bool = Form(True),
    sample_fps: float = Form(1.0),
    segment_threshold: float = Form(0.5),
    caption_with_context: bool = Form(True),
    summary_detail: str = Form("standard"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """上传视频文件，创建 Video 记录（status=pending），不自动启动 Pipeline。

    用户需在参数面板配置后调用 PUT /videos/{id}/params 启动处理。
    """
    config: dict = request.app.state.config
    video_dir = config.get("storage", {}).get("video_dir", "/home/cerno/data/videos")
    os.makedirs(video_dir, exist_ok=True)

    # 保存文件
    file_id = uuid.uuid4()
    ext = os.path.splitext(file.filename or "video.mp4")[1] or ".mp4"
    dest_path = os.path.join(video_dir, f"{file_id}{ext}")

    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = os.path.getsize(dest_path)

    # 创建 Video 记录（pending，不启动 Pipeline）
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


class ReuseRequest(BaseModel):
    """基于已有视频新建记录。"""
    source_video_id: uuid.UUID
    content_type: ContentType = ContentType.GENERAL
    language: str = "auto"
    audio_enabled: bool = False
    vision_enabled: bool = True
    ocr_enabled: bool = False
    caption_enabled: bool = True
    summary_enabled: bool = True
    summary_mode: str = "native_video"
    search_index_enabled: bool = True
    sample_fps: float = Field(default=1.0, ge=0.5, le=3.0)
    segment_threshold: float = Field(default=0.5, ge=0.2, le=0.8)
    caption_with_context: bool = True
    summary_detail: str = "standard"


@router.post("/videos/reuse", status_code=201)
async def reuse_video(
    payload: ReuseRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """基于已有视频的记录创建新处理任务，复用源视频文件。

    当 PUT /params 对 completed 视频返回"需新建记录"时，
    前端调用此接口，复用源文件的 file_path 创建新记录。
    """
    # 查找源视频
    result = await db.execute(
        select(Video).where(Video.id == payload.source_video_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="源视频不存在")

    # 创建新记录
    dto = VideoCreate(
        file_path=source.file_path,
        file_name=source.file_name,
        file_size=source.file_size,
        content_type=payload.content_type,
        language=payload.language,
        audio_enabled=payload.audio_enabled,
        vision_enabled=payload.vision_enabled,
        ocr_enabled=payload.ocr_enabled,
        grounding_enabled=False,
        caption_enabled=payload.caption_enabled,
        summary_enabled=payload.summary_enabled,
        summary_mode=payload.summary_mode,
        search_index_enabled=payload.search_index_enabled,
        sample_fps=payload.sample_fps,
        segment_threshold=payload.segment_threshold,
        caption_with_context=payload.caption_with_context,
        summary_detail=payload.summary_detail,
    )
    video = await create_video(db, dto)

    # 启动 Pipeline
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
    """设置视频处理参数并启动 Pipeline / 增量补跑。

    状态为 pending → 全量启动
    状态为 completed → 仅 L3 功能开关变更可增量，否则需新建
    """
    result = await db.execute(
        select(Video).where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")

    status_val = video.status.value if hasattr(video.status, "value") else video.status

    if status_val == "pending":
        # ── 全量启动 ──
        await db.execute(
            update(Video)
            .where(Video.id == video_id)
            .values(
                content_type=payload.content_type,
                vision_enabled=payload.vision_enabled,
                audio_enabled=payload.audio_enabled,
                ocr_enabled=payload.ocr_enabled,
                caption_enabled=payload.caption_enabled,
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
            
        )
        background_tasks.add_task(service.process_video, video.id)
        logger.info("[Params] video=%s full pipeline starting", video_id)
        return APIResponse(data=VideoResponse.model_validate(video))

    elif status_val in ("completed", "failed"):
        # ── 增量检测 ──
        old = {
            "content_type": video.content_type.value if hasattr(video.content_type, "value") else video.content_type,
            "vision_enabled": video.vision_enabled,
            "audio_enabled": video.audio_enabled,
            "ocr_enabled": video.ocr_enabled,
            "caption_enabled": video.caption_enabled,
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
            "language": payload.language,
            "sample_fps": payload.sample_fps,
            "segment_threshold": payload.segment_threshold,
            "caption_with_context": payload.caption_with_context,
            "summary_detail": payload.summary_detail,
            "summary_enabled": payload.summary_enabled,
            "summary_mode": payload.summary_mode,
            "search_index_enabled": payload.search_index_enabled,
        }

        # 检查只有 L3 功能开关变化
        # summary_mode 改变需新建记录（native_video ↔ vlm_llm 路径完全不同）
        non_l3_keys = {"content_type", "vision_enabled", "audio_enabled", "ocr_enabled",
                       "caption_enabled", "language", "sample_fps", "segment_threshold",
                       "caption_with_context", "summary_detail", "summary_mode"}
        l3_keys = {"summary_enabled", "search_index_enabled"}

        non_l3_changed = {k for k in non_l3_keys if old.get(k) != new.get(k)}
        l3_changed = {k for k in l3_keys if old.get(k) != new.get(k)}
        l3_turned_on = {k for k in l3_changed if new.get(k) is True and old.get(k) is False}

        if non_l3_changed:
            # L1/L2/L4 变了 → 需新建记录
            raise HTTPException(
                status_code=400,
                detail=f"此修改需新建记录。已修改: {', '.join(non_l3_changed)}。仅功能开关（摘要/索引）可增量。",
            )

        if not l3_changed:
            # 什么都没变
            raise HTTPException(status_code=400, detail="参数未改变")

        # ── 增量更新 L3 开关 ──
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
    """查询视频处理状态、进度及 QC/摘要制品。"""
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
    """流式传输原始视频文件，支持 HTTP Range 请求（视频拖动跳转）。

    使用 FastAPI FileResponse 自动处理:
      - Range header → 206 Partial Content
      - If-Modified-Since / If-None-Match → 304 Not Modified
      - Content-Type / Content-Length 自动检测
    """
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


# ═══════════════════════════════════════════════════════════
# 搜索
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
# 语义搜索（服务端自动完成文本→向量编码，三路并行召回）
# ═══════════════════════════════════════════════════════════

@router.post("/search/semantic")
async def search_semantic(
    payload: SemanticSearchRequest,
    request: Request,
) -> APIResponse[SearchResults]:
    """语义搜索：传入自然语言文本，服务端自动编码为向量后检索。

    Embedder 按需加载（首次请求触发），后续请求复用缓存实例。
    三路并行召回：frame（帧级 1fps）+ chunk（窗口过程语义）+ text（caption+ocr+transcript 语义）。
    """
    t0 = time.monotonic()

    # ── 延后初始化 SearchEngine ──
    se: SearchEngine | None = getattr(request.app.state, "_searcher", None)
    if se is None:
        from pipeline.search_engine import SearchEngine
        # embedder 已在 lifespan 启动时预加载到 app.state.embedder
        embedder = request.app.state.embedder
        se = SearchEngine(request.app.state.db_session_factory, embedder)
        request.app.state._searcher = se

    results = await se.search(
        query=payload.query,
        video_ids=payload.video_ids,
        search_types=payload.search_types,
        top_k=payload.top_k,
        min_similarity=payload.min_similarity,
    )

    elapsed = (time.monotonic() - t0) * 1000

    items = [
        SearchResultItem(
            scene_id=r.get("scene_id", 0),
            video_id=r["video_id"],
            scene_index=r["scene_index"],
            scene_range_start=r.get("scene_range_start", r.get("start_sec", 0)),
            scene_range_end=r.get("scene_range_end", r.get("end_sec", 0)),
            precise_start=r.get("precise_start"),
            precise_end=r.get("precise_end"),
            precision_level=r.get("precision_level", "scene"),
            match_paths=r.get("match_paths", []),
            caption=r.get("caption"),
            ocr_text=r.get("ocr_text"),
            aligned_transcript=r.get("aligned_transcript"),
            similarity=r.get("similarity"),
            thumbnail_url=f"/api/v1/videos/{r['video_id']}/thumbnail/{r['scene_index']}",
        )
        for r in results
    ]

    return APIResponse(data=SearchResults(results=items, total=len(items), query_time_ms=elapsed))


# ═══════════════════════════════════════════════════════════
# 系统设置
# ═══════════════════════════════════════════════════════════

class SettingsKeysRequest(BaseModel):
    api_keys: dict[str, str] = Field(default_factory=dict, description="API key 映射表: {id: value}")


@router.get("/settings")
async def get_settings() -> APIResponse[dict]:
    """获取系统设置（API key 状态等）。"""
    from core.settings_service import get_current_keys
    keys = get_current_keys()
    return APIResponse(data={"api_keys": keys})


@router.put("/settings")
async def update_settings(
    payload: SettingsKeysRequest,
) -> APIResponse[dict]:
    """更新系统设置（API key 等）。"""
    from core.settings_service import update_keys, get_current_keys
    update_keys(payload.api_keys)
    keys = get_current_keys()
    return APIResponse(data={"api_keys": keys})