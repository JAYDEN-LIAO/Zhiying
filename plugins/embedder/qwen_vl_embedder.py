"""
plugins/embedder/qwen_vl_embedder.py
═══════════════════════════════════════════════════════════
Qwen3-VL-Embedding 向量编码插件。

图像 / 文本 / 视频 → 4096 维归一化嵌入向量。
模型推理通过 asyncio.to_thread 投递线程池，不阻塞事件循环。

编码方式：
  - 文本：apply_chat_template + pooling_last（非 mean pooling）
  - 图像：process_vision_info + apply_chat_template + pooling_last
  - 批量图像：多帧 packing 为同一 batch，一次前向，池化后拆为独立向量
  - 视频：process_vision_info + apply_chat_template + pooling_last
"""

import asyncio
import logging
import os
from pathlib import Path

import numpy as np
import torch

from core.interfaces import BaseEmbedder
from core.exceptions import PluginLoadError
from core.gpu_lock import gpu_lock

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class QwenVLEmbedder(BaseEmbedder):
    """基于 Qwen3-VL-Embedding 的多模态向量编码器。

    同时兼容 HuggingFace 和 ModelScope 路径。

    Args:
        model_name: 模型名称或路径。
                     HF: "Qwen/Qwen3-VL-Embedding-2B"
                     MS: "Qwen/Qwen3-VL-Embedding-2B"
        device: 推理设备 ("cuda" / "cpu")。
    """

    _SYSTEM_PROMPT = "检索与查询相关的视频内容。"

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-VL-Embedding-2B",
        device: str = "cuda",
        encode_width: int = 336,
        encode_height: int = 224,
        quantization: str = "none",
        **kwargs,
    ):
        try:
            from transformers import AutoModel, AutoProcessor
        except ImportError as e:
            raise PluginLoadError(
                "transformers not installed. Run: pip install transformers"
            ) from e

        self.device = device
        self.encode_size = (encode_width, encode_height)
        # none / 8bit / 4bit — bitsandbytes 量化，低显存机器把 ~16GB 权重降到 ~8GB / ~4GB
        self._quantization = (quantization or "none").strip().lower()

        # 相对路径 → 项目根目录（对齐 plugins/detector/yolo.py，避免依赖 cwd）。
        # 仅当"项目根下确实存在该路径"时才改写，HF 模型 ID（如 Qwen/xxx）保持原样。
        model_path = Path(model_name)
        if not model_path.is_absolute():
            candidate = _PROJECT_ROOT / model_name
            if candidate.exists():
                model_name = str(candidate)

        logger.info(
            "[QwenVLEmbedder] Loading model %s on %s (encode %dx%d, quantization=%s) ...",
            model_name, device, encode_width, encode_height, self._quantization,
        )
        self.processor = AutoProcessor.from_pretrained(
            model_name, trust_remote_code=True,
        )

        if self._quantization in ("8bit", "4bit"):
            # 量化加载：需 bitsandbytes；device_map="auto" 承担设备分配，不能再用 .to(device)
            try:
                from transformers import BitsAndBytesConfig
                import bitsandbytes  # noqa: F401 — 确保已安装
            except ImportError as e:
                raise PluginLoadError(
                    f"[QwenVLEmbedder] quantization={self._quantization} 需要 bitsandbytes。"
                    "请先安装：pip install bitsandbytes"
                ) from e
            self.model = AutoModel.from_pretrained(
                model_name,
                trust_remote_code=True,
                device_map="auto",
                low_cpu_mem_usage=True,
                quantization_config=BitsAndBytesConfig(
                    load_in_8bit=(self._quantization == "8bit"),
                    load_in_4bit=(self._quantization == "4bit"),
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4",
                ),
            )
        else:
            self.model = AutoModel.from_pretrained(
                model_name,
                trust_remote_code=True,
                dtype=torch.float16 if device == "cuda" else torch.float32,
                device_map="auto" if device == "cuda" else None,
                low_cpu_mem_usage=True,
            ).to(device)
        self.model.eval()
        logger.info("[QwenVLEmbedder] Model loaded")

    # ═════════════════════════════════════════════════════════
    # 公开接口
    # ═════════════════════════════════════════════════════════

    async def encode_image(self, image: np.ndarray) -> list[float]:
        """将图像编码为 4096 维单位向量。"""
        if image.ndim == 2:
            image = np.stack([image] * 3, axis=-1)
        elif image.shape[2] == 4:
            image = image[:, :, :3]

        try:
            # 全局 GPU 锁：与 YOLO 前向互斥，避免并发驱动故障
            async with gpu_lock:
                vector = await asyncio.to_thread(
                    self._sync_encode_image, image,
                )
            return vector
        except Exception as e:
            logger.exception("[QwenVLEmbedder] Image encoding failed")
            raise

    async def encode_text(self, text: str) -> list[float]:
        """将文本编码为 4096 维单位向量。"""
        try:
            async with gpu_lock:
                vector = await asyncio.to_thread(
                    self._sync_encode_text, text,
                )
            return vector
        except Exception as e:
            logger.exception("[QwenVLEmbedder] Text encoding failed")
            raise

    async def encode_texts_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本编码 — 多段文本一次前向，比逐条 encode_text 吞吐更高。

        Args:
            texts: 文本列表（如每个场景拼接后的 caption+ocr+transcript）。

        Returns:
            list[list[float]] — 每段 4096 维归一化向量，顺序与输入一致。
        """
        if not texts:
            return []
        try:
            async with gpu_lock:
                vectors = await asyncio.to_thread(
                    self._sync_encode_texts_batch, texts,
                )
            return vectors
        except Exception as e:
            logger.exception("[QwenVLEmbedder] Batch text encoding failed")
            raise

    async def encode_video(
        self, video_path: str, fps: float = 1.0, max_frames: int = 32,
    ) -> list[float]:
        """原生视频编码 — 接受视频文件路径，模型内部处理帧提取与时序融合。"""
        try:
            async with gpu_lock:
                vector = await asyncio.to_thread(
                    self._sync_encode_video, video_path, fps, max_frames,
                )
            return vector
        except Exception as e:
            logger.exception("[QwenVLEmbedder] Video encoding failed")
            raise

    async def encode_images_batch(
        self, images: list[np.ndarray],
        target_size: tuple[int, int] | None = None,
    ) -> list[list[float]]:
        """批量图像编码 — 多帧一次前向，比逐帧 encode_image 吞吐更高。

        Args:
            images: 图像列表，每项为 (H, W, 3) uint8 numpy 数组。
            target_size: 可选 (w, h) 覆盖默认编码分辨率，用于速度预设。

        Returns:
            list[list[float]] — 每帧 4096 维归一化向量，顺序与输入一致。
        """
        # 统一通道数
        processed = []
        for img in images:
            if img.ndim == 2:
                img = np.stack([img] * 3, axis=-1)
            elif img.shape[2] == 4:
                img = img[:, :, :3]
            processed.append(img)

        try:
            # 全局 GPU 锁：与 YOLO 前向互斥，避免并发驱动故障
            async with gpu_lock:
                vectors = await asyncio.to_thread(
                    self._sync_encode_images_batch, processed, target_size,
                )
            return vectors
        except Exception as e:
            logger.exception("[QwenVLEmbedder] Batch image encoding failed")
            raise

    # ═════════════════════════════════════════════════════════
    # 同步推理（线程池中执行）
    # ═════════════════════════════════════════════════════════

    def _sync_encode_text(self, text: str) -> list[float]:
        """文本嵌入：chat template → pooling_last → L2 归一化。

        chat template 提供 system prompt + user 角色标记，让模型进入
        "嵌入模式"而非"语言续写模式"。pooling_last 取最后一个有效 token
        位置的 hidden state，保留完整序列语义而非被 padding 稀释。
        """
        conversation = [
            {"role": "system", "content": [{"type": "text", "text": self._SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "text", "text": text or " "}]},
        ]
        prompt = self.processor.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True,
        )
        inputs = self.processor(
            text=[prompt],
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)

        embedding = self._pool_last_token(
            outputs.last_hidden_state, inputs["attention_mask"],
        )
        return embedding.cpu().to(torch.float32).numpy().astype(np.float64).tolist()

    def _sync_encode_texts_batch(self, texts: list[str]) -> list[list[float]]:
        """批量文本嵌入：每段走 chat template → 一次前向 → 逐行 pooling_last。"""
        conversations = [
            [
                {"role": "system", "content": [{"type": "text", "text": self._SYSTEM_PROMPT}]},
                {"role": "user", "content": [{"type": "text", "text": t or " "}]},
            ]
            for t in texts
        ]
        prompts = [
            self.processor.apply_chat_template(
                conv, tokenize=False, add_generation_prompt=True,
            )
            for conv in conversations
        ]
        inputs = self.processor(
            text=prompts,
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)

        emb = self._pool_last_token(
            outputs.last_hidden_state, inputs["attention_mask"],
        )
        if emb.dim() == 1:  # B=1 时 _pool_last_token 返回 1D，补 batch 维
            emb = emb.unsqueeze(0)
        return emb.cpu().to(torch.float32).numpy().tolist()

    def _sync_encode_image(self, image: np.ndarray) -> list[float]:
        """图像嵌入：numpy → PIL Image（纯内存）→ process_vision_info → pooling_last。"""
        from PIL import Image as PILImage
        from qwen_vl_utils import process_vision_info

        pil_img = PILImage.fromarray(image).resize(self.encode_size, PILImage.LANCZOS)

        conversation = [
            {"role": "system", "content": [{"type": "text", "text": self._SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "image", "image": pil_img}]},
        ]

        text = self.processor.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True,
        )

        images, _ = process_vision_info(conversation)

        inputs = self.processor(
            text=[text],
            images=images,
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)

        embedding = self._pool_last_token(
            outputs.last_hidden_state, inputs["attention_mask"],
        )
        return embedding.cpu().to(torch.float32).numpy().astype(np.float64).tolist()

    def _sync_encode_images_batch(
        self, images: list[np.ndarray],
        target_size: tuple[int, int] | None = None,
    ) -> list[list[float]]:
        """批量图像编码 — 多帧 packing 为同一 batch 送入模型。

        直接走内存路径(PIL Image → processor)，零磁盘 I/O。
        编码前缩放到 encode_size 减少视觉 token（~10x 加速）。
        target_size 可覆盖默认分辨率（用于速度预设）。
        PIL resize 通过线程池并行化，float32 输出（余弦检索精度已足够）。
        """
        from concurrent.futures import ThreadPoolExecutor as Pool
        from PIL import Image as PILImage
        from qwen_vl_utils import process_vision_info

        encode_size = target_size if target_size is not None else self.encode_size

        # ── 并行 PIL 转换 (PIL 线程安全)；帧已达标（keyframe 抽帧已 resize）则跳过二次缩放 ──
        with Pool(max_workers=8) as pool:
            pil_images = list(pool.map(
                lambda img: (
                    PILImage.fromarray(img)
                    if (encode_size is not None
                        and img.shape[1] == encode_size[0] and img.shape[0] == encode_size[1])
                    else PILImage.fromarray(img).resize(encode_size, PILImage.LANCZOS)
                ),
                images,
            ))

        # ── 构建对话 + chat template + vision info (串行: processor 可能非线程安全) ──
        conversations = [
            [
                {"role": "system", "content": [{"type": "text", "text": self._SYSTEM_PROMPT}]},
                {"role": "user", "content": [{"type": "image", "image": pil_img}]},
            ]
            for pil_img in pil_images
        ]

        texts = []
        all_images: list = []
        for conv in conversations:
            text = self.processor.apply_chat_template(
                conv, tokenize=False, add_generation_prompt=True,
            )
            imgs, _ = process_vision_info(conv)
            texts.append(text)
            all_images.append(imgs[0] if imgs else None)

        inputs = self.processor(
            text=texts,
            images=all_images,
            return_tensors="pt",
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)

        # _pool_last_token 已做逐行 L2 归一化，无需后处理
        embeddings = self._pool_last_token(
            outputs.last_hidden_state, inputs["attention_mask"],
        )
        # embeddings shape: (batch_size, hidden_dim)

        # GPU → CPU float32 (4096-dim cos similarity 不需要 float64 精度)
        return embeddings.cpu().to(torch.float32).numpy().tolist()

    def _sync_encode_video(
        self, video_path: str, fps: float, max_frames: int,
    ) -> list[float]:
        """同步视频编码 — 在线程池中执行。"""
        os.environ.setdefault("TRANSFORMERS_DISABLE_TORCH_CHECK", "1")

        from qwen_vl_utils import process_vision_info

        abs_path = os.path.abspath(video_path)

        conversation = [
            {"role": "system", "content": [{"type": "text", "text": self._SYSTEM_PROMPT}]},
            {"role": "user", "content": [
                {"type": "video", "video": abs_path, "fps": fps, "max_frames": max_frames},
            ]},
        ]

        text = self.processor.apply_chat_template(
            conversation, tokenize=False, add_generation_prompt=True,
        )

        images, video_inputs, video_kwargs = process_vision_info(
            conversation,
            return_video_metadata=True,
            return_video_kwargs=True,
        )

        if video_inputs is not None:
            videos, video_metadata = zip(*video_inputs)
            videos = list(videos)
            video_metadata = list(video_metadata)
        else:
            videos, video_metadata = None, None

        inputs = self.processor(
            text=[text],
            images=images,
            videos=videos,
            video_metadata=video_metadata,
            return_tensors="pt",
            padding=True,
            **video_kwargs,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)

        embedding = self._pool_last_token(
            outputs.last_hidden_state, inputs["attention_mask"],
        )
        return embedding.cpu().to(torch.float32).numpy().astype(np.float64).tolist()

    # ═════════════════════════════════════════════════════════
    # 共用辅助
    # ═════════════════════════════════════════════════════════

    @staticmethod
    def _pool_last_token(hidden_states, attention_mask) -> torch.Tensor:
        """从最后一个非 padding token 位置提取向量并 L2 归一化。

        - 单样本 (B=1): 返回 1D (D,) 归一化向量
        - 批量 (B>1): 返回 2D (B, D)，逐行 L2 归一化

        模型训练时嵌入从该位置读取，mean pooling 会稀释语义信号。
        """
        flipped = attention_mask.flip(dims=[1])
        last_pos = flipped.argmax(dim=1)
        col = attention_mask.shape[1] - last_pos - 1
        row = torch.arange(hidden_states.shape[0], device=hidden_states.device)
        embedding = hidden_states[row, col]  # (B, D); 高级索引保留 batch 维度

        if embedding.shape[0] == 1:
            # 单样本: squeeze batch dim → 1D 向量，L2 归一化
            embedding = embedding.squeeze(0)
            norm = torch.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
        else:
            # 批量 (B>1): 逐行 L2 归一化，替代旧的 Frobenius group-norm bug
            embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)

        return embedding
