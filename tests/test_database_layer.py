"""
core/db.py & core/models.py 全套自动化集成测试
═════════════════════════════════════════════════════════════════
依赖真实的 PostgreSQL 17（pgvector 镜像），通过 db_session fixture
自动初始化扩展、表、触发器函数与行级触发器。
"""
import uuid
from datetime import datetime, timedelta
import asyncio

import pytest
from sqlalchemy import text, select

from core.models import Video, Scene, Transcript, VideoStatus, PresetMode, ContentType
from core.db import engine


# ═══════════════════════════════════════════════════════════════
# Test 1 — 基础生命周期：默认值 & updated_at 自动刷新
# ═══════════════════════════════════════════════════════════════
class TestVideoDefaultsAndTimestamps:
    """验证 Video 模型 Python 侧默认值 + updated_at 随更新变化。"""

    async def test_default_values(self, db_session):
        video = Video(
            file_path="/tmp/test_defaults.mp4",
            file_name="test_defaults.mp4",
            file_size=2048,
        )
        db_session.add(video)
        await db_session.flush()  # flush 后 SQLAlchemy 会应用 Column-level defaults

        # ── 枚举默认值 ──
        assert video.status == VideoStatus.PENDING
        assert video.preset == PresetMode.STANDARD
        assert video.content_type == ContentType.GENERAL
        assert video.language == "auto"
        assert video.progress == 0.0

        # ── 6 个感知开关默认值 ──
        assert video.audio_enabled is True
        assert video.vision_enabled is True
        assert video.ocr_enabled is True
        assert video.grounding_enabled is False
        assert video.caption_enabled is True
        assert video.summary_enabled is True

        # ── UUID 主键自动生成 ──
        assert isinstance(video.id, uuid.UUID)

        await db_session.commit()

    async def test_updated_at_changes_on_update(self, db_session):
        """更新字段后 updated_at 应当前进（>= 原始值 + 小 delta）。"""
        video = Video(
            file_path="/tmp/test_timestamp.mp4",
            file_name="test_timestamp.mp4",
            file_size=1024,
        )
        db_session.add(video)
        await db_session.commit()

        original_updated = video.updated_at
        original_created = video.created_at
        assert original_updated is not None
        assert original_created is not None

        # 短暂等待以确保时间可以区分
        await asyncio.sleep(0.02)

        # 更新一个字段
        video.status = VideoStatus.PROCESSING
        await db_session.commit()

        # 验证 updated_at 变更
        assert video.updated_at > original_updated, (
            f"updated_at 应前进: {original_updated} -> {video.updated_at}"
        )
        # created_at 应当保持不变
        assert video.created_at == original_created


# ═══════════════════════════════════════════════════════════════
# Test 2 — 级联删除 CASCADE
# ═══════════════════════════════════════════════════════════════
class TestCascadeDelete:
    """删除 Video 后关联的 Scene / Transcript 应被 DB 级联清除。"""

    async def _count_rows(self, session, table: str, video_id: uuid.UUID) -> int:
        result = await session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE video_id = :vid"),
            {"vid": video_id},
        )
        return result.scalar()

    async def test_cascade_on_video_delete(self, db_session):
        # ── 插入 Video ──
        video = Video(
            file_path="/tmp/test_cascade.mp4",
            file_name="test_cascade.mp4",
            file_size=4096,
        )
        db_session.add(video)
        await db_session.flush()  # 获得 video.id

        video_id = video.id

        # ── 插入 3 条 Scene ──
        for i in range(3):
            db_session.add(Scene(
                video_id=video_id,
                scene_index=i,
                start_sec=float(i * 10),
                end_sec=float(i * 10 + 9),
            ))

        # ── 插入 1 条 Transcript ──
        db_session.add(Transcript(
            video_id=video_id,
            full_text="Full transcript for cascade test.",
        ))

        await db_session.commit()

        # 确认关联数据已写入
        assert await self._count_rows(db_session, "scenes", video_id) == 3
        assert await self._count_rows(db_session, "transcripts", video_id) == 1

        # ── 删除 Video ──
        await db_session.delete(video)
        await db_session.commit()

        # ── 断言级联清除（通过 raw SQL 验证数据库底层 cascade） ──
        assert await self._count_rows(db_session, "scenes", video_id) == 0
        assert await self._count_rows(db_session, "transcripts", video_id) == 0


