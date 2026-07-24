"""
plugins/plate/paddle_plate.py
═══════════════════════════════════════════════════════════
PaddleOCR 车牌检测与识别。

使用 PaddleOCR 端到端车牌检测 + 文字识别:
  - 检测: PaddleOCR 内置 DB 文字检测器
  - 识别: PaddleOCR 内置 CRNN 识别器
  - 后处理: 按车牌格式启发式过滤（短字母数字串）

同步推理通过 asyncio.to_thread 包裹，遵循核心异步约定。
"""

import logging
import asyncio

import numpy as np

from core.interfaces import BasePlateRecognizer

logger = logging.getLogger(__name__)

# 中国车牌常见颜色映射（PaddleOCR 不直接输出颜色，基于文字内容推断）
_PLATE_TYPE_PATTERNS: list[tuple[list[str], str]] = [
    (["京", "津", "沪", "渝", "冀", "豫", "云", "辽", "黑", "湘",
      "皖", "鲁", "新", "苏", "浙", "赣", "鄂", "桂", "甘", "晋",
      "蒙", "陕", "吉", "闽", "贵", "粤", "青", "藏", "川", "宁",
      "琼"], "blue"),   # 普通蓝牌
    (["使", "领"], "black"),                            # 使领馆黑牌
]


def _infer_plate_type(text: str) -> str:
    """根据车牌文字推断牌照类型。"""
    if not text:
        return "unknown"
    # 新能源绿牌: 8 位字符（如 京AD12345）
    if len(text) >= 7:
        return "green"
    # 普通蓝牌判断：首字是否在省份列表中
    for prefixes, ptype in _PLATE_TYPE_PATTERNS:
        if text[0] in prefixes:
            return ptype
    return "blue"  # 默认蓝牌


class PaddlePlateRecognizer(BasePlateRecognizer):
    """PaddleOCR 车牌检测 + 文字识别。

    参数从 config.yaml plugins.plate.params 传入:
      - lang: OCR 语言，默认 "ch"
      - det_db_thresh: DB 检测阈值，默认 0.3
      - rec_thresh: 识别阈值，默认 0.5
      - use_angle_cls: 是否用方向分类器，默认 True
    """

    def __init__(
        self,
        lang: str = "ch",
        det_db_thresh: float = 0.3,
        rec_thresh: float = 0.5,
        use_angle_cls: bool = True,
        **kwargs,
    ) -> None:
        self._lang = lang
        self._det_db_thresh = det_db_thresh
        self._rec_thresh = rec_thresh
        self._use_angle_cls = use_angle_cls
        self._ocr = None

    # ── 公开接口 ──

    async def recognize(self, crops: list[np.ndarray]) -> list[list[dict]]:
        """批量处理 vehicle crops → 每张返回 [{plate_text, plate_type, ...}]。"""
        if self._ocr is None:
            await asyncio.to_thread(self._load)
        return await asyncio.to_thread(self._sync_recognize, crops)

    # ── 内部 ──

    def _load(self) -> None:
        """加载 PaddleOCR 模型（检测 + 识别 + 方向分类器）。"""
        from paddleocr import PaddleOCR
        self._ocr = PaddleOCR(
            use_angle_cls=self._use_angle_cls,
            lang=self._lang,
            det_db_thresh=self._det_db_thresh,
            rec_thresh=self._rec_thresh,
            use_gpu=True,
        )
        logger.info(
            "[PaddlePlate] PaddleOCR loaded (lang=%s, det_thresh=%.2f, rec_thresh=%.2f)",
            self._lang, self._det_db_thresh, self._rec_thresh,
        )

    def _sync_recognize(self, crops: list[np.ndarray]) -> list[list[dict]]:
        """同步识别: 对每张 vehicle crop 运行 PaddleOCR → 过滤车牌格式。"""
        results: list[list[dict]] = []
        for crop in crops:
            if crop is None or crop.size == 0 or min(crop.shape[:2]) < 10:
                results.append([])
                continue

            h, w = crop.shape[:2]

            # PaddleOCR 需要 BGR 格式
            if crop.shape[-1] == 3:
                bgr = crop[..., ::-1]  # RGB → BGR
            else:
                bgr = crop

            ocr_result = self._ocr.ocr(bgr, cls=self._use_angle_cls)
            plate_list: list[dict] = []

            if ocr_result and ocr_result[0]:
                for line in ocr_result[0]:
                    bbox_points, (text, confidence) = line
                    if not text:
                        continue

                    # 启发式车牌过滤: 短字母数字串（含汉字）
                    text = text.strip().replace(" ", "").replace("·", "")
                    if len(text) < 5 or len(text) > 10:
                        continue

                    # 转归一化 bbox
                    xs = [p[0] for p in bbox_points]
                    ys = [p[1] for p in bbox_points]
                    norm_bbox = {
                        "x1": max(0.0, min(xs) / w),
                        "y1": max(0.0, min(ys) / h),
                        "x2": min(1.0, max(xs) / w),
                        "y2": min(1.0, max(ys) / h),
                    }

                    # 逐字符置信度（PaddleOCR 不提供，用整体置信度填充）
                    char_confs = [float(confidence)] * len(text)

                    plate_list.append({
                        "plate_text": text,
                        "plate_type": _infer_plate_type(text),
                        "char_confidences": char_confs,
                        "bbox": norm_bbox,
                        "confidence": float(confidence),
                    })

            results.append(plate_list)
        return results
