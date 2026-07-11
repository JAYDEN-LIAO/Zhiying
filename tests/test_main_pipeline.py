"""
全链路端到端 E2E 集成测试
═════════════════════════════════════════════════════════════════
模拟真实 HTTP 请求，覆盖"视频创建 → 进度轮询 → 多模态混合检索"黄金流程。

测试架构：
  - httpx.AsyncClient 包装 FastAPI app，全异步发送 HTTP 请求。
  - app.dependency_overrides 将 get_db 指向隔离的测试 engine。
  - 同步暴露原始 DB session 供 fixture 直接写入 Scene 伪数据。
"""
import uuid

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)

from core.db import POSTGRES_URI
from core.models import Base, Scene
from main import app
from api.deps import get_db


# ── 768 维常量 ──
VEC_768_ZERO = [0.0] * 768


@pytest_asyncio.fixture
async def client_and_db():
    """创建隔离的测试 engine + 依赖覆盖 + httpx 客户端。

    Yields:
        (httpx.AsyncClient, AsyncSession) — HTTP 客户端 + 原始 DB 会话。
    """
    test_engine = create_async_engine(POSTGRES_URI, echo=False)

    # ── 初始化扩展 / 函数 / 表 / 触发器 ──
    async with test_engine.begin() as conn:
        for ext in ("uuid-ossp", "pg_trgm", "vector"):
            await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))

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

        await conn.run_sync(Base.metadata.create_all)

        await conn.execute(text(
            "DROP TRIGGER IF EXISTS trg_scenes_search_vector ON scenes"
        ))
        await conn.execute(text("""
            CREATE TRIGGER trg_scenes_search_vector
            BEFORE INSERT OR UPDATE ON scenes
            FOR EACH ROW
            EXECUTE FUNCTION scenes_search_vector_update();
        """))

    TestSessionLocal = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )

    # ── 覆盖 FastAPI 的 get_db 依赖 ──
    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # ── 客户端 + 原始会话 ──
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        async with TestSessionLocal() as session:
            yield client, session

    # ── 清理 ──
    app.dependency_overrides.clear()
    await test_engine.dispose()


# ═══════════════════════════════════════════════════════════════
# 全链路测试
# ═══════════════════════════════════════════════════════════════
class TestGoldenPipeline:
    """Step 1‑5 完整黄金链路。"""

    # 用 UUID 保证每次运行的 keyword 不重复
    _tag = uuid.uuid4().hex[:8]
    KEYWORD = f"e2e_token_{_tag}"
    VEC_BASE = int(_tag[:4], 16) % 10_000_000 / 10_000_000.0

    async def test_full_pipeline(self, client_and_db):
        client, db_session = client_and_db

        # ════════════════════════════════════════════════════════
        # Step 1 — 创建视频
        # ════════════════════════════════════════════════════════
        resp = await client.post(
            "/api/v1/videos",
            json={
                "file_path": f"/tmp/{self._tag}.mp4",
                "file_name": f"{self._tag}.mp4",
                "file_size": 65535,
            },
        )
        assert resp.status_code == 201, (
            f"POST /videos 应为 201，收到 {resp.status_code}: {resp.text}"
        )

        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "ok"

        data = body["data"]
        assert data["status"] == "pending"  # Pydantic 序列化使用枚举 .value（小写）
        assert data["progress"] == 0.0
        video_id = data["id"]
        # 验证 UUID 格式
        uuid.UUID(video_id)

        # ════════════════════════════════════════════════════════
        # Step 2 — 获取视频详情
        # ════════════════════════════════════════════════════════
        resp = await client.get(f"/api/v1/videos/{video_id}")
        assert resp.status_code == 200, f"GET /videos/{{id}} 应为 200：{resp.text}"

        body = resp.json()
        assert body["data"]["id"] == video_id
        assert body["data"]["progress"] == 0.0
        assert body["data"]["file_name"] == f"{self._tag}.mp4"

        # ════════════════════════════════════════════════════════
        # Step 3 — 直接经 DB session 插入 5 条 Scene 伪数据
        # ════════════════════════════════════════════════════════
        scene_ids = []
        for i in range(5):
            scene = Scene(
                video_id=uuid.UUID(video_id),
                scene_index=i,
                start_sec=float(i * 20),
                end_sec=float(i * 20 + 19),
                caption=f"Scene {i} with {self.KEYWORD} description" if i % 2 == 0 else None,
                ocr_text=f"OCR text {self.KEYWORD} page {i}" if i % 3 == 0 else None,
                aligned_transcript=None if i == 4 else f"Transcript with {self.KEYWORD} segment",
                embedding=[self.VEC_BASE + i * 0.01] * 768 if i != 4 else None,
            )
            db_session.add(scene)
            await db_session.flush()
            scene_ids.append(scene.id)

        await db_session.commit()

        # ════════════════════════════════════════════════════════
        # Step 4 — 全文检索
        # ════════════════════════════════════════════════════════
        resp = await client.get(
            "/api/v1/search/text",
            params={"q": self.KEYWORD, "limit": 20},
        )
        assert resp.status_code == 200, f"GET /search/text 应为 200：{resp.text}"

        search_body = resp.json()
        assert search_body["code"] == 0
        results = search_body["data"]["results"]
        assert len(results) >= 1, "应召回至少 1 条 scene"

        returned_ids = [r["scene_id"] for r in results]
        matched = [sid for sid in scene_ids if sid in returned_ids]
        assert len(matched) >= 1, (
            f"应召回本测试插入的 scene，插入 ID {scene_ids}，召回 ID {returned_ids}"
        )

        # ════════════════════════════════════════════════════════
        # Step 5 — 混合检索
        # ════════════════════════════════════════════════════════
        query_vector = [self.VEC_BASE] * 768  # 与 scene 0 完全一致
        resp = await client.post(
            "/api/v1/search/hybrid",
            json={
                "query_text": self.KEYWORD,
                "query_vector": query_vector,
                "limit": 10,
            },
        )
        assert resp.status_code == 200, f"POST /search/hybrid 应为 200：{resp.text}"

        hybrid_body = resp.json()
        assert hybrid_body["code"] == 0

        hybrid_results = hybrid_body["data"]["results"]
        assert len(hybrid_results) >= 1, "混合检索应召回至少 1 条 scene"

        # 验证 similarity 字段存在且为 float
        for item in hybrid_results:
            assert isinstance(item.get("similarity"), (int, float)), (
                f"每项应含 similarity 得分，当前项: {item}"
            )

        # scene 0（embedding 与查询向量完全一致 + 含关键词）应排首位
        assert hybrid_results[0]["scene_id"] == scene_ids[0], (
            "Scene 0（embedding 完全一致 + 含关键词）应排在混合检索首位"
        )
        # 融合得分 = 0.7 * (1 - 0) + 0.3 * ts_rank，应接近 0.7+
        assert hybrid_results[0]["similarity"] > 0.6, (
            f"Scene 0 融合得分应 > 0.6，实际 {hybrid_results[0]['similarity']}"
        )

        # 验证总耗时字段
        assert isinstance(hybrid_body["data"]["query_time_ms"], float)
