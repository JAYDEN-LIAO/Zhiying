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
# 格式信息 (v0.13)
# ═══════════════════════════════════════════════════════════

class FormatInfo(BaseModel):
    """ffprobe 探测结果 — 结构化格式信息。"""
    container_format: str
    video_codec: str
    audio_codec: str | None = None
    has_audio: bool = False
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    bit_rate: int | None = None
    frame_rate: float | None = None


class ProxyStatus(BaseModel):
    """代理转码状态。"""
    status: str = "none"       # none / processing / ready / failed
    progress: float = 0.0      # 0.0 ~ 1.0
    proxy_path: str | None = None


# ═══════════════════════════════════════════════════════════
# 请求 DTO
# ═══════════════════════════════════════════════════════════

class VideoCreate(BaseModel):
    """上传视频请求参数（不启动 Pipeline，仅创建记录）。"""
    file_path: str          = Field(..., description="原始视频存储路径(绝对路径)")
    file_name: str          = Field(..., description="上传时原始文件名")
    file_size: int          = Field(..., gt=0, description="字节数")
    source_owned: bool      = Field(default=True, description="源文件是否归 Zhiying 所有（平台共享文件=False，删除不 unlink 源文件）")
    content_type: ContentType = Field(default=ContentType.GENERAL)
    language: str           = Field(default="auto", pattern=r"^(auto|zh|en|ja|ko)$")

    # ── 感知线路开关 ──
    audio_enabled: bool     = Field(default=False)
    vision_enabled: bool    = Field(default=True)
    ocr_enabled: bool       = Field(default=False)
    grounding_enabled: bool = Field(default=False)
    caption_enabled: bool   = Field(default=True)
    detection_enabled: bool = Field(default=False)
    detection_classes: list[str] | None = Field(default=None)
    face_enabled: bool      = Field(default=False)
    plate_enabled: bool     = Field(default=False)
    summary_enabled: bool   = Field(default=True)
    summary_mode: str       = Field(default="vlm_llm", pattern=r"^(native_video|vlm_llm)$")

    # ── 参数层新增 (v0.6) ──
    search_index_enabled: bool  = Field(default=True)
    sample_fps: float           = Field(default=1.0, ge=0.5, le=3.0)
    segment_threshold: float    = Field(default=0.5, ge=0.2, le=0.8)
    caption_with_context: bool  = Field(default=True)
    summary_detail: str         = Field(default="standard", pattern=r"^(brief|standard|detailed)$")

    # ── 分组 (v0.19) ──
    group_id: uuid.UUID | None  = Field(default=None, description="所属分组 ID，批量上传时设置")

    # ── 云智平台外部文件 ID (v0.25.x) ──
    external_file_id: int | None = Field(default=None, description="云智平台文件库资源 ID（Bridge files.select items[].id）")


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
    detection_enabled: bool = Field(default=False)
    detection_classes: list[str] | None = Field(default=None, description="目标类别列表，如 ['person', 'car']；None=全部")
    face_enabled: bool      = Field(default=False, description="人脸识别开关（依赖 detection_enabled）")
    plate_enabled: bool     = Field(default=False, description="车牌识别开关（依赖 detection_enabled）")

    # L3: 功能开关
    search_index_enabled: bool = Field(default=True)
    summary_enabled: bool      = Field(default=True)
    summary_mode: str          = Field(default="vlm_llm", pattern=r"^(native_video|vlm_llm)$")

    # L4: 高级参数
    language: str               = Field(default="auto", pattern=r"^(auto|zh|en|ja|ko)$")
    sample_fps: float           = Field(default=1.0, ge=0.5, le=3.0)
    segment_threshold: float    = Field(default=0.5, ge=0.2, le=0.8)
    caption_with_context: bool  = Field(default=True)
    summary_detail: str         = Field(default="standard", pattern=r"^(brief|standard|detailed)$")
    encode_profile: str | None  = Field(default=None, pattern=r"^(fast|balanced|precise)$", description="编码速度预设；None=使用全局默认")

    @model_validator(mode="after")
    def validate_cross_dependencies(self):
        """跨字段依赖校验 — 与前端连锁规则保持一致。"""
        # vision 关闭 → ocr / caption / detection 必须为 false
        if not self.vision_enabled:
            if self.ocr_enabled:
                raise ValueError("视觉分析已关闭，文字识别必须同时关闭")
            if self.caption_enabled:
                raise ValueError("视觉分析已关闭，画面描述必须同时关闭")
            if self.detection_enabled:
                raise ValueError("视觉分析已关闭，物体检测必须同时关闭")

        # face / plate → detection 必须开启
        if self.face_enabled and not self.detection_enabled:
            raise ValueError("物体检测已关闭，人脸识别必须同时关闭")
        if self.plate_enabled and not self.detection_enabled:
            raise ValueError("物体检测已关闭，车牌识别必须同时关闭")

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


