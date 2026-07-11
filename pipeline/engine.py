"""
pipeline/engine.py
═══════════════════════════════════════════════════════════
五阶段认知 Pipeline 编排器。

作为后台任务被 FastAPI 调用（BackgroundTasks.add_task），
通过 PipelineEngine.run() 入口执行全流程。
"""

import logging
import os

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.interfaces import VideoContext
from core.models import Video, VideoStatus
from core.status_tracker import StatusTracker
from core.prompt_loader import get_prompt_loader
from core.repository import bulk_insert_scenes, save_video_artifacts
from plugins.factory import load_plugin

logger = logging.getLogger(__name__)


class PipelineEngine:
    """五阶段认知工作流编排器。

    设计原则:
      - 每一阶段依赖前一阶段的产出
      - 各阶段之间通过 VideoContext 传递数据
      - 每阶段完成时调用 StatusTracker 更新进度
    """

    def __init__(
        self,
        config: dict,
        db_session_factory: async_sessionmaker[AsyncSession],
        video: Video,
    ):
        self.config = config
        self.db_session_factory = db_session_factory
        self.video = video

        self.tracker = StatusTracker(
            video_id=str(video.id),
            db_session_factory=db_session_factory,
        )
        self.ctx = VideoContext(
            video_id=str(video.id),
            file_path=video.file_path,
        )
        self.prompt_loader = get_prompt_loader()
        self.plugins: dict[str, object] = {}

    # ──────────────────────────────────────────────────────
    # 插件加载
    # ──────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """加载所有 9 类算法插件（可能为 None=被禁用）。"""
        categories = [
            "qc", "transcriber", "segmenter", "detector",
            "ocr", "captioner", "embedder", "summarizer", "grounding",
        ]
        for cat in categories:
            self.plugins[cat] = await load_plugin(self.config, cat)

    # ──────────────────────────────────────────────────────
    # 入口
    # ──────────────────────────────────────────────────────

    async def run(self) -> None:
        """按阶段顺序执行全流程。

        Phase 2（检测/OCR）当前跳过，Demo 阶段仅启用:
          Phase 1 → 关键帧抽取 → Phase 3 → Phase 4 → Phase 5 → Persist
        """
        try:
            await self._set_processing()
            await self.initialize()

            await self._phase1()
            await self._extract_keyframes()
            await self._phase3()
            await self._phase4()
            await self._phase5()
            await self._persist()

            await self.tracker.mark_completed()
            logger.info("[Pipeline] video %s completed", self.video.id)

        except Exception as e:
            logger.exception("[Pipeline] video %s failed: %s", self.video.id, e)
            await self.tracker.mark_failed(str(e))

    async def _set_processing(self) -> None:
        """修改视频状态为 processing。"""
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video.id)
                .values(status=VideoStatus.PROCESSING)
            )
            await session.commit()

    # ──────────────────────────────────────────────────────
    # 各阶段
    # ──────────────────────────────────────────────────────

    async def _phase1(self) -> None:
        """Phase 1: 前置质检 + 音频抽取 + 镜头分割。"""
        from pipeline.phase1_qc import Phase1QC
        engine = Phase1QC(
            ctx=self.ctx,
            plugins=self.plugins,
            config=self.config,
            tracker=self.tracker,
            video=self.video,
        )
        await engine.execute()

    async def _extract_keyframes(self) -> None:
        """关键帧抽取 — Phase 1 后、Phase 4 前执行。

        对每个场景的中点时间戳用 FFmpeg pipe 抽一帧到内存，
        赋值 scene.keyframe 供后续 caption / embedding 使用。
        """
        from utils.video_util import extract_keyframe_to_memory

        scenes = self.ctx.scenes
        if not scenes:
            logger.info("[Pipeline] No scenes to extract keyframes from")
            return

        logger.info("[Pipeline] Extracting %d keyframes ...", len(scenes))
        for i, scene in enumerate(scenes):
            midpoint = (scene.start_sec + scene.end_sec) / 2.0
            try:
                scene.keyframe = await extract_keyframe_to_memory(
                    self.ctx.file_path, midpoint,
                )
            except Exception as e:
                logger.warning(
                    "[Pipeline] Keyframe extraction failed for scene %d @ %.1fs: %s",
                    i, midpoint, e,
                )
                scene.keyframe = None

        extracted = sum(1 for s in scenes if s.keyframe is not None)
        logger.info("[Pipeline] Keyframes extracted: %d/%d", extracted, len(scenes))

    async def _phase3(self) -> None:
        """Phase 3: 模态交叉对齐（转录 → 场景）。"""
        from pipeline.phase3_alignment import Phase3Alignment
        engine = Phase3Alignment(
            ctx=self.ctx,
            plugins=self.plugins,
            config=self.config,
            tracker=self.tracker,
        )
        await engine.execute()

    async def _phase4(self) -> None:
        """Phase 4: 记忆窗口深度描述 + 向量编码。"""
        try:
            from pipeline.phase4_caption import Phase4Caption
        except ImportError:
            logger.warning("[Pipeline] Phase4Caption not implemented, skipping")
            return
        engine = Phase4Caption(
            ctx=self.ctx,
            plugins=self.plugins,
            config=self.config,
            tracker=self.tracker,
            prompt_loader=self.prompt_loader,
        )
        await engine.execute()

    async def _phase5(self) -> None:
        """Phase 5: 全局 LLM 摘要。"""
        try:
            from pipeline.phase5_summary import Phase5Summary
        except ImportError:
            logger.warning("[Pipeline] Phase5Summary not implemented, skipping")
            return
        engine = Phase5Summary(
            ctx=self.ctx,
            plugins=self.plugins,
            config=self.config,
            tracker=self.tracker,
            prompt_loader=self.prompt_loader,
        )
        await engine.execute()

    # ──────────────────────────────────────────────────────
    # 持久化
    # ──────────────────────────────────────────────────────

    async def _persist(self) -> None:
        """将 VideoContext 中的数据写入数据库。

        使用 repository 函数（bulk_insert_scenes / save_video_artifacts）
        和直接 ORM add（transcript）分步写入，每步独立提交。
        """
        # ---- 1. 视频字段（duration） ----
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video.id)
                .values(duration=self.ctx.duration)
            )
            await session.commit()

        # ---- 2. 批量写入 scenes ----
        if self.ctx.scenes:
            scenes_data = [
                {
                    "scene_index": s.scene_index,
                    "start_sec": s.start_sec,
                    "end_sec": s.end_sec,
                    "keyframe_path": s.keyframe_path,
                    "embedding": s.embedding,
                    "ocr_text": s.ocr_text,
                    "aligned_transcript": s.aligned_transcript,
                    "caption": s.caption,
                    "prev_caption": s.prev_caption,
                    "entities": s.entities,
                }
                for s in self.ctx.scenes
            ]
            async with self.db_session_factory() as session:
                await bulk_insert_scenes(session, self.video.id, scenes_data)

        # ---- 3. 写入 transcript ----
        if self.ctx.transcript_full:
            from core.models import Transcript as TranscriptModel
            async with self.db_session_factory() as session:
                session.add(TranscriptModel(
                    video_id=self.video.id,
                    full_text=self.ctx.transcript_full,
                    words=self.ctx.transcript_words,
                ))
                await session.commit()

        # ---- 4. 保存 QC 结果与摘要制品 ----
        if self.ctx.qc_result or self.ctx.summary:
            async with self.db_session_factory() as session:
                await save_video_artifacts(
                    session,
                    self.video.id,
                    qc_result=self.ctx.qc_result or None,
                    summary=self.ctx.summary,
                )
