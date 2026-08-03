"""
core/models.py
═══════════════════════════════════════════════════════════
SQLAlchemy 2.0 ORM 模型 — Video / Scene / Transcript

严格遵循 Mapped 语法 + PostgreSQL 17 高级特性：
  - pgvector (HNSW 索引)
  - JSONB
  - tsvector 全文检索 (GIN 索引)
  - UUID 主键
"""

import uuid
from datetime import datetime
import enum

from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Text,
    ForeignKey, Index, UniqueConstraint, Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pgvector.sqlalchemy import Vector

from core.db import Base


# ═══════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════

class VideoStatus(str, enum.Enum):
    PENDING     = "pending"
    PROCESSING  = "processing"
    COMPLETED   = "completed"
    FAILED      = "failed"


class ContentType(str, enum.Enum):
    GENERAL          = "general"
    MEETING          = "meeting"
    SURVEILLANCE     = "surveillance"
    TEXT_RECOGNITION = "text_recognition"
    CUSTOM           = "custom"


# ═══════════════════════════════════════════════════════════
# VideoGroup — 多视频分组
# ═══════════════════════════════════════════════════════════

class VideoGroup(Base):
    """视频分组表 — 将多个视频关联到一组（批量上传时自动创建）。"""
    __tablename__ = "video_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="组名（可选）",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False,
    )

    # 关联
    videos: Mapped[list["Video"]] = relationship(
        "Video", back_populates="group", cascade="all, delete-orphan",
    )

    __table_args__ = (
        {"comment": "视频分组表 — 批量上传时自动创建，单视频上传 group_id=NULL"},
    )


# ═══════════════════════════════════════════════════════════
# Video
# ═══════════════════════════════════════════════════════════

