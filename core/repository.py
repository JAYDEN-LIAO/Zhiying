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

from core.models import Video, Scene, VideoStatus, FrameEmbedding, Chunk, FrameDetection, Track
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
        content_type=video_dto.content_type,
        language=video_dto.language,
        audio_enabled=video_dto.audio_enabled,
        vision_enabled=video_dto.vision_enabled,
        ocr_enabled=video_dto.ocr_enabled,
        grounding_enabled=video_dto.grounding_enabled,
        caption_enabled=video_dto.caption_enabled,
        detection_enabled=video_dto.detection_enabled,
        detection_classes=video_dto.detection_classes,
        face_enabled=video_dto.face_enabled,
        plate_enabled=video_dto.plate_enabled,
        summary_enabled=video_dto.summary_enabled,
        summary_mode=video_dto.summary_mode,
        search_index_enabled=video_dto.search_index_enabled,
        sample_fps=video_dto.sample_fps,
        segment_threshold=video_dto.segment_threshold,
        caption_with_context=video_dto.caption_with_context,
        summary_detail=video_dto.summary_detail,
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

async def list_videos(
    session: AsyncSession,
    limit: int = 100,
    offset: int = 0,
) -> list[Video]:
    """查询视频列表，按创建时间降序排列。"""
    stmt = (
        select(Video)
        .order_by(Video.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


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
    summary: dict | None,
) -> None:
    """将 Pipeline 输出的摘要写入视频记录。"""
    values: dict = {}
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
# 删除
# ──────────────────────────────────────────────────────────

async def delete_video(session: AsyncSession, video_id: uuid.UUID) -> bool:
    """删除视频记录（scenes 和 transcript 通过 CASCADE 自动清除）。"""
    result = await session.execute(
        select(Video).where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if video is None:
        return False
    await session.delete(video)
    try:
        await session.commit()
        logger.info("[Repo] Video deleted: %s", video_id)
        return True
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to delete video %s", video_id)
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


# ═══════════════════════════════════════════════════════════
# 逐帧向量 & chunk 向量写入
# ═══════════════════════════════════════════════════════════

async def bulk_insert_frames(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入 frame_embeddings。"""
    if not rows:
        return
    try:
        stmt = insert(FrameEmbedding.__table__)
        await session.execute(stmt, rows)
        await session.commit()
        logger.info("[Repo] Bulk inserted %d frame embeddings", len(rows))
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk insert frame embeddings")
        raise


async def bulk_insert_chunks(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入 chunks。"""
    if not rows:
        return
    try:
        stmt = insert(Chunk.__table__)
        await session.execute(stmt, rows)
        await session.commit()
        logger.info("[Repo] Bulk inserted %d chunk embeddings", len(rows))
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk insert chunk embeddings")
        raise


# ═══════════════════════════════════════════════════════════
# 检测与追踪写入
# ═══════════════════════════════════════════════════════════

async def bulk_insert_frame_detections(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入逐帧检测结果。

    rows 已包含全部列 (video_id, track_id, timestamp_sec,
    class_name, confidence, bbox)。
    """
    if not rows:
        return
    try:
        stmt = insert(FrameDetection.__table__)
        await session.execute(stmt, rows)
        await session.commit()
        logger.info("[Repo] Bulk inserted %d frame detections", len(rows))
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk insert frame detections")
        raise


async def bulk_insert_tracks(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入追踪轨迹。

    使用 ON CONFLICT DO NOTHING 防止增量重跑时产生重复记录。
    """
    if not rows:
        return
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(Track.__table__).values(rows).on_conflict_do_nothing(
            constraint="uq_track_video"
        )
        await session.execute(stmt)
        await session.commit()
        logger.info("[Repo] Bulk inserted %d tracks", len(rows))
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk insert tracks")
        raise


async def bulk_insert_track_embeddings(
    session: AsyncSession,
    video_id: uuid.UUID,
    rows: list[dict],
) -> None:
    """批量写入 track 嵌入向量 — track_encode runner 产出。"""
    if not rows:
        return
    try:
        from core.models import TrackEmbedding
        session.add_all([
            TrackEmbedding(
                video_id=video_id,
                track_id=r["track_id"],
                class_name=r["class_name"],
                embedding=r.get("embedding"),
                timestamp_sec=r["timestamp_sec"],
                bbox=r["bbox"],
            )
            for r in rows
        ])
        await session.commit()
        logger.info("[Repo] Bulk inserted %d track embeddings", len(rows))
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk insert track embeddings")
        raise


# ═══════════════════════════════════════════════════════════
# 人脸识别 & 车牌识别写入
# ═══════════════════════════════════════════════════════════

async def bulk_insert_face_identities(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入人脸身份聚类结果 — FaceRunner 产出。"""
    if not rows:
        return
    try:
        from core.models import FaceIdentity
        session.add_all([
            FaceIdentity(
                video_id=r["video_id"],
                identity_label=r["identity_label"],
                face_count=r["face_count"],
                first_seen=r["first_seen"],
                last_seen=r["last_seen"],
                avg_quality=r.get("avg_quality", 0.0),
                face_embedding=r.get("face_embedding"),
                best_face_timestamp=r.get("best_face_timestamp"),
                best_face_bbox=r.get("best_face_bbox"),
                best_face_path=r.get("best_face_path"),
            )
            for r in rows
        ])
        await session.commit()
        logger.info("[Repo] Bulk inserted %d face identities", len(rows))
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk insert face identities")
        raise


async def bulk_insert_face_detections(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入逐帧人脸检测结果 — FaceRunner 产出。"""
    if not rows:
        return
    try:
        from core.models import FaceDetection
        from sqlalchemy import insert
        stmt = insert(FaceDetection.__table__)
        await session.execute(stmt, rows)
        await session.commit()
        logger.info("[Repo] Bulk inserted %d face detections", len(rows))
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk insert face detections")
        raise


async def bulk_insert_plate_detections(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入车牌检测结果 — PlateRunner 产出。"""
    if not rows:
        return
    try:
        from core.models import PlateDetection
        from sqlalchemy import insert
        stmt = insert(PlateDetection.__table__)
        await session.execute(stmt, rows)
        await session.commit()
        logger.info("[Repo] Bulk inserted %d plate detections", len(rows))
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk insert plate detections")
        raise
