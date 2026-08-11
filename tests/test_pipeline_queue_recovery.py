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
