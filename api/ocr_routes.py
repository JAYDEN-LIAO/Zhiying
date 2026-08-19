"""
api/ocr_routes.py
═══════════════════════════════════════════════════════════
OCR 画面文字数据 API — 前端"文字"标签页获取识别清单。

导出（/ocr/export）与文字框缩略图（/ocr/thumbnail）为预留接口，后续补。
"""

import uuid
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db
from api.schemas import APIResponse
from core.models import OCRDetection

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{video_id}/ocr/data")
async def get_ocr_data(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """获取视频的画面文字识别清单（按时间戳升序）。

    返回格式：
    {
      "has_ocr": bool,
      "detections": [
        {
          "id": int, "timestamp_sec": float, "text": str,
          "bbox": {...归一化 0-1}, "confidence": float,
        },
      ]
    }
    """
    stmt = (
        select(OCRDetection)
        .where(OCRDetection.video_id == video_id)
        .order_by(OCRDetection.timestamp_sec)
    )
    result = await db.execute(stmt)
    dets = list(result.scalars().all())

    return APIResponse(data={
        "has_ocr": bool(dets),
        "detections": [
            {
                "id": d.id,
                "timestamp_sec": d.timestamp_sec,
                "text": d.text,
                "bbox": d.bbox,
                "confidence": d.confidence,
            }
            for d in dets
        ],
    })