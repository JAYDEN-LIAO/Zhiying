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
from core.cancellation import is_cancelled
from core.status_tracker import StatusTracker, STAGE2_OPS
from core.prompt_loader import get_prompt_loader
from core.repository import (
    bulk_insert_scenes, save_video_artifacts, bulk_update_scenes_captions,
    bulk_update_scenes_entities,
    bulk_insert_frame_detections, bulk_insert_tracks,
    bulk_insert_track_embeddings,
    bulk_insert_face_identities, bulk_insert_face_detections,
    bulk_insert_plate_detections, bulk_insert_ocr_detections,
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
        on_log: object | None = None,
    ):
        self._ops = {op.name: op for op in operations}
        self._pctx = pctx
        self._tracker = tracker
        self._on_log = on_log  # 可选异步日志钩子 (message, level) → 任务日志（阶段级明细）
        self._done: dict[str, asyncio.Event] = {
            name: asyncio.Event() for name in self._ops
        }

    async def _log(self, message: str, level: str = "info") -> None:
        if self._on_log is not None:
            try:
                await self._on_log(message, level)
            except Exception:
                logger.exception("[Scheduler] task log write failed (non-blocking)")

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

        import time as _time
        _t0 = _time.time()
        logger.info("[Scheduler] START %s", name)
        # 阶段级任务日志：op 中文标签 + 描述（任务中心可见详细处理过程）
        await self._log(f"「{op.label}」开始：{op.description}")
        try:
            await op.runner.run(self._pctx)
        finally:
            self._done[name].set()
            _elapsed = _time.time() - _t0
            logger.info("[Scheduler] DONE  %s in %.1fs", name, _elapsed)
            await self._log(f"「{op.label}」完成（耗时 {_elapsed:.1f}s）")


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
            if all(
                dep in completed or dep not in name_to_op
                for dep in name_to_op[name].depends_on
            )
        }
        if not ready:
            raise ValueError(f"循环依赖: {remaining}")
        batches.append([name_to_op[name] for name in ready])
        completed |= ready
        remaining -= ready

    return batches


# ═══════════════════════════════════════════════════════════
# 跨 op 后处理 — 所有 op 完成后、persist 前执行
# ═══════════════════════════════════════════════════════════


