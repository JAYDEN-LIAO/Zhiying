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

    # ── 初始化扩展 / 函数 / 表 / 触发器 ──
    async with test_engine.begin() as conn:
        # 扩展
        for ext in ("uuid-ossp", "pg_trgm", "vector"):
            await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))

        # 触发器函数
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION scenes_search_vector_update()
            RETURNS trigger AS $$
            BEGIN
                NEW.search_vector :=
                    setweight(to_tsvector('simple', coalesce(NEW.caption, '')), 'A') ||
                    setweight(to_tsvector('simple', coalesce(NEW.ocr_text, '')), 'B') ||
                    setweight(to_tsvector('simple', coalesce(NEW.aligned_transcript, '')), 'C');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))

        # 所有 ORM 表
        await conn.run_sync(Base.metadata.create_all)

        # scenes 表行级触发器
        await conn.execute(text(
            "DROP TRIGGER IF EXISTS trg_scenes_search_vector ON scenes"
        ))
        await conn.execute(text("""
            CREATE TRIGGER trg_scenes_search_vector
            BEFORE INSERT OR UPDATE ON scenes
            FOR EACH ROW
            EXECUTE FUNCTION scenes_search_vector_update();
        """))

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