class Video(Base):
    __tablename__ = "videos"

    # ── 主键 ──
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── 状态 ──
    status: Mapped[VideoStatus] = mapped_column(
        SAEnum(VideoStatus, name="video_status_enum"),
        default=VideoStatus.PENDING,
        index=True,
        nullable=False,
    )
    progress: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False,
        comment="0.0 ~ 1.0, 供前端展示进度条",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 文件信息 ──
    file_path: Mapped[str] = mapped_column(
        String(1024), nullable=False,
        comment="原始视频存储路径(绝对路径)",
    )
    file_name: Mapped[str] = mapped_column(
        String(512), nullable=False,
        comment="上传时原始文件名",
    )
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="字节数",
    )
    duration: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="视频时长(秒), QC 阶段填充",
    )

    # ── 配置 ──
    content_type: Mapped[ContentType] = mapped_column(
        SAEnum(ContentType, name="content_type_enum"),
        default=ContentType.GENERAL,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(
        String(16), default="auto", nullable=False,
        comment="auto / zh / en / ja / ...",
    )

    # ── 感知线路开关 ──
    audio_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="语音转录开关",
    )
    vision_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="物体检测开关",
    )
    ocr_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="OCR 文字提取开关",
    )
    grounding_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Grounding 第二阶段开关",
    )
    caption_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="场景描述开关",
    )
    detection_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="物体检测与追踪开关（YOLO11 + ByteTrack）",
    )
    detection_classes: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True,
        comment="目标检测类别列表，如 ['person', 'car']；NULL = 所有 80 类",
    )
    face_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="人脸识别开关（SCRFD + ArcFace，依赖 detection_enabled）",
    )
    plate_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="车牌识别开关（PaddleOCR，依赖 detection_enabled）",
    )
    summary_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="摘要生成开关",
    )
    summary_mode: Mapped[str] = mapped_column(
        String(16), default="native_video", nullable=False,
        comment="摘要模式: native_video(本地Qwen2.5-VL) / vlm_llm(VLM+LLM)",
    )

    # ── 参数层新增 (v0.6) ──
    search_index_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="搜索索引建立开关（3-path 编码）",
    )
    track_stitch_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="全局重识别缝合开关（合并被遮挡分开的同一身份 track）",
    )
    sample_fps: Mapped[float] = mapped_column(
        Float, default=1.0, nullable=False,
        comment="分割器采样帧率 0.5~3.0",
    )
    segment_threshold: Mapped[float] = mapped_column(
        Float, default=0.5, nullable=False,
        comment="TransNetV2 镜头切换敏感度 0.2~0.8",
    )
    caption_with_context: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="Caption 是否带前一场景上下文",
    )
    summary_detail: Mapped[str] = mapped_column(
        String(16), default="standard", nullable=False,
        comment="摘要详细度: brief / standard / detailed",
    )
    encode_profile: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default=None,
        comment="编码速度预设: fast / balanced / precise；NULL=全局默认",
    )

    # ── 摘要 (JSONB) ──
    summary: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="BaseSummarizer 输出: {one_liner, scenes_summary, tags, main_topics, ...}",
    )

    # ── 管道实时状态 ──
    status_detail: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="管道实时操作描述, 如'正在对齐第 12/23 个场景'",
    )

    # ── 格式信息 (v0.13) ──
    container_format: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="真实容器格式: mp4/mkv/mpeg_ps/mpeg_ts/mov/avi/flv/wmv/webm/raw",
    )
    video_codec: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="视频编码: h264/hevc/av1/vp9/mpeg4/wmv3/prores/raw",
    )
    audio_codec: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="音频编码: aac/mp3/ac3/opus/vorbis/wma/none",
    )
    has_audio: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="是否含音频流",
    )
    remuxed_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True,
        comment="Remux 后 MP4 文件路径（容器标准化 + 音频 AAC）",
    )
    proxy_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True,
        comment="H.264 代理文件路径（编码兼容）",
    )
    proxy_status: Mapped[str] = mapped_column(
        String(16), default="none", nullable=False,
        comment="代理转码状态: none/processing/ready/failed",
    )
    proxy_progress: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False,
        comment="代理转码进度 0.0 ~ 1.0",
    )

    # ── 元数据缓存 (v0.17) ──
    metadata_json: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="缓存的完整技术元数据（上传后一次性提取，避免每次 GET 重复解析 pymediainfo）",
    )

    # ── 来源分析与 AI 检测 (v0.17) ──
    source_analysis: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="视频来源分析结果：来源类型/置信度/证据链/监控品牌（规则引擎输出，首次 GET /metadata 时写入）",
    )
    ai_detect_result: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="AI 生成检测结果（待接入新检测引擎）",
    )

    # ── 分组（v0.19 多视频处理） ──
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("video_groups.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="所属分组 ID，NULL=单视频未分组",
    )

    # ── 时间戳 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False,
    )

    # ── 关联 ──
    group: Mapped["VideoGroup | None"] = relationship(
        "VideoGroup", back_populates="videos",
    )
    scenes: Mapped[list["Scene"]] = relationship(
        "Scene", back_populates="video", cascade="all, delete-orphan",
    )
    transcript: Mapped["Transcript | None"] = relationship(
        "Transcript", back_populates="video", uselist=False,
        cascade="all, delete-orphan",
    )
    frame_embeddings: Mapped[list["FrameEmbedding"]] = relationship(
        "FrameEmbedding", back_populates="video", cascade="all, delete-orphan",
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="video", cascade="all, delete-orphan",
    )
    frame_detections: Mapped[list["FrameDetection"]] = relationship(
        "FrameDetection", back_populates="video", cascade="all, delete-orphan",
    )
    tracks_video: Mapped[list["Track"]] = relationship(
        "Track", back_populates="video", cascade="all, delete-orphan",
    )
    face_identities: Mapped[list["FaceIdentity"]] = relationship(
        "FaceIdentity", back_populates="video", cascade="all, delete-orphan",
    )
    face_detections: Mapped[list["FaceDetection"]] = relationship(
        "FaceDetection", back_populates="video", cascade="all, delete-orphan",
    )
    plate_detections: Mapped[list["PlateDetection"]] = relationship(
        "PlateDetection", back_populates="video", cascade="all, delete-orphan",
    )

    __table_args__ = (
        {"comment": "视频主表 — 元数据 / 状态 / 摘要"},
    )


# ═══════════════════════════════════════════════════════════
# Scene
# ═══════════════════════════════════════════════════════════

