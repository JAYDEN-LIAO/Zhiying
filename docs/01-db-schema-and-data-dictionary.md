# Cerno DB Schema 与数据字典

> 版本：v0.1 | 数据库：PostgreSQL 17 + pgvector 0.8 | 驱动：asyncpg (SQLAlchemy async)

---

## 一、总览

| 表名 | 行数/视频 | 用途 |
|---|---|---|
| `videos` | 1 | 视频元数据、状态、QC 结果、摘要 |
| `scenes` | ~30-100 | 场景时间范围、向量、OCR、转录片段、实体、含上下文描述 |
| `transcripts` | 1 | 全视频转录全文（字词级时间戳） |

---

## 二、SQLAlchemy Base 配置

```python
# core/db.py
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData

POSTGRES_URI = "postgresql+asyncpg://cerno:cerno@localhost:5432/cerno"

engine = create_async_engine(POSTGRES_URI, pool_size=20, max_overflow=10, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    metadata = MetaData(schema="public")
```

---

## 三、表结构详细定义

### 3.1 videos

```python
# core/models.py

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from core.db import Base
import enum

class VideoStatus(str, enum.Enum):
    PENDING     = "pending"       # 刚上传，等待入队
    PROCESSING  = "processing"    # pipeline 执行中
    COMPLETED   = "completed"     # 全链路成功
    FAILED      = "failed"        # 处理异常

class PresetMode(str, enum.Enum):
    QUICK   = "quick"
    STANDARD = "standard"
    FULL    = "full"
    CUSTOM  = "custom"

class ContentType(str, enum.Enum):
    GENERAL     = "general"
    MEETING     = "meeting"
    SURVEILLANCE = "surveillance"
    PRODUCT     = "product"

class Video(Base):
    __tablename__ = "videos"

    # ── 主键 ──────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # ── 状态 ──────────────────────────────────────────
    status: Mapped[VideoStatus] = mapped_column(
        SAEnum(VideoStatus, name="video_status_enum"),
        default=VideoStatus.PENDING,
        index=True,
        nullable=False
    )
    progress: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False,
        comment="0.0 ~ 1.0, 供前端展示进度条"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── 文件信息 ──────────────────────────────────────
    file_path: Mapped[str] = mapped_column(
        String(1024), nullable=False, comment="原始视频存储路径(绝对路径)"
    )
    file_name: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="上传时原始文件名"
    )
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="字节数"
    )
    duration: Mapped[float] = mapped_column(
        Float, nullable=True, comment="视频时长(秒), QC 阶段填充"
    )

    # ── 配置 ──────────────────────────────────────────
    preset: Mapped[PresetMode] = mapped_column(
        SAEnum(PresetMode, name="preset_mode_enum"),
        default=PresetMode.STANDARD,
        nullable=False
    )
    content_type: Mapped[ContentType] = mapped_column(
        SAEnum(ContentType, name="content_type_enum"),
        default=ContentType.GENERAL,
        nullable=False
    )
    language: Mapped[str] = mapped_column(
        String(16), default="auto", nullable=False,
        comment="auto / zh / en / ja / ..."
    )

    # ── 感知线路开关 (Phase 2 独立控制) ────────────────
    audio_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="语音转录开关"
    )
    vision_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="物体检测开关"
    )
    ocr_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="OCR 文字提取开关"
    )
    grounding_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False,
        comment="Grounding 第二阶段开关"
    )
    caption_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="场景描述开关"
    )
    summary_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False,
        comment="摘要生成开关"
    )

    # ── QC 结果 (JSONB) ───────────────────────────────
    qc_result: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="BaseQC 输出: {is_valid, black_segments, silent_segments, ...}"
    )

    # ── 摘要 (JSONB) ──────────────────────────────────
    summary: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="BaseSummarizer 输出: {one_liner, scenes_summary, tags, main_topics, ...}"
    )

    # ── 时间戳 ────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # ── 关联 ──────────────────────────────────────────
    scenes: Mapped[list["Scene"]] = relationship(
        "Scene", back_populates="video", cascade="all, delete-orphan"
    )
    transcript: Mapped["Transcript | None"] = relationship(
        "Transcript", back_populates="video", uselist=False, cascade="all, delete-orphan"
    )

    # ── 索引 ──────────────────────────────────────────
    __table_args__ = (
        {"comment": "视频主表 — 元数据 / 状态 / QC / 摘要"}
    )
```

