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
    """镜头分割执行器。"""

    async def run(self, pctx: PipelineContext) -> None:
        segmenter = pctx.plugins.get("segmenter")
        if segmenter is None:
            logger.info("[SegmentRunner] Segmenter plugin disabled, skipping")
            return

        await pctx.tracker.update("segmentation")

        sample_fps = pctx.config.get("pipeline", {}).get("sample_fps", 1.0)
        raw_scenes = await segmenter.segment(
            pctx.ctx.file_path, sample_fps=sample_fps,
        )

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

        pctx.ctx.scenes = scenes
        await pctx.tracker.update(
            "segmentation",
            description=f"镜头分割完成: 共 {len(scenes)} 个场景",
        )
        logger.info("[SegmentRunner] Done: %d scenes", len(scenes))
