"""
core/db.py
═══════════════════════════════════════════════════════════
异步数据库引擎、Session 工厂、声明式基类与初始化入口。
"""

import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData, text

from core.config_loader import load_config
from core.embedding_profile import get_embed_dim

# 数据库连接地址：
#   ① 环境变量 POSTGRES_URI 优先（部署覆盖入口，如服务器 start.sh 指向 5433）
#   ② 否则读 config.yaml 的 database.uri（机器相关主配置，各机端口自定）
#   ③ 兜底与 config_schema.DatabaseConfig 默认一致（本地标准 postgres 5432）
POSTGRES_URI = (
    os.environ.get("POSTGRES_URI")
    or load_config().get("database", {}).get("uri")
    or "postgresql+asyncpg://zhiying:zhiying@localhost:5432/zhiying"
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
    # ⚠️ 必须 import models 注册 ORM 表：否则独立调用 init_db()（安装器 6/6 / 脚本）
    # 时 Base.metadata 为空，create_all 建不出任何表，后续迁移报 relation does not exist
    from core import models  # noqa: F401
    async with engine.begin() as conn:
        # ── 扩展 ──
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "vector"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "fuzzystrmatch"'))

        # ── 创建所有表 ──
        await conn.run_sync(Base.metadata.create_all)

        # ── 增量迁移：为已有表补充新列（create_all 对已有表无效） ──
        await conn.execute(text(f"""
            ALTER TABLE scenes
            ADD COLUMN IF NOT EXISTS text_embedding vector({get_embed_dim()})
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
                DEFAULT 'vlm_llm' NOT NULL
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

        # ── 增量迁移 v0.23: 源文件所有权（平台共享文件就地引用，删除不 unlink 源文件） ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS source_owned boolean
                DEFAULT true NOT NULL
        """))

        # ── 增量迁移 v0.10: tracks.segments (ReID 合并时间片段) ──
        await conn.execute(text("""
            ALTER TABLE tracks
            ADD COLUMN IF NOT EXISTS segments jsonb
        """))

        # ── 增量迁移: display_seq 类内展示序号（每视频每类别 1..N, persist 赋值）──
        await conn.execute(text("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS display_seq int"))
        await conn.execute(text("ALTER TABLE frame_detections ADD COLUMN IF NOT EXISTS display_seq int"))
        await conn.execute(text("ALTER TABLE track_embeddings ADD COLUMN IF NOT EXISTS display_seq int"))

        # ── 增量迁移 v0.10: track 嵌入表 ──
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS track_embeddings (
                id SERIAL PRIMARY KEY,
                video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                track_id INTEGER NOT NULL,
                class_name VARCHAR(64) NOT NULL,
                embedding vector({get_embed_dim()}),
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
        # ── 增量迁移 v0.30: 人脸身份检索锚点升级（最佳单脸 + 来源 track 映射）──
        await conn.execute(text("""
            ALTER TABLE face_identities
            ADD COLUMN IF NOT EXISTS best_face_embedding vector(512)
        """))
        await conn.execute(text("""
            ALTER TABLE face_identities
            ADD COLUMN IF NOT EXISTS best_track_id INTEGER
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_face_identities_best_track
            ON face_identities (best_track_id)
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

        # ── 增量迁移 v0.34: OCR 画面文字识别表 ──
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS ocr_detections (
                id SERIAL PRIMARY KEY,
                video_id UUID NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
                timestamp_sec DOUBLE PRECISION NOT NULL,
                text VARCHAR(1024) NOT NULL,
                bbox JSONB NOT NULL,
                confidence DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_ocr_dets_video_ts
            ON ocr_detections (video_id, timestamp_sec)
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

        # ── 增量迁移 v0.25.x: 云智平台外部文件 ID（前端据此自动跳转到对应视频） ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS external_file_id integer
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_videos_external_file_id
            ON videos (external_file_id)
        """))

        # ── 增量迁移 v0.34: 版本链（文件库/多版本解析） ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS file_id uuid
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS version_no integer
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_videos_file_id
            ON videos (file_id)
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_videos_file_version
            ON videos (file_id, version_no)
            WHERE file_id IS NOT NULL
        """))
        # ── 增量迁移 v0.34: 案例/文件库字段（编号/负责人） ──
        await conn.execute(text("""
            ALTER TABLE video_groups
            ADD COLUMN IF NOT EXISTS number VARCHAR(64)
        """))
        await conn.execute(text("""
            ALTER TABLE video_groups
            ADD COLUMN IF NOT EXISTS owner VARCHAR(64)
        """))
        # ── 增量迁移 v0.34: 案例素材表（图片等非视频） ──
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS case_assets (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                group_id UUID NOT NULL REFERENCES video_groups(id) ON DELETE CASCADE,
                kind VARCHAR(16) NOT NULL DEFAULT 'image',
                name VARCHAR(512) NOT NULL,
                path VARCHAR(1024) NOT NULL,
                file_size INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_case_assets_group
            ON case_assets (group_id)
        """))
        # ── 增量迁移 v0.34: 任务日志表 ──
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_logs (
                id SERIAL PRIMARY KEY,
                task_id UUID NOT NULL,
                seq INTEGER NOT NULL DEFAULT 0,
                level VARCHAR(16) NOT NULL DEFAULT 'info',
                message TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_task_logs_task_seq
            ON task_logs (task_id, seq)
        """))

        # ── 增量迁移 v0.34: 任务中心耗时（管道开始处理时间） ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ
        """))

        # ── 增量迁移 v0.37: 智能参数推荐持久化（抽屉小面板回填用） ──
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS suggested_scene_key VARCHAR(64)
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS suggested_scene_label VARCHAR(64)
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS suggested_confidence DOUBLE PRECISION
        """))
        await conn.execute(text("""
            ALTER TABLE videos
            ADD COLUMN IF NOT EXISTS suggested_params JSONB
        """))

        # ── 增量迁移: scenes (video_id, scene_index) 唯一约束 ──
        # 旧代码 bulk_insert_scenes 重跑管道不删旧行 → 同一视频累积重复场景 → thumbnail 查询报错。
        # 先按 id 保留每组最早一行去重，再建唯一约束防再犯。
        await conn.execute(text("""
            DELETE FROM scenes a
            USING scenes b
            WHERE a.video_id = b.video_id
              AND a.scene_index = b.scene_index
              AND a.id > b.id
        """))
        await conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_scenes_video_scene
            ON scenes (video_id, scene_index)
        """))

        # ── 增量迁移 v0.6: 图片素材库（关注目标 + 底库照片 + 分轨检索向量） ──
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS image_subjects (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                kind VARCHAR(16) NOT NULL DEFAULT 'other',
                name VARCHAR(256) NOT NULL,
                tags JSONB,
                photo_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_image_subjects_kind
            ON image_subjects (kind)
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS subject_photos (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                subject_id UUID NOT NULL REFERENCES image_subjects(id) ON DELETE CASCADE,
                file_path VARCHAR(1024) NOT NULL,
                crop JSONB,
                is_primary BOOLEAN NOT NULL DEFAULT false,
                source VARCHAR(16) NOT NULL DEFAULT 'upload',
                source_video_id UUID,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_subject_photos_subject
            ON subject_photos (subject_id)
        """))
        await conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS subject_photo_embedding (
                id SERIAL PRIMARY KEY,
                photo_id UUID NOT NULL REFERENCES subject_photos(id) ON DELETE CASCADE UNIQUE,
                kind VARCHAR(16) NOT NULL DEFAULT 'other',
                face_embedding vector(512),
                other_embedding vector({get_embed_dim()}),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_subject_photo_emb_kind
            ON subject_photo_embedding (kind)
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
        # 回退两阶段处理流（v0.35 前后端协同）字段：后端已恢复单状态机，前端改为参数面板
        await conn.execute(text("""
            ALTER TABLE videos DROP COLUMN IF EXISTS process_status
        """))
        await conn.execute(text("""
            ALTER TABLE videos DROP COLUMN IF EXISTS parse_mode
        """))
        await conn.execute(text("""
            ALTER TABLE videos DROP COLUMN IF EXISTS analysis_progress
        """))
        await conn.execute(text("""
            ALTER TABLE videos DROP COLUMN IF EXISTS analysis_entities
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
