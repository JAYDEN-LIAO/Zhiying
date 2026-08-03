"""
api/search_routes.py
═══════════════════════════════════════════════════════════
搜索端点 — 语义搜索 + Pipeline 操作查询。
"""

import io
import time
import uuid
import logging

import numpy as np
from PIL import Image

from fastapi import APIRouter, Depends, Request, UploadFile, File, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse, SemanticSearchRequest, SearchResultItem, SearchResults
from core.models import Video
from core.config_loader import load_config
from core.search import face_identity_search
from pipeline.operations import ALL_OPERATIONS

logger = logging.getLogger(__name__)

router = APIRouter()


# ═══════════════════════════════════════════════════════════
# 语义搜索
# ═══════════════════════════════════════════════════════════

@router.post("/search/semantic")
async def search_semantic(
    payload: SemanticSearchRequest,
    request: Request,
) -> APIResponse[SearchResults]:
    """语义搜索：传入自然语言文本，服务端自动编码为向量后检索。

    三路并行召回：frame（帧级 1fps）+ chunk（窗口过程语义）+ text（caption+ocr+transcript 语义）。
    """
    t0 = time.monotonic()

    # searchless 部署（未装 Embedding）→ 语义搜索不可用，返回友好错误
    if getattr(request.app.state, "embedder", None) is None:
        raise HTTPException(status_code=400, detail="语义搜索未启用：本部署未安装 Embedding 模型（searchless 模式）")

    se = getattr(request.app.state, "_searcher", None)
    if se is None:
        from pipeline.search_engine import SearchEngine
        embedder = request.app.state.embedder
        se = SearchEngine(request.app.state.db_session_factory, embedder)
        request.app.state._searcher = se

    results = await se.search(
        query=payload.query,
        video_ids=payload.video_ids,
        search_types=payload.search_types,
        top_k=payload.top_k,
        min_similarity=payload.min_similarity,
    )

    elapsed = (time.monotonic() - t0) * 1000

    items = [
        SearchResultItem(
            scene_id=r.get("scene_id", 0),
            video_id=r["video_id"],
            scene_index=r["scene_index"],
            scene_range_start=r.get("scene_range_start", r.get("start_sec", 0)),
            scene_range_end=r.get("scene_range_end", r.get("end_sec", 0)),
            precise_start=r.get("precise_start"),
            precise_end=r.get("precise_end"),
            precision_level=r.get("precision_level", "scene"),
            match_paths=r.get("match_paths", []),
            caption=r.get("caption"),
            ocr_text=r.get("ocr_text"),
            aligned_transcript=r.get("aligned_transcript"),
            similarity=r.get("similarity"),
            thumbnail_url=r.get("thumbnail_url") or f"/api/v1/videos/{r['video_id']}/thumbnail/{r['scene_index']}",
            track_id=r.get("track_id"),
            class_name=r.get("class_name"),
            bbox=r.get("bbox"),
        )
        for r in results
    ]

    return APIResponse(data=SearchResults(results=items, total=len(items), query_time_ms=elapsed))


# ═══════════════════════════════════════════════════════════
# 人脸图片搜索
# ═══════════════════════════════════════════════════════════

@router.post("/search/face")
async def search_face(
    file: UploadFile = File(...),
    video_ids: str | None = None,
    top_k: int = 20,
    request: Request = None,
) -> APIResponse[list[dict]]:
    """上传人脸图片 → ArcFace R50 512d embedding → 比对 face_identities 表。

    Args:
        file:      人脸照片（JPEG/PNG，单张）
        video_ids: 逗号分隔的 video UUID 列表，可选
        top_k:     返回结果数量上限
    """
    t0 = time.monotonic()

    face_recognizer = getattr(request.app.state, "face_recognizer", None)
    if face_recognizer is None:
        raise HTTPException(status_code=503, detail="Face recognizer not configured (set plugins.face.backend)")

    # 读取图片 → numpy array
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
        image = np.array(img)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    # ArcFace R50 提取 512d embedding
    query_emb = await face_recognizer.extract_best_embedding(image)
    if query_emb is None:
        return APIResponse(data=[], message="No face detected in uploaded image")

    # 解析 video_ids
    vid_list: list[str] | None = None
    if video_ids:
        vid_list = [v.strip() for v in video_ids.split(",") if v.strip()]

    # 搜索
    async with request.app.state.db_session_factory() as session:
        results = await face_identity_search(
            session, query_emb, limit=top_k, video_ids=vid_list,
        )

    elapsed = (time.monotonic() - t0) * 1000

    items: list[dict] = []
    for identity, sim in results:
        items.append({
            "identity_id": identity.id,
            "video_id": str(identity.video_id),
            "identity_label": identity.identity_label,
            "face_count": identity.face_count,
            "first_seen": identity.first_seen,
            "last_seen": identity.last_seen,
            "avg_quality": identity.avg_quality,
            "similarity": round(float(sim), 4),
            "best_face_timestamp": identity.best_face_timestamp,
            "best_face_bbox": identity.best_face_bbox,
            "thumbnail_url": (
                f"/api/v1/videos/{identity.video_id}/face/thumbnail"
                f"?identity_id={identity.id}"
            ),
            "query_time_ms": elapsed,
        })

    return APIResponse(data=items)


