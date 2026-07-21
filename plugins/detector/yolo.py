"""
plugins/detector/yolo.py
═══════════════════════════════════════════════════════════
YOLO11 物体检测 + 追踪 — 实现 BaseDetector 批量接口。

使用 ultralytics YOLO11s（~22 MB），GPU 批量推理 + 内置 BoT-SORT 追踪。
model.track(persist=True) 替代手写追踪器，跨 batch 保持 track ID 一致。
"""

import asyncio
import logging

import numpy as np

from core.interfaces import BaseDetector

logger = logging.getLogger(__name__)

# COCO 80 类名（YOLO11 原生输出）
COCO_CLASSES: list[str] = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
]


class YoloDetector(BaseDetector):
    """YOLO11 物体检测 + 追踪 — 批量 GPU 推理 + 内置 BoT-SORT。

    参数从 config.yaml plugins.detector 传入：
    - model: 模型文件名，默认 yolo26s.pt
    - confidence_threshold: 置信度阈值，默认 0.4
    - iou_threshold: NMS IoU 阈值，默认 0.5

    detect() 内部调用 model.track(persist=True)，输出每帧检测物自带 track_id。
    track ID 跨 batch 保持一致，处理新视频前需调用 reset_tracker()。
    """

    def __init__(
        self,
        model: str = "yolo26s.pt",
        confidence_threshold: float = 0.4,
        iou_threshold: float = 0.5,
        **kwargs,
    ) -> None:
        self._model_name = model
        self._conf = confidence_threshold
        self._iou = iou_threshold

        # 延迟加载 — 首次调用 detect() 时加载模型，避免 import 时下载权重
        self._model = None

        # 类别过滤 — None = 全部 80 类
        self._target_class_ids: list[int] | None = None

    # ── 公开接口 ──

    async def detect(self, frames: list[np.ndarray]) -> list[list[dict]]:
        """批量检测+追踪（异步包装，内部走 asyncio.to_thread）。

        Returns:
            与 frames 等长的列表。每个元素是该帧的检测物列表::

                [{bbox, confidence, class_name, track_id}, ...]

            track_id 由 ultralytics 内置 BoT-SORT 分配，跨 batch 保持一致。
        """
        if self._model is None:
            await asyncio.to_thread(self._load_model)

        return await asyncio.to_thread(self._sync_track, frames)

    def reset_tracker(self) -> None:
        """重置追踪器状态 — 处理新视频前调用，清除跨视频的 track ID 残留。"""
        if self._model is not None and hasattr(self._model, "predictor"):
            self._model.predictor = None
            logger.debug("[YoloDetector] Tracker reset for new video")

    def set_target_classes(self, classes: list[str] | None) -> None:
        """设置目标检测类别 — None = 全部 80 类，[] = 不检测任何物体。

        将类别名转为 YOLO 类别 ID 列表，传入 model.track(classes=...)。
        未匹配到的类别名被静默忽略。
        """
        if classes is None:
            self._target_class_ids = None
        elif len(classes) == 0:
            self._target_class_ids = []
        else:
            self._target_class_ids = [
                COCO_CLASSES.index(c) for c in classes if c in COCO_CLASSES
            ]
        logger.debug("[YoloDetector] Target classes: %s → ids=%s", classes, self._target_class_ids)

    # ── 内部实现 ──

    def _load_model(self) -> None:
        """加载 YOLO11 模型（首次调用时触发）。"""
        from pathlib import Path
        from ultralytics import YOLO

        # 相对路径 → 基于项目根目录解析（和 config_loader / prompt_loader 一致）
        project_root = Path(__file__).resolve().parent.parent.parent
        model_path = self._model_name
        if not Path(model_path).is_absolute():
            model_path = str(project_root / model_path)

        # 本地 tracker 配置（track_buffer=120, 6s @ 20fps）
        self._tracker_config = str(project_root / "config" / "botsort.yaml")

        import torch

        logger.info("[YoloDetector] Loading model: %s", model_path)
        self._model = YOLO(model_path)
        # 显式迁移到 GPU — 避免首次推理时隐式迁移导致 ~1.2s 额外延迟
        if torch.cuda.is_available():
            self._model.to("cuda")
        logger.info("[YoloDetector] Model loaded. Device: %s", self._model.device)

    def _sync_track(self, frames: list[np.ndarray]) -> list[list[dict]]:
        """同步批量检测+追踪（在 asyncio.to_thread 中执行）。

        使用 model.track(persist=True, tracker="botsort.yaml")：
        - persist=True 保证跨 batch 的 track ID 一致
        - 内置 BoT-SORT 含 ReID 外观特征 + 卡尔曼滤波 + 确认机制
        """
        results = self._model.track(
            frames,
            conf=self._conf,
            iou=self._iou,
            classes=self._target_class_ids,
            persist=True,
            tracker=self._tracker_config,
            verbose=False,
        )

        output: list[list[dict]] = []
        for result in results:
            dets: list[dict] = []
            if result.boxes is not None:
                boxes = result.boxes
                # xyxyn: normalized [x1, y1, x2, y2] in 0-1 range
                xyxy = boxes.xyxyn.cpu().numpy() if boxes.xyxyn is not None else np.empty((0, 4))
                confs = boxes.conf.cpu().numpy() if boxes.conf is not None else np.empty((0,))
                cls_ids = boxes.cls.cpu().numpy().astype(int) if boxes.cls is not None else np.empty((0,), dtype=int)
                # track ID: model.track() 为每个检测分配跨帧一致的 ID
                track_ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else np.empty((0,), dtype=int)

                for i in range(len(xyxy)):
                    cls_id = int(cls_ids[i])
                    class_name = COCO_CLASSES[cls_id] if cls_id < len(COCO_CLASSES) else "unknown"
                    det = {
                        "bbox": {
                            "x1": float(xyxy[i][0]),
                            "y1": float(xyxy[i][1]),
                            "x2": float(xyxy[i][2]),
                            "y2": float(xyxy[i][3]),
                        },
                        "confidence": float(confs[i]),
                        "class_name": class_name,
                        "track_id": int(track_ids[i]) if i < len(track_ids) else -1,
                    }
                    dets.append(det)
            output.append(dets)

        return output
