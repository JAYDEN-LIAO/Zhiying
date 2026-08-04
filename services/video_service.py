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
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Video
from core.schemas import VideoCreate, VideoResponse
from core.config_loader import load_config
from core.repository import create_video
from core.status_tracker import StatusTracker
from pipeline.engine import PipelineEngine

logger = logging.getLogger(__name__)

# 运行中的视频 id 集合 — 闭合 PUT /params 返回后、后台任务置 PROCESSING 之前
# 的窗口竞态（删除守卫使用）。单进程内有效（uvicorn 默认单 worker）。
RUNNING_VIDEOS: set[uuid.UUID] = set()

# ── 并发管道限制 — 低显存机器（如 24GB）防组批量并发 OOM ──
# config pipeline.max_concurrent_videos：0 = 不限（默认）；>0 时同一时刻最多 N 个管道在跑。
# 静态权重是共享单实例不会翻倍，但激活峰值按并发数叠加，故需限流。
_pipeline_limit: int = 0
_pipeline_sem: asyncio.Semaphore | None = None
_pipeline_sem_lock = asyncio.Lock()


async def _acquire_pipeline_slot(config: dict) -> asyncio.Semaphore | None:
    """按配置获取并发管道信号量；0=不限返回 None；限制变化时重建信号量。"""
    global _pipeline_limit, _pipeline_sem
    limit = int((config.get("pipeline", {}) or {}).get("max_concurrent_videos", 0) or 0)
    if limit <= 0:
        return None
    async with _pipeline_sem_lock:
        if _pipeline_limit != limit:
            _pipeline_limit = limit
            _pipeline_sem = asyncio.Semaphore(limit)
        sem = _pipeline_sem
    await sem.acquire()
    return sem


def _release_pipeline_slot(sem: asyncio.Semaphore | None) -> None:
    if sem is not None:
        sem.release()


class VideoService:
    """视频业务服务 — 创建记录与 Pipeline 后台调度。"""

    def __init__(
        self,
        config: dict,
        db_session_factory: async_sessionmaker[AsyncSession],
        embedder=None,
        captioner=None,
        detector=None,
    ):
        self.config = config
        self.db_session_factory = db_session_factory
        self.embedder = embedder
        self.captioner = captioner
        self.detector = detector

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
        """增量后台任务：对已完成的视频补跑指定功能阶段。"""
        logger.info("[VideoService] Incremental %s for video %s", added_modalities, video_id)
        RUNNING_VIDEOS.add(video_id)
        try:
            sem = await _acquire_pipeline_slot(load_config())
            try:
                await self._incremental_process(video_id, added_modalities)
            finally:
                _release_pipeline_slot(sem)
        finally:
            RUNNING_VIDEOS.discard(video_id)

    async def _incremental_process(self, video_id: uuid.UUID, added_modalities: set[str]) -> None:
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
                config=load_config(),
                db_session_factory=self.db_session_factory,
                video=video,
                shared_embedder=self.embedder,
                shared_captioner=self.captioner,
                shared_detector=self.detector,
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
        """后台任务入口：加载视频 → Pipeline → 完成/失败。"""
        logger.info("[VideoService] Starting pipeline for video %s", video_id)
        RUNNING_VIDEOS.add(video_id)
        try:
            # 并发上限（0=不限）：组批量上传会并发启动多个管道，激活峰值叠加需限流
            sem = await _acquire_pipeline_slot(load_config())
            try:
                await self._process_video(video_id)
            finally:
                _release_pipeline_slot(sem)
        finally:
            RUNNING_VIDEOS.discard(video_id)

    async def _process_video(self, video_id: uuid.UUID) -> None:
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
                config=load_config(),
                db_session_factory=self.db_session_factory,
                video=video,
                shared_embedder=self.embedder,
                shared_captioner=self.captioner,
                shared_detector=self.detector,
            )
            await engine.run()
        except Exception as e:
            logger.exception(
                "[VideoService] Pipeline crashed for video %s: %s", video_id, e,
            )
            tracker = StatusTracker(
                video_id=str(video_id),
                db_session_factory=self.db_session_factory,
            )
            await tracker.mark_failed(f"Pipeline crashed: {e}")
