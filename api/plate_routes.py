"""
api/plate_routes.py
═══════════════════════════════════════════════════════════
车牌识别数据 API — 前端车牌 Tab 获取检测列表 + 缩略图。
"""

import io
import os
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image

from api.deps import get_db
from api.schemas import APIResponse
from core.models import PlateDetection, Video
from utils.video_util import extract_keyframe_to_memory

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{video_id}/plate/data")
async def get_plate_data(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取视频的车牌识别结果列表。

    返回格式：
    {
      "has_plate": bool,
      "detections": [
        {
          "id": int, "track_id": int, "class_name": str,
          "timestamp_sec": float, "plate_text": str, "plate_type": str,
          "char_confidences": [float], "bbox": {...}, "confidence": float,
          "thumbnail_url": str | null,
        },
      ]
    }
    """
    stmt = (
        select(PlateDetection)
        .where(PlateDetection.video_id == video_id)
        .order_by(PlateDetection.timestamp_sec)
    )
    result = await db.execute(stmt)
    db_dets = list(result.scalars().all())

    if not db_dets:
        return APIResponse(data={
            "has_plate": False,
            "detections": [],
        })

    detections_data = [
        {
            "id": d.id,
            "track_id": d.track_id,
            "class_name": d.class_name,
            "timestamp_sec": d.timestamp_sec,
            "plate_text": d.plate_text,
            "plate_type": d.plate_type,
            "char_confidences": d.char_confidences,
            "bbox": d.bbox,
            "confidence": d.detection_confidence,
            "thumbnail_url": (
                f"/api/v1/videos/{video_id}/plate/thumbnail"
                f"?timestamp={d.timestamp_sec}"
                f"&x1={d.bbox['x1']}&y1={d.bbox['y1']}"
                f"&x2={d.bbox['x2']}&y2={d.bbox['y2']}"
            ) if d.bbox else None,
        }
        for d in db_dets
    ]

    return APIResponse(data={
        "has_plate": True,
        "detections": detections_data,
    })


@router.get("/{video_id}/plate/thumbnail")
async def get_plate_thumbnail(
    video_id: uuid.UUID,
    timestamp: float = Query(..., description="视频时间戳(秒)"),
    x1: float | None = Query(None), y1: float | None = Query(None),
    x2: float | None = Query(None), y2: float | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """提取车牌缩略图 JPEG（裁剪车牌区域）。"""
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

    # 裁剪车牌区域
    has_bbox = all(v is not None for v in [x1, y1, x2, y2])
    if has_bbox:
        h, w = frame.shape[:2]
        px1, py1 = max(0, int(x1 * w)), max(0, int(y1 * h))
        px2, py2 = min(w, int(x2 * w)), min(h, int(y2 * h))
        if px2 > px1 and py2 > py1:
            frame = frame[py1:py2, px1:px2]

    # 缩放到 300px 宽（车牌横向长条）
    img = Image.fromarray(frame)
    thumb_w = 300
    ratio = thumb_w / img.width
    thumb_h = max(1, int(img.height * ratio))
    img = img.resize((thumb_w, thumb_h), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)

    return Response(content=buf.getvalue(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})
