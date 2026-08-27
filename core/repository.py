"""
core/repository.py
═══════════════════════════════════════════════════════════
数据访问层 — 高频数据库读写操作封装。

所有方法接收 AsyncSession 作为参数，由调用方管理 session 生命周期。
方法内部负责事务提交与异常回滚。
"""

import uuid
import logging

from sqlalchemy import select, update, insert, delete, func, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.models import (
    Video, Scene, VideoStatus, FrameEmbedding, Chunk, FrameDetection, Track,
    VideoGroup, TaskLog,
)
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
        group_id=video_dto.group_id,
        source_owned=video_dto.source_owned,
        external_file_id=video_dto.external_file_id,
    )
    session.add(video)
    try:
        await session.commit()
        await session.refresh(video)
        logger.info("[Repo] Video created: %s", video.id)
        # 任务日志首行：任务生命周期起点（上传/平台注册/重解析等一切创建入口统一走这）
        await append_task_log(session, video.id, "任务已创建（待配置参数）")
        return video
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to create video")
        raise


# ──────────────────────────────────────────────────────────
# 任务日志（v0.34）
# ──────────────────────────────────────────────────────────

async def append_task_log(
    session: AsyncSession,
    task_id: uuid.UUID | str,
    message: str,
    level: str = "info",
) -> None:
    """追加任务日志行（task_id = 版本行 videos.id）。供上传/参数/管道/重试全链路复用。

    注意：本文件后段曾重复定义同名函数（后者覆盖前者）——已合并为单一实现，
    批量写（traceback 等）走 append_task_logs。
    """
    await append_task_logs(session, task_id, [message], level=level)


# ──────────────────────────────────────────────────────────
# 查询
# ──────────────────────────────────────────────────────────

