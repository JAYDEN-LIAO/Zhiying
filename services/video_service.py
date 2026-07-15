"""
services/video_service.py
═══════════════════════════════════════════════════════════
视频业务逻辑层 — 处理流程编排。

VideoService 作为 Pipeline 的调用方，负责:
  1. create_and_process — 创建记录 + 触发后台处理
  2. process_video — 后台任务：加载 Video → 实例化 PipelineEngine → 执行
"""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Video
from core.schemas import VideoCreate, VideoResponse
from core.repository import create_video
from core.status_tracker import StatusTracker
from pipeline.engine import PipelineEngine

logger = logging.getLogger(__name__)


class VideoService:
    """视频业务服务 — 创建记录与 Pipeline 后台调度。"""

    def __init__(
        self,
        config: dict,
        db_session_factory: async_sessionmaker[AsyncSession],
        embedder=None,
    ):
        self.config = config
        self.db_session_factory = db_session_factory
        self.embedder = embedder

    async def create_and_process(
        self,
        dto: VideoCreate,
    ) -> VideoResponse:
        """创建视频记录并返回（不等待 Pipeline 完成）。

        调用方应将 process_video 通过 BackgroundTasks 异步触发。
        """
        async with self.db_session_factory() as session:
            video = await create_video(session, dto)
        return VideoResponse.model_validate(video)

    async def incremental_process(self, video_id: uuid.UUID, added_modalities: set[str]) -> None:
        """增量后台任务：对已完成的视频补跑指定功能阶段。

        Args:
            video_id: 视频 ID
            added_modalities: {'summary'} / {'search_index'} / 两者都有
        """
        logger.info("[VideoService] Incremental %s for video %s", added_modalities, video_id)

        async with self.db_session_factory() as session:
            result = await session.execute(
                select(Video).where(Video.id == video_id)
            )
            video = result.scalar_one_or_none()

        if video is None:
            logger.error("[VideoService] Video %s not found, aborting", video_id)
            return

        try:
            engine = PipelineEngine(
                config=self.config,
                db_session_factory=self.db_session_factory,
                video=video,
                shared_embedder=self.embedder,
            )
            await engine.run_incremental(added_modalities)
        except Exception as e:
            logger.exception(
                "[VideoService] Incremental pipeline crashed for video %s: %s", video_id, e,
            )
            tracker = StatusTracker(
                video_id=str(video_id),
                db_session_factory=self.db_session_factory,
            )
            await tracker.mark_failed(f"Incremental crashed: {e}")

    async def process_video(self, video_id: uuid.UUID) -> None:
        """后台任务入口：加载视频 → Pipeline → 完成/失败。

        由 FastAPI BackgroundTasks.add_task 调用。
        """
        logger.info("[VideoService] Starting pipeline for video %s", video_id)

        # 加载 Video ORM 记录
        async with self.db_session_factory() as session:
            result = await session.execute(
                select(Video).where(Video.id == video_id)
            )
            video = result.scalar_one_or_none()

        if video is None:
            logger.error("[VideoService] Video %s not found, aborting", video_id)
            return

        # 实例化并运行 Pipeline
        try:
            engine = PipelineEngine(
                config=self.config,
                db_session_factory=self.db_session_factory,
                video=video,
                shared_embedder=self.embedder,
            )
            await engine.run()
        except Exception as e:
            logger.exception(
                "[VideoService] Pipeline crashed for video %s: %s", video_id, e,
            )
            # 兜底：标记为失败
            tracker = StatusTracker(
                video_id=str(video_id),
                db_session_factory=self.db_session_factory,
            )
            await tracker.mark_failed(f"Pipeline crashed: {e}")