class Scene(Base):
    __tablename__ = "scenes"

    # ── 主键 & 外键 ──
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── 场景序号与时间 ──
    scene_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="视频内场景序号, 从 0 开始",
    )
    start_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="开始时间(秒)",
    )
    end_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="结束时间(秒)",
    )

    # ── 关键帧 ──
    keyframe_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True,
        comment="关键帧图片路径(缩略图)",
    )

    # ── 向量 (pgvector) ──
    # DEPRECATED (v0.8): 不再由 Pipeline 写入，仅兼容旧数据读取。搜索请用 text_embedding。
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(4096),
        nullable=True,
        comment="关键帧图像编码向量(Qwen3-VL-Embedding-2B输出2048维) — DEPRECATED",
    )
    text_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(4096),
        nullable=True,
        comment="caption 文本语义向量, encode_text(caption) 输出, 用于文本语义搜索",
    )

    # ── 文本模态字段 ──
    ocr_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="关键帧 OCR 文字(PPT/字幕/车牌等)",
    )
    aligned_transcript: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="切分到本场景的语音转录文本",
    )
    caption: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="含上下文的深度画面描述(VLM 输出)",
    )
    prev_caption: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="上一场景的 caption, 记忆传递用",
    )

    # ── 实体 (JSONB) ──
    entities: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True,
        comment=(
            "检测物列表, 结构: [{label, bbox: [x1,y1,x2,y2], confidence, "
            "start_sec, end_sec, track_id?}]"
        ),
    )

    # ── 时间戳 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    # ── 关联 ──
    video: Mapped["Video"] = relationship("Video", back_populates="scenes")

    # ── 索引 ──
    __table_args__ = (
        Index("idx_scenes_video_scene", "video_id", "scene_index"),
        Index("idx_scenes_start_sec", "video_id", "start_sec"),
        {"comment": "场景表 — 核心检索粒度, 每行代表一个镜头片段"},
    )


# ═══════════════════════════════════════════════════════════
# Transcript
# ═══════════════════════════════════════════════════════════

class Transcript(Base):
    __tablename__ = "transcripts"

    # ── 主键 & 外键 ──
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # ── 全文 ──
    full_text: Mapped[str] = mapped_column(
        Text, nullable=False, comment="全视频转录全文(纯文本)",
    )

    # ── 字词级时间戳 (JSONB) ──
    words: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True,
        comment=(
            "字词级时间戳数组, 结构: [{word, start, end, confidence?}]\n"
            "faster-whisper 原生输出格式"
        ),
    )

    # ── 元数据 ──
    language: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="检测到的语言",
    )
    duration_transcribed: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="转录覆盖的音频时长(秒)",
    )

    # ── 时间戳 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    # ── 关联 ──
    video: Mapped["Video"] = relationship("Video", back_populates="transcript")

    # ── 索引 ──
    __table_args__ = (
        Index(
            "idx_transcripts_full_text_gin",
            "full_text",
            postgresql_using="gin",
            postgresql_ops={"full_text": "gin_trgm_ops"},
        ),
        {"comment": "转录表 — 每视频一行, 包含字词级时间戳"},
    )


# ═══════════════════════════════════════════════════════════
# FrameEmbedding — 逐帧向量，1fps 采样
# ═══════════════════════════════════════════════════════════

class FrameEmbedding(Base):
    """逐帧向量表 — 1fps 采样，用于帧级精确搜索定位。"""

    __tablename__ = "frame_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="所属场景序号",
    )
    timestamp_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="精确时间戳(秒)",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(4096), nullable=True,
        comment="encode_image(单帧) 编码, 2048 维",
    )
    thumbnail_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="帧缩略图路径, 仅 keyframe 有值",
    )
    is_keyframe: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="是否被 VLM caption 选为代表帧",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video", back_populates="frame_embeddings")

    __table_args__ = (
        Index("idx_frame_emb_video_scene", "video_id", "scene_index"),
        Index("idx_frame_emb_video_time", "video_id", "timestamp_sec"),
        {"comment": "逐帧向量表 — 1fps 采样，用于帧级精确搜索定位"},
    )


# ═══════════════════════════════════════════════════════════
# Chunk — 场景内滑动窗口，多帧原生编码
# ═══════════════════════════════════════════════════════════

