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

from core.models import Scene, Transcript

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
) -> list[Scene]:
    """pgvector 余弦相似度检索。

    使用 HNSW 索引加速的 cosine_distance 排序，
    距离越小越相似 → 按距离升序排列。
    """
    stmt = (
        select(Scene)
        .where(Scene.embedding.isnot(None))
        .order_by(Scene.embedding.cosine_distance(query_vector))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ═══════════════════════════════════════════════════════════
# 2. 全文检索
# ═══════════════════════════════════════════════════════════

async def full_text_search(
    session: AsyncSession,
    query_text: str,
    limit: int = 10,
) -> list[Scene]:
    """PostgreSQL 原生全文检索。

    流程：
      1. query_text → to_tsquery（词位表达式）
      2. search_vector @@ tsquery 过滤
      3. ts_rank 计算相关性得分 → 降序排列
    """
    tsq = func.to_tsquery("simple", _to_tsquery(query_text))
    rank = func.ts_rank(Scene.search_vector, tsq).label("rank")

    stmt = (
        select(Scene)
        .where(
            Scene.search_vector.isnot(None),
            Scene.search_vector.op("@@")(tsq),
        )
        .order_by(rank.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


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
        query_vector: 查询向量（768 维）。
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
