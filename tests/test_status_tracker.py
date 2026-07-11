"""
core/status_tracker.py 集成测试
═════════════════════════════════════════════════════════════════
依赖真实数据库（复用 conftest.py 的 db_session fixture），
验证进度更新、完成与失败标记的正确持久化。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from core.models import VideoStatus
from core.schemas import VideoCreate
from core.repository import create_video
from core.status_tracker import StatusTracker
from core.exceptions import CernoException


class TestStatusTracker:
    """StatusTracker 进度更新与状态变更。"""

    async def test_update_progress(self, db_session):
        # ── 创建视频 ──
        video = await create_video(
            db_session,
            VideoCreate(
                file_path="/tmp/test_tracker.mp4",
                file_name="test_tracker.mp4",
                file_size=1024,
            ),
        )
        video_id = video.id

        # ── 从 db_session 的 bind 创建 session_factory ──
        factory = async_sessionmaker(
            db_session.bind,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        tracker = StatusTracker(str(video_id), factory)

        # ── 调用 update("phase_4_caption") → 预期 progress = 0.50 ──
        await tracker.update("phase_4_caption")
        row = (
            await db_session.execute(
                text("SELECT progress FROM videos WHERE id = :vid"),
                {"vid": video_id},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == 0.50, (
            f"phase_4_caption 应设置 progress=0.50，实际 {row[0]}"
        )

    async def test_mark_completed(self, db_session):
        video = await create_video(
            db_session,
            VideoCreate(
                file_path="/tmp/test_complete.mp4",
                file_name="test_complete.mp4",
                file_size=512,
            ),
        )
        factory = async_sessionmaker(
            db_session.bind, class_=AsyncSession, expire_on_commit=False,
        )
        tracker = StatusTracker(str(video.id), factory)

        await tracker.mark_completed()

        row = (
            await db_session.execute(
                text("SELECT status::text, progress FROM videos WHERE id = :vid"),
                {"vid": video.id},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "COMPLETED", f"状态应为 COMPLETED，实际 {row[0]}"
        assert row[1] == 1.0, f"progress 应为 1.0，实际 {row[1]}"

    async def test_mark_failed(self, db_session):
        video = await create_video(
            db_session,
            VideoCreate(
                file_path="/tmp/test_failed.mp4",
                file_name="test_failed.mp4",
                file_size=256,
            ),
        )
        factory = async_sessionmaker(
            db_session.bind, class_=AsyncSession, expire_on_commit=False,
        )
        tracker = StatusTracker(str(video.id), factory)

        await tracker.mark_failed("测试错误")

        row = (
            await db_session.execute(
                text(
                    "SELECT status::text, progress, error_message FROM videos WHERE id = :vid"
                ),
                {"vid": video.id},
            )
        ).fetchone()
        assert row is not None
        assert row[0] == "FAILED", f"状态应为 FAILED，实际 {row[0]}"
        assert row[1] == 1.0, f"failed 时 progress 应为 1.0，实际 {row[1]}"
        assert row[2] == "测试错误", f"error_message 应保留，实际 {row[2]}"