def _aggregate_scene_entities(
    scenes: list | None,       # list[core.interfaces.Scene]
    detections: list[dict] | None,
) -> None:
    """将逐帧检测结果按场景聚合去重，写入 scene.entities。

    使用排序 + 双指针 O(n log n + n + m)，替代旧 O(n×m) 嵌套循环。
    在所有 op 完成后调用 — 确保 scenes 和 detections 均已就绪。

    每个 track_id 在单个场景中只出现一次（首次检测时间戳）。
    """
    if not scenes or not detections:
        return

    # 按时间戳排序 → 双指针扫描
    dets = sorted(detections, key=lambda d: d["timestamp_sec"])
    det_idx = 0
    n_dets = len(dets)

    for scene in scenes:
        seen_tracks: set[int] = set()
        entities: list[dict] = []

        # 跳过此场景时间范围之前的 detection
        while det_idx < n_dets and dets[det_idx]["timestamp_sec"] < scene.start_sec:
            det_idx += 1

        # 收集此场景时间范围内的 detection（首次 track_id 去重）
        i = det_idx
        while i < n_dets and dets[i]["timestamp_sec"] <= scene.end_sec:
            fd = dets[i]
            tid = fd["track_id"]
            if tid not in seen_tracks:
                seen_tracks.add(tid)
                entities.append({
                    "label": fd["class_name"],
                    "bbox": [fd["bbox"]["x1"], fd["bbox"]["y1"],
                             fd["bbox"]["x2"], fd["bbox"]["y2"]],
                    "confidence": fd["confidence"],
                    "start_sec": fd["timestamp_sec"],
                    "end_sec": fd["timestamp_sec"],
                    "track_id": tid,
                })
            i += 1

        # 跳过已处理的 detection，下一场景从新位置开始
        det_idx = i

        scene.entities = entities if entities else []


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
        shared_captioner=None,
        shared_detector=None,
        progress_callback=None,
    ):
        self.config = config
        self.db_session_factory = db_session_factory
        self.video = video
        self._shared_embedder = shared_embedder
        self._shared_captioner = shared_captioner
        self._shared_detector = shared_detector
        # 可选进度回调 (progress 0~1, description) → 云智自动化任务推送平台进度
        self._progress_callback = progress_callback

        # v0.13: 优先使用 remuxed MP4（容器 demux 效率远高于 PS/TS/AVI）
        # ASSUMPTION: remuxed 文件的帧数/时长/时间戳与原始文件一致（_c copy 流复制保证）
        pipeline_source = video.remuxed_path or video.file_path
        self.ctx = VideoContext(
            video_id=str(video.id),
            file_path=pipeline_source,
        )
        self.prompt_loader = get_prompt_loader()
        self.plugins: dict[str, object] = {}

    def _new_tracker(self, operations: list | None = None) -> StatusTracker:
        """构造 StatusTracker，注入可选进度回调（云智平台进度推送）。"""
        return StatusTracker(
            video_id=str(self.video.id),
            db_session_factory=self.db_session_factory,
            operations=operations,
            on_progress=self._progress_callback,
        )

    # ── 入口 ──

    async def run(self) -> None:
        """门控过滤 → 拓扑排序 → 加载插件 → 逐批执行 → 持久化。"""
        v = self.video

        try:
            await self._set_processing()
            await self._log_task("管道开始")

            # 1. 门控过滤
            enabled = [op for op in ALL_OPERATIONS if op.gate(v, self.config)]

            # 2. 管道配置快照（任务日志——系统/模型/量化/fps 等全量参数，方便溯源）
            await self._log_pipeline_config(v, enabled)

            # 3. 拓扑排序 → 分批
            batches = topological_batches(enabled)

            # 3. 加载所需插件（从 enabled operations 的 required_plugins 推导）
            await self._load_plugins(enabled)
            # 注入共享实例（已在 lifespan 预加载，避免重复加载）
            if self._shared_captioner is not None:
                self.plugins["captioner"] = self._shared_captioner
            if self._shared_detector is not None:
                self.plugins["detector"] = self._shared_detector

            # 4. 创建 tracker（动态进度权重）和 context
            tracker = self._new_tracker(enabled)
            # 生产者-消费者队列：keyframes → frame_encode 流式通道
            enabled_names = {op.name for op in enabled}
            frame_queue: asyncio.Queue | None = (
                asyncio.Queue(maxsize=512)
                if "frame_encode" in enabled_names
                else None
            )
            # 共享 NVDEC 流队列：detection → search_encode 共享解码流
            search_frame_queue: asyncio.Queue | None = (
                asyncio.Queue(maxsize=128)
                if "search_encode" in enabled_names and "detection" in enabled_names
                else None
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
                frame_queue=frame_queue,
                search_frame_queue=search_frame_queue,
                log=self._log_task,
            )

            # 5. 事件驱动调度 (替代原拓扑分批+gather)
            scheduler = EventDrivenScheduler(enabled, pctx, tracker, on_log=self._log_task)
            await scheduler.run()

            # 6. 持久化 — 视频被删除（允许删处理中记录）→ 中止，避免写已删行 FK 异常
            if is_cancelled(self.video.id):
                logger.info("[Pipeline] video %s deleted, aborting pipeline", self.video.id)
                return
            await self._persist()

            # 产物落库汇总（各表行数——对照后端 Bulk inserted 明细，方便核对）
            parts = [f"场景 {len(self.ctx.scenes)}"]
            if self.ctx.transcript_full:
                parts.append("转录 1")
            if self.ctx.frame_detections:
                parts.append(f"帧检测 {len(self.ctx.frame_detections)}")
            if self.ctx.tracks:
                parts.append(f"轨迹 {len(self.ctx.tracks)}")
            if self.ctx.track_embeddings:
                parts.append(f"轨迹向量 {len(self.ctx.track_embeddings)}")
            if self.ctx.face_detections:
                parts.append(f"人脸检测 {len(self.ctx.face_detections)}")
            if self.ctx.plate_detections:
                parts.append(f"车牌 {len(self.ctx.plate_detections)}")
            if self.ctx.ocr_detections:
                parts.append(f"文字 {len(self.ctx.ocr_detections)}")
            await self._log_task("产物落库：" + "、".join(parts))

            # 卸载 captioner（仅当不是共享实例时才释放 GPU 显存）
            if self._shared_captioner is None:
                cap = self.plugins.get("captioner")
                if cap is not None and hasattr(cap, "unload"):
                    result = cap.unload()
                    if asyncio.iscoroutine(result):
                        await result

            await self._log_task("管道完成")
            # v0.35 两阶段：精析族 ops 实际运行过 → COMPLETED；仅摘要（quick）→ READY_FOR_ANALYSIS
            # 词汇对齐前端 ProcessStatus 枚举（PRE_PROCESSING/READY_FOR_ANALYSIS/ANALYZING/COMPLETED/FAILED）
            stage2_ran = any(n in STAGE2_OPS for n in enabled_names)
            await tracker.mark_completed(process_status="COMPLETED" if stage2_ran else "READY_FOR_ANALYSIS")
            logger.info("[Pipeline] video %s completed", self.video.id)

        except Exception as e:
            if is_cancelled(self.video.id):
                # 删除落在 persist 窗口内 → 写已删行抛 FK，静默中止（不 mark_failed）
                logger.info("[Pipeline] video %s deleted mid-run, aborting (%s)", self.video.id, e)
                return
            logger.exception("[Pipeline] video %s failed: %s", self.video.id, e)
            # 完整错误入任务日志（含 traceback，多行）——排查必须能看到调用栈
            import traceback
            tb = traceback.format_exc()
            await self._log_task("管道失败", level="error")
            for line in tb.rstrip("\n").splitlines():
                await self._log_task(f"  {line}", level="error")
            tracker = self._new_tracker()
            await tracker.mark_failed(str(e))

    async def run_incremental(self, added_modalities: set[str]) -> None:
        """增量运行：对已完成的视频补跑指定操作。

        Args:
            added_modalities: {'summary'} / {'search_index'} / {'summary', 'search_index'}
        """
        v = self.video
        need_summary = 'summary' in added_modalities
        need_search = 'search_index' in added_modalities
        need_detection = 'detection' in added_modalities  # v0.35 阶段二：精细化精析
        prev_process_status = v.process_status  # 失败时还原（阶段二中断不把已完成视频停在 ANALYZING）

        try:
            # v0.35 阶段二 → ANALYZING；其余增量 → PRE_PROCESSING（词汇对齐前端 ProcessStatus 枚举）
            await self._set_processing("ANALYZING" if need_detection else "PRE_PROCESSING")

            # 确定需要运行的操作子集
            op_names: set[str] = set()
            if need_summary and v.caption_enabled and v.vision_enabled:
                # 摘要路径: keyframes(重抽帧供 caption) → caption → summary
                op_names.update(["keyframes", "caption", "summary"])
                if v.search_index_enabled:
                    op_names.add("text_encode")  # 摘要后刷新文本向量
            if need_search and v.vision_enabled:
                if v.summary_enabled:
                    # 摘要路径: keyframes → frame_encode + text_encode
                    op_names.update(["keyframes", "frame_encode", "text_encode"])
                    if self.config.get("pipeline", {}).get("chunk_encoding", False):
                        op_names.add("chunk_encode")
                else:
                    # 纯搜索路径: search_encode（自抽帧+编码，不依赖 scene）
                    op_names.add("search_encode")
            if need_detection and v.detection_enabled and v.vision_enabled:
                # 阶段二：detection → track_encode / face / plate
                # 硬约束：face/plate 消费 detection 内存态 track_best_frames（不落库），必须一起重跑
                op_names.add("detection")
                if v.search_index_enabled:
                    op_names.add("track_encode")
                if v.face_enabled:
                    op_names.add("face")
                if v.plate_enabled:
                    op_names.add("plate")

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
                    if v.summary_enabled:
                        await session.execute(
                            update(Scene)
                            .where(Scene.video_id == v.id)
                            .values(text_embedding=None)
                        )
                    await session.commit()

            # 清理旧检测/精析产物（阶段二重跑防残留叠加）
            if need_detection:
                from sqlalchemy import delete as sa_delete
                from core.models import FrameDetection, Track, TrackEmbedding, FaceIdentity, FaceDetection, PlateDetection
                async with self.db_session_factory() as session:
                    await session.execute(sa_delete(FrameDetection).where(FrameDetection.video_id == v.id))
                    await session.execute(sa_delete(Track).where(Track.video_id == v.id))
                    await session.execute(sa_delete(TrackEmbedding).where(TrackEmbedding.video_id == v.id))
                    await session.execute(sa_delete(FaceDetection).where(FaceDetection.video_id == v.id))
                    await session.execute(sa_delete(FaceIdentity).where(FaceIdentity.video_id == v.id))
                    await session.execute(sa_delete(PlateDetection).where(PlateDetection.video_id == v.id))
                    # 场景实体聚合待重算，先清空
                    await session.execute(
                        update(Scene).where(Scene.video_id == v.id).values(entities=None)
                    )
                    await session.commit()

            # 从 DB 加载已有场景（need_summary / need_search / need_detection 且摘要开启时）
            if (need_summary or need_search or need_detection) and v.summary_enabled:
                await self._load_scenes_from_db()

            await self._load_plugins(enabled)
            if self._shared_captioner is not None:
                self.plugins["captioner"] = self._shared_captioner
            if self._shared_detector is not None:
                self.plugins["detector"] = self._shared_detector

            batches = topological_batches(enabled)
            tracker = self._new_tracker(enabled)
            enabled_names = {op.name for op in enabled}
            frame_queue: asyncio.Queue | None = (
                asyncio.Queue(maxsize=512)
                if "frame_encode" in enabled_names
                else None
            )
            search_frame_queue: asyncio.Queue | None = (
                asyncio.Queue(maxsize=128)
                if "search_encode" in enabled_names and "detection" in enabled_names
                else None
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
                frame_queue=frame_queue,
                search_frame_queue=search_frame_queue,
                log=self._log_task,
            )

            for batch in batches:
                await asyncio.gather(*[
                    op.runner.run(pctx) for op in batch
                ])

            # 视频被删除 → 中止，跳过 persist/mark_completed
            if is_cancelled(self.video.id):
                logger.info("[Incremental] video %s deleted, aborting", self.video.id)
                return

            if need_detection:
                await self._persist_detection_only()
            if need_summary:
                await self._persist_summary_only()

            # v0.35 阶段二完成 → COMPLETED；摘要/搜索增量保持原阶段状态
            await tracker.mark_completed(process_status="COMPLETED" if need_detection else None)
            logger.info("[Incremental] video %s completed", self.video.id)

        except Exception as e:
            if is_cancelled(self.video.id):
                logger.info("[Incremental] video %s deleted mid-run, aborting (%s)", self.video.id, e)
                return
            logger.exception("[Incremental] video %s failed: %s (reverting to completed)", self.video.id, e)
            async with self.db_session_factory() as session:
                await session.execute(
                    update(Video)
                    .where(Video.id == self.video.id)
                    .values(
                        status=VideoStatus.COMPLETED,
                        process_status=prev_process_status,
                        error_message=f"Incremental failed: {e}",
                    )
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
        if self._shared_captioner is not None:
            needed.discard("captioner")
        if self._shared_detector is not None:
            needed.discard("detector")

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

            # ── 检测实体聚合到场景（所有 op 完成后两者均已就绪）──
            # 从 DetectionRunner 移至此：detection 不依赖 segmentation，
            # 在 detection 完成时 scenes 可能为空。此处保证两者均已产出。
            _aggregate_scene_entities(self.ctx.scenes, self.ctx.frame_detections)

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

            # 人脸识别 — 先插入 identities 获取 DB ID 映射，再回填 detections
            if self.ctx.face_identities:
                label_to_id = await bulk_insert_face_identities(session, self.ctx.face_identities)
                if self.ctx.face_detections and label_to_id:
                    for fd in self.ctx.face_detections:
                        db_id = label_to_id.get(fd.pop("_label", ""))
                        if db_id is not None:
                            fd["identity_id"] = db_id
                await bulk_insert_face_detections(session, self.ctx.face_detections)
            elif self.ctx.face_detections:
                await bulk_insert_face_detections(session, self.ctx.face_detections)

            # 车牌识别
            if self.ctx.plate_detections:
                await bulk_insert_plate_detections(session, self.ctx.plate_detections)

            # OCR 画面文字
            if self.ctx.ocr_detections:
                await bulk_insert_ocr_detections(session, self.ctx.ocr_detections)

            await session.commit()

    async def _persist_summary_only(self) -> None:
        """增量摘要：写 summary + 批量更新已有 scenes 的 caption 等文本字段。"""
        async with self.db_session_factory() as session:
            if self.ctx.summary:
                await save_video_artifacts(
                    session, self.video.id, summary=self.ctx.summary,
                )
            if self.ctx.scenes:
                await bulk_update_scenes_captions(session, self.video.id, [
                    {
                        "scene_index": s.scene_index,
                        "caption": s.caption,
                        "prev_caption": s.prev_caption,
                        "keyframe_path": s.keyframe_path,
                        "text_embedding": s.text_embedding,
                    }
                    for s in self.ctx.scenes
                ])

    async def _persist_detection_only(self) -> None:
        """阶段二精析落库：检测/追踪/人脸/车牌 + 场景实体聚合 + 产物计数。

        不碰 scenes/summary（阶段一已落）；检测表已由 run_incremental 清理过，直接重插。
        """
        async with self.db_session_factory() as session:
            # 检测实体聚合到场景（scenes 已从 DB 重载）
            _aggregate_scene_entities(self.ctx.scenes, self.ctx.frame_detections)

            # 检测 + 追踪
            if self.ctx.frame_detections:
                await bulk_insert_frame_detections(session, self.ctx.frame_detections)
                await bulk_insert_tracks(session, self.ctx.tracks)

            # track 嵌入
            if self.ctx.track_embeddings:
                await bulk_insert_track_embeddings(
                    session, self.video.id, self.ctx.track_embeddings,
                )

            # 人脸识别 — 先插 identities 拿 DB ID 映射，再回填 detections
            if self.ctx.face_identities:
                label_to_id = await bulk_insert_face_identities(session, self.ctx.face_identities)
                if self.ctx.face_detections and label_to_id:
                    for fd in self.ctx.face_detections:
                        db_id = label_to_id.get(fd.pop("_label", ""))
                        if db_id is not None:
                            fd["identity_id"] = db_id
                await bulk_insert_face_detections(session, self.ctx.face_detections)
            elif self.ctx.face_detections:
                await bulk_insert_face_detections(session, self.ctx.face_detections)

            # 车牌识别
            if self.ctx.plate_detections:
                await bulk_insert_plate_detections(session, self.ctx.plate_detections)

            # 场景实体聚合回写（阶段二前已清空）
            if self.ctx.scenes:
                await bulk_update_scenes_entities(session, self.video.id, [
                    {"scene_index": s.scene_index, "entities": s.entities}
                    for s in self.ctx.scenes
                ])

            # 阶段二产物计数（详情抽屉统计条数据源）
            await session.execute(
                update(Video)
                .where(Video.id == self.video.id)
                .values(
                    analysis_entities={
                        "face": len(self.ctx.face_identities) if self.ctx.face_identities else 0,
                        "plate": len(self.ctx.plate_detections) if self.ctx.plate_detections else 0,
                        "ocr": 0,
                    },
                    analysis_progress=1.0,
                )
            )
            await session.commit()

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

    async def _set_processing(self, process_status: str = "PRE_PROCESSING") -> None:
        """修改视频状态为 processing，并记录处理开始时间（任务中心「耗时」）。

        process_status: v0.35 两阶段状态 — run() 阶段一 PRE_PROCESSING，
        run_incremental 阶段二 ANALYZING（词汇对齐前端 ProcessStatus 枚举）。
        """
        from datetime import datetime, timezone
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video.id)
                .values(
                    status=VideoStatus.PROCESSING,
                    processing_started_at=datetime.now(timezone.utc),
                    process_status=process_status,
                )
            )
            await session.commit()

    async def _log_task(self, message: str, level: str = "info") -> None:
        """追加任务日志行（v0.34，task_id = 版本行 video.id）。"""
        from core.repository import append_task_log
        async with self.db_session_factory() as session:
            await append_task_log(session, self.video.id, message, level)

    async def _log_pipeline_config(self, v: Video, enabled: list) -> None:
        """管道配置快照 → 任务日志（系统参数/感知开关/编码/检测/量化/fps 全量，溯源用）。"""
        pl = self.config.get("pipeline", {})
        det = self.config.get("plugins", {}).get("detector", {}) or {}
        emb = self.config.get("plugins", {}).get("embedder", {}) or {}
        cap = self.config.get("plugins", {}).get("captioner", {}) or {}
        profiles = pl.get("encode_profiles", {}) or {}
        cur_profile = v.encode_profile or pl.get("default_encode_profile") or "fast"
        prof = profiles.get(cur_profile, {}) or {}

        def _on(label: str, flag: bool) -> str:
            return f"{label}={'开' if flag else '关'}"

        # 感知/功能开关（多行，每行独立——任务中心逐行可读）
        switches = "  ".join([
            _on("视觉", v.vision_enabled), _on("音频", v.audio_enabled),
            _on("OCR", v.ocr_enabled), _on("描述", v.caption_enabled),
            _on("检测", v.detection_enabled), _on("人脸", v.face_enabled),
            _on("车牌", v.plate_enabled), _on("摘要", v.summary_enabled),
            _on("搜索索引", v.search_index_enabled),
        ])
        await self._log_task(
            f"管道配置：场景类型={v.content_type} 摘要模式={v.summary_mode} 语言={v.language} "
            f"采样帧率={v.sample_fps}fps 场景敏感度={v.segment_threshold} 编码预设={cur_profile} {switches}"
        )
        if v.detection_classes:
            await self._log_task(f"  检测类别：{', '.join(v.detection_classes)}")
        await self._log_task(
            f"  编码（{cur_profile}）：{prof.get('encode_width', '?')}×{prof.get('encode_height', '?')} "
            f"批大小={prof.get('encode_batch_size', '?')} 量化={emb.get('quantization', '无')}"
        )
        if v.detection_enabled:
            await self._log_task(
                f"  检测：YOLO@{det.get('detection_fps', pl.get('detection_fps', 10))}fps "
                f"批大小={det.get('batch_size', 128)} imgsz={det.get('imgsz', 640)} "
                f"置信度={det.get('confidence_threshold', 0.4)} IoU={det.get('iou_threshold', 0.5)}"
            )
        # 实际启用的操作链（含后端/模型来源）
        op_chain = " → ".join(op.label for op in enabled) or "（无启用操作）"
        await self._log_task(f"  操作链：{op_chain}")
        await self._log_task(
            f"  后端：检测={det.get('backend', 'yolo')} 编码器={emb.get('backend', '?')} "
            f"描述={cap.get('backend', '?')}"
        )
