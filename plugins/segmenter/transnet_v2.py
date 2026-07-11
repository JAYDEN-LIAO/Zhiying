"""
plugins/segmenter/transnet_v2.py
═══════════════════════════════════════════════════════════
TransNetV2 镜头分割插件。

模型推理（model.predict_video）是同步 GPU 密集型调用，
必须使用 asyncio.to_thread() 包裹。
"""

import asyncio
import logging

from core.interfaces import BaseSegmenter
from core.exceptions import PluginLoadError

logger = logging.getLogger(__name__)


class TransNetV2Segmenter(BaseSegmenter):
    """基于 TransNetV2 的镜头分割实现。

    Args:
        device: 推理设备 ("cuda" / "cpu")。
        scene_min_duration: 最短场景时长（秒），短于此值的场景将被过滤。
    """

    def __init__(
        self,
        device: str = "cuda",
        scene_min_duration: float = 1.0,
        **kwargs,
    ):
        try:
            from transnetv2 import TransNetV2
        except ImportError as e:
            raise PluginLoadError(
                "TransNetV2 package not installed. "
                "See: https://github.com/soCzech/TransNetV2"
            ) from e

        self._model = TransNetV2()
        self.device = device
        self.scene_min_duration = scene_min_duration
        logger.info(
            "[TransNetV2] Loaded device=%s min_duration=%.1fs",
            device, scene_min_duration,
        )

    async def segment(
        self,
        video_path: str,
        sample_fps: float = 1.0,
    ) -> list[dict]:
        """将视频按镜头切换切分为场景片段。

        Args:
            video_path: 视频文件路径。
            sample_fps: 抽帧频率（帧/秒）。

        Returns:
            [
                {
                    "scene_index": int,
                    "start_sec": float,
                    "end_sec": float,
                    "keyframe": None,        # 后续由 engine 统一抽取
                },
            ]
        """
        try:
            predictions = await asyncio.to_thread(
                self._sync_predict,
                video_path,
            )
        except Exception as e:
            logger.exception("[TransNetV2] Segmentation failed")
            raise

        scenes = self._predictions_to_scenes(predictions, video_path, sample_fps)

        logger.info(
            "[TransNetV2] Segmented %d scenes from %s",
            len(scenes), video_path,
        )
        return scenes

    def _sync_predict(self, video_path: str):
        """同步模型推理 — 在线程池中执行。"""
        return self._model.predict_video(video_path)

    def _predictions_to_scenes(
        self,
        predictions,
        video_path: str,
        sample_fps: float,
    ) -> list[dict]:
        """将 TransNetV2 原始输出转换为标准场景列表。"""
        # predictions: (single_frame_predictions, (optional) many_frame_predictions)
        single_frame_preds = predictions[0]

        # 找出场景切换帧索引
        # TransNetV2 输出形状: (num_frames, 1)，值 > 0.5 表示场景切换
        scene_borders = []
        for i in range(1, len(single_frame_preds)):
            if (
                single_frame_preds[i - 1] < 0.5 <= single_frame_preds[i]
                or single_frame_preds[i] >= 0.5
            ):
                if single_frame_preds[i] >= 0.5:
                    scene_borders.append(i)

        # 构建场景列表
        scenes: list[dict] = []
        prev_border = 0

        for idx, border in enumerate(scene_borders):
            start_frame = prev_border
            end_frame = border

            start_sec = start_frame / sample_fps
            end_sec = end_frame / sample_fps
            duration = end_sec - start_sec

            # 过滤过短场景
            if duration >= self.scene_min_duration:
                scenes.append({
                    "scene_index": len(scenes),
                    "start_sec": round(start_sec, 2),
                    "end_sec": round(end_sec, 2),
                    "keyframe": None,
                })

            prev_border = border

        # 最后一个场景（尾部）
        if predictions[0] is not None:
            total_frames = len(single_frame_preds)
            last_start = prev_border / sample_fps
            last_end = total_frames / sample_fps
            if last_end - last_start >= self.scene_min_duration:
                scenes.append({
                    "scene_index": len(scenes),
                    "start_sec": round(last_start, 2),
                    "end_sec": round(last_end, 2),
                    "keyframe": None,
                })

        return scenes
