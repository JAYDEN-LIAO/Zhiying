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
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image

from api.deps import get_db
from api.schemas import APIResponse
from core.models import FrameDetection, Track, Video
from utils.video_util import extract_keyframe_to_memory

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{video_id}/detection/data")
async def get_detection_data(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取视频的逐帧检测框与追踪轨迹数据。

    返回格式：
    {
      "has_detection": bool,
      "tracks": [{track_id, class_name, first_seen, last_seen, frame_count}, ...],
      "detections": {
        "0.0": [{bbox, class_name, track_id}, ...],   # key = int(timestamp_sec) 字符串
        "1.0": [...],
        ...
      }
    }

    前端播放时通过 video.currentTime 取整查找，O(1) 时间。
    """
    # 1. 查询 tracks
    stmt_tracks = (
        select(Track)
        .where(Track.video_id == video_id)
        .order_by(Track.first_seen)
    )
    track_result = await db.execute(stmt_tracks)
    db_tracks = list(track_result.scalars().all())

    # 2. 查询 frame_detections（按时间戳排序）
    stmt_dets = (
        select(FrameDetection)
        .where(FrameDetection.video_id == video_id)
        .order_by(FrameDetection.timestamp_sec)
    )
    det_result = await db.execute(stmt_dets)
    db_dets = list(det_result.scalars().all())

    # 3. 无检测数据 → 返回空
    if not db_dets and not db_tracks:
        return APIResponse(data={
            "has_detection": False,
            "tracks": [],
            "detections": {},
        })

    # 4. 构建 tracks 摘要
    tracks_data = [
        {
            "track_id": t.track_id,
            "class_name": t.class_name,
            "first_seen": t.first_seen,
            "last_seen": t.last_seen,
            "frame_count": t.frame_count,
            "segments": t.segments or [{"start": t.first_seen, "end": t.last_seen}],
        }
        for t in db_tracks
    ]

    # 5. 构建按时间戳分组的 detections dict
    # key 精确到 0.1 秒（适配 10fps 检测帧率），前端通过 nearest 0.1s 查找
    detections_by_ts: dict[str, list[dict]] = {}
    for d in db_dets:
        ts_key = f"{d.timestamp_sec:.1f}"
        if ts_key not in detections_by_ts:
            detections_by_ts[ts_key] = []
        detections_by_ts[ts_key].append({
            "bbox": d.bbox,
            "class_name": d.class_name,
            "track_id": d.track_id,
        })

    return APIResponse(data={
        "has_detection": True,
        "tracks": tracks_data,
        "detections": detections_by_ts,
    })


@router.get("/{video_id}/detection/thumbnail")
async def get_detection_thumbnail(
    video_id: uuid.UUID,
    timestamp: float = Query(..., description="视频时间戳(秒)"),
    x1: float | None = Query(None), y1: float | None = Query(None),
    x2: float | None = Query(None), y2: float | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """提取指定时间点帧，返回 JPEG 缩略图。

    可选 bbox 参数（归一化 0-1）进行裁剪；不传 bbox 则返回全帧。
    始终缩放到 120px 宽，高度按比例缩放。
    """
    result = await db.execute(
        select(Video.file_path).where(Video.id == video_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")

    file_path: str = row[0]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")
    frame = await extract_keyframe_to_memory(file_path, timestamp)

    # 可选裁剪
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

    return Response(content=buf.getvalue(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})
