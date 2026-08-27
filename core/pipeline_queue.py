"""
core/pipeline_queue.py
═══════════════════════════════════════════════════════════
全局视频管道任务队列 — FIFO + 有界并发 worker 池 + DB 持久化。

技术主管要求：文件库会批量上传视频，需队列排队处理，避免并发管道 GPU OOM。
接口保持异步（yunzhi jobs 202 / 上传接口不变），内部统一入队。

设计：
  - FIFO：asyncio.Queue（worker 逐个取任务，先进先出）
  - 有界并发：worker 数 = pipeline.max_concurrent_videos（0/未设 → 1 串行防 OOM）
  - DB 持久化：pipeline_tasks 表记录 queued/running/completed/failed，
    重启后 recover() 重入队/续跑，回调 URL + token 存 payload_json 保证恢复后仍可回调
  - 幂等：dedup_key 列，重启后查重不重复入队

任务类型：
  - yunzhi_job   → execute_yunzhi_task（建视频+管道+回调；恢复时按 video_id 续跑）
  - pipeline     → execute_pipeline_task（对已有视频跑全管道）
  - incremental  → execute_incremental_task（增量补跑）
"""

import asyncio
import json
import logging
import uuid

logger = logging.getLogger(__name__)

# 哨兵：worker 收到后退出（避免取消 Queue.get() 等待者的竞态挂起）
_STOP = object()