class Chunk(Base):
    """视频窗口向量表 — 场景内滑动窗口，多帧原生编码。"""

    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="所属场景序号",
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="场景内窗口序号",
    )
    start_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="窗口开始时间(秒)",
    )
    end_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="窗口结束时间(秒)",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(4096), nullable=True,
        comment="encode_video(窗口内全部帧) 原生编码, 2048 维",
    )
    thumbnail_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="窗口中间帧缩略图路径",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video", back_populates="chunks")

    __table_args__ = (
        Index("idx_chunks_video_scene", "video_id", "scene_index"),
        Index("idx_chunks_time_range", "video_id", "start_sec", "end_sec"),
        {"comment": "视频窗口向量表 — 场景内滑动窗口，用于过程语义搜索"},
    )


# ═══════════════════════════════════════════════════════════
# FrameDetection — 逐帧物体检测结果，1fps 采样
# ═══════════════════════════════════════════════════════════

class FrameDetection(Base):
    """逐帧检测结果表 — 每帧每物体一行。

    按 (video_id, timestamp_sec) 复合索引，前端 canvas overlay
    通过时间戳 O(1) 查找当前帧的检测框。
    """

    __tablename__ = "frame_detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    track_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True,
        comment="ByteTrack 分配的跨帧追踪 ID",
    )
    timestamp_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="视频时间戳(秒)，1fps 粒度",
    )
    class_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="COCO 类别名，如 person/car/dog",
    )
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, comment="YOLO 置信度 (0~1)",
    )
    bbox: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        comment="归一化边界框 {x1, y1, x2, y2}，坐标 0-1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video", back_populates="frame_detections")

    __table_args__ = (
        Index("ix_frame_detections_video_ts", "video_id", "timestamp_sec"),
        # v0.22: 每 track 最大面积 bbox 查询（/detection/tracks 惰性 best）
        Index("ix_frame_detections_video_track", "video_id", "track_id"),
        {"comment": "逐帧检测结果表 — 1fps 采样，前端逐帧查询 bbox"},
    )


# ═══════════════════════════════════════════════════════════
# Track — 跨帧追踪轨迹摘要
# ═══════════════════════════════════════════════════════════

class Track(Base):
    """追踪轨迹摘要表 — 每个 ByteTrack track_id 一行。

    前端点击选中 + 高亮同一 track 的跨帧 bbox 时使用。
    """

    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    track_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="ByteTrack 内部追踪 ID",
    )
    class_name: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="多数类别（track 跨帧投票得出）",
    )
    first_seen: Mapped[float] = mapped_column(
        Float, nullable=False, comment="首次出现时间戳(秒)",
    )
    last_seen: Mapped[float] = mapped_column(
        Float, nullable=False, comment="最后出现时间戳(秒)",
    )
    frame_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="出现帧数",
    )
    segments: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True,
        comment="时间片段列表 [{start, end}]；被 ReID 合并的 track 有多个片段",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video", back_populates="tracks_video")

    __table_args__ = (
        UniqueConstraint("video_id", "track_id", name="uq_track_video"),
        Index("ix_tracks_video_class", "video_id", "class_name"),
        {"comment": "追踪轨迹摘要表 — 每 track_id 一行，用于跨帧高亮与搜索"},
    )


# ═══════════════════════════════════════════════════════════
# TrackEmbedding — YOLO track crop 跨模态嵌入
# ═══════════════════════════════════════════════════════════

class TrackEmbedding(Base):
    """Track 语义嵌入表 — YOLO crop 跨模态编码，用于 track 路搜索 + 全局 ReID。

    每条 track 存储其最佳帧 crop 的 Qwen3-VL-Embedding 向量，
    encode_text(查询) vs embedding 直接命中具体物体。
    """

    __tablename__ = "track_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    track_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="合并后的最终 track ID",
    )
    class_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="COCO 类别名",
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(4096), nullable=True,
        comment="crop 跨模态嵌入, encode_image(best_frame_crop) 输出",
    )
    timestamp_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="最佳帧时间戳(秒)",
    )
    bbox: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="最佳帧归一化 bbox {x1,y1,x2,y2}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video")

    __table_args__ = (
        Index("ix_track_emb_video_track", "video_id", "track_id"),
        {"comment": "Track 语义嵌入表 — crop 跨模态编码，track 路搜索 + 全局 ReID"},
    )


# ═══════════════════════════════════════════════════════════
# FaceIdentity — 人脸身份聚类结果
# ═══════════════════════════════════════════════════════════

