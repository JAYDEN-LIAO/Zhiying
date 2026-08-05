"""
core/status_tracker.py
═══════════════════════════════════════════════════════════
Pipeline 进度持久化 — 动态权重 + 各操作真实子进度聚合。

根据本次启用的 operations 权重聚合各操作的真实子进度，
      并行操作的进度统一计算为加权总进度。
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Video, VideoStatus


class StatusTracker:
    """异步状态更新器 — Pipeline 进度持久化。

    进度计算：
      - 根据 operations 的 progress_weight 按比例分配范围 → _ranges
      - update() 接受可选的 sub_progress（0.0~1.0）在操作内部插值
      - 例: caption weight=0.20, 总权重=1.0 → 范围 [0.50, 0.70]
             sub_progress=0.5 → progress=0.60（caption 操作内一半）

    若无 operations（旧调用方），回退到静态 PHASE_WEIGHTS。
    """

    # ── 静态回退（deprecated）──
    PHASE_WEIGHTS: dict[str, float] = {
        "phase_1_audio":    0.0,
        "phase_1_segment":  0.15,
        "phase_2_vision":   0.20,
        "phase_2_ocr":      0.30,
        "phase_3_align":    0.40,
        "phase_4_caption":  0.50,
        "phase_4_embed":    0.75,
        "phase_5_summary":  0.85,
        "completed":        1.0,
    }

    PHASE_DESCRIPTIONS: dict[str, str] = {
        "phase_1_audio":    "音频抽取与转录中...",
        "phase_1_segment":  "镜头分割中...",
        "phase_2_vision":   "物体检测中...",
        "phase_2_ocr":      "文字提取中...",
        "phase_3_align":    "模态对齐中...",
        "phase_4_caption":  "深度理解中...",
        "phase_4_embed":    "向量编码中...",
        "phase_5_summary":  "摘要生成中...",
    }

    def __init__(
        self,
        video_id: str,
        db_session_factory: async_sessionmaker[AsyncSession],
        operations: list | None = None,
        on_progress: Callable[[float, str], Awaitable[None]] | None = None,
    ):
        """进度持久化。

        on_progress: 可选回调 (overall_progress 0~1, description) → await。
        云智自动化任务用它把 Cerno 管道进度推到平台 callback.progressUrl；
        回调异常吞掉，不阻塞管道。
        """
        self.video_id = video_id
        self.db_session_factory = db_session_factory
        self._on_progress = on_progress
        self._ops = operations or []
        self._ranges: dict[str, tuple[float, float]] = {}  # op.name → (start, end)
        self._descriptions: dict[str, str] = {}
        self._weights: dict[str, float] = {}
        self._op_progress: dict[str, float] = {}
        self._overall_progress = 0.0
        self._lock = asyncio.Lock()
        self._compute_weights()

    # ── 权重计算 ──

    def _compute_weights(self) -> None:
        """根据本次实际启用的 operations 建立权重和进度状态。"""
        if not self._ops:
            self._ranges = {k: (v, v) for k, v in self.PHASE_WEIGHTS.items()}
            self._descriptions = dict(self.PHASE_DESCRIPTIONS)
            return

        raw_weights = {
            op.name: (op.progress_weight if op.progress_weight > 0 else 1.0)
            for op in self._ops
        }
        total_weight = sum(raw_weights.values()) or 1.0
        self._weights = {name: weight / total_weight for name, weight in raw_weights.items()}
        self._op_progress = {op.name: 0.0 for op in self._ops}

        cumulative = 0.0
        for i, op in enumerate(self._ops):
            start = cumulative / total_weight
            end = (cumulative + raw_weights[op.name]) / total_weight
            if i == len(self._ops) - 1:
                end = 1.0
            self._ranges[op.name] = (round(start, 4), round(end, 4))
            self._descriptions[op.name] = op.description or op.label or op.name
            cumulative += raw_weights[op.name]

    # ── 进度更新 ──

    async def update(
        self,
        phase: str,
        progress: float | None = None,
        sub_progress: float | None = None,
        description: str | None = None,
    ) -> None:
        """记录 operation 子进度，并持久化所有启用 operation 的加权总进度。"""
        async with self._lock:
            if sub_progress is not None and phase in self._op_progress:
                sub = max(0.0, min(1.0, sub_progress))
                # 单个 operation 只允许前进，避免并行更新造成进度回退。
                self._op_progress[phase] = max(self._op_progress[phase], sub)
                val = sum(
                    self._weights[name] * self._op_progress[name]
                    for name in self._op_progress
                )
            elif progress is not None:
                val = max(0.0, min(1.0, progress))
            elif sub_progress is not None:
                start, end = self._ranges.get(phase, (0.0, 1.0))
                sub = max(0.0, min(1.0, sub_progress))
                val = start + sub * (end - start)
            else:
                val = self._overall_progress

            self._overall_progress = max(self._overall_progress, val)
            if description is None:
                description = self._descriptions.get(phase, phase)

            async with self.db_session_factory() as session:
                await session.execute(
                    update(Video)
                    .where(Video.id == self.video_id)
                    .values(
                        progress=round(self._overall_progress, 4),
                        status_detail=description,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()

            if self._on_progress is not None:
                try:
                    await self._on_progress(self._overall_progress, description)
                except Exception:
                    # 平台回调失败（网络抖动/超时）不阻塞管道
                    pass

    # ── 最终状态 ──

    async def mark_completed(self) -> None:
        """标记视频处理完成。"""
        async with self._lock:
            self._overall_progress = 1.0
            await self._set_status(VideoStatus.COMPLETED, progress=1.0)
            if self._on_progress is not None:
                try:
                    await self._on_progress(1.0, "处理完成")
                except Exception:
                    pass

    async def mark_failed(self, error: str) -> None:
        """标记视频处理失败，保留失败时的真实进度。"""
        async with self._lock:
            async with self.db_session_factory() as session:
                await session.execute(
                    update(Video)
                    .where(Video.id == self.video_id)
                    .values(
                        status=VideoStatus.FAILED,
                        error_message=error,
                        progress=round(self._overall_progress, 4),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
            if self._on_progress is not None:
                try:
                    await self._on_progress(self._overall_progress, f"处理失败: {error}")
                except Exception:
                    pass

    async def _set_status(self, status: VideoStatus, progress: float) -> None:
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video_id)
                .values(
                    status=status,
                    progress=progress,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
