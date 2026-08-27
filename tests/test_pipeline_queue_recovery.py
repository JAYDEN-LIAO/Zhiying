"""PipelineQueue 启动恢复测试 — queued 重入队 / running yunzhi 续跑 / running pipeline 标失败。"""
import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from core.models import PipelineTask


async def _insert(db_session_factory, task_type, status, dedup_key=None, video_id=None, payload=None):
    tid = str(uuid.uuid4())
    async with db_session_factory() as s:
        s.add(PipelineTask(
            id=uuid.UUID(tid), type=task_type, dedup_key=dedup_key,
            video_id=uuid.UUID(video_id) if video_id else None,
            payload_json=json.dumps(payload or {"a": 1}), status=status,
        ))
        await s.commit()
    return tid


@pytest.mark.asyncio
async def test_recover_requeues_queued(db_session_factory, queue_factory):
    calls = []

    async def executor(tid, payload, vid):
        calls.append((tid, payload, vid))

    q = queue_factory(executor, max_workers=2)
    tid = await _insert(db_session_factory, "yunzhi_job", "queued")
    await q.recover()
    for _ in range(60):
        if calls:
            break
        await asyncio.sleep(0.05)
    assert calls and calls[0][0] == tid  # queued 任务被重入队并执行


@pytest.mark.asyncio
async def test_recover_running_yunzhi_resumes_with_video(db_session_factory, queue_factory):
    calls = []

    async def executor(tid, payload, vid):
        calls.append((tid, payload, vid))

    q = queue_factory(executor, max_workers=2)
    vid = str(uuid.uuid4())
    tid = await _insert(db_session_factory, "yunzhi_job", "running", video_id=vid)
    await q.recover()
    for _ in range(60):
        if calls:
            break
        await asyncio.sleep(0.05)
    # 续跑：executor 收到已建 video_id（复用，不重复建视频）
    assert calls and calls[0][2] == vid
    # 状态回退 queued（随后 worker 置 running/completed）
    async with db_session_factory() as s:
        row = (await s.execute(select(PipelineTask).where(PipelineTask.id == uuid.UUID(tid)))).scalar_one()
    assert row.status in ("running", "completed")


@pytest.mark.asyncio
async def test_recover_running_pipeline_marks_failed_not_rerun(db_session_factory, queue_factory):
    async def executor(tid, payload, vid):
        raise AssertionError("running pipeline 不应被重跑")

    q = queue_factory(executor, max_workers=1)
    tid = await _insert(db_session_factory, "pipeline", "running")
    await q.recover()
    await asyncio.sleep(0.1)
    async with db_session_factory() as s:
        row = (await s.execute(select(PipelineTask).where(PipelineTask.id == uuid.UUID(tid)))).scalar_one()
    assert row.status == "failed"  # 不静默重跑，标失败让用户重跑


# ═══ v0.6.2 存储卫生：queued 任务的视频已删 → 标 failed 不再重入队 ═══

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import registry as sa_registry

import core.models as core_models


@pytest.fixture
async def db_factory_with_videos(monkeypatch):
    """pipeline_tasks + 最小 videos 影子表（真实 Video 带 pgvector/JSONB 建不了）。

    recover() 内部 `from core.models import Video` → 用影子 ORM 类顶替。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(PipelineTask.__table__.create)
        await conn.exec_driver_sql("CREATE TABLE videos (id CHAR(32) PRIMARY KEY)")

    class ShadowVideo:
        pass

    reg = sa_registry()

    shadow_table = __import__("sqlalchemy").Table(
        "videos", reg.metadata,
        __import__("sqlalchemy").Column("id", __import__("sqlalchemy").Uuid(as_uuid=True), primary_key=True),
    )
    reg.map_imperatively(ShadowVideo, shadow_table)
    monkeypatch.setattr(core_models, "Video", ShadowVideo)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    try:
        await engine.dispose()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_recover_skips_queued_task_whose_video_deleted(db_factory_with_videos):
    """视频已删的排队任务重启恢复时标 failed（含原因），不再入队空转。"""
    from core.pipeline_queue import PipelineQueue

    factory = db_factory_with_videos
    vid_present, vid_gone = uuid.uuid4(), uuid.uuid4()
    async with factory() as s:
        # videos 影子表里只有「还在」的那个视频（CHAR(32) 无连字符格式）
        await s.execute(
            text("INSERT INTO videos (id) VALUES (:vid)"),
            {"vid": str(vid_present).replace("-", "")},
        )
        s.add(PipelineTask(id=uuid.uuid4(), type="yunzhi_job",
                           video_id=vid_present, payload_json=json.dumps({"a": 1}),
                           status="queued"))
        s.add(PipelineTask(id=uuid.uuid4(), type="pipeline",
                           video_id=vid_gone, payload_json=json.dumps({"video_id": str(vid_gone)}),
                           status="queued"))
        await s.commit()

    calls = []

    async def executor(tid, payload, vid):
        calls.append((tid, payload, vid))

    q = PipelineQueue()
    q.bind(factory, {"yunzhi_job": executor, "pipeline": executor, "incremental": executor},
           max_workers=2)
    try:
        await q.recover()
        for _ in range(60):
            if calls:
                break
            await asyncio.sleep(0.05)
        # 只有「视频还在」的任务被执行；已删视频的任务不执行
        assert len(calls) == 1 and calls[0][2] == str(vid_present)
        async with factory() as s:
            rows = (await s.execute(select(PipelineTask))).scalars().all()
        gone = [r for r in rows if r.video_id == vid_gone][0]
        assert gone.status == "failed"
        assert "不存在" in (gone.error or "")
    finally:
        await q.shutdown()
