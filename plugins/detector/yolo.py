"""
plugins/detector/yolo.py
═══════════════════════════════════════════════════════════
YOLO11 物体检测 + 追踪 — 实现 BaseDetector 批量接口。

使用 ultralytics YOLO11s（~22 MB），GPU 批量推理 + BoT-SORT 追踪。

v0.16 性能重构:
  - _init_tracker(): model.track(dummy) 初始化 predictor + tracker 配置
  - _sync_predict(): model.predict(frames, batch=128) 一次调用批量推理
    （predictor 已有 tracker 配置时，predict() 内部自动追踪，无需额外调用）
  - 大幅提升检测 runner 的攒批大小（128 → 1024），减少 predict() 调用开销
"""

import asyncio
import logging

import numpy as np

from core.interfaces import BaseDetector
from core.gpu_lock import gpu_lock

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
    """YOLO11 物体检测 + 追踪 — 批量 GPU 推理 + BoT-SORT。

    参数从 config.yaml plugins.detector 传入：
    - model: 模型文件名，默认 yolo26s.pt
    - confidence_threshold: 置信度阈值，默认 0.4
    - iou_threshold: NMS IoU 阈值，默认 0.5

    架构:
      _init_tracker()     → model.track(dummy)  初始化 predictor + tracker 配置（每视频 1 次）
      _sync_predict()     → model.predict(frames, batch=batch_size)  公有 API，批量 GPU + 自动追踪
    """

    def __init__(
        self,
        model: str = "yolo26s.pt",
        confidence_threshold: float = 0.4,
        iou_threshold: float = 0.5,
        batch_size: int = 128,
        imgsz: int = 640,
        **kwargs,
    ) -> None:
        self._model_name = model
        self._conf = confidence_threshold
        self._iou = iou_threshold
        # 单次 predict() 的 GPU 批大小（config.yaml plugins.detector.batch_size）—
        # 低显存机器可调小，避免 YOLO 激活峰值 OOM
        self._batch_size = batch_size
        # YOLO 推理分辨率（config.yaml plugins.detector.imgsz）— 低显存可 512/416，激活近似减半
        self._imgsz = imgsz

        # 延迟加载 — 首次调用 detect() 时加载模型
        self._model = None

        # 类别过滤 — None = 全部 80 类
        self._target_class_ids: list[int] | None = None

    # ── 公开接口 ──

    async def detect(self, frames: list[np.ndarray]) -> list[list[dict]]:
        """批量检测+追踪（异步包装，内部走 asyncio.to_thread）。

        Returns:
            与 frames 等长的列表。每个元素是该帧的检测物列表::

                [{bbox, confidence, class_name, track_id}, ...]

            track_id 由 BoT-SORT 分配，跨 batch 保持一致。
        """
        # 全局 GPU 锁：与 embedder 前向互斥（YOLO 卷积 + 8bit matmul 并发会触发驱动故障）。
        # 模型加载/tracker 初始化/批量前向都算 GPU 计算，统一锁内执行。
        async with gpu_lock:
            if self._model is None:
                await asyncio.to_thread(self._load_model)

            # 初始化 predictor + tracker（每个视频首次调用时触发）
            await asyncio.to_thread(self._init_tracker)

            return await asyncio.to_thread(self._sync_predict, frames)

    def reset_tracker(self) -> None:
        """重置追踪器状态 — 处理新视频前调用，清除跨视频的 track ID 残留。

        原地 reset tracker（BYTETracker.reset()），而非把 predictor 置 None：
        predictor 置 None 会让 _init_tracker() 再次 model.track()，从而**重复注册**
        register_tracker 回调 → on_predict_postprocess_end 每批执行 N 次
        （N=已处理视频数）→ 每视频逐批线性变慢 + track ID 膨胀（回归源：共享单实例）。
        BYTETracker.reset() 清空 tracked/lost/removed + frame_id + Kalman + 全局 ID 计数器。
        """
        pred = getattr(self._model, "predictor", None) if self._model is not None else None
        if pred is not None and hasattr(pred, "trackers"):
            for t in pred.trackers:
                t.reset()  # BOTSORT.reset(): super()(BYTETracker.reset) + gmc.reset_params()
            logger.debug("[YoloDetector] Tracker reset for new video")

    def set_target_classes(self, classes: list[str] | None) -> None:
        """设置目标检测类别 — None = 全部 80 类，[] = 不检测任何物体。"""
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

        project_root = Path(__file__).resolve().parent.parent.parent
        model_path = self._model_name
        if not Path(model_path).is_absolute():
            model_path = str(project_root / model_path)

        self._tracker_config = str(project_root / "config" / "botsort.yaml")

        import torch

        logger.info("[YoloDetector] Loading model: %s", model_path)
        self._model = YOLO(model_path)
        if torch.cuda.is_available():
            self._model.to("cuda")
        logger.info("[YoloDetector] Model loaded. Device: %s", self._model.device)

    def _init_tracker(self) -> None:
        """初始化 predictor + BoT-SORT tracker 配置。

        model.track(dummy frame) 一次性创建 predictor 并注入 tracker 配置。
        此后 model.predict() 内部会自动启用追踪（因为 predictor 已有 tracker 配置）。
        仅在 predictor 为 None（首次或 reset 后）时执行。
        """
        if self._model.predictor is not None:
            return

        logger.debug("[YoloDetector] Initializing predictor + tracker config via dummy frame")
        dummy = np.zeros((64, 64, 3), dtype=np.uint8)
        list(self._model.track(
            [dummy],
            conf=self._conf,
            iou=self._iou,
            classes=self._target_class_ids,
            persist=True,
            tracker=self._tracker_config,
            imgsz=self._imgsz,
            verbose=False,
        ))

    def _sync_predict(self, frames: list[np.ndarray]) -> list[list[dict]]:
        """批量 GPU 推理 + 自动追踪。

        model.predict(frames, batch=128) — 公有 API：
          - ultralytics 内部处理 dataset/dataloader/预处理/NMS
          - 因 predictor 已注入 tracker 配置，结果自带 track_id（7 列：xyxy+conf+cls+id）
        """
        target_classes = self._target_class_ids

        # 一次调用，ultralytics 内部按 self._batch_size 分批 GPU 推理 + 自动追踪
        results = list(self._model.predict(
            frames,
            conf=self._conf,
            iou=self._iou,
            classes=target_classes,
            batch=self._batch_size,
            imgsz=self._imgsz,
            verbose=False,
            stream=True,    # 流式输出，消除 ultralytics RAM 警告
        ))

        output: list[list[dict]] = []
        for result in results:
            dets: list[dict] = []
            if result.boxes is not None:
                boxes = result.boxes
                xyxy = boxes.xyxyn.cpu().numpy() if boxes.xyxyn is not None else np.empty((0, 4))
                confs = boxes.conf.cpu().numpy() if boxes.conf is not None else np.empty((0,))
                cls_ids = boxes.cls.cpu().numpy().astype(int) if boxes.cls is not None else np.empty((0,), dtype=int)
                # 追踪 ID：predictor 有 tracker 配置时 predict() 内部自动分配
                track_ids = boxes.id.cpu().numpy().astype(int) if boxes.id is not None else np.empty((0,), dtype=int)

                for i in range(len(xyxy)):
                    cls_id = int(cls_ids[i])
                    if target_classes is not None and cls_id not in target_classes:
                        continue
                    class_name = COCO_CLASSES[cls_id] if cls_id < len(COCO_CLASSES) else "unknown"
                    dets.append({
                        "bbox": {
                            "x1": float(xyxy[i][0]),
                            "y1": float(xyxy[i][1]),
                            "x2": float(xyxy[i][2]),
                            "y2": float(xyxy[i][3]),
                        },
                        "confidence": float(confs[i]),
                        "class_name": class_name,
                        "track_id": int(track_ids[i]) if i < len(track_ids) else -1,
                    })
            output.append(dets)

        return output
