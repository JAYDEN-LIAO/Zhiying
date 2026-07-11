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
    ForeignKey, Index, Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, TSVECTOR
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


class PresetMode(str, enum.Enum):
    QUICK    = "quick"
    STANDARD = "standard"
    FULL     = "full"
    CUSTOM   = "custom"


class ContentType(str, enum.Enum):
    GENERAL      = "general"
    MEETING      = "meeting"
    SURVEILLANCE = "surveillance"
    PRODUCT      = "product"


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
    preset: Mapped[PresetMode] = mapped_column(
        SAEnum(PresetMode, name="preset_mode_enum"),
        default=PresetMode.STANDARD,
        nullable=False,
    )
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
    summary_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="摘要生成开关",
    )

    # ── QC 结果 (JSONB) ──
    qc_result: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="BaseQC 输出: {is_valid, black_segments, silent_segments, ...}",
    )

    # ── 摘要 (JSONB) ──
    summary: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="BaseSummarizer 输出: {one_liner, scenes_summary, tags, main_topics, ...}",
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

    __table_args__ = (
        {"comment": "视频主表 — 元数据 / 状态 / QC / 摘要"},
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
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(2048),
        nullable=True,
        comment="关键帧图像编码向量(Qwen3-VL-Embedding-2B输出2048维), HNSW 索引用于向量检索",
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

    # ── 全文检索向量 (PostgreSQL tsvector) ──
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        nullable=True,
        comment=(
            "组合 caption + ocr_text + aligned_transcript 的全文检索向量, "
            "通过 PostgreSQL 触发器或应用层 GIN 索引维护"
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
        # pgvector 索引限制 ≤2000 维，Qwen3-VL-Embedding-2B 输出 2048 维
        # Demo 阶段数据量小（<100 场景），全表扫描 <1ms，跳过索引
        # Index("idx_scenes_embedding_ivfflat", ...)
        Index(
            "idx_scenes_search_vector_gin",
            "search_vector",
            postgresql_using="gin",
        ),
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
