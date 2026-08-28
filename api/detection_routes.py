"""
api/detection_routes.py
═══════════════════════════════════════════════════════════
检测数据 API — 前端 canvas overlay 获取逐帧检测框 + 追踪轨迹 + 缩略图。
"""

import io
import os
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image

from api.deps import get_db
from api.schemas import APIResponse
from core.models import FrameDetection, Track
from core.repository import get_video_source_path
from utils.video_util import extract_keyframe_to_memory

logger = logging.getLogger(__name__)

router = APIRouter()


# ── v0.22 (S0/A2): 每 track 最大面积 bbox 惰性计算 ──
# 替代前端 DetectionPanel.getThumbBbox 的 O(tracks×detections) 全表扫描。
# frame_detections 已是缝合后最终 track_id（track_encode 已用 merge_map 重映射），
# 准则=最大面积（与 getThumbBbox 一致）→ 缩略图内容零变化。

_BEST_FRAME_SQL = text("""
    SELECT DISTINCT ON (track_id) track_id, timestamp_sec, bbox
    FROM frame_detections
    WHERE video_id = :video_id
    ORDER BY track_id,
        ((bbox->>'x2')::float - (bbox->>'x1')::float)
        * ((bbox->>'y2')::float - (bbox->>'y1')::float) DESC
""")

# 按 video_id 的内存缓存。frame_detections 管道完成后不可变（track 重缝合需新建记录），
# 无失效窗口；删除视频后对应 key 不再被访问（端点先查数据）。LRU 上限防泄漏。
_BEST_CACHE: dict[uuid.UUID, dict[int, dict]] = {}
_BEST_CACHE_MAX = 64

# /detection/detections 单次窗口上限（秒）——Overlay 只消费当前 ±30s，300s 足够覆盖大 seek 跳转
MAX_WINDOW_SEC = 300.0


async def _best_frames(db: AsyncSession, video_id: uuid.UUID) -> dict[int, dict]:
    """每 track 面积最大的 bbox 帧。

    Returns: {track_id: {"timestamp_sec": float, "bbox": {x1,y1,x2,y2}}}
    """
    cached = _BEST_CACHE.get(video_id)
    if cached is not None:
        return cached
    result = await db.execute(_BEST_FRAME_SQL, {"video_id": str(video_id)})
    best = {
        row.track_id: {"timestamp_sec": float(row.timestamp_sec), "bbox": row.bbox}
        for row in result.all()
    }
    if len(_BEST_CACHE) >= _BEST_CACHE_MAX:
        _BEST_CACHE.pop(next(iter(_BEST_CACHE)))
    _BEST_CACHE[video_id] = best
    return best


def _thumb_url(
    video_id: uuid.UUID, track_id: int, ts: float,
    bbox: dict | None,
) -> str | None:
    """缩略图 URL（带 track_id，供磁盘缓存文件名用）。bbox 缺失返回 None（前端落色点）。"""
    if not bbox:
        return None
    return (
        f"/api/v1/videos/{video_id}/detection/thumbnail"
        f"?track_id={track_id}&timestamp={ts}"
        f"&x1={bbox['x1']}&y1={bbox['y1']}&x2={bbox['x2']}&y2={bbox['y2']}"
    )


def _build_tracks_data(
    video_id: uuid.UUID,
    db_tracks: list[Track],
    best: dict[int, dict],
) -> list[dict]:
    """构建 track 摘要（含后端预计算缩略图信息）。/detection/tracks 与旧 /detection/data 共用。"""
    data = []
    for t in db_tracks:
        b = best.get(t.track_id)
        ts = b["timestamp_sec"] if b else t.first_seen
        bbox = b["bbox"] if b else None
        data.append({
            "track_id": t.track_id,
            "class_name": t.class_name,
            "display_seq": t.display_seq,
            "first_seen": t.first_seen,
            "last_seen": t.last_seen,
            "frame_count": t.frame_count,
            "segments": t.segments or [{"start": t.first_seen, "end": t.last_seen}],
            "best_thumb_ts": ts,
            "best_bbox": bbox,
            "thumbnail_url": _thumb_url(video_id, t.track_id, ts, bbox),
        })
    return data


# ═══════════════════════════════════════════════════════════
# v0.22 (S1/A1): 接口拆分 — 检测栏/时间轴走轻量 tracks，Overlay 走时间窗 detections
# v0.22 (S2): 旧 /detection/data 已删除（前端全量迁移至 tracks/range，零消费者）
# ═══════════════════════════════════════════════════════════