# ═══════════════════════════════════════════════════════════
# 通用图搜
# ═══════════════════════════════════════════════════════════

@router.post("/search/image")
async def search_image(
    file: UploadFile = File(...),
    video_ids: str | None = None,
    search_types: str | None = None,
    top_k: int = 20,
    min_similarity: float = 0.3,
    request: Request = None,
) -> APIResponse[SearchResults]:
    """上传任意图片 → Qwen3-VL-Embedding 4096-dim → 与 frame_embeddings 表向量匹配。

    和人脸搜索不同：整图直接编码，不检测/不切割图片内容。

    Args:
        file:          图片文件（JPEG/PNG/WebP）
        video_ids:     逗号分隔的 video UUID 列表，可选
        search_types:  逗号分隔的检索路，默认 "frame,track"
        top_k:         返回结果数量上限
        min_similarity:最低相似度阈值
    """
    t0 = time.monotonic()

    embedder = getattr(request.app.state, "embedder", None)
    if embedder is None:
        raise HTTPException(status_code=503, detail="Embedder not loaded")

    # 读取图片 → numpy array
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
        image = np.array(img)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    # Qwen3-VL-Embedding 编码 → 4096-dim 向量
    vec = await embedder.encode_image(image)

    # 初始化 SearchEngine
    se = getattr(request.app.state, "_searcher", None)
    if se is None:
        from pipeline.search_engine import SearchEngine
        se = SearchEngine(request.app.state.db_session_factory, embedder)
        request.app.state._searcher = se

    # 解析参数
    vid_list: list[str] | None = None
    if video_ids:
        vid_list = [v.strip() for v in video_ids.split(",") if v.strip()]

    st_list: list[str] | None = None
    if search_types:
        st_list = [s.strip() for s in search_types.split(",") if s.strip()]
    else:
        st_list = ["frame", "track"]

    # 搜索（图搜专用路径：帧不聚类，不补 scene 信息）
    results = await se.search_image_only(
        vec=vec,
        video_ids=vid_list,
        search_types=st_list,
        top_k=top_k,
        min_similarity=min_similarity,
    )

    elapsed = (time.monotonic() - t0) * 1000

    items = [
        SearchResultItem(
            scene_id=r.get("scene_id", 0),
            video_id=r["video_id"],
            scene_index=r["scene_index"],
            scene_range_start=r.get("scene_range_start", r.get("start_sec", 0)),
            scene_range_end=r.get("scene_range_end", r.get("end_sec", 0)),
            precise_start=r.get("precise_start"),
            precise_end=r.get("precise_end"),
            precision_level=r.get("precision_level", "frame"),
            match_paths=r.get("match_paths", []),
            caption=r.get("caption"),
            similarity=r.get("similarity"),
            thumbnail_url=r.get("thumbnail_url") or f"/api/v1/videos/{r['video_id']}/thumbnail/{r['scene_index']}",
            track_id=r.get("track_id"),
            class_name=r.get("class_name"),
            bbox=r.get("bbox"),
        )
        for r in results
    ]

    return APIResponse(data=SearchResults(results=items, total=len(items), query_time_ms=elapsed))


# ═══════════════════════════════════════════════════════════
# Pipeline 操作查询（前端进度条用）
# ═══════════════════════════════════════════════════════════

@router.get("/pipeline/operations")
async def get_pipeline_operations(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[list[dict]]:
    """返回指定视频的启用操作列表及进度范围（供前端 PipelineBar 渲染）。

    根据视频参数动态计算 gate 结果，前端无需重复实现 gate 逻辑。
    """
    result = await db.execute(
        select(Video).where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if video is None:
        return APIResponse(data=[])

    config = load_config()
    enabled = [op for op in ALL_OPERATIONS if op.gate(video, config)]

    total_weight = sum(op.progress_weight if op.progress_weight > 0 else 1.0 for op in enabled) or 1.0
    cumulative = 0.0
    ops_data: list[dict] = []
    for i, op in enumerate(enabled):
        weight = op.progress_weight if op.progress_weight > 0 else 1.0
        start = cumulative / total_weight
        end = (cumulative + weight) / total_weight
        if i == len(enabled) - 1:
            end = 1.0
        ops_data.append({
            "name": op.name,
            "label": op.label,
            "description": op.description,
            "progress_start": round(start, 4),
            "progress_end": round(end, 4),
        })
        cumulative += weight

    return APIResponse(data=ops_data)
