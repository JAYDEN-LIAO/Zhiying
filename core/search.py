"""
core/search.py
═══════════════════════════════════════════════════════════
高级搜索服务 — pgvector HNSW 余弦检索 / GIN 全文检索 / 混合检索

索引布局（models.py 中定义）：
  idx_scenes_embedding_hnsw  → HNSW + vector_cosine_ops
  idx_scenes_search_vector_gin → GIN (tsvector)
  idx_transcripts_full_text_gin → GIN + gin_trgm_ops (transcript.full_text)
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Scene, Transcript, FrameEmbedding, Chunk

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────────────────

def _to_tsquery(query_text: str) -> str:
    """将用户自然语言查询转换为 to_tsquery 接受的词位表达式。

    Example:
        "猫 打碎 水杯" → "猫 & 打碎 & 水杯"
    """
    terms = query_text.strip().split()
    if not terms:
        return ""
    return " & ".join(terms)


# ═══════════════════════════════════════════════════════════
# 1. 向量相似度检索
# ═══════════════════════════════════════════════════════════

async def vector_similarity_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 10,
    video_ids: list[str] | None = None,
) -> list[tuple[Scene, float]]:
    """pgvector 余弦相似度检索。

    返回 (Scene, similarity) 元组列表，
    similarity = 1 - cosine_distance，范围 (0, 1]，越大越相似。
    """
    similarity = (1.0 - Scene.embedding.cosine_distance(query_vector)).label("similarity")
    stmt = (
        select(Scene, similarity)
        .where(Scene.embedding.isnot(None))
        .order_by(similarity.desc())
        .limit(limit)
    )
    if video_ids:
        stmt = stmt.where(Scene.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.Scene, row.similarity) for row in result]


# ═══════════════════════════════════════════════════════════
# 2. 全文检索
# ═══════════════════════════════════════════════════════════

async def full_text_search(
    session: AsyncSession,
    query_text: str,
    limit: int = 10,
    video_ids: list[str] | None = None,
) -> list[tuple[Scene, float]]:
    """PostgreSQL 原生全文检索。

    返回 (Scene, relevance) 元组列表，
    relevance 为 ts_rank 得分，越大越相关。
    """
    tsq = func.to_tsquery("simple", _to_tsquery(query_text))
    rank = func.ts_rank(Scene.search_vector, tsq).label("relevance")

    stmt = (
        select(Scene, rank)
        .where(
            Scene.search_vector.isnot(None),
            Scene.search_vector.op("@@")(tsq),
        )
        .order_by(rank.desc())
        .limit(limit)
    )
    if video_ids:
        stmt = stmt.where(Scene.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.Scene, row.relevance) for row in result]


# ═══════════════════════════════════════════════════════════
# 3. 混合检索（向量 + 全文的加权融合）
# ═══════════════════════════════════════════════════════════

async def hybrid_search(
    session: AsyncSession,
    query_vector: list[float],
    query_text: str,
    vector_weight: float = 0.7,
    limit: int = 10,
) -> list[tuple[Scene, float]]:
    """混合检索：余弦相似度 × 权重 + ts_rank × 互补权重。

    融合策略（单次 SQL 完成）：
      hybrid_score = vector_weight × (1 - cosine_distance)
                   + (1 - vector_weight) × COALESCE(ts_rank, 0)

    Args:
        query_vector: 查询向量（2048 维）。
        query_text:   全文检索查询文本。
        vector_weight: 向量相似度权重（0~1），全文权重 = 1 - vector_weight。
        limit:        返回条数。

    Returns:
        list[(Scene, hybrid_score)] — 按融合得分降序排列。
    """
    tsq = func.plainto_tsquery("simple", query_text)

    # ── 两路得分 ──
    vector_sim = (1.0 - Scene.embedding.cosine_distance(query_vector)).label("vscore")
    text_rank = func.coalesce(func.ts_rank(Scene.search_vector, tsq), 0.0).label("tscore")

    # ── 加权融合 ──
    hybrid = (
        vector_weight * (1.0 - Scene.embedding.cosine_distance(query_vector))
        + (1.0 - vector_weight)
        * func.coalesce(func.ts_rank(Scene.search_vector, tsq), 0.0)
    ).label("hybrid_score")

    stmt = (
        select(Scene, hybrid)
        .where(Scene.embedding.isnot(None))
        .order_by(hybrid.desc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    return [(row.Scene, row.hybrid_score) for row in result]


# ═══════════════════════════════════════════════════════════
# 4. 转录文本模糊搜索
# ═══════════════════════════════════════════════════════════

async def fuzzy_transcript_search(
    session: AsyncSession,
    keyword: str,
    limit: int = 5,
) -> list[Transcript]:
    """对 transcripts.full_text 进行 ILIKE 模糊匹配。

    利用 idx_transcripts_full_text_gin（GIN + gin_trgm_ops）加速，
    pg_trgm 将 LIKE/ILIKE 查询转换为三元组匹配 → 走索引扫描。
    """
    # 对 keyword 中的 LIKE 通配符做转义，防止语义注入
    safe_keyword = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{safe_keyword}%"

    stmt = (
        select(Transcript)
        .where(Transcript.full_text.ilike(pattern))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════
# 5. 帧级向量搜索（帧级精确时间定位）
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
# 6. chunk 窗口向量搜索（过程语义搜索）
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
# 7. 文本语义向量搜索（caption + ocr + transcript 的文本嵌入）
# ═══════════════════════════════════════════════════════════

async def text_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[Scene, float]]:
    """文本语义搜索 — encode_text(query) vs encode_text(caption)。

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
