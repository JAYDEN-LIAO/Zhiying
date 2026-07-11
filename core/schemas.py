"""
core/schemas.py
═══════════════════════════════════════════════════════════
Pydantic v2 校验模型 — JSONB 结构校验 / 请求 DTO / 响应 DTO

所有 JSONB 字段在入库前经过此层校验，确保结构完整、边界合法。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional

from core.models import VideoStatus, PresetMode, ContentType


# ═══════════════════════════════════════════════════════════
# JSONB 内部结构模型
# ═══════════════════════════════════════════════════════════

class TimeSegment(BaseModel):
    """视频片段时间区间（黑屏段 / 静音段 / 过曝段共用）。"""
    start_sec: float = Field(..., ge=0.0, description="开始时间(秒)")
    end_sec: float   = Field(..., ge=0.0, description="结束时间(秒)")


class QCResult(BaseModel):
    """videos.qc_result — 质量检测结果。"""
    is_valid: bool                                = Field(..., description="视频是否通过质检")
    estimated_duration: float                     = Field(..., ge=0.0, description="估算时长(秒)")
    black_segments: list[TimeSegment]             = Field(default_factory=list, description="黑屏段列表")
    silent_segments: list[TimeSegment]            = Field(default_factory=list, description="静音段列表")
    overexposed_segments: list[TimeSegment]       = Field(default_factory=list, description="过曝段列表")


class SceneSummaryItem(BaseModel):
    """videos.summary.scenes_summary 中的单个场景条目。"""
    scene_index: int   = Field(..., ge=0, description="场景序号")
    start_sec: float   = Field(..., ge=0.0, description="开始时间(秒)")
    end_sec: float     = Field(..., ge=0.0, description="结束时间(秒)")
    description: str   = Field(..., description="场景内容描述")
    keywords: list[str] = Field(default_factory=list, description="场景关键词")


class VideoSummary(BaseModel):
    """videos.summary — 全局结构化摘要。"""
    one_liner: str                        = Field(..., description="一句话总结")
    scenes_summary: list[SceneSummaryItem] = Field(default_factory=list, description="场景摘要列表")
    tags: list[str]                       = Field(default_factory=list, description="标签")
    main_topics: list[str]                = Field(default_factory=list, description="核心主题")
    main_entities: list[str]              = Field(default_factory=list, description="主要实体")


class SceneEntity(BaseModel):
    """scenes.entities 中的单个检测物。"""
    label: str                        = Field(..., description="物体标签")
    bbox: list[float]                 = Field(
        ..., min_length=4, max_length=4,
        description="边界框 [x1, y1, x2, y2]",
    )
    confidence: float                 = Field(..., ge=0.0, le=1.0, description="置信度")
    start_sec: float                  = Field(..., ge=0.0, description="出现时间(秒)")
    end_sec: float                    = Field(..., ge=0.0, description="消失时间(秒)")
    track_id: int | None              = Field(default=None, description="跟踪 ID")


class WordTimestamp(BaseModel):
    """transcripts.words 中的单个字词时间戳。"""
    word: str                         = Field(..., description="字词文本")
    start: float                      = Field(..., ge=0.0, description="开始时间(秒)")
    end: float                        = Field(..., ge=0.0, description="结束时间(秒)")
    confidence: float | None          = Field(default=None, ge=0.0, le=1.0, description="置信度")


# ═══════════════════════════════════════════════════════════
# 请求 DTO
# ═══════════════════════════════════════════════════════════

class VideoCreate(BaseModel):
    """上传视频请求参数。"""
    file_path: str          = Field(..., description="原始视频存储路径(绝对路径)")
    file_name: str          = Field(..., description="上传时原始文件名")
    file_size: int          = Field(..., gt=0, description="字节数")
    preset: PresetMode      = Field(default=PresetMode.STANDARD)
    content_type: ContentType = Field(default=ContentType.GENERAL)
    language: str           = Field(default="auto", pattern=r"^(auto|zh|en|ja)$")

    # ── 感知线路开关 ──
    audio_enabled: bool     = Field(default=True)
    vision_enabled: bool    = Field(default=True)
    ocr_enabled: bool       = Field(default=True)
    grounding_enabled: bool = Field(default=False)
    caption_enabled: bool   = Field(default=True)
    summary_enabled: bool   = Field(default=True)


# ═══════════════════════════════════════════════════════════
# 响应 DTO
# ═══════════════════════════════════════════════════════════

class VideoResponse(BaseModel):
    """视频详情响应 — 完整映射 Video ORM 模型。"""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: VideoStatus
    progress: float            = Field(..., ge=0.0, le=1.0)
    error_message: str | None  = None

    file_path: str
    file_name: str
    file_size: int             = Field(..., gt=0)
    duration: float | None     = None

    preset: PresetMode
    content_type: ContentType
    language: str

    audio_enabled: bool
    vision_enabled: bool
    ocr_enabled: bool
    grounding_enabled: bool
    caption_enabled: bool
    summary_enabled: bool

    qc_result: QCResult | None     = None
    summary: VideoSummary | None   = None

    created_at: datetime
    updated_at: datetime


class VideoListItem(BaseModel):
    """视频列表项 — 轻量摘要。"""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: VideoStatus
    progress: float                = Field(..., ge=0.0, le=1.0)
    file_name: str
    duration: float | None         = None
    preset: PresetMode
    content_type: ContentType
    scene_count: int | None        = None
    summary_one_liner: str | None  = None
    created_at: datetime
    updated_at: datetime


class SceneResponse(BaseModel):
    """场景响应 — 映射 Scene ORM 模型。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_id: uuid.UUID
    scene_index: int               = Field(..., ge=0)
    start_sec: float               = Field(..., ge=0.0)
    end_sec: float                 = Field(..., ge=0.0)
    keyframe_path: str | None      = None
    ocr_text: str | None           = None
    aligned_transcript: str | None = None
    caption: str | None            = None
    prev_caption: str | None       = None
    entities: list[SceneEntity] | None = None
    embedding: list[float] | None  = None
    created_at: datetime


class TranscriptResponse(BaseModel):
    """转录响应 — 映射 Transcript ORM 模型。"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    video_id: uuid.UUID
    full_text: str
    words: list[WordTimestamp] | None = None
    language: str | None              = None
    duration_transcribed: float | None = None
    created_at: datetime
