"""
plugins/plate/hyperlpr_plate.py
═══════════════════════════════════════════════════════════
HyperLPR3 车牌检测与识别 — 专用中文车牌框架。

对比 PaddleOCR 通用文字识别:
  - 专用车牌检测器（定位四角 + 透视校正）
  - LPR 专用 CNN 字符识别（非通用 CRNN）
  - 车牌类型分类器（蓝/黄/绿/白/黑）
  - <100ms/image（ONNX Runtime 推理）
  - aarch64 原生支持（无需 PaddlePaddle 全家桶）

HyperLPR3 返回格式 (Plate.to_result()):
  每个检测结果是一个 list: [plate_code, rec_confidence, plate_type_int, det_bbox_list]
  - plate_code:       str    车牌号文本
  - rec_confidence:   float  识别置信度
  - plate_type_int:   int    车牌类型常量 (0=BLUE, 1=YELLOW_SINGLE, 2=WHILE_SINGLE, 3=GREEN, ...)
  - det_bbox_list:    list   检测框 [x1, y1, x2, y2] 像素坐标

配置示例（config.yaml）:
  plate:
    backend: "hyperlpr"
    params:
      detect_level: "high"   # low (320×320) / high (640×640)
"""

import logging
import asyncio

import numpy as np

from core.interfaces import BasePlateRecognizer

logger = logging.getLogger(__name__)

# HyperLPR3 车牌类型整数常量 → Cerno 字符串标签
# 常量定义见 hyperlpr3.common.typedef
_PLATE_TYPE_INT_MAP: dict[int, str] = {
    0: "blue",     # BLUE
    1: "yellow",   # YELLOW_SINGLE
    2: "white",    # WHILE_SINGLE
    3: "green",    # GREEN
    4: "black",    # BLACK_HK_MACAO
    5: "black",    # HK_SINGLE
    6: "black",    # HK_DOUBLE
    7: "black",    # MACAO_SINGLE
    8: "black",    # MACAO_DOUBLE
    9: "yellow",   # YELLOW_DOUBLE
}


class HyperLPRPlateRecognizer(BasePlateRecognizer):
    """HyperLPR3 车牌检测 + 识别。

    Args:
        detect_level: 检测精度，"low"（320×320, 更快）或 "high"（640×640, 更准）。
    """

    def __init__(
        self,
        detect_level: str = "high",
        **kwargs,
    ) -> None:
        self._detect_level = detect_level
        self._catcher = None

    # ── 公开接口 ──

    async def recognize(self, crops: list[np.ndarray]) -> list[list[dict]]:
        """批量处理 vehicle crops → 每张返回 [{plate_text, plate_type, ...}]。"""
        if not crops:
            return []

        if self._catcher is None:
            await asyncio.to_thread(self._load)

        return await asyncio.to_thread(self._sync_recognize, crops)

    # ── 内部 ──

    def _load(self) -> None:
        """加载 HyperLPR3 模型（ONNX Runtime，自动下载模型文件）。"""
        from hyperlpr3 import LicensePlateCatcher
        from hyperlpr3.common.typedef import DETECT_LEVEL_LOW, DETECT_LEVEL_HIGH

        level_map = {"low": DETECT_LEVEL_LOW, "high": DETECT_LEVEL_HIGH}
        level = level_map.get(self._detect_level, DETECT_LEVEL_HIGH)
        self._catcher = LicensePlateCatcher(detect_level=level)
        logger.info(
            "[HyperLPR] LicensePlateCatcher loaded (detect_level=%s→%d)",
            self._detect_level, level,
        )

    def _sync_recognize(self, crops: list[np.ndarray]) -> list[list[dict]]:
        """同步识别：对每张 vehicle crop 运行 HyperLPR3 检测 + 识别。

        HyperLPR3 LicensePlateCatcher.__call__() 返回 list[list]，每个元素为:
          [plate_code: str, rec_confidence: float, plate_type: int, det_bbox: list]
        （即 Plate.to_result() 的返回值）
        """
        results: list[list[dict]] = []

        for crop in crops:
            if crop is None or crop.size == 0 or min(crop.shape[:2]) < 20:
                results.append([])
                continue

            h, w = crop.shape[:2]

            # HyperLPR3 接受 BGR 格式的 numpy 数组
            if crop.shape[-1] == 3:
                bgr = crop[..., ::-1]  # RGB → BGR
            else:
                bgr = crop

            try:
                lpr_results = self._catcher(bgr)
            except Exception:
                logger.warning("[HyperLPR] Recognition failed for crop %dx%d", w, h)
                results.append([])
                continue

            plate_list: list[dict] = []
            if lpr_results:
                for res in lpr_results:
                    # HyperLPR3 返回格式: [plate_code, rec_confidence, plate_type_int, det_bbox]
                    if not isinstance(res, (list, tuple)) or len(res) < 4:
                        continue

                    plate_code = (res[0] or "").strip()
                    rec_confidence = float(res[1]) if res[1] is not None else 0.0
                    plate_type_int = int(res[2]) if res[2] is not None else -1
                    det_bbox = res[3]  # [x1, y1, x2, y2] 像素坐标

                    if not plate_code or len(plate_code) < 5:
                        continue

                    # 归一化 bbox（det_bbox 是像素坐标 [x1, y1, x2, y2]）
                    if det_bbox is not None and len(det_bbox) == 4:
                        norm_bbox = {
                            "x1": max(0.0, min(1.0, float(det_bbox[0]) / w)),
                            "y1": max(0.0, min(1.0, float(det_bbox[1]) / h)),
                            "x2": max(0.0, min(1.0, float(det_bbox[2]) / w)),
                            "y2": max(0.0, min(1.0, float(det_bbox[3]) / h)),
                        }
                    else:
                        norm_bbox = {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}

                    # 逐字符置信度（HyperLPR3 不提供，用整体置信度填充）
                    char_confs = [rec_confidence] * len(plate_code)

                    plate_list.append({
                        "plate_text": plate_code,
                        "plate_type": _PLATE_TYPE_INT_MAP.get(plate_type_int, "blue"),
                        "char_confidences": char_confs,
                        "bbox": norm_bbox,
                        "confidence": rec_confidence,
                    })

            results.append(plate_list)

        return results