async def list_videos(
    session: AsyncSession,
    limit: int = 100,
    offset: int = 0,
) -> list[Video]:
    """查询视频列表，按创建时间降序排列。

    v0.34：只返回「根文件」（独立视频 file_id NULL，或某文件链的最小版本行），
    版本行不重复出现在文件列表（避免多版本刷屏）。
    """
    from sqlalchemy.orm import aliased
    Video2 = aliased(Video)
    root_cond = (
        (Video.file_id.is_(None))
        | (
            Video.version_no
            == select(func.min(Video2.version_no))
            .where(Video2.file_id == Video.file_id)
            .scalar_subquery()
        )
    )
    stmt = (
        select(Video)
        .where(root_cond)
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


async def get_video_by_external_file_id(
    session: AsyncSession,
    file_id: int,
) -> Video | None:
    """按云智平台文件库资源 ID 查找视频（平台 id 一对一；防御性取最新一条）。

    供前端 Bridge connect() 携带 context.resource.id 时自动跳转到对应视频。
    """
    stmt = (
        select(Video)
        .where(Video.external_file_id == file_id)
        .order_by(Video.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


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

async def delete_video(
    session: AsyncSession,
    video: Video,
    storage_manager=None,
) -> int:
    """删除视频记录并清理磁盘产物，返回释放字节数。

    - DB: 批量 DELETE videos 行，子表（scenes/transcript/embeddings/detections/...）
      由 DB 级 ON DELETE CASCADE 级联清除 —— 避免 ORM cascade 把 10 万+ 子行
      全量 load 进内存再逐条删。
    - 空组: 同事务内统计组内剩余视频，为 0 则删除 group 行（闭合并发删除竞态）。
    - 磁盘: 删除 commit 后调用 storage_manager.remove_video_artifacts，
      按 videos 表剩余引用判定清理原始/remux/proxy 文件 + 缩略图/音频/chunk 目录。
      文件清理非致命（DB 已删，即使磁盘删除失败也返回成功）。
    """
    # delete 前捕获路径（expire_on_commit=False，delete 后实例不可再访问）
    video_id = video.id
    file_path = video.file_path
    remuxed_path = video.remuxed_path
    proxy_path = video.proxy_path
    source_owned = getattr(video, "source_owned", True)
    group_id = video.group_id

    try:
        # task_logs 无 FK（bootstrap 手建表），CASCADE 级联不到 —— 不清则孤儿日志
        # 永久残留（v0.34 起删除视频前显式清理）
        await session.execute(delete(TaskLog).where(TaskLog.task_id == video_id))
        await session.execute(delete(Video).where(Video.id == video_id))

        await session.commit()
        logger.info("[Repo] Video deleted: %s", video_id)
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to delete video %s", video_id)
        raise

    freed = 0
    if storage_manager is not None:
        freed = await storage_manager.remove_video_artifacts(
            session, video_id, file_path, remuxed_path, proxy_path,
            source_owned=source_owned,
        )
    return freed


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
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(Scene.__table__).values(scene_rows).on_conflict_do_nothing(
            index_elements=["video_id", "scene_index"],
        )
        await session.execute(stmt)
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


async def bulk_update_scenes_captions(
    session: AsyncSession,
    video_id: uuid.UUID,
    scenes_list: list[dict],
) -> None:
    """批量更新已有场景的 caption 等文本字段（增量摘要用）。

    scenes_list 每项: {scene_index, caption, prev_caption, keyframe_path, text_embedding}。
    按 (video_id, scene_index) 匹配，不新增行。方法内 commit。
    """
    if not scenes_list:
        logger.warning("[Repo] Empty scenes_list for video %s, skipping", video_id)
        return

    try:
        stmt = (
            update(Scene.__table__)
            .where(Scene.video_id == video_id)
            .where(Scene.scene_index == bindparam("_scene_index"))
            .values(
                caption=bindparam("caption"),
                prev_caption=bindparam("prev_caption"),
                keyframe_path=bindparam("keyframe_path"),
                text_embedding=bindparam("text_embedding"),
            )
        )
        rows = [
            {
                "_scene_index": s.get("scene_index"),
                "caption": s.get("caption"),
                "prev_caption": s.get("prev_caption"),
                "keyframe_path": s.get("keyframe_path"),
                "text_embedding": s.get("text_embedding"),
            }
            for s in scenes_list
        ]
        await session.execute(stmt, rows)
        await session.commit()
        logger.info("[Repo] Bulk updated %d scene captions for video %s", len(rows), video_id)
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk update scene captions for video %s", video_id)
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
                display_seq=r.get("display_seq"),
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
) -> dict[str, int]:
    """批量写入人脸身份聚类结果 — FaceRunner 产出。

    Returns:
        {identity_label: db_id} 映射，用于 face_detections 的 identity_id 回填。
    """
    if not rows:
        return {}
    try:
        from core.models import FaceIdentity
        objs = [
            FaceIdentity(
                video_id=r["video_id"],
                identity_label=r["identity_label"],
                face_count=r["face_count"],
                first_seen=r["first_seen"],
                last_seen=r["last_seen"],
                avg_quality=r.get("avg_quality", 0.0),
                face_embedding=r.get("face_embedding"),
                best_face_embedding=r.get("best_face_embedding"),
                best_track_id=r.get("best_track_id"),
                best_face_timestamp=r.get("best_face_timestamp"),
                best_face_bbox=r.get("best_face_bbox"),
                best_face_path=r.get("best_face_path"),
            )
            for r in rows
        ]
        session.add_all(objs)
        await session.flush()  # 获取 DB 自增 ID（不提交事务）
        label_to_id = {obj.identity_label: obj.id for obj in objs}
        logger.info("[Repo] Bulk inserted %d face identities", len(rows))
        return label_to_id
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


async def bulk_insert_ocr_detections(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入 OCR 画面文字识别结果 — OcrRunner 产出。"""
    if not rows:
        return
    try:
        from core.models import OCRDetection
        from sqlalchemy import insert
        stmt = insert(OCRDetection.__table__)
        await session.execute(stmt, rows)
        await session.commit()
        logger.info("[Repo] Bulk inserted %d OCR detections", len(rows))
    except Exception:
        await session.rollback()
        logger.exception("[Repo] Failed to bulk insert OCR detections")
        raise


# ═══════════════════════════════════════════════════════════
# 文件库 / 多版本（v0.34）
# ═══════════════════════════════════════════════════════════

async def list_file_roots(session: AsyncSession) -> list[dict]:
    """文件库列表：每个文件一行（根行全部字段 + current_status/progress/summary 取当前版本）。

    版本化文件（file_id 非空）取该 file_id 分组中 version_no 最小（根）行；
    独立文件（file_id NULL）自身即根。当前版本 = 最新 completed，否则最新 version_no。
    """
    result = await session.execute(text("""
        WITH ranked AS (
            SELECT v.*,
                   LOWER(v.status::text) AS status_lower,
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(v.file_id, v.id)
                       ORDER BY v.version_no NULLS FIRST, v.created_at
                   ) AS rn,
                   -- 当前状态优先级：处理中 > 已完成 > 待参数 > 失败（活跃状态优先；
                   --   待参数不覆盖已完成——老版本已完成、新版本刚建 pending ≠ 整个文件待参数）
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(v.file_id, v.id)
                       ORDER BY (v.status::text = 'processing') DESC,
                                (v.status::text = 'completed') DESC,
                                (v.status::text = 'pending') DESC,
                                v.version_no DESC NULLS LAST
                   ) AS cur_rn
            FROM videos v
        ),
        -- 每文件版本数（在 CTE 内算，避免外层 WHERE rn=1 把窗口作用域压成单行）
        with_cnt AS (
            SELECT COALESCE(file_id, id) AS fkey, COUNT(*) AS versions_count
            FROM videos
            GROUP BY COALESCE(file_id, id)
        ),
        -- 当前版本行（completed 优先，否则最新 version_no）
        current_row AS (
            SELECT r2.id, COALESCE(r2.file_id, r2.id) AS fkey,
                   r2.status_lower AS cur_status,
                   r2.progress AS cur_progress, r2.summary AS cur_summary, r2.version_no AS cur_vno
            FROM ranked r2
            WHERE r2.cur_rn = 1
        )
        SELECT r.*,
               cr.cur_status AS current_status,
               cr.cur_progress AS current_progress,
               cr.cur_summary AS current_summary,
               cr.cur_vno AS current_version_no,
               wc.versions_count
        FROM ranked r
        LEFT JOIN with_cnt wc ON wc.fkey = COALESCE(r.file_id, r.id)
        LEFT JOIN current_row cr ON cr.fkey = COALESCE(r.file_id, r.id)
        WHERE r.rn = 1
        ORDER BY r.created_at DESC
    """))
    return [dict(row) for row in result.mappings()]


async def list_file_versions(session: AsyncSession, file_id: uuid.UUID) -> list[Video]:
    """某文件（file_id）的全部版本行，按 version_no 升序。"""
    result = await session.execute(
        select(Video)
        .where(Video.file_id == file_id)
        .order_by(Video.version_no.asc())
    )
    return list(result.scalars().all())


async def current_version_for_file(session: AsyncSession, file_id: uuid.UUID) -> Video | None:
    """文件的当前版本：最新 completed，否则最新 version_no。"""
    result = await session.execute(
        select(Video)
        .where(Video.file_id == file_id, Video.status == VideoStatus.COMPLETED)
        .order_by(Video.version_no.desc())
        .limit(1)
    )
    v = result.scalar_one_or_none()
    if v is not None:
        return v
    result = await session.execute(
        select(Video)
        .where(Video.file_id == file_id)
        .order_by(Video.version_no.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def resolve_file_id(video: Video) -> uuid.UUID:
    """解析一个 video 行所属的逻辑文件 ID：file_id 非空用它，否则自身（独立文件）。"""
    return video.file_id or video.id


async def append_task_logs(
    session: AsyncSession,
    task_id: uuid.UUID,
    entries: "list[str] | list[tuple[str, str]]",
    level: str = "info",
) -> None:
    """批量追加任务日志行：一次 SELECT max(seq) + 一次 commit。

    entries 为 str（统一用 level）或 (message, level) 二元组。此前失败 traceback
    逐行 append_task_log → 每行一个往返事务（十几行 = 十几次提交），合并后单次落库。
    """
    from core.models import TaskLog
    if not entries:
        return
    last = await session.execute(
        select(func.coalesce(func.max(TaskLog.seq), 0))
        .where(TaskLog.task_id == task_id)
    )
    seq = int(last.scalar() or 0)
    for entry in entries:
        msg, lv = entry if isinstance(entry, tuple) else (entry, level)
        seq += 1
        session.add(TaskLog(task_id=task_id, seq=seq, level=lv, message=msg))
    await session.commit()


# 任务日志保留策略（天）：超过该时长的日志行随 maintenance/sweep 清理
TASK_LOG_RETENTION_DAYS = 90


async def cleanup_orphan_task_logs(session: AsyncSession, dry_run: bool = True) -> int:
    """清扫孤儿任务日志：task_id 不在任何 videos 行上（历史删除遗留 —— task_logs
    无 FK，v0.6 之前 delete_video 不清日志）。返回行数；dry_run=True 只统计。"""
    from core.models import TaskLog
    cond = ~TaskLog.task_id.in_(select(Video.id))
    if dry_run:
        res = await session.execute(select(func.count()).select_from(TaskLog).where(cond))
        return int(res.scalar() or 0)
    res = await session.execute(delete(TaskLog).where(cond))
    await session.commit()
    return int(res.rowcount or 0)


async def prune_old_task_logs(
    session: AsyncSession,
    days: int = TASK_LOG_RETENTION_DAYS,
    dry_run: bool = True,
) -> int:
    """保留策略清理：删除 created_at 早于 days 天的日志行（默认 90 天）。
    重解析会重新追加新日志，历史行清掉不影响现有视频。返回行数；dry_run 只统计。"""
    from core.models import TaskLog
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=int(days))
    if dry_run:
        res = await session.execute(
            select(func.count()).select_from(TaskLog).where(TaskLog.created_at < cutoff)
        )
        return int(res.scalar() or 0)
    res = await session.execute(delete(TaskLog).where(TaskLog.created_at < cutoff))
    await session.commit()
    return int(res.rowcount or 0)