### 3.2 scenes

```python
from pgvector.sqlalchemy import Vector  # pgvector 官方 SQLAlchemy 扩展

class Scene(Base):
    __tablename__ = "scenes"

    # ── 主键 & 外键 ───────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # ── 场景序号与时间 ────────────────────────────────
    scene_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="视频内场景序号, 从 0 开始"
    )
    start_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="开始时间(秒)"
    )
    end_sec: Mapped[float] = mapped_column(
        Float, nullable=False, comment="结束时间(秒)"
    )

    # ── 关键帧 ────────────────────────────────────────
    keyframe_path: Mapped[str | None] = mapped_column(
        String(1024), nullable=True,
        comment="关键帧图片路径(缩略图), 可 NULL (搜索阶段不依赖落盘图片)"
    )

    # ── 向量 (pgvector) ───────────────────────────────
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(768),     # Qwen3-VL-Embedding-2B 输出维度
        nullable=True,
        comment="关键帧图像编码向量, HNSW 索引用于向量检索"
    )

    # ── 文本模态字段 ──────────────────────────────────
    ocr_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="关键帧 OCR 文字(PPT/字幕/车牌等)"
    )
    aligned_transcript: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="切分到本场景的语音转录文本"
    )
    caption: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="含上下文的深度画面描述(VLM 输出)"
    )
    prev_caption: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="上一场景的 caption, 记忆传递用"
    )

    # ── 实体 (JSONB) ──────────────────────────────────
    entities: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True,
        comment=(
            "检测物列表, 结构: [{label, bbox: [x1,y1,x2,y2], confidence, "
            "start_sec, end_sec, track_id?}]"
        )
    )

    # ── 全文检索向量 (PostgreSQL tsvector) ────────────
    search_vector: Mapped[str | None] = mapped_column(
        "tsvector",       # 注意: 需在 migration 中用 raw SQL 创建
        nullable=True,
        comment=(
            "组合 caption + ocr_text + aligned_transcript 的全文检索向量, "
            "通过 PostgreSQL 触发器或应用层 GIN 索引维护"
        )
    )

    # ── 时间戳 ────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # ── 关联 ──────────────────────────────────────────
    video: Mapped["Video"] = relationship("Video", back_populates="scenes")

    # ── 索引 ──────────────────────────────────────────
    __table_args__ = (
        Index("idx_scenes_video_scene", "video_id", "scene_index"),
        Index("idx_scenes_start_sec", "video_id", "start_sec"),
        Index(
            "idx_scenes_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 200},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "idx_scenes_search_vector_gin",
            "search_vector",
            postgresql_using="gin",
        ),
        {"comment": "场景表 — 核心检索粒度, 每行代表一个镜头片段"}
    )
```

### 3.3 transcripts

```python
class Transcript(Base):
    __tablename__ = "transcripts"

    # ── 主键 & 外键 ───────────────────────────────────
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )

    # ── 全文 ──────────────────────────────────────────
    full_text: Mapped[str] = mapped_column(
        Text, nullable=False, comment="全视频转录全文(纯文本)"
    )

    # ── 字词级时间戳 (JSONB) ──────────────────────────
    words: Mapped[list[dict] | None] = mapped_column(
        JSONB, nullable=True,
        comment=(
            "字词级时间戳数组, 结构: [{word, start, end, confidence?}]\n"
            "faster-whisper 原生输出格式"
        )
    )

    # ── 元数据 ────────────────────────────────────────
    language: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="检测到的语言"
    )
    duration_transcribed: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="转录覆盖的音频时长(秒)"
    )

    # ── 时间戳 ────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # ── 关联 ──────────────────────────────────────────
    video: Mapped["Video"] = relationship("Video", back_populates="transcript")

    # ── 索引 ──────────────────────────────────────────
    __table_args__ = (
        Index(
            "idx_transcripts_full_text_gin",
            "full_text",
            postgresql_using="gin",
            postgresql_ops={"full_text": "gin_trgm_ops"},
        ),
        {"comment": "转录表 — 每视频一行, 包含字词级时间戳"}
    )
```

