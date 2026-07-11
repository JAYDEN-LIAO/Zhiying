"""
core/status_tracker.py
═══════════════════════════════════════════════════════════
Pipeline 执行期间更新 videos 表的 status / progress / current_phase。

Pipeline 各阶段调用 update() 报告进度，
完成或失败时调用 mark_completed() / mark_failed()。
"""

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.models import Video, VideoStatus


class StatusTracker:
    """异步状态更新器 — 负责 Pipeline 进度持久化。"""

    # 阶段名 → 全局进度值映射（0.0 ~ 1.0）
    PHASE_WEIGHTS: dict[str, float] = {
        "phase_1_qc":       0.0,
        "phase_1_audio":    0.10,
        "phase_1_segment":  0.15,
        "phase_2_vision":   0.20,
        "phase_2_ocr":      0.30,
        "phase_3_align":    0.40,
        "phase_4_caption":  0.50,
        "phase_4_embed":    0.75,
        "phase_5_summary":  0.85,
        "completed":        1.0,
    }

    # 阶段名 → 前端友好描述
    PHASE_DESCRIPTIONS: dict[str, str] = {
        "phase_1_qc":       "质量检测中...",
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
    ):
        self.video_id = video_id
        self.db_session_factory = db_session_factory

    async def update(
        self,
        phase: str,
        progress: float | None = None,
        description: str | None = None,
    ) -> None:
        """更新 videos 表的进度与阶段信息。

        Args:
            phase: 阶段名（如 "phase_2_vision"），将反映在 current_phase 字段。
            progress: 具体进度值 0.0~1.0。为 None 时从 PHASE_WEIGHTS 获取。
            description: 进度描述文本。为 None 时从 PHASE_DESCRIPTIONS 获取。
        """
        if progress is None:
            progress = self.PHASE_WEIGHTS.get(phase, 0.0)
        if description is None:
            description = self.PHASE_DESCRIPTIONS.get(phase, phase)

        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video_id)
                .values(
                    progress=progress,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    async def mark_completed(self) -> None:
        """标记视频处理完成。"""
        await self._set_status(
            VideoStatus.COMPLETED, progress=1.0,
        )

    async def mark_failed(self, error: str) -> None:
        """标记视频处理失败，记录错误信息。

        Args:
            error: 错误消息。
        """
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video_id)
                .values(
                    status=VideoStatus.FAILED,
                    error_message=error,
                    progress=self.PHASE_WEIGHTS.get("completed", 1.0),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    async def _set_status(self, status: VideoStatus, progress: float) -> None:
        """内部辅助 — 设置视频状态和进度。"""
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
