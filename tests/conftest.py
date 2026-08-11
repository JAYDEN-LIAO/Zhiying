"""pytest 共享 fixtures — 队列/任务表单元测试用 SQLite（aiosqlite，仅 pipeline_tasks 表）。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# 让测试能 import 项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import PipelineTask
from core.pipeline_queue import PipelineQueue

# 生产 Base 用 PG schema "public"；SQLite 测试需去掉 schema 前缀（仅本测试进程生效）
PipelineTask.__table__.schema = None


@pytest_asyncio.fixture
async def db_session_factory():
    """SQLite 内存库，仅建 pipeline_tasks 表（Video 等带 pgvector 的表不适合 SQLite）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(PipelineTask.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    try:
        await engine.dispose()
    except Exception:
        pass  # aiosqlite 线程在 loop 关闭后的残留 close 噪声，忽略


@pytest_asyncio.fixture
async def fake_app(db_session_factory):
    """极简 app：只有 state.db_session_factory（供 _lookup_task_biz_id 等使用）。"""
    return SimpleNamespace(state=SimpleNamespace(db_session_factory=db_session_factory))


@pytest_asyncio.fixture
async def queue_factory(db_session_factory):
    """构造绑定 fake executor 的 PipelineQueue，teardown 统一 shutdown（释放 DB 会话）。"""
    queues: list[PipelineQueue] = []

    def make(executor, max_workers: int = 1):
        q = PipelineQueue()
        q.bind(
            db_session_factory,
            {"yunzhi_job": executor, "pipeline": executor, "incremental": executor},
            max_workers,
        )
        queues.append(q)
        return q

    yield make
    for q in queues:
        await q.shutdown()
