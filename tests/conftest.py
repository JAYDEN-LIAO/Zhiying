"""
共享 fixture — 每个测试独立创建 engine + session，避免连接跨事件循环污染。
"""
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from core.db import POSTGRES_URI
from core.models import Base


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """为每个测试函数创建独立 engine + 会话，测试结束后彻底销毁。"""
    # ── 每个测试独立的 engine（避免连接绑定到旧循环） ──
    test_engine = create_async_engine(POSTGRES_URI, echo=False)

    # ── 初始化扩展 / 表 ──
    async with test_engine.begin() as conn:
        for ext in ("uuid-ossp", "vector"):
            await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
        await conn.run_sync(Base.metadata.create_all)

    # ── 测试会话 ──
    TestAsyncSessionLocal = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with TestAsyncSessionLocal() as session:
        yield session

    # ── 销毁 engine，释放所有连接 ──
    await test_engine.dispose()
