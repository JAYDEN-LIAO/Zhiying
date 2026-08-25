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

from core.models import Scene, FrameEmbedding, Chunk, TrackEmbedding, PlateDetection, FaceIdentity, OCRDetection

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
    if video_ids is not None:
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
    if video_ids is not None:
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
    if video_ids is not None:
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
    if video_ids is not None:
        stmt = stmt.where(TrackEmbedding.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.TrackEmbedding, row.sim) for row in result]


# ═══════════════════════════════════════════════════════════
# 5. 车牌文本搜索（精确/模糊匹配）
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
# 车牌搜索归一化（模糊搜索的健壮性基石）
#   - 全角 → 半角（中文输入法打出的 ０-９/Ａ-Ｚ/ａ-ｚ）
#   - 去分隔符（· 全角空格 连字符变体 普通空格 / .）
#   - 统一大写（levenshtein 区分大小写，ILIKE 不区分）
# 查询侧用 _normalize_plate，DB 侧用同规则的 _plate_norm_sql，
# 两者必须完全一致，否则匹配失真。
# ═══════════════════════════════════════════════════════════
_FULL_WIDTH = "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
_HALF_WIDTH = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
# 分隔符含聊天常见中点（・･）：OCR 提取的聊天文本/姓名常带，做匹配分隔符统一剔除（v0.34）
_SEPARATORS = "·　-‐–— ／/." + "･・"


def _normalize_plate(s: str) -> str:
    """Python 侧归一化查询：全角→半角、去分隔符、统一大写。"""
    s = s.translate(str.maketrans(_FULL_WIDTH, _HALF_WIDTH))
    return "".join(ch for ch in s if ch not in _SEPARATORS).upper()


def _plate_norm_sql(col):
    """SQL 侧归一化 plate_text（与 _normalize_plate 同规则）。

    translate: from 前 62 位一一映射到半角，末尾的分隔符（无对应）被删除。
    """
    return func.upper(
        func.translate(col, _FULL_WIDTH + _SEPARATORS, _HALF_WIDTH)
    )


async def plate_text_search(
    session: AsyncSession,
    query: str,
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[PlateDetection, float]]:
    """车牌文本模糊搜索 — 归一化后 ILIKE 子串 + Levenshtein 编辑距离。

    候选：归一化文本包含查询（ILIKE）或编辑距离 ≤ 2（近似拼写）。
    相似度 = 1 / (1 + min(编辑距离, 2)) 封顶 0.33，保证候选都能跨过 0.3 门槛。
    支持：一个字（省份/数字/字母）→ 列出所有相关；部分牌号 → 子串匹配；
    近拼写（错 ≤2 位）→ 编辑距离容错。全角/分隔符/大小写由归一化统一处理。
    """
    from sqlalchemy import func as sa_func, or_, case

    q = _normalize_plate(query)
    plate_norm = _plate_norm_sql(PlateDetection.plate_text)
    dist = sa_func.levenshtein(plate_norm, q).label("dist")
    similarity = (1.0 / (1.0 + sa_func.least(dist, 2))).label("sim")
    stmt = (
        select(PlateDetection, similarity)
        .where(or_(
            plate_norm.ilike(f"%{q}%"),
            dist <= 2,
        ))
        .order_by(dist.asc())
        .limit(limit)
    )
    if video_ids is not None:
        stmt = stmt.where(PlateDetection.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.PlateDetection, row.sim) for row in result]


# ═══════════════════════════════════════════════════════════
# 5b. OCR 画面文字精确搜索（v0.34，第 8 路）
# ═══════════════════════════════════════════════════════════

async def ocr_text_search(
    session: AsyncSession,
    query: str,
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[OCRDetection, float]]:
    """OCR 文字精确检索 — 归一化后 ILIKE 子串 + Levenshtein 编辑距离（照 plate_text_search）。

    复用 _normalize_plate 的归一化规则（全角→半角 / 去分隔符 / 统一大写）——聊天文本同样适用。
    聊天场景核心价值：引原话 / 搜人名 / 数字 / 链接，逐字节定位到那一帧。
    """
    from sqlalchemy import func as sa_func, or_

    q = _normalize_plate(query)
    ocr_norm = _plate_norm_sql(OCRDetection.text)
    dist = sa_func.levenshtein(ocr_norm, q).label("dist")
    similarity = (1.0 / (1.0 + sa_func.least(dist, 2))).label("sim")
    stmt = (
        select(OCRDetection, similarity)
        .where(or_(
            ocr_norm.ilike(f"%{q}%"),
            dist <= 2,
        ))
        .order_by(dist.asc())
        .limit(limit)
    )
    if video_ids is not None:
        stmt = stmt.where(OCRDetection.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.OCRDetection, row.sim) for row in result]