# ═══════════════════════════════════════════════════════════════
# Test 3 — 全文检索触发器
# ═══════════════════════════════════════════════════════════════
class TestSearchVectorTrigger:
    """验证 scenes 表上的 trg_scenes_search_vector 触发器正确组装 tsvector。"""

    async def test_search_vector_is_populated(self, db_session):
        # 前置 Video
        video = Video(
            file_path="/tmp/test_trigger.mp4",
            file_name="test_trigger.mp4",
            file_size=512,
        )
        db_session.add(video)
        await db_session.flush()

        scene = Scene(
            video_id=video.id,
            scene_index=0,
            start_sec=0.0,
            end_sec=10.0,
            caption="A beautiful deep vision descriptor",
            ocr_text="PPT Text Content",
            aligned_transcript="Whisper audio text sequence",
        )
        db_session.add(scene)
        await db_session.commit()

        # ── 验证 search_vector 不为 NULL ──
        result = await db_session.execute(
            text("SELECT search_vector::text FROM scenes WHERE id = :sid"),
            {"sid": scene.id},
        )
        row = result.fetchone()
        assert row is not None, "应能查到刚插入的 scene"
        tsvector_text = row[0]
        assert tsvector_text is not None, "search_vector 不应为 NULL"
        assert len(tsvector_text) > 0, "search_vector 不应为空字符串"

        # ── 全文检索验证：caption 权重 A 应能被检索到 ──
        result = await db_session.execute(
            text(
                "SELECT id FROM scenes "
                "WHERE search_vector @@ to_tsquery('simple', 'beautiful')"
            ),
        )
        assert result.fetchone() is not None, (
            "应能通过 'beautiful' 检索到 scene (caption 权重 A)"
        )

        # ── 全文检索验证：ocr_text 权重 B ──
        result = await db_session.execute(
            text(
                "SELECT id FROM scenes "
                "WHERE search_vector @@ to_tsquery('simple', 'PPT')"
            ),
        )
        assert result.fetchone() is not None, (
            "应能通过 'PPT' 检索到 scene (ocr_text 权重 B)"
        )

        # ── 全文检索验证：aligned_transcript 权重 C ──
        result = await db_session.execute(
            text(
                "SELECT id FROM scenes "
                "WHERE search_vector @@ to_tsquery('simple', 'Whisper')"
            ),
        )
        assert result.fetchone() is not None, (
            "应能通过 'Whisper' 检索到 scene (aligned_transcript 权重 C)"
        )


# ═══════════════════════════════════════════════════════════════
# Test 4 — pgvector 向量字段
# ═══════════════════════════════════════════════════════════════
class TestVectorEmbedding:
    """验证 Vector(768) 列可正常保存浮点列表。"""

    async def test_save_768_dim_vector(self, db_session):
        video = Video(
            file_path="/tmp/test_vector.mp4",
            file_name="test_vector.mp4",
            file_size=256,
        )
        db_session.add(video)
        await db_session.flush()

        embedding = [float(i % 100) / 100.0 for i in range(768)]

        scene = Scene(
            video_id=video.id,
            scene_index=0,
            start_sec=0.0,
            end_sec=5.0,
            embedding=embedding,
        )
        db_session.add(scene)
        await db_session.commit()

        # ── 重新查询验证 ══
        result = await db_session.execute(
            text("SELECT embedding::text FROM scenes WHERE id = :sid"),
            {"sid": scene.id},
        )
        row = result.fetchone()
        assert row is not None and row[0] is not None, (
            "embedding 应被持久化且不为 NULL"
        )

        # ── 向量维度正确 ──
        result = await db_session.execute(
            text("SELECT vector_dims(embedding) FROM scenes WHERE id = :sid"),
            {"sid": scene.id},
        )
        dims = result.scalar()
        assert dims == 768, f"向量维度应为 768，实际为 {dims}"

        # ── 余弦距离可计算 ──
        # pgvector 适配器要求以字符串形式传入向量参数
        vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
        result = await db_session.execute(
            text(
                "SELECT embedding <=> CAST(:vec AS vector) AS dist FROM scenes WHERE id = :sid"
            ),
            {"vec": vec_str, "sid": scene.id},
        )
        dist = result.scalar()
        assert dist == 0.0, f"自身余弦距离应为 0，实际为 {dist}"
