"""
api/search_routes.py
═══════════════════════════════════════════════════════════
搜索端点 — 语义搜索 + Pipeline 操作查询。
"""

import time
import uuid
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse, SemanticSearchRequest, SearchResultItem, SearchResults
from core.models import Video
from core.config_loader import load_config
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

    step = 1.0 / len(enabled) if enabled else 1.0
    ops_data: list[dict] = []
    for i, op in enumerate(enabled):
        ops_data.append({
            "name": op.name,
            "label": op.label,
            "description": op.description,
            "progress_start": round(i * step, 2),
            "progress_end": round((i + 1) * step, 2) if i < len(enabled) - 1 else 1.0,
        })

    return APIResponse(data=ops_data)
