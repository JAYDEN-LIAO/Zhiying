"""
core/repository.py 全套集成测试
═════════════════════════════════════════════════════════════════
依赖 pgvector 镜像内的真实 PostgreSQL，覆盖 CRUD / 批量写入 / 预加载 / 回滚。
"""
import uuid

import pytest
from sqlalchemy import text

from core.models import Video, VideoStatus
from core.schemas import VideoCreate
from core.repository import (
    create_video,
    update_video_progress,
    bulk_insert_scenes,
    get_video_with_relations,
)


# ═══════════════════════════════════════════════════════════════
# Test 1 — 创建与状态变更
# ═══════════════════════════════════════════════════════════════
class TestVideoCreateAndUpdate:
    """create_video → update_video_progress → 重新读取验证。"""

    async def test_create_and_update_progress(self, db_session):
        # ── 1. 创建视频 ──
        dto = VideoCreate(
            file_path="/tmp/test_repo_create.mp4",
            file_name="test_repo_create.mp4",
            file_size=1024,
        )
        video = await create_video(db_session, dto)

        assert video.id is not None
        assert isinstance(video.id, uuid.UUID)
        assert video.status == VideoStatus.PENDING
        assert video.progress == 0.0
        assert video.file_path == "/tmp/test_repo_create.mp4"
        assert video.file_size == 1024

        # ── 2. 更新状态与进度 ──
        updated = await update_video_progress(
            db_session,
            video_id=video.id,
            status=VideoStatus.PROCESSING,
            progress=0.45,
        )

        assert updated is not None
        assert updated.status == VideoStatus.PROCESSING
        assert updated.progress == 0.45

        # ── 3. 重新从数据库读取验证 ──
        # 注意：SQLAlchemy SAEnum 在 PostgreSQL 原生 ENUM 中存储的是 Python 枚举的 .name（大写）
        result = await db_session.execute(
            text(
                "SELECT status::text, progress FROM videos WHERE id = :vid"
            ),
            {"vid": video.id},
        )
        row = result.fetchone()
        assert row is not None
        assert row._mapping["status"] == VideoStatus.PROCESSING.name
        assert row._mapping["progress"] == 0.45


# ═══════════════════════════════════════════════════════════════
# Test 2 — 批量场景插入（50 条）
# ═══════════════════════════════════════════════════════════════
class TestBulkInsertScenes:
    """bulk_insert_scenes 写入 50 个分镜后的数量与连续性断言。"""

    async def test_bulk_insert_50_scenes(self, db_session):
        # ── 创建视频 ──
        dto = VideoCreate(
            file_path="/tmp/test_bulk_50.mp4",
            file_name="test_bulk_50.mp4",
            file_size=4096,
        )
        video = await create_video(db_session, dto)

        # ── 构造 50 个分镜（仅必需字段） ──
        scenes = [
            {
                "scene_index": i,
                "start_sec": float(i * 10),
                "end_sec": float(i * 10 + 9),
            }
            for i in range(50)
        ]
        await bulk_insert_scenes(db_session, video.id, scenes)

        # ── 断言总数 ──
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM scenes WHERE video_id = :vid"),
            {"vid": video.id},
        )
        assert result.scalar() == 50, "应有 50 条 scene 记录"

        # ── 断言 scene_index 连续 0‑49 ──
        result = await db_session.execute(
            text(
                "SELECT scene_index FROM scenes WHERE video_id = :vid ORDER BY scene_index"
            ),
            {"vid": video.id},
        )
        indices = [row[0] for row in result.fetchall()]
        assert indices == list(range(50)), (
            f"scene_index 应从 0 连续到 49，实际为 {indices}"
        )


# ═══════════════════════════════════════════════════════════════
# Test 3 — 关联对象预加载验证
# ═══════════════════════════════════════════════════════════════
class TestEagerLoadRelations:
    """get_video_with_relations 应通过 selectinload 预加载 .scenes。"""

    async def test_access_scenes_without_missing_greenlet(self, db_session):
        # ── 创建含分镜的视频 ──
        dto = VideoCreate(
            file_path="/tmp/test_eager_load.mp4",
            file_name="test_eager_load.mp4",
            file_size=512,
        )
        video = await create_video(db_session, dto)

        scenes_data = [
            {"scene_index": i, "start_sec": float(i), "end_sec": float(i + 1)}
            for i in range(3)
        ]
        await bulk_insert_scenes(db_session, video.id, scenes_data)

        # ── 重新加载并访问关联 ──
        # 注意：必须使用 fresh session 才能验证 selectinload 生效，
        # 因为之前 session 中的 video 对象可能已被 expire
        loaded = await get_video_with_relations(db_session, video.id)
        assert loaded is not None

        # 访问 .scenes — 若未预加载会触发 MissingGreenlet 异常
        scene_list = loaded.scenes
        assert len(scene_list) == 3
        assert sorted(s.scene_index for s in scene_list) == [0, 1, 2]


# ═══════════════════════════════════════════════════════════════
# Test 4 — 异常事务回滚测试
# ═══════════════════════════════════════════════════════════════
class TestTransactionRollback:
    """违反 NOT NULL 约束时批量插入应整体回滚。"""

    async def test_bulk_insert_rollback_on_missing_required_field(self, db_session):
        # ── 创建视频 ──
        dto = VideoCreate(
            file_path="/tmp/test_rollback.mp4",
            file_name="test_rollback.mp4",
            file_size=256,
        )
        video = await create_video(db_session, dto)
        video_id = video.id  # rollback 前缓存主键，防止回滚后 ORM 对象过期触发 MissingGreenlet

        # ── 构造 10 条合法数据 + 1 条缺少 start_sec 的非法数据 ──
        scenes = [
            {"scene_index": i, "start_sec": float(i), "end_sec": float(i + 1)}
            for i in range(10)
        ]
        # 在第 5 位插入一条缺 start_sec 的记录（→ NOT NULL 冲突）
        scenes.insert(5, {"scene_index": 99, "end_sec": 10.0})

        # ── 断言抛出异常 ──
        with pytest.raises(Exception) as exc_info:
            await bulk_insert_scenes(db_session, video_id, scenes)

        # 确认是约束类异常（IntegrityError）
        exc = exc_info.value
        assert any(
            keyword in type(exc).__name__
            for keyword in ["Integrity", "Programming", "Data"]
        ) or "null value" in str(exc).lower()

        # ── 事务回滚后数据库中不应残留任何 scene 记录 ──
        result = await db_session.execute(
            text("SELECT COUNT(*) FROM scenes WHERE video_id = :vid"),
            {"vid": video_id},
        )
        assert result.scalar() == 0, (
            "整个批量插入应被原子回滚，不应残留脏数据"
        )