class FaceIdentity(Base):
    """人脸身份聚类表 — 每条记录代表一个自动识别的人脸身份。

    通过 ArcFace 余弦聚类自动分组，标注为"人物 A"、"人物 B"等。
    """

    __tablename__ = "face_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    identity_label: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="自动标签，如 '人物 A', '人物 B'",
    )
    face_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="该身份的检出次数",
    )
    first_seen: Mapped[float] = mapped_column(
        Float, nullable=False, comment="首次出现时间戳(秒)",
    )
    last_seen: Mapped[float] = mapped_column(
        Float, nullable=False, comment="最后出现时间戳(秒)",
    )
    avg_quality: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
        comment="平均人脸质量分数 (0~1)",
    )
    face_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(512), nullable=True,
        comment="代表性嵌入向量 — 最优帧的 ArcFace R50 512 维向量",
    )
    best_face_timestamp: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="最优人脸帧的时间戳",
    )
    best_face_bbox: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="最优人脸帧的归一化 bbox {x1,y1,x2,y2}",
    )
    best_face_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="最佳人脸缩略图路径",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video", back_populates="face_identities")

    __table_args__ = (
        Index("ix_face_identities_video", "video_id"),
        UniqueConstraint("video_id", "identity_label", name="uq_face_identity_label"),
        {"comment": "人脸身份聚类表 — 自动标注，ArcFace 512 维向量"},
    )


# ═══════════════════════════════════════════════════════════
# FaceDetection — 逐次人脸出现记录
# ═══════════════════════════════════════════════════════════

class FaceDetection(Base):
    """逐帧人脸检测结果表 — 每检测到的人脸一行。

    关联到 YOLO person track 和 FaceIdentity。
    """

    __tablename__ = "face_detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    identity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("face_identities.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="聚类后的人脸身份 ID",
    )
    track_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True,
        comment="对应的 YOLO person track ID",
    )
    timestamp_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="视频时间戳(秒)",
    )
    bbox: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        comment="人脸边界框 {x1,y1,x2,y2}，归一化 0-1",
    )
    quality_score: Mapped[float] = mapped_column(
        Float, nullable=False, comment="SCRFD 检测质量分数 (0~1)",
    )
    face_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(512), nullable=True,
        comment="ArcFace R50 512 维嵌入向量",
    )
    thumbnail_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="人脸缩略图路径",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video", back_populates="face_detections")

    __table_args__ = (
        Index("ix_face_dets_video_ts", "video_id", "timestamp_sec"),
        Index("ix_face_dets_track", "video_id", "track_id"),
        {"comment": "逐帧人脸检测结果表 — 关联 YOLO person track + 人脸身份"},
    )


# ═══════════════════════════════════════════════════════════
# PlateDetection — 车牌识别结果
# ═══════════════════════════════════════════════════════════

class PlateDetection(Base):
    """车牌检测结果表 — 每块检测到的车牌一行。"""

    __tablename__ = "plate_detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    track_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True,
        comment="对应的 YOLO vehicle track ID",
    )
    class_name: Mapped[str] = mapped_column(
        String(64), nullable=False,
        comment="车辆 COCO 类别名 (car/truck/bus/motorcycle)",
    )
    timestamp_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="视频时间戳(秒)",
    )
    plate_text: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="识别出的车牌号文本",
    )
    plate_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="blue",
        comment="牌照类型: blue/yellow/green/white/black/unknown",
    )
    char_confidences: Mapped[list[float] | None] = mapped_column(
        JSONB, nullable=True,
        comment="逐字符识别置信度数组",
    )
    bbox: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        comment="车牌边界框 {x1,y1,x2,y2}，归一化 0-1",
    )
    detection_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, comment="整体检测置信度 (0~1)",
    )
    thumbnail_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="车牌缩略图路径",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video", back_populates="plate_detections")

    __table_args__ = (
        Index("ix_plate_dets_video_ts", "video_id", "timestamp_sec"),
        Index("ix_plate_dets_text", "video_id", "plate_text"),
        Index("ix_plate_dets_track", "video_id", "track_id"),
        {"comment": "车牌检测结果表 — PaddleOCR 检测 + 识别，支持文本搜索"},
    )
