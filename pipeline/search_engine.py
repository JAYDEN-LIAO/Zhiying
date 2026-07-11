"""
pipeline/search_engine.py
═══════════════════════════════════════════════════════════
多路召回 + RRF 融合搜索编排器。

三路并行召回:
  1. vector  — pgvector <=> cosine distance  (core.search.vector_similarity_search)
  2. fulltext — ts_rank + tsquery 全文检索     (core.search.full_text_search)
  3. label   — JSONB @> 精确匹配 entities.label
融合策略: Reciprocal Rank Fusion (RRF, k=60)
"""

import asyncio
import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Scene
from core.search import vector_similarity_search, full_text_search

logger = logging.getLogger(__name__)


class SearchEngine:
    """多路召回 + Reciprocal Rank Fusion 融合搜索引擎。"""

    RRF_K: int = 60

    def __init__(
        self,
        db_session_factory: async_sessionmaker[AsyncSession],
        embedder=None,
    ):
        self.db_session_factory = db_session_factory
        self.embedder = embedder

    async def search(
        self,
        query: str | None = None,
        image_vec: list[float] | None = None,
        video_ids: list[str] | None = None,
        search_types: list[str] | None = None,
        top_k: int = 20,
        min_similarity: float = 0.3,
    ) -> list[dict]:
        """多路召回 + RRF 融合。

        Args:
            query:        文本查询（与 image_vec 二选一）。
            image_vec:    图像查询向量（与 query 二选一）。
            video_ids:    限定视频范围，None=全库。
            search_types: 启用哪些检索路 ["vector","fulltext","label"]，默认全开。
            top_k:        最终返回条数。
            min_similarity: 最低相似度阈值。

        Returns:
            [{"scene_id", "video_id", "scene_index", "start_sec", "end_sec",
              "caption", "ocr_text", "aligned_transcript", "entities",
              "similarity", "source"}, ...]
        """
        if search_types is None:
            search_types = ["vector", "fulltext", "label"]

        # 文本查询 → 向量编码
        vec = image_vec
        if query and "vector" in search_types and self.embedder:
            vec = await self.embedder.encode_text(query)

        # ── 三路并行召回 ──
        tasks = []
        if "vector" in search_types and vec is not None:
            tasks.append(self._vector_search(vec, video_ids, top_k * 2))
        if "fulltext" in search_types and query:
            tasks.append(self._fulltext_search(query, video_ids, top_k * 2))
        if "label" in search_types and query:
            tasks.append(self._label_search(query, video_ids, top_k * 2))

        if not tasks:
            return []

        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        ranked_lists = [r for r in results_list if not isinstance(r, Exception) and r]
        if not ranked_lists:
            return []

        # ── 融合 ──
        if len(ranked_lists) == 1:
            # 单路召回：排名位置计算相似度，避免 RRF 单路时分数过低被过滤
            total = max(len(ranked_lists[0]), 2)
            for rank, item in enumerate(ranked_lists[0]):
                item["similarity"] = round(1.0 - (rank / total), 4)
            fused = ranked_lists[0]
        else:
            # 多路召回：RRF 融合
            fused = self._rrf_fuse(ranked_lists, k=self.RRF_K)

        # ── 过滤低分 + Top-K ──
        filtered = [item for item in fused if item["similarity"] >= min_similarity]
        return filtered[:top_k]

    # ──────────────────────────────────────────────────────
    # 各路召回
    # ──────────────────────────────────────────────────────

    async def _vector_search(
        self,
        vec: list[float],
        video_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """向量余弦相似度召回。"""
        async with self.db_session_factory() as session:
            scenes = await vector_similarity_search(
                session, vec, limit=limit,
            )
        return [
            self._scene_to_dict(s, 1.0, "vector")
            for s in scenes
        ]

    async def _fulltext_search(
        self,
        query: str,
        video_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """GIN tsvector 全文检索召回。"""
        async with self.db_session_factory() as session:
            scenes = await full_text_search(
                session, query, limit=limit,
            )
        return [
            self._scene_to_dict(s, 1.0, "fulltext")
            for s in scenes
        ]

    async def _label_search(
        self,
        query: str,
        video_ids: list[str] | None,
        limit: int,
    ) -> list[dict]:
        """JSONB 精确匹配 entities.label 召回。"""
        async with self.db_session_factory() as session:
            stmt = (
                select(Scene)
                .where(Scene.entities.op("@>")(
                    f'[{{"label": "{query}"}}]'
                ))
                .limit(limit)
            )
            if video_ids:
                stmt = stmt.where(Scene.video_id.in_(video_ids))
            result = await session.execute(stmt)
            scenes = list(result.scalars().all())

        return [
            self._scene_to_dict(s, 1.0, "label")
            for s in scenes
        ]

    # ──────────────────────────────────────────────────────
    # RRF 融合
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _rrf_fuse(
        ranked_lists: list[list[dict]],
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion: 合并多路召回的排名。"""
        scores: dict[int, tuple[dict, float]] = {}

        for ranked in ranked_lists:
            for rank, item in enumerate(ranked, start=1):
                sid = item["scene_id"]
                rrf_score = 1.0 / (k + rank)
                if sid in scores:
                    existing, prev = scores[sid]
                    scores[sid] = (existing, prev + rrf_score)
                else:
                    scores[sid] = (item, rrf_score)

        fused = [
            {"scene_id": sid, **item, "similarity": round(score, 4)}
            for sid, (item, score) in scores.items()
        ]
        fused.sort(key=lambda x: x["similarity"], reverse=True)
        return fused

    # ──────────────────────────────────────────────────────
    # 辅助
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _scene_to_dict(
        scene: Scene,
        similarity: float,
        source: str,
    ) -> dict:
        return {
            "scene_id": scene.id,
            "video_id": str(scene.video_id),
            "video_name": getattr(scene, "video_name", None),
            "scene_index": scene.scene_index,
            "start_sec": scene.start_sec,
            "end_sec": scene.end_sec,
            "caption": scene.caption,
            "ocr_text": scene.ocr_text,
            "aligned_transcript": scene.aligned_transcript,
            "entities": scene.entities or [],
            "similarity": similarity,
            "source": source,
        }
