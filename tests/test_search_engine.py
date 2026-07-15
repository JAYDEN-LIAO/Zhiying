"""
core/search.py 向量检索集成测试
═════════════════════════════════════════════════════════════════
覆盖三条有效路径：frame / chunk / text（语义向量而非全文检索）。

注意：每个测试使用 uuid 派生唯一值，防止跨测试数据污染。
"""
import uuid

import pytest
from sqlalchemy import text

from core.models import Scene, FrameEmbedding, Chunk
from core.schemas import VideoCreate
from core.repository import create_video
from core.search import (
    frame_vector_search,
    chunk_vector_search,
    text_vector_search,
)


def _unique_tag() -> str:
    """返回简短唯一标识，用于区分各次测试产生的数据。"""
    return uuid.uuid4().hex[:12]


# ══════════════════════════════════════════════════════════════
# Test — frame 级向量检索
# ══════════════════════════════════════════════════════════════
class TestFrameVectorSearch:
    """FrameEmbedding 表向量检索，验证排序正确。"""

    async def test_frame_search_ordering(self, db_session):
        # 清理旧数据
        await db_session.execute(text("DELETE FROM frame_embeddings"))
        await db_session.commit()

        tag = _unique_tag()
        video = await create_video(
            db_session,
            VideoCreate(
                file_path=f"/tmp/frame_{tag}.mp4",
                file_name=f"frame_{tag}.mp4",
                file_size=100,
            ),
        )

        query_vector = [0.5] * 2048

        # frame A: 与查询完全一致
        fa = FrameEmbedding(
            video_id=video.id, scene_index=0, timestamp_sec=1.0,
            embedding=[0.5] * 2048, is_keyframe=True,
        )
        # frame B: 正交
        fb = FrameEmbedding(
            video_id=video.id, scene_index=1, timestamp_sec=5.0,
            embedding=[1.0 if i % 2 == 0 else -1.0 for i in range(2048)],
            is_keyframe=False,
        )
        db_session.add_all([fa, fb])
        await db_session.commit()

        results = await frame_vector_search(db_session, query_vector, limit=5)
        assert len(results) >= 2, "应返回至少 2 条 frame"
        assert results[0][0].id == fa.id, "frame A（距离 0）应排首位"
        assert results[0][1] > results[1][1], "相似度降序排列"

    async def test_frame_search_video_filter(self, db_session):
        """验证 video_ids 过滤参数。"""
        await db_session.execute(text("DELETE FROM frame_embeddings"))
        await db_session.commit()

        tag = _unique_tag()
        v1 = await create_video(db_session, VideoCreate(file_path=f"/tmp/f1_{tag}.mp4", file_name=f"f1_{tag}.mp4", file_size=100))
        v2 = await create_video(db_session, VideoCreate(file_path=f"/tmp/f2_{tag}.mp4", file_name=f"f2_{tag}.mp4", file_size=100))

        for v in [v1, v2]:
            db_session.add(FrameEmbedding(video_id=v.id, scene_index=0, timestamp_sec=1.0, embedding=[0.5] * 2048))
        await db_session.commit()

        results = await frame_vector_search(db_session, [0.5] * 2048, limit=10, video_ids=[str(v1.id)])
        assert len(results) == 1, "应只返回 v1 的 1 条 frame"


# ══════════════════════════════════════════════════════════════
# Test — chunk 窗口向量检索
# ══════════════════════════════════════════════════════════════
class TestChunkVectorSearch:
    """Chunks 表向量检索。"""

    async def test_chunk_search_ordering(self, db_session):
        await db_session.execute(text("DELETE FROM chunks"))
        await db_session.commit()

        tag = _unique_tag()
        video = await create_video(
            db_session,
            VideoCreate(
                file_path=f"/tmp/chunk_{tag}.mp4",
                file_name=f"chunk_{tag}.mp4",
                file_size=100,
            ),
        )

        query_vector = [0.3] * 2048

        c1 = Chunk(
            video_id=video.id, scene_index=0, chunk_index=0,
            start_sec=0.0, end_sec=10.0, embedding=[0.3] * 2048,
        )
        c2 = Chunk(
            video_id=video.id, scene_index=1, chunk_index=0,
            start_sec=10.0, end_sec=20.0, embedding=[0.0] * 2048,
        )
        db_session.add_all([c1, c2])
        await db_session.commit()

        results = await chunk_vector_search(db_session, query_vector, limit=5)
        assert len(results) >= 2
        assert results[0][0].id == c1.id, "chunk A 应排首位"


# ══════════════════════════════════════════════════════════════
# Test — 文本语义向量检索
# ══════════════════════════════════════════════════════════════
class TestTextVectorSearch:
    """scenes.text_embedding 语义检索。"""

    async def test_text_search_ordering(self, db_session):
        await db_session.execute(text("UPDATE scenes SET text_embedding = NULL"))
        await db_session.commit()

        tag = _unique_tag()
        video = await create_video(
            db_session,
            VideoCreate(
                file_path=f"/tmp/text_{tag}.mp4",
                file_name=f"text_{tag}.mp4",
                file_size=100,
            ),
        )

        query_vector = [0.7] * 2048

        s1 = Scene(
            video_id=video.id, scene_index=0,
            start_sec=0.0, end_sec=10.0,
            text_embedding=[0.7] * 2048, caption="test A",
        )
        s2 = Scene(
            video_id=video.id, scene_index=1,
            start_sec=10.0, end_sec=20.0,
            text_embedding=[0.0] * 2048, caption="test B",
        )
        db_session.add_all([s1, s2])
        await db_session.commit()

        results = await text_vector_search(db_session, query_vector, limit=5)
        assert len(results) >= 2
        assert results[0][0].id == s1.id, "Scene A（text_embedding 完全匹配）应排首位"
