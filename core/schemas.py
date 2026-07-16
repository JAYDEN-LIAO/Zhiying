"""
core/schemas.py
═══════════════════════════════════════════════════════════
Pydantic v2 校验模型 — JSONB 结构校验 / 请求 DTO / 响应 DTO

所有 JSONB 字段在入库前经过此层校验，确保结构完整、边界合法。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import Optional

from core.models import VideoStatus, ContentType


# ═══════════════════════════════════════════════════════════
# JSONB 内部结构模型
# ═══════════════════════════════════════════════════════════

class TimeSegment(BaseModel):
    """视频片段时间区间（黑屏段 / 静音段 / 过曝段共用）。"""
    start_sec: float = Field(..., ge=0.0, description="开始时间(秒)")
    end_sec: float   = Field(..., ge=0.0, description="结束时间(秒)")


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
    """上传视频请求参数（不启动 Pipeline，仅创建记录）。"""
    file_path: str          = Field(..., description="原始视频存储路径(绝对路径)")
    file_name: str          = Field(..., description="上传时原始文件名")
    file_size: int          = Field(..., gt=0, description="字节数")
    content_type: ContentType = Field(default=ContentType.GENERAL)
    language: str           = Field(default="auto", pattern=r"^(auto|zh|en|ja|ko)$")

    # ── 感知线路开关 ──
    audio_enabled: bool     = Field(default=False)
    vision_enabled: bool    = Field(default=True)
    ocr_enabled: bool       = Field(default=False)
    grounding_enabled: bool = Field(default=False)
    caption_enabled: bool   = Field(default=True)
    summary_enabled: bool   = Field(default=True)
    summary_mode: str       = Field(default="native_video", pattern=r"^(native_video|vlm_llm)$")

    # ── 参数层新增 (v0.6) ──
    search_index_enabled: bool  = Field(default=True)
    sample_fps: float           = Field(default=1.0, ge=0.5, le=3.0)
    segment_threshold: float    = Field(default=0.5, ge=0.2, le=0.8)
    caption_with_context: bool  = Field(default=True)
    summary_detail: str         = Field(default="standard", pattern=r"^(brief|standard|detailed)$")


class PipelineParams(BaseModel):
    """Pipeline 启动参数 — 四级参数统一校验模型。

    前端 PUT /api/v1/videos/{id}/params 时传入，
    model_validator 执行跨字段依赖校验。
    """
    content_type: ContentType = Field(default=ContentType.GENERAL)

    # L2: 感知模块
    vision_enabled: bool    = Field(default=True)
    audio_enabled: bool     = Field(default=False)
    ocr_enabled: bool       = Field(default=False)
    caption_enabled: bool   = Field(default=True)

    # L3: 功能开关
    search_index_enabled: bool = Field(default=True)
    summary_enabled: bool      = Field(default=True)
    summary_mode: str          = Field(default="native_video", pattern=r"^(native_video|vlm_llm)$")

    # L4: 高级参数
    language: str               = Field(default="auto", pattern=r"^(auto|zh|en|ja|ko)$")
    sample_fps: float           = Field(default=1.0, ge=0.5, le=3.0)
    segment_threshold: float    = Field(default=0.5, ge=0.2, le=0.8)
    caption_with_context: bool  = Field(default=True)
    summary_detail: str         = Field(default="standard", pattern=r"^(brief|standard|detailed)$")

    @model_validator(mode="after")
    def validate_cross_dependencies(self):
        """跨字段依赖校验 — 与前端连锁规则保持一致。"""
        # vision 关闭 → ocr / caption 必须为 false
        if not self.vision_enabled:
            if self.ocr_enabled:
                raise ValueError("视觉分析已关闭，文字识别必须同时关闭")
            if self.caption_enabled:
                raise ValueError("视觉分析已关闭，画面描述必须同时关闭")

        # caption 关闭 → summary 必须为 false
        if not self.caption_enabled and self.summary_enabled:
            raise ValueError("画面描述已关闭，智能摘要必须同时关闭")

        # 至少一个感知源
        if not self.vision_enabled and not self.audio_enabled:
            raise ValueError("视觉分析和音频转录至少开启一个")

        # 至少一个功能
        if not self.search_index_enabled and not self.summary_enabled:
            raise ValueError("搜索索引和智能摘要至少开启一个")

        return self


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

    content_type: ContentType
    language: str

    audio_enabled: bool
    vision_enabled: bool
    ocr_enabled: bool
    grounding_enabled: bool
    caption_enabled: bool
    summary_enabled: bool
    summary_mode: str

    search_index_enabled: bool
    sample_fps: float
    segment_threshold: float
    caption_with_context: bool
    summary_detail: str

    status_detail: str | None      = None

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
    content_type: ContentType
    scene_count: int | None        = None
    summary_one_liner: str | None  = None

    # 参数展示字段（来自 Video ORM）
    audio_enabled: bool            = False
    caption_enabled: bool          = True
    summary_enabled: bool          = True
    summary_mode: str              = "native_video"
    search_index_enabled: bool     = True
    sample_fps: float              = 1.0
    language: str                  = "auto"

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
