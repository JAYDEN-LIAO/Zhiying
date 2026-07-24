"""
plugins/face/insightface_face.py
═══════════════════════════════════════════════════════════
InsightFace 人脸检测与识别 — SCRFD + ArcFace R50 (buffalo_l)。

通过 insightface.app.FaceAnalysis 统一 API：
  - 检测: SCRFD-10g（buffalo_l 中的 det_10g.onnx）
  - 识别: ArcFace R50（buffalo_l 中的 w600k_r50.onnx）
  - embedding 维度: 512

同步推理通过 asyncio.to_thread 包裹，遵循核心异步约定。
"""

import logging
import asyncio

import numpy as np

from core.interfaces import BaseFaceRecognizer

logger = logging.getLogger(__name__)


class InsightFaceRecognizer(BaseFaceRecognizer):
    """InsightFace SCRFD + ArcFace R50 统一人脸分析器。

    参数从 config.yaml plugins.face.params 传入:
      - det_thresh:  SCRFD 检测阈值 (0~1)，默认 0.5
      - rec_thresh:  ArcFace 识别阈值 (0~1)，默认 0.4（仅内部用，聚类由 FaceRunner 做）
    """

    def __init__(
        self,
        det_thresh: float = 0.5,
        rec_thresh: float = 0.4,
        **kwargs,
    ) -> None:
        self._det_thresh = det_thresh
        self._rec_thresh = rec_thresh
        self._app = None

    # ── 公开接口 ──

    async def extract(self, crops: list[np.ndarray]) -> list[list[dict]]:
        """批量处理 person crops → 每张返回 [{bbox, quality, embedding}]。"""
        if self._app is None:
            await asyncio.to_thread(self._load)
        return await asyncio.to_thread(self._sync_extract, crops)

    # ── 搜索用：单张图片 → 最佳人脸 512d embedding ──

    async def extract_best_embedding(self, image: np.ndarray) -> list[float] | None:
        """对单张图片检测人脸，返回最优人脸（最大 bbox）的 512d embedding。

        用于人脸图片搜索：用户上传照片 → ArcFace embedding → 比对 face_identities 表。
        如果没有检测到人脸，返回 None。
        """
        if self._app is None:
            await asyncio.to_thread(self._load)
        return await asyncio.to_thread(self._sync_extract_best, image)

    def _sync_extract_best(self, image: np.ndarray) -> list[float] | None:
        if image is None or image.size == 0:
            return None
        if image.shape[-1] == 3:
            bgr = image[..., ::-1]
        else:
            bgr = image
        faces = self._app.get(bgr)
        if not faces:
            return None
        # 选面积最大的人脸作为主目标
        best = max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        )
        return best.embedding.tolist()

    # ── 内部 ──

    def _load(self) -> None:
        """加载 insightface buffalo_l 模型包（SCRFD + ArcFace R50）。"""
        import insightface
        self._app = insightface.app.FaceAnalysis(name="buffalo_l")
        self._app.prepare(
            ctx_id=0,  # GPU 0
            det_thresh=self._det_thresh,
            det_size=(640, 640),
        )
        logger.info(
            "[InsightFace] buffalo_l loaded (det_thresh=%.2f, rec_thresh=%.2f)",
            self._det_thresh, self._rec_thresh,
        )

    def _sync_extract(self, crops: list[np.ndarray]) -> list[list[dict]]:
        """同步提取: 对每张 crop 调用 insightface get() 检测+嵌入。"""
        results: list[list[dict]] = []
        for crop in crops:
            if crop is None or crop.size == 0 or min(crop.shape[:2]) < 20:
                results.append([])
                continue

            # BGR 格式（insightface 需要 BGR 输入）
            if crop.shape[-1] == 3:
                bgr = crop[..., ::-1]  # RGB → BGR
            else:
                bgr = crop

            faces = self._app.get(bgr)
            face_list: list[dict] = []
            for f in faces:
                bbox = f.bbox.astype(float)  # [x1, y1, x2, y2] in pixels
                h, w = crop.shape[:2]
                face_list.append({
                    "bbox": {
                        "x1": max(0.0, float(bbox[0] / w)),
                        "y1": max(0.0, float(bbox[1] / h)),
                        "x2": min(1.0, float(bbox[2] / w)),
                        "y2": min(1.0, float(bbox[3] / h)),
                    },
                    "quality": float(f.det_score),
                    "embedding": f.embedding.tolist(),  # 512-dim float
                })
            results.append(face_list)
        return results
