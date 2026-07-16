"""
api/schemas.py
═══════════════════════════════════════════════════════════
API 层共享 Pydantic 模型 — 请求/响应 DTO + 通用信封。

从 api/routes.py 提取，供各子路由文件共用。
"""


import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


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
# 搜索 DTO
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
# 视频管理 DTO
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


class ReuseRequest(BaseModel):
    """基于已有视频新建记录。"""
    source_video_id: uuid.UUID
    content_type: str = "general"
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


# ═══════════════════════════════════════════════════════════
# 设置 DTO
# ═══════════════════════════════════════════════════════════

class SettingsKeysRequest(BaseModel):
    api_keys: dict[str, str] = Field(default_factory=dict, description="API key 映射表: {id: value}")
