"""
pipeline/engine.py
═══════════════════════════════════════════════════════════
声明式操作 DAG 编排器（v0.10 — 事件驱动调度）。

操作通过 pipeline/operations.py 中的 ALL_OPERATIONS 声明，
引擎负责门控过滤 → 事件驱动调度：每个操作只等直接上游，
就绪即启动 — 不再有批次壁垒。
"""

import asyncio
import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.interfaces import VideoContext
from core.models import Video, Scene, VideoStatus
from core.status_tracker import StatusTracker
from core.prompt_loader import get_prompt_loader
from core.repository import (
    bulk_insert_scenes, save_video_artifacts,
    bulk_insert_frame_detections, bulk_insert_tracks,
    bulk_insert_track_embeddings,
)
from plugins.factory import load_plugin
from pipeline.operations import ALL_OPERATIONS
from pipeline.runners.base import PipelineContext, Operation

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 事件驱动 DAG 调度器 (v0.10)
# ═══════════════════════════════════════════════════════════

class EventDrivenScheduler:
    """每个 op 独立 task → await 上游 done events → 就绪即跑。

    替代原 topological_batches + asyncio.gather 的静态批次模式。
    """

    def __init__(
        self,
        operations: list[Operation],
        pctx: PipelineContext,
        tracker: StatusTracker,
    ):
        self._ops = {op.name: op for op in operations}
        self._pctx = pctx
        self._tracker = tracker
        self._done: dict[str, asyncio.Event] = {
            name: asyncio.Event() for name in self._ops
        }

    async def run(self) -> None:
        """启动所有 op, 每个内部先等依赖完成, 再执行。"""
        tasks = [
            asyncio.create_task(self._run_op(name))
            for name in self._ops
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            logger.error("[Scheduler] %d ops failed", len(errors))
            for e in errors:
                logger.error("[Scheduler] %s", e)
            raise errors[0]

    async def _run_op(self, name: str) -> None:
        op = self._ops[name]

        # 等所有上游
        for dep_name in op.depends_on:
            event = self._done.get(dep_name)
            if event is not None:
                await event.wait()

        logger.debug("[Scheduler] Starting: %s", name)
        try:
            await op.runner.run(self._pctx)
        finally:
            self._done[name].set()
            logger.debug("[Scheduler] Completed: %s", name)


# ── 保留：增量处理仍需拓扑分批（逻辑简单，不改）──

def topological_batches(ops: list) -> list[list]:
    """按依赖拓扑排序，返回可并行执行的批次列表。

    每个批次内的操作相互无依赖，可以 asyncio.gather 并行执行。
    批次之间串行：上一批全部完成后才开始下一批。

    Args:
        ops: Operation 列表，每个 op 有 .name 和 .depends_on 属性。

    Returns:
        list[list[Operation]] — 从先到后排列的批次。

    Raises:
        ValueError: 检测到循环依赖。
    """
    name_to_op = {op.name: op for op in ops}
    batches: list[list] = []
    completed: set[str] = set()
    remaining: set[str] = set(name_to_op.keys())

    while remaining:
        ready = {
            name for name in remaining
            if all(dep in completed for dep in name_to_op[name].depends_on)
        }
        if not ready:
            raise ValueError(f"循环依赖: {remaining}")
        batches.append([name_to_op[name] for name in ready])
        completed |= ready
        remaining -= ready

    return batches


class PipelineEngine:
    """声明式操作 DAG 编排器。

    设计原则:
      - 操作通过 ALL_OPERATIONS 声明（gate / depends_on / required_plugins）
      - 引擎只做门控过滤 + 拓扑排序 + 逐批执行
      - 各操作之间通过 VideoContext 传递数据
    """

    def __init__(
        self,
        config: dict,
        db_session_factory: async_sessionmaker[AsyncSession],
        video: Video,
        shared_embedder=None,
    ):
        self.config = config
        self.db_session_factory = db_session_factory
        self.video = video
        self._shared_embedder = shared_embedder

        self.ctx = VideoContext(
            video_id=str(video.id),
            file_path=video.file_path,
        )
        self.prompt_loader = get_prompt_loader()
        self.plugins: dict[str, object] = {}

    # ── 入口 ──

    async def run(self) -> None:
        """门控过滤 → 拓扑排序 → 加载插件 → 逐批执行 → 持久化。"""
        v = self.video

        try:
            await self._set_processing()

            # 1. 门控过滤
            enabled = [op for op in ALL_OPERATIONS if op.gate(v, self.config)]

            # 2. 拓扑排序 → 分批
            batches = topological_batches(enabled)

            # 3. 加载所需插件（从 enabled operations 的 required_plugins 推导）
            await self._load_plugins(enabled)

            # 4. 创建 tracker（动态进度权重）和 context
            tracker = StatusTracker(
                video_id=str(v.id),
                db_session_factory=self.db_session_factory,
                operations=enabled,
            )
            pctx = PipelineContext(
                video=v,
                ctx=self.ctx,
                config=self.config,
                plugins=self.plugins,
                tracker=tracker,
                db_session_factory=self.db_session_factory,
                shared_embedder=self._shared_embedder,
                prompt_loader=self.prompt_loader,
                embedder_lock=asyncio.Lock(),
            )

            # 5. 事件驱动调度 (替代原拓扑分批+gather)
            scheduler = EventDrivenScheduler(enabled, pctx, tracker)
            await scheduler.run()

            # 6. 持久化
            await self._persist()

            # 6. 卸载 captioner（释放 GPU 显存）
            cap = self.plugins.get("captioner")
            if cap is not None and hasattr(cap, "unload"):
                cap.unload()

            await tracker.mark_completed()
            logger.info("[Pipeline] video %s completed", self.video.id)

        except Exception as e:
            logger.exception("[Pipeline] video %s failed: %s", self.video.id, e)
            tracker = StatusTracker(
                video_id=str(self.video.id),
                db_session_factory=self.db_session_factory,
            )
            await tracker.mark_failed(str(e))

    async def run_incremental(self, added_modalities: set[str]) -> None:
        """增量运行：对已完成的视频补跑指定操作。

        Args:
            added_modalities: {'summary'} / {'search_index'} / {'summary', 'search_index'}
        """
        v = self.video
        need_summary = 'summary' in added_modalities
        need_search = 'search_index' in added_modalities

        try:
            await self._set_processing()

            # 确定需要运行的操作子集
            op_names: set[str] = set()
            if need_summary and v.caption_enabled:
                op_names.update(["caption", "summary"])
            if need_search and v.vision_enabled:
                op_names.update(["keyframes", "frame_encode", "text_encode"])
                if self.config.get("pipeline", {}).get("chunk_encoding", False):
                    op_names.add("chunk_encode")

            enabled = [op for op in ALL_OPERATIONS if op.name in op_names]

            # 清理旧编码数据（防重入）
            if need_search:
                from sqlalchemy import delete as sa_delete
                from core.models import FrameEmbedding, Chunk
                async with self.db_session_factory() as session:
                    await session.execute(
                        sa_delete(FrameEmbedding).where(FrameEmbedding.video_id == v.id)
                    )
                    await session.execute(
                        sa_delete(Chunk).where(Chunk.video_id == v.id)
                    )
                    await session.execute(
                        update(Scene)
                        .where(Scene.video_id == v.id)
                        .values(text_embedding=None)
                    )
                    await session.commit()

            # 从 DB 加载已有场景
            await self._load_scenes_from_db()

            await self._load_plugins(enabled)

            batches = topological_batches(enabled)
            tracker = StatusTracker(
                video_id=str(v.id),
                db_session_factory=self.db_session_factory,
                operations=enabled,
            )
            pctx = PipelineContext(
                video=v,
                ctx=self.ctx,
                config=self.config,
                plugins=self.plugins,
                tracker=tracker,
                db_session_factory=self.db_session_factory,
                shared_embedder=self._shared_embedder,
                prompt_loader=self.prompt_loader,
            )

            for batch in batches:
                await asyncio.gather(*[
                    op.runner.run(pctx) for op in batch
                ])

            if need_summary:
                await self._persist_summary_only()

            await tracker.mark_completed()
            logger.info("[Incremental] video %s completed", self.video.id)

        except Exception as e:
            logger.exception("[Incremental] video %s failed: %s (reverting to completed)", self.video.id, e)
            async with self.db_session_factory() as session:
                await session.execute(
                    update(Video)
                    .where(Video.id == self.video.id)
                    .values(status=VideoStatus.COMPLETED, error_message=f"Incremental failed: {e}")
                )
                await session.commit()

    # ── 插件加载 ──

    async def _load_plugins(self, ops: list) -> None:
        """从启用的 operations 推导需要的插件并加载。

        共享实例（embedder）优先：已通过 shared_embedder 注入则跳过工厂加载，
        避免重复初始化 GPU 模型。没有共享实例时（如独立测试），仍正常加载。
        """
        needed: set[str] = set()
        for op in ops:
            needed.update(op.required_plugins)

        # 共享实例优先 — 已在 lifespan 预加载到 GPU，runner 通过 PipelineContext 注入
        if self._shared_embedder is not None:
            needed.discard("embedder")

        for cat in needed:
            self.plugins[cat] = await load_plugin(self.config, cat)

    # ── 持久化 ──

    async def _persist(self) -> None:
        """将 VideoContext 中的数据写入数据库（单 session 批量写入）。"""
        async with self.db_session_factory() as session:
            # 视频时长
            await session.execute(
                update(Video)
                .where(Video.id == self.video.id)
                .values(duration=self.ctx.duration)
            )

            # scenes
            if self.ctx.scenes:
                scenes_data = [
                    {
                        "scene_index": s.scene_index, "start_sec": s.start_sec,
                        "end_sec": s.end_sec, "keyframe_path": s.keyframe_path,
                        "text_embedding": s.text_embedding, "ocr_text": s.ocr_text,
                        "aligned_transcript": s.aligned_transcript,
                        "caption": s.caption, "prev_caption": s.prev_caption,
                        "entities": s.entities,
                    }
                    for s in self.ctx.scenes
                ]
                await bulk_insert_scenes(session, self.video.id, scenes_data)

            # transcript
            if self.ctx.transcript_full:
                from core.models import Transcript as TranscriptModel
                session.add(TranscriptModel(
                    video_id=self.video.id,
                    full_text=self.ctx.transcript_full,
                    words=self.ctx.transcript_words,
                ))

            # 摘要
            if self.ctx.summary:
                await save_video_artifacts(
                    session, self.video.id, summary=self.ctx.summary,
                )

            # 检测 + 追踪
            if self.ctx.frame_detections:
                await bulk_insert_frame_detections(session, self.ctx.frame_detections)
                await bulk_insert_tracks(session, self.ctx.tracks)

            # track 嵌入
            if self.ctx.track_embeddings:
                await bulk_insert_track_embeddings(
                    session, self.video.id, self.ctx.track_embeddings,
                )

            await session.commit()

    async def _persist_summary_only(self) -> None:
        """仅写入摘要（增量用）。"""
        if self.ctx.summary:
            async with self.db_session_factory() as session:
                await save_video_artifacts(
                    session, self.video.id, summary=self.ctx.summary,
                )

    async def _load_scenes_from_db(self) -> None:
        """从 DB 加载已有场景数据到 ctx.scenes（增量用）。"""
        from sqlalchemy import select
        from core.models import Scene as SceneModel
        from core.interfaces import Scene as SceneData

        async with self.db_session_factory() as session:
            result = await session.execute(
                select(SceneModel)
                .where(SceneModel.video_id == self.video.id)
                .order_by(SceneModel.scene_index)
            )
            db_scenes = result.scalars().all()

        for s in db_scenes:
            scene = SceneData(
                scene_id=s.scene_index,
                scene_index=s.scene_index,
                start_sec=s.start_sec,
                end_sec=s.end_sec,
                keyframe_path=s.keyframe_path,
                caption=s.caption,
                ocr_text=s.ocr_text,
                aligned_transcript=s.aligned_transcript,
            )
            self.ctx.scenes.append(scene)

        for i in range(1, len(self.ctx.scenes)):
            self.ctx.scenes[i].prev_caption = self.ctx.scenes[i - 1].caption

        logger.info("[Pipeline] Loaded %d scenes from DB for incremental run", len(self.ctx.scenes))

    async def _set_processing(self) -> None:
        """修改视频状态为 processing。"""
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video.id)
                .values(status=VideoStatus.PROCESSING)
            )
            await session.commit()