---

## 四、数据库初始化脚本

### 4.1 扩展创建

```sql
-- 在 CREATE TABLE 之前执行
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "vector";       -- pgvector
```

### 4.2 tsvector 自动维护触发器

```sql
-- 触发器函数: scenes 插入/更新时自动更新 search_vector
CREATE OR REPLACE FUNCTION scenes_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('simple', coalesce(NEW.caption, '')), 'A') ||
        setweight(to_tsvector('simple', coalesce(NEW.ocr_text, '')), 'B') ||
        setweight(to_tsvector('simple', coalesce(NEW.aligned_transcript, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_scenes_search_vector
    BEFORE INSERT OR UPDATE ON scenes
    FOR EACH ROW
    EXECUTE FUNCTION scenes_search_vector_update();
```

### 4.3 异步初始化入口

```python
# core/db.py (续)

async def init_db():
    """创建所有表 + 扩展 + 索引 (Alembic migration 的快速替代, 仅开发阶段)"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"pg_trgm\""))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"vector\""))
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION scenes_search_vector_update() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector :=
                    setweight(to_tsvector('simple', coalesce(NEW.caption, '')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(NEW.ocr_text, '')), 'B') ||
                    setweight(to_tsvector('simple', coalesce(NEW.aligned_transcript, '')), 'C');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))
        # 触发器在表存在时才创建, 这里放在 migration 中更合理
    await conn.run_sync(Base.metadata.create_all)
```

---

## 五、数据字典速查

### 5.1 videos 字段速查

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | UUID | Y | 主键, uuid4 |
| `status` | Enum | Y | pending / processing / completed / failed |
| `progress` | Float | Y | 0.0 ~ 1.0 |
| `error_message` | Text | N | 失败时的错误信息 |
| `file_path` | String(1024) | Y | 服务器上原始视频绝对路径 |
| `file_name` | String(512) | Y | 上传原始文件名 |
| `file_size` | Integer | Y | 字节数 |
| `duration` | Float | N | QC 阶段填充 |
| `preset` | Enum | Y | quick / standard / full / custom |
| `content_type` | Enum | Y | general / meeting / surveillance / product |
| `language` | String(16) | Y | auto / zh / en / ja ... |
| `audio_enabled` | Bool | Y | 语音转录开关 |
| `vision_enabled` | Bool | Y | 物体检测开关 |
| `ocr_enabled` | Bool | Y | OCR 开关 |
| `grounding_enabled` | Bool | Y | Grounding 开关 |
| `caption_enabled` | Bool | Y | 场景描述开关 |
| `summary_enabled` | Bool | Y | 摘要开关 |
| `qc_result` | JSONB | N | `{is_valid, black_segments[], silent_segments[]}` |
| `summary` | JSONB | N | `{one_liner, scenes_summary[], tags[], main_topics[]}` |
| `created_at` | DateTime(tz) | Y | 创建时间 |
| `updated_at` | DateTime(tz) | Y | 最后更新时间 |

