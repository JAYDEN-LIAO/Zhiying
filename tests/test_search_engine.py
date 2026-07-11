"""
core/search.py 全套检索集成测试
═════════════════════════════════════════════════════════════════
覆盖：向量余弦距离排序 / 全文检索权重 / 混合检索融合分数 / 模糊转录检索。

注意：每个测试使用 uuid 派生唯一嵌入值和关键词，防止跨测试数据污染。
"""
import uuid

import pytest
from sqlalchemy import text

from core.models import Scene, Transcript
from core.schemas import VideoCreate
from core.repository import create_video
from core.search import (
    vector_similarity_search,
    full_text_search,
    hybrid_search,
    fuzzy_transcript_search,
)


def _unique_tag() -> str:
    """返回简短唯一标识，用于区分各次测试产生的数据。"""
    return uuid.uuid4().hex[:12]


# ═══════════════════════════════════════════════════════════════
# Test 1 — 向量余弦距离
# ═══════════════════════════════════════════════════════════════
class TestVectorCosineDistance:
    """插入两个有确定夹角关系的向量，验证排序与 limit 正确。"""

    async def test_cosine_distance_ordering(self, db_session):
        # 清理旧向量数据，防止余弦距离=0 的旧 scene 干扰排序
        await db_session.execute(text("DELETE FROM scenes WHERE embedding IS NOT NULL"))
        await db_session.commit()

        tag = _unique_tag()
        base = int(tag[:8], 16) % 10_000_000 / 10_000_000.0  # 0.0 ~ 0.9999999
        video = await create_video(
            db_session,
            VideoCreate(
                file_path=f"/tmp/vec_{tag}.mp4",
                file_name=f"vec_{tag}.mp4",
                file_size=100,
            ),
        )

        # query / Scene A : base × 768 → 完全一致 → distance = 0
        # Scene B          : 交替 1,-1   → 与 base×768 正交  → distance = 1
        query_vector = [base] * 768

        scene_a = Scene(
            video_id=video.id, scene_index=0,
            start_sec=0.0, end_sec=10.0,
            embedding=[base] * 768,
        )
        scene_b = Scene(
            video_id=video.id, scene_index=1,
            start_sec=10.0, end_sec=20.0,
            embedding=[1.0 if i % 2 == 0 else -1.0 for i in range(768)],
        )
        db_session.add_all([scene_a, scene_b])
        await db_session.commit()

        # ── limit=5 检索：Scene A 应排首位 ──
        results = await vector_similarity_search(db_session, query_vector, limit=5)
        assert len(results) >= 2, "应返回至少 2 条 scene"
        assert results[0].id == scene_a.id, "Scene A（距离 0）应排首位"

        # ── limit=1：只返回最近的一条 ──
        top1 = await vector_similarity_search(db_session, query_vector, limit=1)
        assert len(top1) == 1
        assert top1[0].id == scene_a.id, "limit=1 时也应返回 Scene A"


