"""
plugins/embedder/qwen_vl_embedder.py
═══════════════════════════════════════════════════════════
Qwen3-VL-Embedding 向量编码插件。

图像 / 文本 → 768 维归一化嵌入向量。
模型推理通过 asyncio.to_thread 投递线程池，不阻塞事件循环。
"""

import asyncio
import logging

import numpy as np
import torch

from core.interfaces import BaseEmbedder
from core.exceptions import PluginLoadError

logger = logging.getLogger(__name__)


class QwenVLEmbedder(BaseEmbedder):
    """基于 Qwen3-VL-Embedding 的多模态向量编码器。

    同时兼容 HuggingFace 和 ModelScope 路径。

    Args:
        model_name: 模型名称或路径。
                     HF: "Qwen/Qwen3-VL-Embedding-2B"
                     MS: "Qwen/Qwen3-VL-Embedding-2B"
        device: 推理设备 ("cuda" / "cpu")。
    """

    IMAGE_PROMPT = "<|vision_start|><|image_pad|><|vision_end|>"

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-VL-Embedding-2B",
        device: str = "cuda",
        **kwargs,
    ):
        try:
            from transformers import AutoModel, AutoProcessor
        except ImportError as e:
            raise PluginLoadError(
                "transformers not installed. Run: pip install transformers"
            ) from e

        self.device = device

        logger.info("[QwenVLEmbedder] Loading model %s on %s ...", model_name, device)
        self.processor = AutoProcessor.from_pretrained(
            model_name, trust_remote_code=True,
        )
        self.model = AutoModel.from_pretrained(
            model_name,
            trust_remote_code=True,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map="auto" if device == "cuda" else None,
            low_cpu_mem_usage=True,
        ).to(device)
        self.model.eval()
        logger.info("[QwenVLEmbedder] Model loaded")

    async def encode_image(self, image: np.ndarray) -> list[float]:
        """将图像编码为 2048 维单位向量。

        Args:
            image: (H, W, C) uint8。

        Returns:
            2048 维归一化 float 向量。
        """
        if image.ndim == 2:
            image = np.stack([image] * 3, axis=-1)
        elif image.shape[2] == 4:
            image = image[:, :, :3]

        try:
            vector = await asyncio.to_thread(
                self._sync_encode_image, image,
            )
            return vector
        except Exception as e:
            logger.exception("[QwenVLEmbedder] Image encoding failed")
            raise

    async def encode_text(self, text: str) -> list[float]:
        """将文本编码为 2048 维单位向量。

        Args:
            text: 输入文本。

        Returns:
            2048 维归一化 float 向量。
        """
        try:
            vector = await asyncio.to_thread(
                self._sync_encode_text, text,
            )
            return vector
        except Exception as e:
            logger.exception("[QwenVLEmbedder] Text encoding failed")
            raise

    # ──────────────────────────────────────────────────────
    # 同步推理（线程池中执行）
    # ──────────────────────────────────────────────────────

    def _sync_encode_image(self, image: np.ndarray) -> list[float]:
        """图像嵌入：processor → model → mean pooling → L2 归一化。"""
        inputs = self.processor(
            text=[self.IMAGE_PROMPT],
            images=[image],
            return_tensors="pt",
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)

        # 取最后一层 hidden state，做 mean pooling
        hidden = outputs.last_hidden_state  # (1, seq_len, dim)
        embedding = hidden.mean(dim=1).squeeze(0)  # (dim,)

        # L2 归一化
        embedding_np = embedding.cpu().numpy().astype(np.float64)
        norm = np.linalg.norm(embedding_np)
        if norm > 0:
            embedding_np = embedding_np / norm

        return embedding_np.tolist()

    def _sync_encode_text(self, text: str) -> list[float]:
        """文本嵌入：processor → model → mean pooling → L2 归一化。"""
        prompt = text or " "
        inputs = self.processor(
            text=[prompt],
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)

        hidden = outputs.last_hidden_state
        embedding = hidden.mean(dim=1).squeeze(0)

        embedding_np = embedding.cpu().numpy().astype(np.float64)
        norm = np.linalg.norm(embedding_np)
        if norm > 0:
            embedding_np = embedding_np / norm

        return embedding_np.tolist()
