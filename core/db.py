"""
core/db.py
═══════════════════════════════════════════════════════════
异步数据库引擎、Session 工厂、声明式基类与初始化入口。
"""

import os

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData, text

POSTGRES_URI = os.environ.get(
    "POSTGRES_URI",
    "postgresql+asyncpg://cerno:cerno@localhost:5432/cerno",
)

engine = create_async_engine(
    POSTGRES_URI,
    pool_size=20,
    max_overflow=10,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    metadata = MetaData(schema="public")


async def init_db():
    """初始化数据库扩展、触发器函数及所有表。

    - 创建 uuid-ossp / pg_trgm / vector 扩展
    - 创建 scenes_search_vector_update 触发器函数
    - 创建所有 ORM 表（通过 Base.metadata.create_all）
    """
    async with engine.begin() as conn:
        # ── 扩展 ──
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "vector"'))

        # ── 触发器函数（用于 scenes 表 tsvector 自动维护） ──
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

        # ── 创建所有表 ──
        await conn.run_sync(Base.metadata.create_all)

        # ── 行级触发器（在表创建后附着） ──
        await conn.execute(text("""
            DROP TRIGGER IF EXISTS trg_scenes_search_vector ON scenes
        """))
        await conn.execute(text("""
            CREATE TRIGGER trg_scenes_search_vector
            BEFORE INSERT OR UPDATE ON scenes
            FOR EACH ROW
            EXECUTE FUNCTION scenes_search_vector_update();
        """))