# ═══════════════════════════════════════════════════════════════
# Test 2 — 全文检索权重与排序
# ═══════════════════════════════════════════════════════════════
class TestFullTextSearchWeight:
    """caption(权重 A) 应比 aligned_transcript(权重 C) 获得更高 ts_rank。"""

    async def test_weight_a_beats_weight_c(self, db_session):
        tag = _unique_tag()
        video = await create_video(
            db_session,
            VideoCreate(
                file_path=f"/tmp/fts_{tag}.mp4",
                file_name=f"fts_{tag}.mp4",
                file_size=100,
            ),
        )

        # 使用唯一 token 避免过往数据匹配
        token = f"wproof_{tag}"

        # ── Scene 1: 关键词出现在 caption（权重 A） ──
        s1 = Scene(
            video_id=video.id, scene_index=0,
            start_sec=0.0, end_sec=10.0,
            caption=f"The caption contains {token} here",
        )
        # ── Scene 2: 关键词出现在 aligned_transcript（权重 C） ──
        s2 = Scene(
            video_id=video.id, scene_index=1,
            start_sec=10.0, end_sec=20.0,
            aligned_transcript=f"The transcript contains {token} here",
        )
        db_session.add_all([s1, s2])
        await db_session.commit()

        # ── 调用全文检索 ──
        results = await full_text_search(db_session, token, limit=5)
        assert len(results) >= 2, "两个 scene 都应被召回"

        assert results[0].id == s1.id, (
            "caption(权重 A) 应排在 aligned_transcript(权重 C) 之前"
        )

        # ── 通过 raw SQL 验证 ts_rank 数值严格高于 Scene 2 ──
        rows = (
            await db_session.execute(
                text("""
                    SELECT
                      id,
                      ts_rank(
                        search_vector,
                        to_tsquery('simple', :tsq)
                      ) AS rank
                    FROM scenes
                    WHERE id IN (:id1, :id2)
                    ORDER BY rank DESC
                """),
                {"tsq": token, "id1": s1.id, "id2": s2.id},
            )
        ).fetchall()

        assert len(rows) == 2, f"应返回 2 行 rank 记录，收到 {len(rows)}"
        rank_s1, rank_s2 = rows[0][1], rows[1][1]
        assert rank_s1 > rank_s2, (
            f"Scene 1(caption) rank({rank_s1}) 应 > Scene 2(transcript) rank({rank_s2})"
        )


# ═══════════════════════════════════════════════════════════════
# Test 3 — 混合检索融合测试
# ═══════════════════════════════════════════════════════════════
class TestHybridSearch:
    """hybrid_search 应同时处理向量与文本输入，返回融合后的浮点分数。"""

    async def test_hybrid_search_returns_fused_score(self, db_session):
        tag = _unique_tag()
        video = await create_video(
            db_session,
            VideoCreate(
                file_path=f"/tmp/hyb_{tag}.mp4",
                file_name=f"hyb_{tag}.mp4",
                file_size=100,
            ),
        )

        token = f"hybrid_{tag}"
        base = 0.5
        query_vector = [base] * 768
        scene = Scene(
            video_id=video.id, scene_index=0,
            start_sec=0.0, end_sec=10.0,
            embedding=[base] * 768,
            caption=f"The {token} is here for hybrid test",
        )
        db_session.add(scene)
        await db_session.commit()

        # ── 混合检索 ──
        results = await hybrid_search(
            db_session,
            query_vector=query_vector,
            query_text=token,
            vector_weight=0.7,
            limit=10,
        )

        assert len(results) >= 1, "应至少召回 1 条 scene"

        row = results[0]
        assert len(row) == 2, "每个结果应为 (Scene, float) 二元组"

        result_scene, score = row
        assert result_scene.id == scene.id
        assert isinstance(score, float), f"融合得分应为 float，收到 {type(score)}"

        # 与自身完全一致时：向量部分贡献 0.7×1.0 = 0.7，全文贡献 > 0
        assert score > 0.6, f"融合得分应 > 0.6，实际 {score}"


# ═══════════════════════════════════════════════════════════════
# Test 4 — 模糊转录内容检索
# ═══════════════════════════════════════════════════════════════
class TestFuzzyTranscriptSearch:
    """fuzzy_transcript_search 应能通过 ILIKE 匹配子串。"""

    async def test_fuzzy_match_keyword(self, db_session):
        tag = _unique_tag()
        video = await create_video(
            db_session,
            VideoCreate(
                file_path=f"/tmp/fuzzy_{tag}.mp4",
                file_name=f"fuzzy_{tag}.mp4",
                file_size=100,
            ),
        )

        keyword = f"earnings_{tag}"
        full_text = f"Cerno Q3 {keyword} report detail statement"
        transcript = Transcript(
            video_id=video.id,
            full_text=full_text,
        )
        db_session.add(transcript)
        await db_session.commit()

        # ── 搜索关键词 ──
        results = await fuzzy_transcript_search(db_session, keyword, limit=5)

        assert len(results) >= 1, "应召回匹配的转录记录"
        assert results[0].id == transcript.id
        assert keyword in results[0].full_text
