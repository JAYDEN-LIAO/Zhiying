"""
core/repository.py
═══════════════════════════════════════════════════════════
数据访问层 — 高频数据库读写操作封装。

所有方法接收 AsyncSession 作为参数，由调用方管理 session 生命周期。
方法内部负责事务提交与异常回滚。
"""

import uuid
import logging

from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import Video, Scene, VideoStatus
from core.schemas import VideoCreate

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────
# 创建
# ──────────────────────────────────────────────────────────

async def create_video(session: AsyncSession, video_dto: VideoCreate) -> Video:
    """创建视频元数据记录，初始状态为 pending。"""
    video = Video(
        file_path=video_dto.file_path,
        file_name=video_dto.file_name,
        file_size=video_dto.file_size,
        preset=video_dto.preset,
        content_type=video_dto.content_type,
        language=video_dto.language,
        audio_enabled=video_dto.audio_enabled,
        vision_enabled=video_dto.vision_enabled,
        ocr_enabled=video_dto.ocr_enabled,
        grounding_enabled=video_dto.grounding_enabled,
        caption_enabled=video_dto.caption_enabled,
        summary_enabled=video_dto.summary_enabled,
    )
    session.add(video)
    try:
        await session.commit()
        await session.refresh(video)
        logger.info("[Repo] Video created: %s", video.id)
        return video
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to create video")
        raise


# ──────────────────────────────────────────────────────────
# 查询
# ──────────────────────────────────────────────────────────

async def get_video_with_relations(
    session: AsyncSession,
    video_id: uuid.UUID,
) -> Video | None:
    """查询视频及其关联的 scenes 和 transcript（selectinload 预加载防 N+1）。"""
    stmt = (
        select(Video)
        .where(Video.id == video_id)
        .options(
            selectinload(Video.scenes),
            selectinload(Video.transcript),
        )
    )
    result = await session.execute(stmt)
    return result.unique().scalar_one_or_none()


# ──────────────────────────────────────────────────────────
# 更新
# ──────────────────────────────────────────────────────────

async def update_video_progress(
    session: AsyncSession,
    video_id: uuid.UUID,
    status: VideoStatus,
    progress: float,
    error_message: str | None = None,
) -> Video | None:
    """原子化更新视频处理状态、进度与错误信息。"""
    try:
        await session.execute(
            update(Video)
            .where(Video.id == video_id)
            .values(
                status=status,
                progress=progress,
                error_message=error_message,
            )
        )
        await session.commit()

        # 返回最新状态
        result = await session.execute(
            select(Video).where(Video.id == video_id)
        )
        video = result.scalar_one_or_none()
        if video is None:
            logger.warning(
                "[Repo] Video not found after progress update: %s", video_id
            )
        return video
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to update progress for video %s", video_id)
        raise


async def save_video_artifacts(
    session: AsyncSession,
    video_id: uuid.UUID,
    qc_result: dict | None,
    summary: dict | None,
) -> None:
    """将 Pipeline 输出的 QC 结果和摘要写入视频记录。"""
    values: dict = {}
    if qc_result is not None:
        values["qc_result"] = qc_result
    if summary is not None:
        values["summary"] = summary

    if not values:
        logger.info("[Repo] No artifacts to save for video %s", video_id)
        return

    try:
        await session.execute(
            update(Video).where(Video.id == video_id).values(**values)
        )
        await session.commit()
        logger.info("[Repo] Artifacts saved for video %s", video_id)
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to save artifacts for video %s", video_id)
        raise


# ──────────────────────────────────────────────────────────
# 批量写入
# ──────────────────────────────────────────────────────────

async def bulk_insert_scenes(
    session: AsyncSession,
    video_id: uuid.UUID,
    scenes_list: list[dict],
) -> None:
    """批量插入场景记录。

    使用 SQLAlchemy Core insert() 实现单条多行 INSERT，
    自动为每行绑定 video_id。30-100 条场景的批量写入性能远优于逐条 add()。
    """
    if not scenes_list:
        logger.warning("[Repo] Empty scenes_list for video %s, skipping", video_id)
        return

    scene_rows = [
        {
            "video_id": video_id,
            "scene_index": s.get("scene_index"),
            "start_sec": s.get("start_sec"),
            "end_sec": s.get("end_sec"),
            "keyframe_path": s.get("keyframe_path"),
            "embedding": s.get("embedding"),
            "ocr_text": s.get("ocr_text"),
            "aligned_transcript": s.get("aligned_transcript"),
            "caption": s.get("caption"),
            "prev_caption": s.get("prev_caption"),
            "entities": s.get("entities"),
        }
        for s in scenes_list
    ]

    try:
        stmt = insert(Scene.__table__)
        await session.execute(stmt, scene_rows)
        await session.commit()
        logger.info(
            "[Repo] Bulk inserted %d scenes for video %s",
            len(scene_rows), video_id,
        )
    except Exception:
        await session.rollback()
        logger.exception(
            "[Repo] Failed to bulk insert scenes for video %s", video_id
        )
        raise