@router.get("/{video_id}/detection/tracks")
async def get_detection_tracks(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """轻量 track 摘要（含预计算缩略图信息），检测栏 + 时间轴数据源。

    几千条 track ≈ 几十 KB；不携带逐帧 detections（Overlay 走 /detection/detections）。
    """
    result = await db.execute(
        select(Track)
        .where(Track.video_id == video_id)
        .order_by(Track.first_seen)
    )
    db_tracks = list(result.scalars().all())
    if not db_tracks:
        return APIResponse(data={"has_detection": False, "tracks": []})

    best = await _best_frames(db, video_id)
    return APIResponse(data={
        "has_detection": True,
        "tracks": _build_tracks_data(video_id, db_tracks, best),
    })


@router.get("/{video_id}/detection/detections")
async def get_detection_detections(
    video_id: uuid.UUID,
    start_sec: float = Query(0.0, description="窗口起始(秒)"),
    end_sec: float = Query(..., description="窗口结束(秒)"),
    db: AsyncSession = Depends(get_db),
):
    """时间窗内的逐帧检测框，Overlay 用（命中 ix_frame_detections_video_ts 索引）。

    窗宽上限 MAX_WINDOW_SEC；返回 {ts: [bbox/class/track]} 字典（0.1s 精度，对齐 10fps）。
    """
    if end_sec <= start_sec:
        raise HTTPException(status_code=400, detail="end_sec must be greater than start_sec")
    if end_sec - start_sec > MAX_WINDOW_SEC:
        raise HTTPException(
            status_code=400,
            detail=f"window too large (max {MAX_WINDOW_SEC:.0f}s)",
        )

    result = await db.execute(
        select(FrameDetection)
        .where(
            FrameDetection.video_id == video_id,
            FrameDetection.timestamp_sec >= start_sec,
            FrameDetection.timestamp_sec <= end_sec,
        )
        .order_by(FrameDetection.timestamp_sec)
    )
    db_dets = list(result.scalars().all())

    detections_by_ts: dict[str, list[dict]] = {}
    for d in db_dets:
        ts_key = f"{d.timestamp_sec:.1f}"
        detections_by_ts.setdefault(ts_key, []).append({
            "bbox": d.bbox,
            "class_name": d.class_name,
            "track_id": d.track_id,
            "display_seq": d.display_seq,
        })

    return APIResponse(data={
        "has_detection": bool(detections_by_ts),
        "start_sec": start_sec,
        "end_sec": end_sec,
        "detections": detections_by_ts,
    })


@router.get("/{video_id}/detection/thumbnail")
async def get_detection_thumbnail(
    video_id: uuid.UUID,
    request: Request,
    timestamp: float = Query(..., description="视频时间戳(秒)"),
    track_id: int | None = Query(None, description="track 缩略图磁盘缓存文件名用"),
    x1: float | None = Query(None), y1: float | None = Query(None),
    x2: float | None = Query(None), y2: float | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """提取指定时间点帧，返回 JPEG 缩略图。

    可选 bbox 参数（归一化 0-1）进行裁剪；不传 bbox 则返回全帧。
    始终缩放到 200px 宽，高度按比例缩放。

    v0.22 (S1/A3): 读盘优先 —— 命中 thumbnails/{video_id}/track_{track_id}.jpg 直接返回；
    miss 才 ffmpeg 抽帧 + 精确 bbox 裁剪，生成后写盘供下次（惰性落盘，best-effort）。
    """
    # ── 读盘优先（磁盘缓存命中）──
    storage_manager = getattr(request.app.state, "storage_manager", None)
    thumb_path: str | None = None
    if track_id is not None and storage_manager is not None:
        thumb_path = os.path.join(
            storage_manager.thumbnail_dir(video_id), f"track_{track_id}.jpg"
        )
        if os.path.exists(thumb_path):
            return FileResponse(
                thumb_path, media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=86400"},
            )

    # ── miss: ffmpeg 抽帧（原逻辑，行为一致）──
    # 必须用管道实际处理的文件（remuxed 优先，与检测时间戳同时间轴）：
    # 否则 remux 重封装改变 start_time 时，-ss 在原始文件上钳到开头/错帧 → 缩略图抽到错误画面。
    file_path = await get_video_source_path(db, video_id)
    if file_path is None:
        raise HTTPException(status_code=404, detail="Video not found")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")
    frame = await extract_keyframe_to_memory(file_path, timestamp)

    # 可选裁剪（精确 bbox，与前端历史行为一致）
    has_bbox = (x1 is not None and y1 is not None and x2 is not None and y2 is not None)
    if has_bbox:
        h, w = frame.shape[:2]
        px1, py1 = max(0, int(x1 * w)), max(0, int(y1 * h))
        px2, py2 = min(w, int(x2 * w)), min(h, int(y2 * h))
        if px2 > px1 and py2 > py1:
            frame = frame[py1:py2, px1:px2]

    # 缩放到 200px 宽（原 120px，增大后支持前端 hover 大图预览）
    img = Image.fromarray(frame)
    thumb_w = 200
    ratio = thumb_w / img.width
    thumb_h = max(1, int(img.height * ratio))
    img = img.resize((thumb_w, thumb_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)

    # ── 惰性落盘（best-effort，失败仍返回图像，下次再补）──
    if thumb_path is not None:
        try:
            os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
            img.save(thumb_path, format="JPEG", quality=85)
        except OSError as e:
            logger.warning("[DetectionThumb] 落盘失败 %s: %s", thumb_path, e)

    return Response(content=buf.getvalue(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})