class PipelineQueue:
    """全局 FIFO 任务队列。单进程（uvicorn 单 worker）内有效。"""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._idle: set[asyncio.Task] = set()      # 空闲（等 queue.get）的 worker，可安全取消
        self._retiring: set[asyncio.Task] = set()  # 标记为"跑完当前后退出"的 worker
        self._max_workers = 1
        self._started = False
        self._db: callable | None = None            # async session factory
        self._executors: dict[str, callable] = {}   # type → (task_id, payload, video_id) -> coroutine

    # ── 生命周期 ──────────────────────────────────────────

    def bind(self, db_session_factory, executors: dict[str, callable], max_workers: int = 1) -> None:
        """绑定 DB 会话工厂 + 执行器 + worker 数。可被测试注入 mock。"""
        self._db = db_session_factory
        self._executors = executors
        self._max_workers = max(1, int(max_workers or 1))
        if not self._started:
            self._started = True
            for _ in range(self._max_workers):
                self._workers.append(asyncio.create_task(self._worker()))
            logger.info("[PipelineQueue] started %d worker(s)", self._max_workers)

    def configure(self, max_workers: int) -> None:
        """运行时调整 worker 数（配置变更）：增加直接补；减少先取消空闲、否则标记 retire。"""
        target = max(1, int(max_workers or 1))
        if target == self._max_workers:
            return
        self._max_workers = target
        if not self._started:
            return
        # 增加
        while len(self._workers) < target:
            self._workers.append(asyncio.create_task(self._worker()))
        # 减少：优先取消空闲 worker；否则标记 retire（跑完当前任务后退出）
        while len(self._workers) - len(self._retiring) > target:
            if self._idle:
                w = self._idle.pop()
                if w in self._workers:
                    self._workers.remove(w)
                w.cancel()
            else:
                non_retiring = [w for w in self._workers if w not in self._retiring]
                if not non_retiring:
                    break
                self._retiring.add(non_retiring[-1])
        logger.info("[PipelineQueue] reconfigured to %d worker(s)", target)

    # ── 入队 ──────────────────────────────────────────────

    async def enqueue(
        self,
        task_type: str,
        payload: dict,
        dedup_key: str | None = None,
        video_id: str | None = None,
    ) -> str:
        """入队一个任务：INSERT queued 行（DB 持久化）+ 喂内存队列。立即返回 task_id。"""
        task_id = str(uuid.uuid4())
        # ⚠️ 调用方一般把 video_id 放在 payload 里（{"video_id": ...}）而非形参；
        #   形参未传时从 payload 取，保证 pipeline_tasks.video_id 列非空
        #   → 侧栏「排队中」黄徽章 / _task_to_dto.queued 靠它匹配（此前一直 NULL 查不到）
        if video_id is None and isinstance(payload, dict):
            video_id = payload.get("video_id")
        if self._db is not None:
            from core.models import PipelineTask
            async with self._db() as session:
                session.add(PipelineTask(
                    id=uuid.UUID(task_id),
                    type=task_type,
                    dedup_key=dedup_key,
                    video_id=uuid.UUID(video_id) if video_id else None,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    status="queued",
                ))
                await session.commit()
        await self._queue.put((task_id, task_type, payload, video_id))
        return task_id

    # ── worker ────────────────────────────────────────────

    async def _worker(self) -> None:
        task = asyncio.current_task()
        try:
            while True:
                # retire 检查放在取任务前：retiring worker 不再取新任务
                if task in self._retiring:
                    self._retiring.discard(task)
                    if task in self._workers:
                        self._workers.remove(task)
                    return
                self._idle.add(task)
                try:
                    item = await self._queue.get()
                except asyncio.CancelledError:
                    self._idle.discard(task)
                    return
                finally:
                    self._idle.discard(task)
                # 哨兵：退出（不用取消 getter，避免竞态挂起）
                if item is _STOP:
                    self._queue.task_done()
                    return
                try:
                    await self._run_item(item)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _run_item(self, item: tuple) -> None:
        task_id, task_type, payload, video_id = item
        await self._mark(task_id, "running")
        logger.info("[PipelineQueue] task %s (%s) running", task_id, task_type)
        try:
            executor = self._executors.get(task_type)
            if executor is None:
                raise RuntimeError(f"no executor for task type {task_type}")
            await executor(task_id, payload, video_id)
            await self._mark(task_id, "completed")
            logger.info("[PipelineQueue] task %s (%s) completed", task_id, task_type)
        except Exception as e:
            logger.exception("[PipelineQueue] task %s (%s) crashed", task_id, task_type)
            await self._mark(task_id, "failed", str(e))

    async def _mark(self, task_id: str, status: str, error: str | None = None) -> None:
        if self._db is None:
            return
        from core.models import PipelineTask
        from sqlalchemy import select
        async with self._db() as session:
            row = (await session.execute(
                select(PipelineTask).where(PipelineTask.id == uuid.UUID(task_id))
            )).scalar_one_or_none()
            if row is not None:
                row.status = status
                row.error = error
                await session.commit()

    # ── 启动恢复 ──────────────────────────────────────────

    async def shutdown(self) -> None:
        """停止所有 worker：入队哨兵让空闲 worker 退出；忙的限时等待，超时强制取消。

        应用关停 / 测试 teardown 调用；不取消 Queue.get() 等待者（避免竞态挂起）。
        """
        self._started = False
        # 每个 worker 一个哨兵 → 空闲 worker 收到即退出
        for _ in range(len(self._workers)):
            await self._queue.put(_STOP)
        for w in list(self._workers):
            try:
                await asyncio.wait_for(asyncio.shield(w), timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                w.cancel()
        self._workers.clear()
        self._retiring.clear()
        self._idle.clear()

    async def recover(self) -> None:
        """启动恢复：queued → 重入队；running+yunzhi → 续跑（回退 queued）；running+pipeline/incremental → 标视频 failed。"""
        if self._db is None:
            return
        from core.models import PipelineTask, Video, VideoStatus
        from sqlalchemy import select
        async with self._db() as session:
            rows = (await session.execute(
                select(PipelineTask).where(PipelineTask.status.in_(["queued", "running"]))
            )).scalars().all()
            # 一次性取活视频 id 集：queued 任务的视频可能已在排队期间被删除
            #（v0.6.2 前 delete_video 不清队列行）→ 重入队只会空转成僵尸任务。
            # 视频表不可查询时（极简单测环境无 videos 表）→ 置 None 退回旧行为，
            # 不阻断恢复流程（生产 PostgreSQL 恒有该表，恒走校验）。
            try:
                live_video_ids = {row[0] for row in await session.execute(select(Video.id))}
            except Exception:
                logger.warning("[PipelineQueue] recover: cannot verify video existence, skipping stale-task filter")
                live_video_ids = None
        for row in rows:
            try:
                payload = json.loads(row.payload_json)
                video_id = str(row.video_id) if row.video_id else None
                if live_video_ids is not None and row.video_id is not None and row.video_id not in live_video_ids:
                    # 视频已不存在 → 标 failed 而非重入队（yunzhi 已建视频的续跑同理）
                    async with self._db() as session:
                        db_row = (await session.execute(
                            select(PipelineTask).where(PipelineTask.id == row.id)
                        )).scalar_one_or_none()
                        if db_row is not None:
                            db_row.status = "failed"
                            db_row.error = "视频不存在（可能在排队期间被删除）"
                            await session.commit()
                    logger.info(
                        "[PipelineQueue] recover skipped task %s (%s): video %s gone",
                        row.id, row.type, video_id,
                    )
                    continue
                if row.status == "queued":
                    await self._queue.put((str(row.id), row.type, payload, video_id))
                    logger.info("[PipelineQueue] recovered queued task %s (%s)", row.id, row.type)
                elif row.type == "yunzhi_job":
                    # running 云智任务 → 续跑（有 video_id 复用，防重复建视频）；状态回退 queued
                    async with self._db() as session:
                        db_row = (await session.execute(
                            select(PipelineTask).where(PipelineTask.id == row.id)
                        )).scalar_one_or_none()
                        if db_row is not None:
                            db_row.status = "queued"
                            await session.commit()
                    await self._queue.put((str(row.id), row.type, payload, video_id))
                    logger.info("[PipelineQueue] recovered running yunzhi_job %s -> resume", row.id)
                else:
                    # running pipeline/incremental → 不静默重跑：标视频 failed（用户可重跑）
                    if row.video_id:
                        async with self._db() as session:
                            v = (await session.execute(
                                select(Video).where(Video.id == row.video_id)
                            )).scalar_one_or_none()
                            if v is not None and v.status == VideoStatus.PROCESSING:
                                v.status = VideoStatus.FAILED
                                v.error_message = "服务重启中断，请重新处理"
                                await session.commit()
                    await self._mark(str(row.id), "failed", "服务重启中断")
                    logger.info("[PipelineQueue] interrupted %s task %s -> video marked failed", row.type, row.id)
            except Exception:
                logger.exception("[PipelineQueue] recover failed for task %s", row.id)


# 模块级单例（main.py lifespan bind + recover）
pipeline_queue = PipelineQueue()
