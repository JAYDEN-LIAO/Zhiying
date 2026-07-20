"""
api/detection_routes.py
═══════════════════════════════════════════════════════════
检测数据 API — 前端 canvas overlay 获取逐帧检测框 + 追踪轨迹。
"""

import uuid
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse
from core.models import FrameDetection, Track

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