### 5.2 scenes 字段速查

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | Integer | Y | 自增主键 |
| `video_id` | UUID FK | Y | 关联 videos.id |
| `scene_index` | Integer | Y | 场景序号, 0-based |
| `start_sec` | Float | Y | 开始秒数 |
| `end_sec` | Float | Y | 结束秒数 |
| `keyframe_path` | String(1024) | N | 关键帧缩略图路径 |
| `embedding` | Vector(768) | N | 图像向量, HNSW 索引 |
| `ocr_text` | Text | N | OCR 提取文字 |
| `aligned_transcript` | Text | N | 对齐后的语音转录片段 |
| `caption` | Text | N | VLM 深度描述 |
| `prev_caption` | Text | N | 上一场景 caption(记忆) |
| `entities` | JSONB | N | `[{label, bbox, confidence, start_sec, end_sec}]` |
| `search_vector` | tsvector | N | GIN 全文检索, 自动维护 |
| `created_at` | DateTime(tz) | Y | 创建时间 |

### 5.3 transcripts 字段速查

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | Integer | Y | 自增主键 |
| `video_id` | UUID FK | Y | 关联 videos.id, unique |
| `full_text` | Text | Y | 全转录纯文本 |
| `words` | JSONB | N | `[{word, start, end, confidence}]` |
| `language` | String(16) | N | 检测语言 |
| `duration_transcribed` | Float | N | 转录覆盖时长 |
| `created_at` | DateTime(tz) | Y | 创建时间 |

### 5.4 JSONB 字段详细结构

**videos.qc_result:**
```json
{
  "is_valid": true,
  "estimated_duration": 3600.0,
  "black_segments": [
    {"start_sec": 10.0, "end_sec": 15.0}
  ],
  "silent_segments": [
    {"start_sec": 120.0, "end_sec": 180.0}
  ],
  "overexposed_segments": []
}
```

**videos.summary:**
```json
{
  "one_liner": "这是一场关于Q3财报的会议,讨论了营收增长和成本控制",
  "scenes_summary": [
    {
      "scene_index": 0,
      "start_sec": 0.0,
      "end_sec": 120.0,
      "description": "主持人开场,介绍会议议程",
      "keywords": ["开场", "议程"]
    }
  ],
  "tags": ["财报", "会议", "Q3"],
  "main_topics": ["营收增长15%", "成本控制措施", "Q4展望"],
  "main_entities": ["张三", "李四", "财务部"]
}
```

**scenes.entities:**
```json
[
  {
    "label": "cat",
    "bbox": [400, 200, 600, 350],
    "confidence": 0.92,
    "start_sec": 130.0,
    "end_sec": 138.0,
    "track_id": 1
  },
  {
    "label": "cup",
    "bbox": [500, 300, 550, 360],
    "confidence": 0.85,
    "start_sec": 130.0,
    "end_sec": 138.0,
    "track_id": 2
  }
]
```

**transcripts.words:**
```json
[
  {"word": "大家", "start": 0.0,  "end": 0.5, "confidence": 0.98},
  {"word": "好",   "start": 0.5,  "end": 0.8, "confidence": 0.99},
  {"word": "今天", "start": 1.2,  "end": 1.6, "confidence": 0.97}
]
```

---

## 六、索引策略总结

| 索引名 | 表 | 列 | 类型 | 用途 |
|---|---|---|---|---|
| `videos_pkey` | videos | id | B-tree (PK) | 主键 |
| `videos_status_idx` | videos | status | B-tree | 状态筛选 |
| `scenes_pkey` | scenes | id | B-tree (PK) | 主键 |
| `idx_scenes_video_scene` | scenes | video_id, scene_index | B-tree | 视频内场景排序 |
| `idx_scenes_start_sec` | scenes | video_id, start_sec | B-tree | 时间范围查询 |
| `idx_scenes_embedding_hnsw` | scenes | embedding | HNSW | 向量相似度检索 (cosine) |
| `idx_scenes_search_vector_gin` | scenes | search_vector | GIN | 全文检索 |
| `idx_transcripts_full_text_gin` | transcripts | full_text | GIN (trgm) | 转录文本模糊搜索 |
| `transcripts_video_id_key` | transcripts | video_id | B-tree (UNIQUE) | 每视频一个转录行 |
