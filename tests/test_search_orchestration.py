"""
pipeline/search_engine.py 多路融合测试
═════════════════════════════════════════════════════════════════
写入已知 Scene 数据，验证多路召回 + RRF 融合排序正确性。
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from core.models import Scene, VideoStatus
from core.schemas import VideoCreate
from core.repository import create_video
from pipeline.search_engine import SearchEngine


class TestSearchOrchestration:
    """SearchEngine 多路召回 + RRF 融合。"""

    async def test_rrf_fusion_ranks_dual_match_first(self, db_session):
        """双路命中的 Scene A 应排在单路命中的前面。"""
        video = await create_video(
            db_session,
            VideoCreate(file_path="/tmp/se.mp4", file_name="se.mp4", file_size=100),
        )
        vid = video.id

        # Scene A: caption 含关键词 + embedding 与查询一致（双路命中）
        s_a = Scene(
            video_id=vid, scene_index=0, start_sec=0, end_sec=10,
            caption="target_keyword_X this is scene A",
            embedding=[0.5] * 768,
        )
        # Scene B: 只有 caption 含关键词（单路：全文）
        s_b = Scene(
            video_id=vid, scene_index=1, start_sec=10, end_sec=20,
            caption="target_keyword_X this is scene B",
            embedding=None,
        )
        # Scene C: 只有 embedding 与查询一致（单路：向量）
        s_c = Scene(
            video_id=vid, scene_index=2, start_sec=20, end_sec=30,
            caption="unrelated content",
            embedding=[0.5] * 768,
        )
        db_session.add_all([s_a, s_b, s_c])
        await db_session.commit()

        # ── 构造 SearchEngine ──
        factory = async_sessionmaker(
            db_session.bind, class_=AsyncSession, expire_on_commit=False,
        )
        engine = SearchEngine(db_session_factory=factory)

        results = await engine.search(
            query="target_keyword_X",
            image_vec=[0.5] * 768,
            search_types=["vector", "fulltext"],
            top_k=10,
            min_similarity=0.0,
        )

        # Scene A 应排首位（双路命中 → RRF 分更高）
        assert len(results) >= 1
        assert results[0]["scene_id"] == s_a.id, (
            f"Scene A(双路) 应排首位，实际首位 scene_id={results[0]['scene_id']}"
        )

        # 所有结果应有 similarity > 0
        for item in results:
            assert item["similarity"] > 0, (
                f"RRF 融合分应 > 0，scene_id={item['scene_id']} similarity={item['similarity']}"
            )

    async def test_search_returns_empty_for_no_match(self, db_session):
        factory = async_sessionmaker(
            db_session.bind, class_=AsyncSession, expire_on_commit=False,
        )
        engine = SearchEngine(db_session_factory=factory)
        results = await engine.search(
            query="__nonexistent_query__",
            search_types=["fulltext"],
            top_k=5,
            min_similarity=0.0,
        )
        assert results == []
