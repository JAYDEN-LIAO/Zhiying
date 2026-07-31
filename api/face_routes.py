"""
api/face_routes.py
═══════════════════════════════════════════════════════════
人脸识别数据 API — 前端人脸 Tab 获取身份列表 + 逐帧检测 + 缩略图。
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
from core.models import FaceIdentity, FaceDetection, Video
from utils.video_util import extract_keyframe_to_memory

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{video_id}/face/data")
async def get_face_data(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取视频的人脸身份列表和逐帧检测数据。

    返回格式：
    {
      "has_face": bool,
      "identities": [{id, label, face_count, first_seen, last_seen,
                       avg_quality, best_thumbnail_url}, ...],
      "detections": {
        "12.3": [{identity_id, track_id, bbox, quality}, ...],
        ...
      }
    }
    """
    # 1. 查询身份
    stmt_ids = (
        select(FaceIdentity)
        .where(FaceIdentity.video_id == video_id)
        .order_by(FaceIdentity.first_seen)
    )
    result = await db.execute(stmt_ids)
    db_identities = list(result.scalars().all())

    # 2. 查询逐帧检测
    stmt_dets = (
        select(FaceDetection)
        .where(FaceDetection.video_id == video_id)
        .order_by(FaceDetection.timestamp_sec)
    )
    det_result = await db.execute(stmt_dets)
    db_dets = list(det_result.scalars().all())

    if not db_identities and not db_dets:
        return APIResponse(data={
            "has_face": False,
            "identities": [],
            "detections": {},
        })

    # 3. 构建身份摘要
    identities_data = [
        {
            "id": fi.id,
            "label": fi.identity_label,
            "face_count": fi.face_count,
            "first_seen": fi.first_seen,
            "last_seen": fi.last_seen,
            "avg_quality": fi.avg_quality,
            "best_face_timestamp": fi.best_face_timestamp,
            "best_face_bbox": fi.best_face_bbox,
            "best_thumbnail_url": (
                f"/api/v1/videos/{video_id}/face/thumbnail"
                f"?identity_id={fi.id}"
            ) if fi.best_face_timestamp is not None else None,
        }
        for fi in db_identities
    ]

    # 4. 构建按时间戳分组的 detections dict（0.1s 精度）
    detections_by_ts: dict[str, list[dict]] = {}
    for d in db_dets:
        ts_key = f"{d.timestamp_sec:.1f}"
        detections_by_ts.setdefault(ts_key, []).append({
            "identity_id": d.identity_id,
            "track_id": d.track_id,
            "bbox": d.bbox,
            "quality": d.quality_score,
            "thumbnail_url": (
                f"/api/v1/videos/{video_id}/face/thumbnail"
                f"?timestamp={d.timestamp_sec}"
                f"&x1={d.bbox['x1']}&y1={d.bbox['y1']}"
                f"&x2={d.bbox['x2']}&y2={d.bbox['y2']}"
            ) if d.bbox else None,
        })

    return APIResponse(data={
        "has_face": True,
        "identities": identities_data,
        "detections": detections_by_ts,
    })


@router.get("/{video_id}/face/thumbnail")
async def get_face_thumbnail(
    video_id: uuid.UUID,
    identity_id: int | None = Query(None, description="人脸身份 ID（返回最佳帧缩略图）"),
    timestamp: float | None = Query(None, description="视频时间戳(秒)"),
    x1: float | None = Query(None), y1: float | None = Query(None),
    x2: float | None = Query(None), y2: float | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """提取人脸缩略图 JPEG。

    两种调用方式:
      - identity_id: 返回该身份的最佳帧人脸 crop
      - timestamp + bbox: 返回指定时刻+位置的人脸 crop
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

    # 通过 identity_id 查找最佳帧参数
    if identity_id is not None and timestamp is None:
        id_result = await db.execute(
            select(FaceIdentity).where(
                FaceIdentity.id == identity_id,
                FaceIdentity.video_id == video_id,
            )
        )
        identity = id_result.scalar_one_or_none()
        if identity is None or identity.best_face_timestamp is None or identity.best_face_bbox is None:
            raise HTTPException(status_code=404, detail="Face identity or best frame not found")
        timestamp = identity.best_face_timestamp
        bbox = identity.best_face_bbox
        x1, y1, x2, y2 = bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]

    if timestamp is None:
        raise HTTPException(status_code=400, detail="timestamp or identity_id required")

    frame = await extract_keyframe_to_memory(file_path, timestamp)

    # 裁剪人脸区域
    has_bbox = all(v is not None for v in [x1, y1, x2, y2])
    if has_bbox:
        h, w = frame.shape[:2]
        px1, py1 = max(0, int(x1 * w)), max(0, int(y1 * h))
        px2, py2 = min(w, int(x2 * w)), min(h, int(y2 * h))
        if px2 > px1 and py2 > py1:
            frame = frame[py1:py2, px1:px2]

    # 缩放到 200px 宽
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
