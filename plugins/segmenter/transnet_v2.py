"""
plugins/segmenter/transnet_v2.py
═══════════════════════════════════════════════════════════
TransNetV2 镜头分割插件（PyTorch 实现）。

基于 transnetv2-pytorch，检测真实镜头切换边界。
模型推理通过 asyncio.to_thread 投递线程池，不阻塞事件循环。

依赖: pip install transnetv2-pytorch
权重: 首次运行时自动下载 ~30MB
"""

import asyncio
import logging

from core.interfaces import BaseSegmenter
from core.exceptions import PluginLoadError

logger = logging.getLogger(__name__)


class TransNetV2Segmenter(BaseSegmenter):
    """基于 TransNetV2 的镜头分割实现。

    使用预训练神经网络逐帧分析画面特征，
    检测镜头切换点（硬切/渐变），生成精确的场景段落。

    Args:
        device: 推理设备 ("cuda" / "cpu")。
        threshold: 场景切换检测阈值 (0.0~1.0)，越低越敏感。
        scene_min_duration: 最短场景时长（秒），短于此值的场景被过滤。
    """

    def __init__(
        self,
        device: str = "cuda",
        threshold: float = 0.5,
        scene_min_duration: float = 1.0,
        **kwargs,
    ):
        try:
            from transnetv2_pytorch import TransNetV2
        except ImportError as e:
            raise PluginLoadError(
                "transnetv2-pytorch not installed. Run: pip install transnetv2-pytorch"
            ) from e

        self._model = TransNetV2()
        self.device = device
        self.threshold = threshold
        self.scene_min_duration = scene_min_duration

        logger.info(
            "[TransNetV2] Loaded device=%s threshold=%.2f min_duration=%.1fs",
            device, threshold, scene_min_duration,
        )

    async def segment(
        self,
        video_path: str,
        sample_fps: float = 1.0,
    ) -> list[dict]:
        """将视频按镜头切换切分为场景片段。

        Args:
            video_path: 视频文件路径。
            sample_fps: （本参数由 TransNetV2 内部处理，保持接口兼容）。

        Returns:
            [
                {
                    "scene_index": int,
                    "start_sec": float,
                    "end_sec": float,
                    "keyframe": None,      # 后续由 engine 统一抽取
                },
            ]
        """
        try:
            predictions = await asyncio.to_thread(
                self._sync_predict, video_path,
            )
            scenes = await asyncio.to_thread(
                self._predictions_to_scenes, predictions, video_path,
            )
        except Exception as e:
            logger.exception("[TransNetV2] Segmentation failed: %s", e)
            raise

        logger.info(
            "[TransNetV2] %s → %d scenes",
            video_path, len(scenes),
        )
        return scenes

    def _sync_predict(self, video_path: str) -> list:
        """同步模型推理 — 在线程池中执行。

        predict_video 返回 (video_frames, single_frame_preds, all_frame_preds)，
        取 single_frame_preds 转换为 numpy 用于后处理。
        """
        _, single_frame_preds, _ = self._model.predict_video(
            video_path, quiet=True,
        )
        return single_frame_preds.cpu().detach().numpy().flatten()

    def _predictions_to_scenes(
        self,
        predictions: list,
        video_path: str,
    ) -> list[dict]:
        """将 TransNetV2 原始预测转换为标准场景列表。

        策略：基于帧级预测值穿越 threshold 的位置定位镜头切换点。
        """
        fps = self._model.get_video_fps(video_path)

        # ── 寻找镜头切换点 ──
        borders = []
        for i in range(1, len(predictions)):
            if predictions[i - 1] < self.threshold <= predictions[i]:
                borders.append(i)

        # ── 转换为场景列表 ──
        scenes: list[dict] = []
        prev = 0

        for border in borders:
            start_sec = prev / fps
            end_sec = border / fps
            if end_sec - start_sec >= self.scene_min_duration:
                scenes.append({
                    "scene_index": len(scenes),
                    "start_sec": round(start_sec, 2),
                    "end_sec": round(end_sec, 2),
                    "keyframe": None,
                })
            prev = border

        # ── 最后一个场景（尾部剩余） ──
        last_sec = len(predictions) / fps
        last_start = prev / fps
        if last_sec - last_start >= self.scene_min_duration:
            scenes.append({
                "scene_index": len(scenes),
                "start_sec": round(last_start, 2),
                "end_sec": round(last_sec, 2),
                "keyframe": None,
            })

        return scenes