# ═══════════════════════════════════════════════════════════
# 6. 人脸身份向量搜索（图片搜人脸 — ArcFace 512d）
# ═══════════════════════════════════════════════════════════

# 人脸搜索命中阈值 — 聚类在 face.py（同 track 0.30 / 跨 track 0.58 护栏式）。
# 搜索比聚类略宽松（0.45 < 跨 track 0.58）：容忍查询图与身份代表脸的角度/光照小差异，
# 且不引入误并（搜索只取 top-k + 按相似度排序，无"合并"副作用）。
# 原单一 0.40 会把不同人并错进身份导致搜不到，见 face.py 注释。
FACE_SEARCH_MIN_SIM = 0.45

async def face_identity_search(
    session: AsyncSession,
    query_embedding: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
    min_similarity: float = FACE_SEARCH_MIN_SIM,
) -> list[tuple[FaceIdentity, float]]:
    """人脸身份搜索 — ArcFace 512d 查询向量 vs face_identities 表。

    similarity = 1 - cosine_distance，范围 (0, 1]。

    v0.30 检索锚点：同时比 best_face_embedding（最典型单脸）与 face_embedding（均值），
    取两者更高者。实测教训：单一锚点会漏——质量分高的单脸可能偏角度（人物N: 0.38 搜不到），
    均值 0.634 却命中；反之均值可能被噪声拉偏时单脸更准。GREATEST 双锚取优，漏检最低。
    """
    # 双锚：best 单脸与均值各自算相似度，GREATEST 取高；任一为 NULL 时用另一列。
    best_col = FaceIdentity.best_face_embedding
    mean_col = FaceIdentity.face_embedding
    sim_best = (1.0 - best_col.cosine_distance(query_embedding))
    sim_mean = (1.0 - mean_col.cosine_distance(query_embedding))
    similarity = func.greatest(sim_best, sim_mean).label("sim")
    stmt = (
        select(FaceIdentity, similarity)
        .where(best_col.isnot(None) | mean_col.isnot(None))
        .where(similarity >= min_similarity)
        .order_by(similarity.desc())
        .limit(limit)
    )
    if video_ids is not None:
        stmt = stmt.where(FaceIdentity.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.FaceIdentity, row.sim) for row in result]


# ═══════════════════════════════════════════════════════════
# 4. 素材库检索（v0.6，分轨）
# person → face_embedding Vector(512)  ;  other → other_embedding EmbedVector()
# ═══════════════════════════════════════════════════════════

async def subject_embedding_search(
    session: AsyncSession,
    face_vec: list[float] | None,
    other_vec: list[float] | None,
    kind: str,
    limit: int = 20,
    min_similarity: float = 0.3,
    kind_filter: str | None = None,
) -> list[tuple["SubjectPhoto", float]]:
    """素材库底库照片检索 — 按 kind 选用匹配的向量列做跨模态检索。

    - kind="person"：用 face_embedding(512)，face_vec 必须传 512 维
    - kind="other" ：用 other_embedding(EmbedVector)，other_vec 必须传对应维度
    kind_filter 用于请求侧若想限定某类目标时收紧（可选）。
    返回携照片记录及其相似度（0,1]。
    """
    from core.models import SubjectPhotoEmbedding, SubjectPhoto

    if kind == "person":
        if face_vec is None:
            return []
        col = SubjectPhotoEmbedding.face_embedding
        query_vec = face_vec
    else:  # other
        if other_vec is None:
            return []
        col = SubjectPhotoEmbedding.other_embedding
        query_vec = other_vec

    similarity = (1.0 - col.cosine_distance(query_vec)).label("sim")
    stmt = (
        select(SubjectPhoto, similarity)
        .join(SubjectPhotoEmbedding, SubjectPhoto.id == SubjectPhotoEmbedding.photo_id)
        .where(col.isnot(None))
        .where(similarity >= min_similarity)
        .order_by(similarity.desc())
        .limit(limit)
    )
    if kind_filter is not None:
        stmt = stmt.where(SubjectPhotoEmbedding.kind == kind_filter)
    result = await session.execute(stmt)
    return [(row.SubjectPhoto, row.sim) for row in result]
