"""
api/schemas.py
═══════════════════════════════════════════════════════════
API 层共享 Pydantic 模型 — 请求/响应 DTO + 通用信封。

从 api/routes.py 提取，供各子路由文件共用。
"""


import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, field_validator


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

    # Track 搜索专用字段
    track_id: int | None = None
    class_name: str | None = None
    bbox: dict | None = None


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
    detection_enabled: bool = False
    detection_classes: list[str] | None = None
    face_enabled: bool = False
    plate_enabled: bool = False
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


# ═══════════════════════════════════════════════════════════
# 来源分析 & AI 检测 DTO (v0.17)
# ═══════════════════════════════════════════════════════════

class SourceAnalysis(BaseModel):
    """视频来源分析结果 — 规则引擎输出。"""
    source_type: str = Field(..., description="来源类型: phone/camera/screen_recording/surveillance/non_camera_source/unknown")
    source_label: str = Field(..., description="中文标签，如'手机视频'")
    confidence: str = Field(..., description="置信度: high/medium/low")
    evidence: list[str] = Field(default_factory=list, description="判断依据列表")
    surveillance_brand: str | None = Field(default=None, description="命中的监控品牌")
    surveillance_method: str | None = Field(default=None, description="品牌判断方法")


class AIDetectSignal(BaseModel):
    """单个 AI 检测信号 — 来自 AICheck。"""
    source: str = Field(..., description="信号来源: C2PA / MP4 / XMP / EXIF / WATERMARK / FILE / SPEC")
    confidence: str = Field(..., description="high / medium / low")
    description: str = Field(..., description="人类可读描述")
    tool: str | None = Field(default=None, description="命中的 AI 工具名")


class AIDetectResult(BaseModel):
    """AI 生成检测结果 — AICheck CLI 输出。"""
    status: str = Field(default="not_run", description="not_run / analyzing / completed / error")
    score: float | None = Field(default=None, description="综合置信度 0.0-1.0")
    verdict: str | None = Field(default=None, description="ai_generated / likely_ai / no_signal / error")
    signals: list[AIDetectSignal] = Field(default_factory=list, description="命中的信号列表")
    software_info: list[tuple[str, str]] = Field(default_factory=list, description="非 AI 创作软件信息")
    error_message: str | None = Field(default=None)
    deep_analysis_used: bool = Field(default=False, description="是否执行了像素级深度检测")


# ═══════════════════════════════════════════════════════════
# 元数据 DTO — 类型化流信息
# ═══════════════════════════════════════════════════════════

class VideoStreamInfo(BaseModel):
    """视频流技术参数。"""
    codec: str | None = None
    codec_profile: str | None = None
    codec_level: str | None = None
    codec_tier: str | None = None
    resolution: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bitrate: int | None = None
    pixel_format: str | None = None
    color_space: str | None = None
    color_primaries: str | None = None
    transfer_characteristics: str | None = None
    chroma_subsampling: str | None = None
    bit_depth: int | None = None
    display_aspect_ratio: str | None = None
    rotation: float | None = None
    encoder: str | None = None

    # ── 防御性类型转换：ffprobe 某些字段返回整数 ──
    @field_validator(
        "codec_level", "codec_tier", "codec_profile",
        "codec", "pixel_format", "color_space",
        "color_primaries", "transfer_characteristics",
        "chroma_subsampling", "display_aspect_ratio", "encoder",
        mode="before",
    )
    @classmethod
    def _coerce_to_str(cls, v: object) -> str | None:
        """Coerce ffprobe integers (e.g. level=120) to strings."""
        if v is None:
            return None
        return str(v)


class AudioStreamInfo(BaseModel):
    """音频流技术参数。"""
    codec: str | None = None
    channels: int | None = None
    channel_layout: str | None = None
    sample_rate: int | None = None
    bitrate: int | None = None
    language: str | None = None


class SubtitleStreamInfo(BaseModel):
    """字幕流信息。"""
    format: str | None = None
    language: str | None = None
    title: str | None = None
    forced: bool = False


class VideoMetadataResponse(BaseModel):
    """视频文件技术元数据 — 编码/分辨率/GPS/设备/HDR信息等。"""
    container: str | None = None
    format_name: str | None = Field(default=None, description="原始容器格式名（ffprobe format_name）")
    duration: float | None = None
    file_size: int | None = None
    overall_bitrate: int | None = None
    video_streams: list[VideoStreamInfo] = Field(default_factory=list)
    audio_streams: list[AudioStreamInfo] = Field(default_factory=list)
    subtitle_streams: list[SubtitleStreamInfo] = Field(default_factory=list)
    device: dict | None = None
    timestamps: dict | None = None
    raw: dict | None = Field(default=None, description="原始提取数据，仅 ?verbose=true 时返回")
    source_analysis: SourceAnalysis | None = Field(default=None, description="视频来源分析（首次提取后缓存）")
    ai_detect: AIDetectResult | None = Field(default=None, description="AI 生成检测结果（上传时自动全面检测：元数据+SEI+C2PA+像素级深度分析）")


# ═══════════════════════════════════════════════════════════
# 导出 DTO
# ═══════════════════════════════════════════════════════════

class ExportClipRequest(BaseModel):
    """视频片段导出请求。start_sec == end_sec 时视为单帧导出。"""
    start_sec: float = Field(..., ge=0.0, description="起始时间(秒)")
    end_sec: float = Field(..., ge=0.0, description="结束时间(秒)，与 start 相同则导出单帧")
    output_format: str = Field(default="mp4", pattern=r"^(mp4)$", description="输出格式")
    output_format: str = Field(default="mp4", pattern=r"^(mp4)$", description="输出格式")


class ExportFramesRequest(BaseModel):
    """帧序列导出请求。"""
    timestamps: list[float] = Field(
        ..., min_length=1, max_length=100,
        description="导出时间点列表(秒)",
    )
    format: str = Field(default="jpg", pattern=r"^(jpg|png)$", description="图片格式")


class ExportTrackRequest(BaseModel):
    """追踪轨迹导出请求。"""
    draw_bbox: bool = Field(default=True, description="是否在视频上绘制边界框")


class ExportThumbnailsRequest(BaseModel):
    """缩略图导出请求。"""
    scene_indices: list[int] | None = Field(
        default=None, description="场景序号列表；不传则导出全部",
    )
