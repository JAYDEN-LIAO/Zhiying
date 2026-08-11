"""PipelineQueue 单元测试 — FIFO / 并发 / 失败 / configure。"""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from core.models import PipelineTask


@pytest.mark.asyncio
async def test_enqueue_runs_executor_and_marks_completed(db_session_factory, queue_factory):
    called = asyncio.Event()

    async def executor(tid, payload, vid):
        called.set()

    q = queue_factory(executor)
    tid = await q.enqueue("yunzhi_job", {"x": 1})
    await asyncio.wait_for(called.wait(), timeout=3)
    await asyncio.sleep(0.05)  # 等 worker 写 completed
    async with db_session_factory() as s:
        row = (await s.execute(select(PipelineTask).where(PipelineTask.id == uuid.UUID(tid)))).scalar_one()
    assert row.status == "completed"


@pytest.mark.asyncio
async def test_fifo_order(queue_factory):
    order = []

    async def executor(tid, payload, vid):
        order.append(payload["n"])

    q = queue_factory(executor)
    for n in range(3):
        await q.enqueue("pipeline", {"n": n})
    for _ in range(60):
        if len(order) >= 3:
            break
        await asyncio.sleep(0.05)
    assert order == [0, 1, 2]


@pytest.mark.asyncio
async def test_serial_with_one_worker(queue_factory):
    active = 0
    max_active = 0
    entered = asyncio.Event()
    release = asyncio.Event()

    async def executor(tid, payload, vid):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        entered.set()
        await release.wait()
        active -= 1

    q = queue_factory(executor, max_workers=1)
    await q.enqueue("pipeline", {"n": 1})
    await q.enqueue("pipeline", {"n": 2})
    await asyncio.wait_for(entered.wait(), timeout=3)
    await asyncio.sleep(0.1)
    assert max_active == 1       # 1 个 worker → 永不并发
    assert active == 1           # 第二个任务在队列里等
    release.set()
    for _ in range(60):
        if active == 0:
            break
        await asyncio.sleep(0.05)
    assert active == 0


@pytest.mark.asyncio
async def test_configure_adds_workers(queue_factory):
    entered = 0
    gate = asyncio.Event()
    release = asyncio.Event()

    async def executor(tid, payload, vid):
        nonlocal entered
        entered += 1
        gate.set()
        await release.wait()

    q = queue_factory(executor, max_workers=1)
    await q.enqueue("pipeline", {"n": 1})
    await q.enqueue("pipeline", {"n": 2})
    await asyncio.wait_for(gate.wait(), timeout=3)
    q.configure(2)  # 增加 worker → 第二个任务并行进入
    for _ in range(60):
        if entered >= 2:
            break
        await asyncio.sleep(0.05)
    assert entered == 2
    release.set()


@pytest.mark.asyncio
async def test_task_failure_marks_failed_and_queue_survives(db_session_factory, queue_factory):
    async def executor(tid, payload, vid):
        raise RuntimeError("boom")

    q = queue_factory(executor, max_workers=1)
    tid = await q.enqueue("pipeline", {"n": 1})
    row = None
    for _ in range(60):
        async with db_session_factory() as s:
            row = (await s.execute(
                select(PipelineTask).where(PipelineTask.id == uuid.UUID(tid))
            )).scalar_one()
        if row.status in ("completed", "failed"):
            break
        await asyncio.sleep(0.05)
    assert row.status == "failed"
    assert "boom" in (row.error or "")
    # 队列没死：还能继续处理下一个任务
    done = asyncio.Event()

    async def good_executor(tid, payload, vid):
        done.set()

    q._executors["pipeline"] = good_executor  # noqa: SLF001 — 测试注入
    await q.enqueue("pipeline", {"n": 2})
    await asyncio.wait_for(done.wait(), timeout=3)
