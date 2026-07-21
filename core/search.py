"""
core/search.py
═══════════════════════════════════════════════════════════
向量搜索服务 — 仅保留帧级 / chunk / 文本语义三条有效路径。

废弃（不再写入数据，已移除）：
  - vector_similarity_search  → scenes.embedding (Phase 4 不再写入)
  - full_text_search          → scenes.search_vector (tsvector)
  - hybrid_search             → 依赖已废弃的 scenes.embedding
  - fuzzy_transcript_search   → transcripts.full_text (ILIKE, 冗余)
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Scene, FrameEmbedding, Chunk, TrackEmbedding

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 1. 帧级向量搜索（帧级精确时间定位）
# ═══════════════════════════════════════════════════════════

async def frame_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[FrameEmbedding, float]]:
    """1fps 帧级搜索 — 每帧独立编码，返回精确时间戳。

    similarity = 1 - cosine_distance，范围 (0, 1]。
    """
    similarity = (1.0 - FrameEmbedding.embedding.cosine_distance(query_vector)).label("sim")
    stmt = (
        select(FrameEmbedding, similarity)
        .where(FrameEmbedding.embedding.isnot(None))
        .order_by(similarity.desc())
        .limit(limit)
    )
    if video_ids:
        stmt = stmt.where(FrameEmbedding.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.FrameEmbedding, row.sim) for row in result]


# ═══════════════════════════════════════════════════════════
# 2. chunk 窗口向量搜索（过程语义搜索）
# ═══════════════════════════════════════════════════════════

async def chunk_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[Chunk, float]]:
    """chunk 窗口搜索 — 多帧原生编码，捕获过程语义。

    similarity = 1 - cosine_distance，范围 (0, 1]。
    """
    similarity = (1.0 - Chunk.embedding.cosine_distance(query_vector)).label("sim")
    stmt = (
        select(Chunk, similarity)
        .where(Chunk.embedding.isnot(None))
        .order_by(similarity.desc())
        .limit(limit)
    )
    if video_ids:
        stmt = stmt.where(Chunk.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.Chunk, row.sim) for row in result]


# ═══════════════════════════════════════════════════════════
# 3. 文本语义向量搜索（caption + OCR + transcript 的文本嵌入）
# ═══════════════════════════════════════════════════════════

async def text_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[Scene, float]]:
    """文本语义搜索 — encode_text(query) vs encode_text(caption + ocr + transcript)。

    similarity = 1 - cosine_distance，范围 (0, 1]。
    """
    similarity = (1.0 - Scene.text_embedding.cosine_distance(query_vector)).label("sim")
    stmt = (
        select(Scene, similarity)
        .where(Scene.text_embedding.isnot(None))
        .order_by(similarity.desc())
        .limit(limit)
    )
    if video_ids:
        stmt = stmt.where(Scene.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.Scene, row.sim) for row in result]


# ═══════════════════════════════════════════════════════════
# 4. track 级向量搜索（物体 crop 跨模态嵌入 — v0.10）
# ═══════════════════════════════════════════════════════════

async def track_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[TrackEmbedding, float]]:
    """track 嵌入搜索 — encode_text(query) vs crop 跨模态嵌入。"""
    similarity = (1.0 - TrackEmbedding.embedding.cosine_distance(query_vector)).label("sim")
    stmt = (
        select(TrackEmbedding, similarity)
        .where(TrackEmbedding.embedding.isnot(None))
        .order_by(similarity.desc())
        .limit(limit)
    )
    if video_ids:
        stmt = stmt.where(TrackEmbedding.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.TrackEmbedding, row.sim) for row in result]
