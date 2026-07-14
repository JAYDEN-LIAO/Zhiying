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
from sqlalchemy import select

from api.deps import get_db
from core.schemas import (
    VideoCreate, VideoResponse, VideoListItem, SceneResponse,
    PresetMode, ContentType,
)
from core.models import Scene, Video
from core.repository import create_video, get_video_with_relations, list_videos, delete_video
from core.search import full_text_search, hybrid_search
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

class HybridSearchRequest(BaseModel):
    query_text: str = Field(..., description="文本查询")
    query_vector: list[float] = Field(..., description="2048 维查询向量")
    limit: int = Field(default=10, ge=1, le=100)


class SemanticSearchRequest(BaseModel):
    """语义搜索请求 — 用户只需传入文本，向量编码由服务端自动完成。"""
    query: str = Field(..., min_length=1, description="自然语言搜索文本")
    video_ids: list[str] | None = Field(
        default=None,
        description="限定搜索的视频范围，为空则全库搜索",
    )
    search_types: list[str] | None = Field(
        default=None,
        description="检索路: vector / fulltext / label，默认全部启用",
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
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    preset: str = Form("standard"),
    content_type: str = Form("general"),
    language: str = Form("auto"),
    audio_enabled: bool = Form(True),
    vision_enabled: bool = Form(True),
    ocr_enabled: bool = Form(True),
    grounding_enabled: bool = Form(False),
    caption_enabled: bool = Form(True),
    summary_enabled: bool = Form(True),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VideoResponse]:
    """上传视频文件并触发后台处理。

    Content-Type: multipart/form-data
    文件保存到 storage.video_dir 后创建记录并异步启动 Pipeline。
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

    # 创建 Video 记录
    dto = VideoCreate(
        file_path=dest_path,
        file_name=file.filename or f"video_{file_id}{ext}",
        file_size=file_size,
        preset=PresetMode(preset),
        content_type=ContentType(content_type),
        language=language,
        audio_enabled=audio_enabled,
        vision_enabled=vision_enabled,
        ocr_enabled=ocr_enabled,
        grounding_enabled=grounding_enabled,
        caption_enabled=caption_enabled,
        summary_enabled=summary_enabled,
    )

    video = await create_video(db, dto)

    # 后台触发 Pipeline
    db_session_factory = request.app.state.db_session_factory
    service = VideoService(
        config=config,
        db_session_factory=db_session_factory,
        embedder=getattr(request.app.state, "embedder", None),
    )
    background_tasks.add_task(service.process_video, video.id)

    logger.info("[Upload] video=%s file=%s size=%d", video.id, file.filename, file_size)
    return APIResponse(data=VideoResponse.model_validate(video))


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

@router.get("/search/text")
async def search_text(
    q: str,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[SearchResults]:
    """文本模态全文检索（GIN tsvector）。"""
    t0 = time.monotonic()
    results_tuples: list[tuple[Scene, float]] = await full_text_search(db, q, limit=limit)
    elapsed = (time.monotonic() - t0) * 1000

    results = [
        SearchResultItem(
            scene_id=s.id,
            video_id=str(s.video_id),
            scene_index=s.scene_index,
            start_sec=s.start_sec,
            end_sec=s.end_sec,
            caption=s.caption,
            ocr_text=s.ocr_text,
            aligned_transcript=s.aligned_transcript,
            similarity=round(sim, 4),
            thumbnail_url=f"/api/v1/videos/{s.video_id}/thumbnail/{s.scene_index}",
        )
        for s, sim in results_tuples
    ]
    return APIResponse(data=SearchResults(results=results, total=len(results), query_time_ms=elapsed))


@router.post("/search/hybrid")
async def search_hybrid(
    payload: HybridSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[SearchResults]:
    """多模态混合检索：向量相似度 + 全文检索加权融合。"""
    t0 = time.monotonic()
    scored: list[tuple[Scene, float]] = await hybrid_search(
        db,
        query_vector=payload.query_vector,
        query_text=payload.query_text,
        limit=payload.limit,
    )
    elapsed = (time.monotonic() - t0) * 1000

    results = [
        SearchResultItem(
            scene_id=s.id,
            video_id=str(s.video_id),
            scene_index=s.scene_index,
            start_sec=s.start_sec,
            end_sec=s.end_sec,
            caption=s.caption,
            ocr_text=s.ocr_text,
            aligned_transcript=s.aligned_transcript,
            similarity=round(score, 4),
            thumbnail_url=f"/api/v1/videos/{s.video_id}/thumbnail/{s.scene_index}",
        )
        for s, score in scored
    ]
    return APIResponse(data=SearchResults(results=results, total=len(results), query_time_ms=elapsed))


# ═══════════════════════════════════════════════════════════
# 语义搜索（服务端自动完成文本→向量编码）
# ═══════════════════════════════════════════════════════════

@router.post("/search/semantic")
async def search_semantic(
    payload: SemanticSearchRequest,
    request: Request,
) -> APIResponse[SearchResults]:
    """语义搜索：传入自然语言文本，服务端自动编码为向量后检索。

    Embedder 按需加载（首次请求触发），后续请求复用缓存实例。
    默认启用 vector（语义）+ fulltext（关键词）双路召回后 RRF 融合。
    """
    t0 = time.monotonic()

    # ── 延后初始化 SearchEngine（复用 app.state 中的共享 embedder）──
    se: SearchEngine | None = getattr(request.app.state, "_searcher", None)
    if se is None:
        from pipeline.search_engine import SearchEngine
        embedder = getattr(request.app.state, "embedder", None)
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
