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

    # ── 时间戳 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False,
    )

    # ── 关联 ──
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
        Vector(2048),
        nullable=True,
        comment="关键帧图像编码向量(Qwen3-VL-Embedding-2B输出2048维) — DEPRECATED",
    )
    text_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(2048),
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
        Vector(2048), nullable=True,
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
        Vector(2048), nullable=True,
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video", back_populates="tracks_video")

    __table_args__ = (
        UniqueConstraint("video_id", "track_id", name="uq_track_video"),
        Index("ix_tracks_video_class", "video_id", "class_name"),
        {"comment": "追踪轨迹摘要表 — 每 track_id 一行，用于跨帧高亮与搜索"},
    )
