"""
plugins/ocr/paddleocr.py
═══════════════════════════════════════════════════════════
PaddleOCR 画面文字提取（独立感知模块 v0.34）。

CPU 运行（默认）：不占 gpu_lock，不参与 embedder/YOLO 的 GPU 串行队列，
适合「录屏聊天 / 字幕 / 屏幕文字」这类读具体字符的场景。

同步推理通过 asyncio.to_thread 包裹，遵循核心异步约定。

API 版本自适应：
  - paddleocr >= 3.x（本机 3.7.0）：predict() 返回 OCRResult（rec_texts/rec_scores/rec_polys），
    ⚠️ Windows CPU 下 PIR + onednn 有已知 NotImplementedError bug → 3.x 强制 enable_mkldnn=False 绕行
  - paddleocr < 3.x：旧接口 ocr(frame, cls=True) → [[bbox_points, (text, conf)], ...]

模型档位（v0.34 修复）：
  - 3.x 默认会选 server 级 PP-OCRv6_medium（检测+识别 ~134MB），CPU 逐帧 ~15s 极慢
  - 显式 ppocr_version="PP-OCRv4" → mobile 小模型（~10MB），恢复文档设计的 CPU 速度预期；
    use_gpu=true 时同样吃 mobile 模型 + GPU（RTX 5070 → ms 级）
"""

import asyncio
import logging

import numpy as np

from core.interfaces import BaseOCR

logger = logging.getLogger(__name__)


class PaddleOCRExtractor(BaseOCR):
    """PaddleOCR 画面文字提取。

    参数从 config.yaml plugins.ocr.params 传入（可被系统设置页 pipeline.ocr 运行时覆盖）:
      - lang: OCR 语言，默认 "ch"
      - use_gpu: 是否用 GPU（默认 False——OCR 走 CPU，不占 gpu_lock）
      - conf_thresh: 返回结果的置信度门槛（低于此值的文字行丢弃）
      - use_angle_cls: 方向分类器（旧接口用，3.x 忽略）
    """

    def __init__(
        self,
        lang: str = "ch",
        use_gpu: bool = False,
        conf_thresh: float = 0.5,
        use_angle_cls: bool = True,
        **kwargs,
    ) -> None:
        self._lang = lang
        self._use_gpu = use_gpu
        self._conf_thresh = conf_thresh
        self._use_angle_cls = use_angle_cls
        self._ocr = None
        self._api3 = False

    # ── 公开接口 ──

    async def extract(self, frame: np.ndarray) -> list[dict]:
        """对单帧 OCR → [{text, bbox, confidence}]。"""
        if self._ocr is None:
            await asyncio.to_thread(self._load)
        return await asyncio.to_thread(self._sync_extract, frame)

    # ── 内部 ──

    def _load(self) -> None:
        """加载 PaddleOCR（检测 + 识别），按版本自适应初始化。"""
        from paddleocr import PaddleOCR
        import paddleocr

        major = int(str(getattr(paddleocr, "__version__", "0")).split(".")[0])
        self._api3 = major >= 3
        device = "gpu:0" if self._use_gpu else "cpu"

        if self._api3:
            # 3.x：device 替代 use_gpu；显式 ocr_version="PP-OCRv4" → mobile 小模型
            #   （默认会选 PP-OCRv6_medium server 级 ~134MB，CPU/GPU 逐帧都慢）；
            #   Windows CPU 下 PIR+onednn 有 NotImplementedError bug → 关 mkldnn
            self._ocr = PaddleOCR(
                lang=self._lang,
                device=device,
                ocr_version="PP-OCRv4",
                enable_mkldnn=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        else:
            # 2.x 老接口（兼容历史部署）
            self._ocr = PaddleOCR(
                use_angle_cls=self._use_angle_cls,
                lang=self._lang,
                use_gpu=self._use_gpu,
            )
        logger.info(
            "[PaddleOCR] loaded (api=%s, lang=%s, device=%s)",
            "3.x" if self._api3 else "2.x", self._lang, device,
        )

    def _sync_extract(self, frame: np.ndarray) -> list[dict]:
        """同步 OCR：单帧 → 过滤 → 归一化 bbox 文字行列表。"""
        if frame is None or frame.size == 0 or min(frame.shape[:2]) < 10:
            return []

        h, w = frame.shape[:2]

        if self._api3:
            res = self._ocr.predict(frame)
            if not res:
                return []
            r = res[0]
            texts = r.get("rec_texts") or []
            scores = r.get("rec_scores") or []
            polys = r.get("rec_polys") or []
            rows: list[dict] = []
            for i, text in enumerate(texts):
                text = (text or "").strip()
                conf = float(scores[i]) if i < len(scores) else 0.0
                if not text or conf < self._conf_thresh:
                    continue
                bbox = self._poly_bbox(polys[i], w, h) if i < len(polys) and polys[i] is not None else None
                rows.append({
                    "text": text,
                    "bbox": bbox or {"x1": 0.0, "y1": 0.0, "x2": 0.0, "y2": 0.0},
                    "confidence": conf,
                })
            return rows

        # 2.x 老接口
        if frame.shape[-1] == 3:
            bgr = frame[..., ::-1]  # RGB → BGR
        else:
            bgr = frame
        ocr_result = self._ocr.ocr(bgr, cls=self._use_angle_cls)
        rows = []
        if ocr_result and ocr_result[0]:
            for line in ocr_result[0]:
                bbox_points, (text, confidence) = line
                text = (text or "").strip()
                conf = float(confidence or 0.0)
                if not text or conf < self._conf_thresh:
                    continue
                xs = [p[0] for p in bbox_points]
                ys = [p[1] for p in bbox_points]
                rows.append({
                    "text": text,
                    "bbox": {
                        "x1": max(0.0, min(xs) / w),
                        "y1": max(0.0, min(ys) / h),
                        "x2": min(1.0, max(xs) / w),
                        "y2": min(1.0, max(ys) / h),
                    },
                    "confidence": conf,
                })
        return rows

    @staticmethod
    def _poly_bbox(poly, w: int, h: int) -> dict:
        """4 点多边形 → 归一化 bbox {x1,y1,x2,y2}。"""
        pts = np.asarray(poly, dtype=float)
        if pts.size == 0:
            return {"x1": 0.0, "y1": 0.0, "x2": 0.0, "y2": 0.0}
        return {
            "x1": max(0.0, min(1.0, float(pts[:, 0].min()) / w)),
            "y1": max(0.0, min(1.0, float(pts[:, 1].min()) / h)),
            "x2": max(0.0, min(1.0, float(pts[:, 0].max()) / w)),
            "y2": max(0.0, min(1.0, float(pts[:, 1].max()) / h)),
        }