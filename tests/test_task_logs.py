"""任务日志生命周期 + 导出报告 — 单元测试。

- task_logs 表用 SQLite（纯普通列，可建）。
- 报告生成用 mock AsyncSession（Video 带 JSONB 列，SQLite 建不了，故不走真表）。
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from core.models import TaskLog
from core.repository import append_task_log


@pytest.fixture
async def log_factory():
    """SQLite 内存库，只建 task_logs 表。"""
    TaskLog.__table__.schema = None
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(TaskLog.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    try:
        await engine.dispose()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_append_task_log_seq_increments(log_factory):
    tid = uuid.uuid4()
    async with log_factory() as s:
        await append_task_log(s, tid, "任务已创建（待配置参数）")
        await append_task_log(s, tid, "参数已提交，任务入队")
        await append_task_log(s, tid, "管道失败: boom", level="error")

    async with log_factory() as s:
        rows = (await s.execute(
            select(TaskLog).where(TaskLog.task_id == tid).order_by(TaskLog.seq.asc())
        )).scalars().all()

    assert [r.seq for r in rows] == [1, 2, 3]
    assert [r.level for r in rows] == ["info", "info", "error"]
    assert rows[0].message == "任务已创建（待配置参数）"


@pytest.mark.asyncio
async def test_append_task_log_isolation_per_task(log_factory):
    """不同 task_id 的 seq 互不干扰。"""
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    async with log_factory() as s:
        await append_task_log(s, t1, "a")
        await append_task_log(s, t2, "b")
        await append_task_log(s, t1, "c")
    async with log_factory() as s:
        r1 = (await s.execute(
            select(TaskLog).where(TaskLog.task_id == t1).order_by(TaskLog.seq.asc())
        )).scalars().all()
        r2 = (await s.execute(
            select(TaskLog).where(TaskLog.task_id == t2).order_by(TaskLog.seq.asc())
        )).scalars().all()
    assert [r.seq for r in r1] == [1, 2]
    assert [r.seq for r in r2] == [1]


@pytest.mark.asyncio
async def test_build_report_md_includes_core_fields():
    """报告 Markdown 含基本信息 + 统计 + 摘要 + 日志。产物表缺失时降级为 0/—。"""
    from services.report_service import build_report_md
    from core.models import Video, VideoStatus

    now = datetime.now(timezone.utc)
    # 只填 build_report_md 用到的字段；其余 None 不影响
    video = Video(
        id=uuid.uuid4(),
        file_name="demo.mp4",
        version_no=2,
        group_id=None,
        status=VideoStatus.COMPLETED,
        file_path="/tmp/demo.mp4",
        file_size=123,
        duration=65.0,
        created_at=now,
        updated_at=now,
        processing_started_at=None,
        summary={"overview": "整体概述", "highlights": ["要点一", "要点二"]},
    )

    # mock session：所有 count/select 都抛异常 → 走降级路径
    class _Session:
        async def execute(self, stmt):
            raise RuntimeError("no table in unit test")
    session = _Session()

    md = await build_report_md(session, video)
    assert "# 任务报告 · demo.mp4" in md
    assert "V2" in md
    assert "已完成" in md
    assert "整体概述" in md
    assert "要点一" in md
