"""存储卫生 v0.6.2 — 图片素材孤儿清扫、路径归一化、pipeline_tasks 清理。

注：完整 sweep 全流程（PG 17 全表）由 scripts/sweep_storage.py --apply 在
生产库覆盖；此处单测只验证可离线构造的核心逻辑。
"""
import os
import time
import uuid
import json

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from core.models import PipelineTask
from core.storage_manager import StorageManager


# ── 引用集归一化：历史行存相对路径也能对上绝对落盘位置 ──

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt):
        return _FakeResult(self._rows)


@pytest.mark.asyncio
async def test_all_subject_photo_paths_resolves_relative(tmp_path):
    """SubjectPhoto.file_path 相对路径（历史遗留）→ 归一到项目根；绝对路径原样。"""
    sm = StorageManager({"storage": {"artifact_dir": str(tmp_path / "artifacts")}})
    abs_p = str(tmp_path / "artifacts" / "subject_photos" / "x" / "a.jpg")
    rel_p = "data/artifacts/subject_photos/y/b.jpg"
    s = _FakeSession([(abs_p,), (rel_p,), (None,)])
    got = await sm.all_subject_photo_paths(s)
    assert abs_p in got
    assert rel_p.replace("/", os.sep) not in got or str(os.path.abspath(rel_p)) not in got
    # 关键断言：相对路径被收敛到项目根下的绝对形式，且能命中真实文件的 resolve 结果
    from core.paths import project_root
    real = project_root() / rel_p
    assert str(real) in got or str(real.resolve()) in got


def test_orphan_files_under_rules(tmp_path):
    """_orphan_files_under：无引用且超过保护窗 → 回收；被引用/新文件不动。"""
    d = tmp_path / "subject_photos"
    (d / "sid").mkdir(parents=True)
    ref = d / "sid" / "a.jpg"; ref.write_bytes(b"x")
    stale = d / "sid" / "b.jpg"; stale.write_bytes(b"yy")
    fresh = d / "sid" / "c.jpg"; fresh.write_bytes(b"zzz")
    past = time.time() - 7200
    os.utime(stale, (past, past))
    sm = StorageManager({"storage": {"artifact_dir": str(tmp_path)}})
    targets = sm._orphan_files_under(str(d), {str(ref)})
    assert targets == [str(stale)]  # 仅未引用的旧文件


# ── pipeline_tasks：视频删除清行 + 终态行保留策略 ──

@pytest.fixture
async def task_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(PipelineTask.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    try:
        await engine.dispose()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_purge_pipeline_tasks_by_video(task_factory):
    from core.repository import purge_pipeline_tasks
    v1, v2 = uuid.uuid4(), uuid.uuid4()

    def row(v):
        return PipelineTask(id=uuid.uuid4(), type="pipeline", video_id=v,
                            payload_json=json.dumps({}), status="queued")

    async with task_factory() as s:
        s.add(row(v1)); s.add(row(v1)); s.add(row(v2))
        await s.commit()
    async with task_factory() as s:
        n = await purge_pipeline_tasks(s, v1)
        await s.commit()
        assert n == 2
        rest = (await s.execute(
            __import__("sqlalchemy").select(PipelineTask))).scalars().all()
    assert len(rest) == 1 and rest[0].video_id == v2


@pytest.mark.asyncio
async def test_prune_old_pipeline_tasks_keeps_queued(task_factory):
    """终态超期行被清；同期的 queued 行绝不动（重启恢复数据源）。"""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from core.repository import TASK_LOG_RETENTION_DAYS, prune_old_pipeline_tasks

    old = datetime.now(timezone.utc) - timedelta(days=TASK_LOG_RETENTION_DAYS + 1)
    vid = uuid.uuid4()

    async with task_factory() as s:
        s.add(PipelineTask(id=uuid.uuid4(), type="pipeline", video_id=vid,
                           payload_json=json.dumps({}), status="completed",
                           updated_at=old))
        s.add(PipelineTask(id=uuid.uuid4(), type="yunzhi_job", video_id=vid,
                           dedup_key="idem-1", payload_json=json.dumps({}),
                           status="queued", updated_at=old))  # 老但 queued → 保留
        await s.commit()

    async with task_factory() as s:
        assert await prune_old_pipeline_tasks(s, dry_run=True) == 1
    async with task_factory() as s:
        assert await prune_old_pipeline_tasks(s, dry_run=False) == 1
    async with task_factory() as s:
        rows = (await s.execute(select(PipelineTask))).scalars().all()
    assert [r.status for r in rows] == ["queued"]