class ExternalVideoRegister(PipelineParams):
    """注册平台共享路径视频的请求 — 绝对路径就地引用，不上传字节。

    源文件归平台所有（source_owned=False）：删除视频时 Zhiying 不 unlink 源文件。
    file_name 缺省时取 file_path 的 basename。
    """
    file_path: str = Field(..., description="平台共享文件的服务器绝对路径")
    file_name: str | None = Field(default=None, description="原始文件名（缺省取 basename）")
    external_file_id: int | None = Field(default=None, description="云智平台文件库资源 ID（前端据此自动跳转到该视频）")


# ═══════════════════════════════════════════════════════════
# 云智(Yunzhi)平台自动化任务 payload
# ═══════════════════════════════════════════════════════════

class YunzhiJobFile(BaseModel):
    """平台传给扩展应用的共享文件信息。"""
    absolutePath: str = Field(..., description="平台服务器上的绝对路径（与 Zhiying 共享同一挂载视角）")
    name: str = Field(default="", description="文件名")
    # v0.25.x: 平台文件库资源 ID — 无 extra="allow"，必须显式建模，否则被静默丢弃
    id: int | None = Field(default=None, description="平台文件库资源 ID（若平台任务 payload 携带，则存入 videos.external_file_id）")


class YunzhiJobTask(BaseModel):
    """任务中心任务信息。

    平台实测 automationJobId 为数值（如 8），非字符串——2026-08-07 联调发现
    str 定义导致 FastAPI 在进业务代码前返回 422。改 int 后 Pydantic v2 默认
    也能把数字字符串 "8" 强转为 int，两种都兼容。id/type/name 等多余字段由
    默认 extra=ignore 容忍，无需建模。
    """
    automationJobId: int = Field(..., description="自动化任务 ID（平台任务中心数值 ID）")


class YunzhiJobCallback(BaseModel):
    """平台提供的进度/完成/失败回调地址。"""
    progressUrl: str = Field(..., description="进度上报回调")
    completeUrl: str = Field(..., description="任务完成回调")
    failUrl: str = Field(..., description="任务失败回调")


class YunzhiJobPayload(BaseModel):
    """POST /internal/yunzhi/jobs 请求体 — 云智扩展自动化任务契约。

    字段与 extension-automation-demo/server.py 一致；extra="allow" 容忍
    平台后续扩展字段。
    """
    jobToken: str = Field(..., description="任务回调凭证，随回调请求头 X-Yunzhi-Job-Token 返回")
    callback: YunzhiJobCallback
    task: YunzhiJobTask
    file: YunzhiJobFile
    operation: str = Field(default="", description="Manifest 自动化任务 id（作为 Zhiying 参数映射键）")
    eventId: str = Field(default="", description="事件 ID，幂等键")
    workDirectory: str = Field(default="", description="平台分配的任务工作目录（结果文件写入处）")

    model_config = ConfigDict(extra="allow")


# ═══════════════════════════════════════════════════════════
# 响应 DTO
# ═══════════════════════════════════════════════════════════

class VideoGroupResponse(BaseModel):
    """视频分组响应 — 映射 VideoGroup ORM 模型。"""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str | None = None
    video_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


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
    source_owned: bool         = True
    duration: float | None     = None

    content_type: ContentType
    language: str

    audio_enabled: bool
    vision_enabled: bool
    ocr_enabled: bool
    grounding_enabled: bool
    caption_enabled: bool
    detection_enabled: bool
    detection_classes: list[str] | None = None
    face_enabled: bool
    plate_enabled: bool
    summary_enabled: bool
    summary_mode: str

    search_index_enabled: bool
    sample_fps: float
    segment_threshold: float
    caption_with_context: bool
    summary_detail: str

    status_detail: str | None      = None

    # ── 分组 (v0.19) ──
    group_id: uuid.UUID | None     = None

    # ── 云智平台外部文件 ID (v0.25.x) ──
    external_file_id: int | None   = None

    summary: VideoSummary | None   = None

    # ── 格式信息 (v0.13) ──
    container_format: str | None        = None
    video_codec: str | None             = None
    audio_codec: str | None             = None
    has_audio: bool                     = False
    remuxed_path: str | None            = None
    proxy_path: str | None              = None
    proxy_status: str                   = "none"
    proxy_progress: float               = 0.0

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
    detection_enabled: bool        = False
    detection_classes: list[str] | None = None
    face_enabled: bool             = False
    plate_enabled: bool            = False
    summary_enabled: bool          = True
    summary_mode: str              = "vlm_llm"
    search_index_enabled: bool     = True
    sample_fps: float              = 1.0
    language: str                  = "auto"

    # ── 分组 (v0.19) ──
    group_id: uuid.UUID | None     = None

    # ── 格式信息 (v0.13) ──
    container_format: str | None        = None
    video_codec: str | None             = None
    proxy_status: str                   = "none"

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
