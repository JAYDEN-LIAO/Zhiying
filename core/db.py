"""
core/db.py
═══════════════════════════════════════════════════════════
异步数据库引擎、Session 工厂、声明式基类与初始化入口。
"""

import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData, text

POSTGRES_URI = os.environ.get(
    "POSTGRES_URI",
    "postgresql+asyncpg://cerno:cerno@localhost:5432/cerno",
)

engine = create_async_engine(
    POSTGRES_URI,
    pool_size=20,
    max_overflow=10,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    metadata = MetaData(schema="public")


async def init_db():
    """初始化数据库扩展及所有表。

    - 创建 uuid-ossp / vector 扩展
    - 创建所有 ORM 表（通过 Base.metadata.create_all）
    - 执行增量迁移（ALTER TABLE ADD COLUMN）
    - 清理：删除废弃列、枚举类型、tsvector 触发器
    """
    async with engine.begin() as conn:
        # ── 扩展 ──
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "vector"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "fuzzystrmatch"'))

        # ── 创建所有表 ──
        await conn.run_sync(Base.metadata.create_all)

        # ── 增量迁移：为已有表补充新列（create_all 对已有表无效） ──
        await conn.execute(text("""
            ALTER TABLE scenes
            ADD COLUMN IF NOT EXISTS text_embedding vector(4096)
        """))

        # ── 增量迁移：videos 表新增 status_detail 列 ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS status_detail text
        """))

        # ── 增量迁移 v0.6: 参数层新列 ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS search_index_enabled boolean
                DEFAULT true NOT NULL
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS track_stitch_enabled boolean
                DEFAULT true NOT NULL
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS sample_fps double precision
                DEFAULT 1.0 NOT NULL
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS segment_threshold double precision
                DEFAULT 0.5 NOT NULL
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS caption_with_context boolean
                DEFAULT true NOT NULL
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS summary_detail varchar(16)
                DEFAULT 'standard' NOT NULL
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS summary_mode varchar(16)
                DEFAULT 'native_video' NOT NULL
        """))

        # ── 增量迁移 v0.8: 物体检测开关 ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS detection_enabled boolean
                DEFAULT false NOT NULL
        """))

        # ── 增量迁移 v0.9: 检测类别过滤 ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS detection_classes jsonb
        """))

        # ── 增量迁移 v0.10: tracks.segments (ReID 合并时间片段) ──
        await conn.execute(text("""
            ALTER TABLE tracks
            ADD COLUMN IF NOT EXISTS segments jsonb
        """))

        # ── 增量迁移 v0.10: track 嵌入表 ──
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS track_embeddings (
                id SERIAL PRIMARY KEY,
                video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                track_id INTEGER NOT NULL,
                class_name VARCHAR(64) NOT NULL,
                embedding vector(4096),
                timestamp_sec DOUBLE PRECISION NOT NULL,
                bbox JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_track_emb_video_track
            ON track_embeddings (video_id, track_id)
        """))

        # ── 增量迁移 v0.11: 人脸/车牌开关 ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS face_enabled boolean
                DEFAULT false NOT NULL
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS plate_enabled boolean
                DEFAULT false NOT NULL
        """))

        # ── 增量迁移 v0.11: 人脸身份聚类表 ──
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS face_identities (
                id SERIAL PRIMARY KEY,
                video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                identity_label VARCHAR(64) NOT NULL,
                face_count INTEGER NOT NULL DEFAULT 1,
                first_seen DOUBLE PRECISION NOT NULL,
                last_seen DOUBLE PRECISION NOT NULL,
                avg_quality DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                face_embedding vector(512),
                best_face_timestamp DOUBLE PRECISION,
                best_face_bbox JSONB,
                best_face_path VARCHAR(1024),
                created_at TIMESTAMPTZ DEFAULT now(),
                UNIQUE(video_id, identity_label)
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_face_identities_video
            ON face_identities (video_id)
        """))

        # ── 增量迁移 v0.11: 逐帧人脸检测表 ──
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS face_detections (
                id SERIAL PRIMARY KEY,
                video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                identity_id INTEGER REFERENCES face_identities(id) ON DELETE SET NULL,
                track_id INTEGER NOT NULL,
                timestamp_sec DOUBLE PRECISION NOT NULL,
                bbox JSONB NOT NULL,
                quality_score DOUBLE PRECISION NOT NULL,
                face_embedding vector(512),
                thumbnail_path VARCHAR(1024),
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_face_dets_video_ts
            ON face_detections (video_id, timestamp_sec)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_face_dets_track
            ON face_detections (video_id, track_id)
        """))

        # ── 增量迁移 v0.11: 车牌检测表 ──
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS plate_detections (
                id SERIAL PRIMARY KEY,
                video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                track_id INTEGER NOT NULL,
                class_name VARCHAR(64) NOT NULL,
                timestamp_sec DOUBLE PRECISION NOT NULL,
                plate_text VARCHAR(32) NOT NULL,
                plate_type VARCHAR(16) NOT NULL DEFAULT 'blue',
                char_confidences JSONB,
                bbox JSONB NOT NULL,
                detection_confidence DOUBLE PRECISION NOT NULL,
                thumbnail_path VARCHAR(1024),
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_plate_dets_video_ts
            ON plate_detections (video_id, timestamp_sec)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_plate_dets_text
            ON plate_detections (video_id, plate_text)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_plate_dets_track
            ON plate_detections (video_id, track_id)
        """))

        # ── 增量迁移 v0.22: frame_detections (video_id, track_id) 复合索引 ──
        # 服务 /detection/tracks 的 DISTINCT ON 每 track 最大面积 bbox 惰性计算
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_frame_detections_video_track
            ON frame_detections (video_id, track_id)
        """))

        # ── 增量迁移 v0.13: 视频格式兼容字段 ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS container_format VARCHAR(32)
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS video_codec VARCHAR(32)
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS audio_codec VARCHAR(32)
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS has_audio boolean DEFAULT false NOT NULL
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS remuxed_path VARCHAR(1024)
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS proxy_path VARCHAR(1024)
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS proxy_status VARCHAR(16) DEFAULT 'none' NOT NULL
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS proxy_progress float DEFAULT 0.0 NOT NULL
        """))

        # ── 编码速度预设 ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS encode_profile VARCHAR(16) DEFAULT NULL
        """))

        # ── 增量迁移 v0.17: 元数据缓存列 ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS metadata_json jsonb
        """))

        # ── 增量迁移 v0.17: 来源分析与 AI 检测字段 ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS source_analysis jsonb
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS ai_detect_result jsonb
        """))

        # ── 增量迁移 v0.19: 多视频分组 ──
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS video_groups (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(256) DEFAULT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS group_id UUID
                REFERENCES video_groups(id) ON DELETE SET NULL
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_videos_group_id
            ON videos (group_id)
        """))

        # ── 清理：删除废弃的列、枚举类型、触发器 ──
        await conn.execute(text("""
            ALTER TABLE videos DROP COLUMN IF EXISTS ai_detect_enabled
        """))
        await conn.execute(text("""
            ALTER TABLE videos DROP COLUMN IF EXISTS preset
        """))
        await conn.execute(text("""
            ALTER TABLE videos DROP COLUMN IF EXISTS qc_result
        """))
        await conn.execute(text("""
            DROP TYPE IF EXISTS preset_mode_enum
        """))
        await conn.execute(text("""
            DROP TRIGGER IF EXISTS trg_scenes_search_vector ON scenes
        """))
        await conn.execute(text("""
            DROP FUNCTION IF EXISTS scenes_search_vector_update()
        """))
