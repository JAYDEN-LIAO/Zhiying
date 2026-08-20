"""快速缩略图提取工具 — 上传时调用，不依赖 pipeline。

使用 FFmpeg 从视频第一秒提取一帧作为缩略图。
"""

import asyncio
import logging
import os
import uuid

from pathlib import Path

logger = logging.getLogger(__name__)


async def extract_thumbnail_on_upload(
    video_id: uuid.UUID,
    video_path: str,
    config: dict,
) -> str | None:
    """上传时快速提取缩略图（异步，不阻塞上传流程）。

    Args:
        video_id: 视频 ID
        video_path: 视频文件路径
        config: 配置字典

    Returns:
        缩略图路径（成功）或 None（失败）
    """
    try:
        artifact_dir = config.get("storage", {}).get("artifact_dir", "data/artifacts")
        thumb_dir = os.path.join(artifact_dir, "thumbnails", str(video_id))
        os.makedirs(thumb_dir, exist_ok=True)
        thumb_path = os.path.join(thumb_dir, "scene_0000.jpg")

        # 使用 FFmpeg 从视频第一秒提取一帧
        cmd = [
            "ffmpeg",
            "-ss", "1",  # 跳到第 1 秒
            "-i", video_path,
            "-vframes", "1",  # 只取 1 帧
            "-q:v", "2",  # JPEG 质量
            "-y",  # 覆盖已有文件
            thumb_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning("[Thumbnail] FFmpeg failed for video %s: %s", video_id, stderr.decode()[:200])
            return None

        if not os.path.exists(thumb_path):
            logger.warning("[Thumbnail] Thumbnail not created for video %s", video_id)
            return None

        logger.info("[Thumbnail] Extracted thumbnail for video %s: %s", video_id, thumb_path)
        return thumb_path

    except Exception as e:
        logger.warning("[Thumbnail] Failed to extract thumbnail for video %s: %s", video_id, e)
        return None


async def update_video_thumbnail_path(
    db_session_factory,
    video_id: uuid.UUID,
    thumb_path: str,
) -> None:
    """更新视频的缩略图路径到数据库（scenes 表）。

    使用 upsert（ON CONFLICT DO UPDATE）：pipeline 先插入 scene_index=0 时不会冲突，
    仅更新 keyframe_path。
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from core.models import Scene
    from datetime import datetime, timezone

    async with db_session_factory() as session:
        await session.execute(
            pg_insert(Scene.__table__).values(
                video_id=video_id,
                scene_index=0,
                start_sec=0.0,
                end_sec=1.0,
                keyframe_path=thumb_path,
                created_at=datetime.now(timezone.utc),
            ).on_conflict_do_update(
                index_elements=["video_id", "scene_index"],
                set_={"keyframe_path": thumb_path},
            )
        )
        await session.commit()
        logger.info("[Thumbnail] Updated video %s thumbnail path in DB (upsert)", video_id)
