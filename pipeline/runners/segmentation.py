"""
pipeline/runners/segmentation.py
═══════════════════════════════════════════════════════════
场景分割 runner — 将视频按镜头切换切分为场景片段。

v0.33：引入目标场景数上限 max_scenes（pipeline.max_scenes，默认 6）：
  - 长视频(>30min) 不再按 60s 机械切段，而是均匀切成 max_scenes 段；
  - TransNetV2 识别出超过 max_scenes 的场景时，按累计时长合并到上限，
    避免超长/多镜头视频产生碎片化场景（也稳定下游 caption API 调用成本）。
"""

import logging

from core.interfaces import Scene as SceneData
from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class SegmentRunner(OperationRunner):
    """镜头分割执行器 — TransNetV2（≤30min）+ 长视频固定段数 + 场景数上限合并。"""

    # 超过此阈值(秒)的视频跳过 TransNetV2，改用固定段数切段
    _LONG_VIDEO_THRESHOLD = 1800  # 30 min

    @staticmethod
    def _max_scenes(config: dict) -> int:
        """目标场景数上限（pipeline.max_scenes，默认 6）。"""
        return int((config.get("pipeline", {}) or {}).get("max_scenes", 6))

    async def run(self, pctx: PipelineContext) -> None:
        await pctx.tracker.update("segmentation")

        duration = pctx.ctx.duration
        max_scenes = self._max_scenes(pctx.config)

        # 长视频(>30min) → 固定段数均匀切段，秒级完成，规避 TransNetV2 逐帧推理耗时
        if duration and duration > self._LONG_VIDEO_THRESHOLD:
            scenes = await self._fixed_count_segmentation(duration, max_scenes)
            pctx.ctx.scenes = scenes
            await pctx.tracker.update(
                "segmentation",
                description=f"长视频固定分段完成: 共 {len(scenes)} 个场景",
            )
            logger.info(
                "[SegmentRunner] Long video (%.0fs > %ds) → fixed %d scenes",
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
        if max_scenes and len(scenes) > max_scenes:
            scenes = self._merge_to_max(scenes, duration, max_scenes)

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
    async def _fixed_count_segmentation(
        duration: float, max_scenes: int,
    ) -> list[SceneData]:
        """固定段数均匀切段 — 长视频专用，O(1) 无模型推理。

        段长 = duration / max_scenes，任意长视频都产出 max_scenes 段（尾部取整）。
        """
        count = max(int(max_scenes), 1)
        seg_duration = duration / count
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

    @classmethod
    def _merge_to_max(
        cls, scenes: list[SceneData], duration: float, max_scenes: int,
    ) -> list[SceneData]:
        """TransNetV2 结果超上限 → 按累计时长合并到上限段数。

        保留 TransNetV2 检测到的边界直到累计达到目标段长（duration / max_scenes），
        合并出的段落落在相对自然的切换点，而非机械均匀重切。
        """
        if len(scenes) <= max_scenes:
            return scenes
        target = (duration or 0.0) / max(max_scenes, 1)
        if target <= 0:
            return scenes[:max_scenes]

        merged: list[SceneData] = []
        start_sec = scenes[0].start_sec
        accum = 0.0
        for s in scenes:
            accum += s.end_sec - s.start_sec
            if accum >= target:
                merged.append(SceneData(
                    scene_id=len(merged),
                    scene_index=len(merged),
                    start_sec=round(start_sec, 2),
                    end_sec=round(s.end_sec, 2),
                    keyframe=None,
                ))
                start_sec = s.end_sec
                accum = 0.0

        # 尾部剩余（不足一段的尾巴并入最后一段，保证覆盖全视频）
        if start_sec < scenes[-1].end_sec - 1e-9:
            if merged:
                merged[-1].end_sec = round(scenes[-1].end_sec, 2)
            else:
                merged.append(SceneData(
                    scene_id=0, scene_index=0,
                    start_sec=round(scenes[0].start_sec, 2),
                    end_sec=round(scenes[-1].end_sec, 2),
                    keyframe=None,
                ))
        return merged
