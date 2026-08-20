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

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Video
from core.schemas import VideoCreate, VideoResponse, PipelineParams
from core.config_loader import load_config
from core.repository import create_video
from core.status_tracker import StatusTracker
from core.cancellation import unmark_cancelled
from pipeline.engine import PipelineEngine

logger = logging.getLogger(__name__)

# 运行中的视频 id 集合 — 闭合 PUT /params 返回后、后台任务置 PROCESSING 之前
# 的窗口竞态（删除守卫使用）。单进程内有效（uvicorn 默认单 worker）。
RUNNING_VIDEOS: set[uuid.UUID] = set()

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

    async def create_reanalyze_version(
        self, video_id: uuid.UUID, params: PipelineParams,
    ) -> Video:
        """为已有视频创建新版本行（v0.34 多版本解析）。

        - 源视频 file_id 为 NULL（独立文件）→ 生成 file_id 并回写源行 version_no=1
        - 版本号 = 该 file_id 下 max(version_no)+1
        - 新行复制文件信息 + 写入请求参数，返回（由路由负责入队管道）
        """
        async with self.db_session_factory() as session:
            result = await session.execute(select(Video).where(Video.id == video_id))
            src = result.scalar_one_or_none()
            if src is None:
                raise ValueError("源视频不存在")

            file_id = src.file_id
            if file_id is None:
                file_id = uuid.uuid4()
                src.file_id = file_id
                src.version_no = 1
                await session.flush()

            max_row = await session.execute(
                select(func.max(Video.version_no)).where(Video.file_id == file_id)
            )
            new_no = int(max_row.scalar() or 1) + 1

            new_video = Video(
                file_path=src.file_path,
                file_name=src.file_name,
                file_size=src.file_size,
                source_owned=src.source_owned,
                external_file_id=src.external_file_id,
                group_id=src.group_id,
                file_id=file_id,
                version_no=new_no,
                # 复制格式信息（v0.34：否则新版本 video_codec 为空 → 播放器一直"正在分析视频格式"）
                container_format=src.container_format,
                video_codec=src.video_codec,
                audio_codec=src.audio_codec,
                has_audio=src.has_audio,
                duration=src.duration,
                remuxed_path=src.remuxed_path,
                proxy_path=src.proxy_path,
                proxy_status=src.proxy_status,
                proxy_progress=src.proxy_progress,
                metadata_json=src.metadata_json,
                # 请求参数（L1-L4）
                content_type=params.content_type,
                language=params.language,
                vision_enabled=params.vision_enabled,
                audio_enabled=params.audio_enabled,
                ocr_enabled=params.ocr_enabled,
                caption_enabled=params.caption_enabled,
                detection_enabled=params.detection_enabled,
                detection_classes=params.detection_classes,
                face_enabled=params.face_enabled,
                plate_enabled=params.plate_enabled,
                summary_enabled=params.summary_enabled,
                summary_mode=params.summary_mode,
                search_index_enabled=params.search_index_enabled,
                sample_fps=params.sample_fps,
                segment_threshold=params.segment_threshold,
                caption_with_context=params.caption_with_context,
                summary_detail=params.summary_detail,
                encode_profile=params.encode_profile,
            )
            session.add(new_video)
            await session.commit()
            await session.refresh(new_video)
            return new_video

    async def incremental_process(self, video_id: uuid.UUID, added_modalities: set[str]) -> None:
        """增量后台任务：对已完成的视频补跑指定功能阶段。"""
        logger.info("[VideoService] Incremental %s for video %s", added_modalities, video_id)
        RUNNING_VIDEOS.add(video_id)
        try:
            # 并发上限由全局 PipelineQueue worker 池保证（v0.32）
            await self._incremental_process(video_id, added_modalities)
        finally:
            RUNNING_VIDEOS.discard(video_id)
            unmark_cancelled(video_id)

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

    async def process_video(self, video_id: uuid.UUID, progress_callback=None) -> None:
        """后台任务入口：加载视频 → Pipeline → 完成/失败。

        progress_callback: 可选 (progress 0~1, description)，透传给 PipelineEngine，
        云智自动化任务用它推送平台进度。
        """
        logger.info("[VideoService] Starting pipeline for video %s", video_id)
        RUNNING_VIDEOS.add(video_id)
        try:
            # 并发上限由全局 PipelineQueue worker 池保证（v0.32）
            await self._process_video(video_id, progress_callback)
        finally:
            RUNNING_VIDEOS.discard(video_id)
            unmark_cancelled(video_id)

    async def _process_video(self, video_id: uuid.UUID, progress_callback=None) -> None:
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
                progress_callback=progress_callback,
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


# ──────────────────────────────────────────────────────────────
# PipelineQueue 执行器（v0.32 队列机制）— 签名 (task_id, payload, video_id)
# ──────────────────────────────────────────────────────────────

def _build_service(app) -> VideoService:
    return VideoService(
        config=load_config(),
        db_session_factory=app.state.db_session_factory,
        embedder=app.state.embedder,
        captioner=getattr(app.state, "captioner", None),
        detector=getattr(app.state, "detector", None),
    )


async def execute_pipeline_task(app, task_id: str, payload: dict, video_id: str | None = None) -> None:
    """队列 worker 执行的 pipeline 任务：对已有视频跑全管道。"""
    await _build_service(app).process_video(uuid.UUID(payload["video_id"]))


async def execute_incremental_task(app, task_id: str, payload: dict, video_id: str | None = None) -> None:
    """队列 worker 执行的 incremental 任务：对已完成视频补跑指定阶段。"""
    await _build_service(app).incremental_process(
        uuid.UUID(payload["video_id"]),
        set(payload.get("added_modalities", [])),
    )
