"""
api/deps.py
═══════════════════════════════════════════════════════════
FastAPI 依赖注入 — 数据库 Session / 配置 等共享资源。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from core.db import AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖项：提供一次请求一个数据库 Session 的上下文管理。"""
    async with AsyncSessionLocal() as session:
        yield session
