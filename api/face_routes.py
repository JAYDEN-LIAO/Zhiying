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
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from PIL import Image

from api.deps import get_db
from api.schemas import APIResponse
from core.models import FaceIdentity, Video
from utils.video_util import extract_keyframe_to_memory

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{video_id}/face/data")
async def get_face_data(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取视频的人脸身份列表。

    v0.22 (S1): 删除 per-frame detections 字段——前端零消费（已 grep 证实），
    长视频 + 人脸开启时是与 detection 同级的大 JSON 炸弹。若未来要画人脸框，
    按 /detection/detections 的区间模式补。

    返回格式：
    {
      "has_face": bool,
      "identities": [{id, label, face_count, first_seen, last_seen,
                       avg_quality, best_thumbnail_url}, ...],
    }
    """
    # 查询身份（唯一数据源，per-identity 聚合，量级远小于 per-frame）
    stmt_ids = (
        select(FaceIdentity)
        .where(FaceIdentity.video_id == video_id)
        .order_by(FaceIdentity.first_seen)
    )
    result = await db.execute(stmt_ids)
    db_identities = list(result.scalars().all())

    if not db_identities:
        return APIResponse(data={
            "has_face": False,
            "identities": [],
            "track_to_identity": {},
        })

    # v0.30: 构建 track_id → identity_label 映射（前端 person track 条目显示身份标签，
    # 与车牌显示车牌号对称；替代无信息的 👤 emoji）
    from core.models import FaceDetection
    id_by_label = {fi.identity_label: fi.id for fi in db_identities}
    track_map: dict[int, dict] = {}
    trk_result = await db.execute(
        select(FaceDetection.track_id, FaceDetection.identity_id)
        .where(FaceDetection.video_id == video_id)
        .where(FaceDetection.identity_id.isnot(None))
    )
    for trk_id, ident_id in trk_result:
        if trk_id in track_map:
            continue  # 每 track 只记一个身份（该 track 的主身份）
        track_map[trk_id] = {"identity_id": ident_id}

    # 3. 身份 ↔ track 出现时间段（v0.6.1：人脸身份与 person track 匹配后，出现段 = 该
    #    track 的 [first_seen, last_seen]（真实标黄时长），而非人脸采样点——人脸采样稀疏，
    #    单帧会退化成点；也不用跨 track 合并（会并入无关无标黄时间）。每个匹配的 track 即一段。
    appearance_stmt = (
        select(
            FaceDetection.identity_id,
            FaceDetection.track_id,
            func.min(FaceDetection.timestamp_sec),
            func.max(FaceDetection.timestamp_sec),
        )
        .where(FaceDetection.video_id == video_id)
        .where(FaceDetection.identity_id.isnot(None))
        .group_by(FaceDetection.identity_id, FaceDetection.track_id)
    )
    app_rows = list(await db.execute(appearance_stmt))
    # 收集所有 track_id 批量查 track 真实起止（无 track 的人脸回退到采样点）
    from core.models import Track
    track_ids = {r[1] for r in app_rows if r[1] is not None}
    track_range_map: dict[int, tuple[float, float]] = {}
    if track_ids:
        trk_rows = await db.execute(
            select(Track.track_id, Track.first_seen, Track.last_seen)
            .where(Track.track_id.in_(track_ids))
        )
        for tid, fs, ls in trk_rows:
            track_range_map[tid] = (float(fs), float(ls))
    appearances_by_id: dict[int, list[dict]] = {}
    for ident_id, trk_id, det_min, det_max in app_rows:
        # 严格采用整条 track 的 [first_seen, last_seen] 作为出现段（真实标黄时长）；
        # 无 track 的人脸回退到人脸采样点。
        if trk_id is not None and trk_id in track_range_map:
            start_sec, end_sec = track_range_map[trk_id]
        else:
            start_sec, end_sec = det_min, det_max
        appearances_by_id.setdefault(ident_id, []).append({
            "track_id": trk_id,
            "start_sec": round(float(start_sec), 2),
            "end_sec": round(float(end_sec), 2),
        })
    for lst in appearances_by_id.values():
        lst.sort(key=lambda x: x["start_sec"])

    # 4. 构建身份摘要
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
            "appearances": appearances_by_id.get(fi.id, []),
        }
        for fi in db_identities
    ]

    return APIResponse(data={
        "has_face": True,
        "identities": identities_data,
        "track_to_identity": track_map,
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
