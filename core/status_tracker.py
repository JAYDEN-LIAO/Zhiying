"""
core/status_tracker.py
═══════════════════════════════════════════════════════════
Pipeline 进度持久化 — 动态权重 + 操作内子进度插值。

v0.8: 根据 operations 的 progress_weight 按比例分配进度范围，
      支持 sub_progress（0.0~1.0）在操作内部平滑推进。
"""

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
    ):
        self.video_id = video_id
        self.db_session_factory = db_session_factory
        self._ops = operations or []
        self._ranges: dict[str, tuple[float, float]] = {}  # op.name → (start, end)
        self._descriptions: dict[str, str] = {}
        self._compute_weights()

    # ── 权重计算 ──

    def _compute_weights(self) -> None:
        """按 progress_weight 比例分配每个 operation 的进度范围。

        例: duration(0.02) + segmentation(0.15) + keyframes(0.15) + caption(0.20)
             → ranges = {
                 "duration":     (0.00, 0.04),
                 "segmentation": (0.04, 0.33),
                 "keyframes":    (0.33, 0.62),
                 "caption":      (0.62, 1.00),
               }
        caption 权重最大 → 占据最大的进度条区间 → 缓慢推进，不会冻住。
        """
        if not self._ops:
            self._ranges = {k: (v, v) for k, v in self.PHASE_WEIGHTS.items()}
            self._descriptions = dict(self.PHASE_DESCRIPTIONS)
            return

        total_weight = sum(op.progress_weight for op in self._ops)
        if total_weight <= 0:
            total_weight = float(len(self._ops))

        cumulative = 0.0
        for op in self._ops:
            w = op.progress_weight if op.progress_weight > 0 else (1.0 / len(self._ops))
            start = cumulative / total_weight
            end = (cumulative + w) / total_weight
            # 最后一个操作强制到 1.0，避免浮点误差
            if op is self._ops[-1]:
                end = 1.0
            self._ranges[op.name] = (round(start, 4), round(end, 4))
            self._descriptions[op.name] = op.description or op.label or op.name
            cumulative += w

    # ── 进度更新 ──

    async def update(
        self,
        phase: str,
        progress: float | None = None,
        sub_progress: float | None = None,
        description: str | None = None,
    ) -> None:
        """更新进度。

        Args:
            phase: 阶段名（对应 Operation.name）。
            progress: 绝对值 0.0~1.0。为 None 时从范围表计算。
            sub_progress: 操作内部进度 0.0~1.0。
                          给定后，progress = start + sub_progress * (end - start)。
            description: 进度描述文本。
        """
        if progress is not None:
            val = progress
        elif sub_progress is not None:
            start, end = self._ranges.get(phase, (0.0, 1.0))
            sub = max(0.0, min(1.0, sub_progress))
            val = start + sub * (end - start)
        else:
            # 无 sub_progress：使用该操作范围的起始值
            val = self._ranges.get(phase, (0.0, 1.0))[0]

        if description is None:
            description = self._descriptions.get(phase, phase)

        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video_id)
                .values(
                    progress=round(val, 4),
                    status_detail=description,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    # ── 最终状态 ──

    async def mark_completed(self) -> None:
        """标记视频处理完成。"""
        await self._set_status(VideoStatus.COMPLETED, progress=1.0)

    async def mark_failed(self, error: str) -> None:
        """标记视频处理失败。"""
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video_id)
                .values(
                    status=VideoStatus.FAILED,
                    error_message=error,
                    progress=self._ranges.get("completed", (1.0, 1.0))[0],
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

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
