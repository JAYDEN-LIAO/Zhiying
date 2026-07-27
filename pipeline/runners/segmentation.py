"""
pipeline/runners/segmentation.py
═══════════════════════════════════════════════════════════
场景分割 runner — 将视频按镜头切换切分为场景片段。

提取自 pipeline/phase1_qc.py:_run_segmentation()
"""

import logging

from core.interfaces import Scene as SceneData
from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class SegmentRunner(OperationRunner):
    """镜头分割执行器 — 长视频自动降级为固定间隔以规避 TransNetV2 超线性耗时。"""

    # 超过此阈值(秒)的视频跳过 TransNetV2，改用固定间隔切段
    _LONG_VIDEO_THRESHOLD = 1800  # 30 min

    async def run(self, pctx: PipelineContext) -> None:
        await pctx.tracker.update("segmentation")

        duration = pctx.ctx.duration

        # 长视频(B30min) → 固定间隔切段，秒级完成
        if duration and duration > self._LONG_VIDEO_THRESHOLD:
            scenes = await self._time_based_segmentation(duration)
            pctx.ctx.scenes = scenes
            await pctx.tracker.update(
                "segmentation",
                description=f"长视频固定分段完成: 共 {len(scenes)} 个场景 (每 60s 一段)",
            )
            logger.info(
                "[SegmentRunner] Long video (%.0fs > %ds) → time-based: %d scenes",
                duration, self._LONG_VIDEO_THRESHOLD, len(scenes),
            )
            return

        # 短视频 → TransNetV2 神经网络镜头检测
        segmenter = pctx.plugins.get("segmenter")
        if segmenter is None:
            logger.info("[SegmentRunner] Segmenter plugin disabled, skipping")
            return

        sample_fps = pctx.config.get("pipeline", {}).get("sample_fps", 1.0)
        raw_scenes = await segmenter.segment(
            pctx.ctx.file_path, sample_fps=sample_fps,
        )

        scenes = self._build_scenes(raw_scenes)
        pctx.ctx.scenes = scenes
        await pctx.tracker.update(
            "segmentation",
            description=f"镜头分割完成: 共 {len(scenes)} 个场景",
        )
        logger.info("[SegmentRunner] Done: %d scenes", len(scenes))

    # ── 辅助方法 ──

    @staticmethod
    def _build_scenes(raw_scenes: list[dict]) -> list[SceneData]:
        scenes: list[SceneData] = []
        for raw in raw_scenes:
            scene = SceneData(
                scene_id=len(scenes),
                scene_index=raw.get("scene_index", len(scenes)),
                start_sec=raw.get("start_sec", 0.0),
                end_sec=raw.get("end_sec", 0.0),
                keyframe=raw.get("keyframe"),
            )
            scenes.append(scene)
        return scenes

    @staticmethod
    async def _time_based_segmentation(duration: float) -> list[SceneData]:
        """固定 60s 间隔切段 — 长视频专用，O(1) 无模型推理。"""
        seg_duration = 60.0
        scenes: list[SceneData] = []
        start = 0.0
        idx = 0
        while start < duration:
            end = min(start + seg_duration, duration)
            scenes.append(SceneData(
                scene_id=idx,
                scene_index=idx,
                start_sec=round(start, 2),
                end_sec=round(end, 2),
                keyframe=None,
            ))
            idx += 1
            start = end
        return scenes
