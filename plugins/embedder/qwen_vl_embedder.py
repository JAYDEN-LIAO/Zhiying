"""
plugins/embedder/qwen_vl_embedder.py
═══════════════════════════════════════════════════════════
Qwen3-VL-Embedding 向量编码插件。

图像 / 文本 / 视频 → 2048 维归一化嵌入向量。
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
import tempfile

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

    _SYSTEM_PROMPT = "检索与查询相关的视频内容。"

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
        """将图像编码为 2048 维单位向量。"""
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
        """将文本编码为 2048 维单位向量。"""
        try:
            vector = await asyncio.to_thread(
                self._sync_encode_text, text,
            )
            return vector
        except Exception as e:
            logger.exception("[QwenVLEmbedder] Text encoding failed")
            raise

    async def encode_video(
        self, video_path: str, fps: float = 1.0, max_frames: int = 32,
    ) -> list[float]:
        """原生视频编码 — 接受视频文件路径，模型内部处理帧提取与时序融合。"""
        try:
            vector = await asyncio.to_thread(
                self._sync_encode_video, video_path, fps, max_frames,
            )
            return vector
        except Exception as e:
            logger.exception("[QwenVLEmbedder] Video encoding failed")
            raise

    async def encode_images_batch(
        self, images: list[np.ndarray],
    ) -> list[list[float]]:
        """批量图像编码 — 多帧一次前向，比逐帧 encode_image 吞吐更高。

        Args:
            images: 图像列表，每项为 (H, W, 3) uint8 numpy 数组。

        Returns:
            list[list[float]] — 每帧 2048 维归一化向量，顺序与输入一致。
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
            vectors = await asyncio.to_thread(
                self._sync_encode_images_batch, processed,
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
        return embedding.cpu().numpy().astype(np.float64).tolist()

    def _sync_encode_image(self, image: np.ndarray) -> list[float]:
        """图像嵌入：保存临时文件 → process_vision_info → chat template → pooling_last。

        通过 qwen_vl_utils.process_vision_info 处理图像输入，
        确保 processor 正确分配 image tokens。
        使用聊天模板激活嵌入模式，pooling_last 提取语义向量。
        """
        from PIL import Image as PILImage
        from qwen_vl_utils import process_vision_info

        # 内存 numpy → 临时 JPEG 文件（process_vision_info 要求文件路径）
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        tmp_path = tmp.name
        try:
            PILImage.fromarray(image).save(tmp_path, format="JPEG", quality=85)
        except Exception:
            os.unlink(tmp_path)
            raise
        finally:
            tmp.close()

        try:
            conversation = [
                {"role": "system", "content": [{"type": "text", "text": self._SYSTEM_PROMPT}]},
                {"role": "user", "content": [{"type": "image", "image": tmp_path}]},
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
            result = embedding.cpu().numpy().astype(np.float64).tolist()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return result

    def _sync_encode_images_batch(
        self, images: list[np.ndarray],
    ) -> list[list[float]]:
        """批量图像编码 — 多帧 packing 为同一 batch 送入模型。

        每帧独立走 process_vision_info + chat template，
        最后拼成 batch 做一次前向，由 pooling_last 输出各自向量。
        """
        from PIL import Image as PILImage
        from qwen_vl_utils import process_vision_info

        # 将所有帧写入临时 JPEG 文件
        tmp_paths: list[str] = []
        for img in images:
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp_path = tmp.name
            try:
                PILImage.fromarray(img).save(tmp_path, format="JPEG", quality=85)
            except Exception:
                os.unlink(tmp_path)
                raise
            finally:
                tmp.close()
            tmp_paths.append(tmp_path)

        try:
            conversations = [
                [
                    {"role": "system", "content": [{"type": "text", "text": self._SYSTEM_PROMPT}]},
                    {"role": "user", "content": [{"type": "image", "image": p}]},
                ]
                for p in tmp_paths
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

            embeddings = self._pool_last_token(
                outputs.last_hidden_state, inputs["attention_mask"],
            )
            # embeddings shape: (batch_size, hidden_dim)

            results: list[list[float]] = []
            for emb in embeddings:
                norm = torch.linalg.norm(emb)
                if norm > 0:
                    emb = emb / norm
                results.append(emb.cpu().numpy().astype(np.float64).tolist())
            return results

        finally:
            for p in tmp_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass

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
        return embedding.cpu().numpy().astype(np.float64).tolist()

    # ═════════════════════════════════════════════════════════
    # 共用辅助
    # ═════════════════════════════════════════════════════════

    @staticmethod
    def _pool_last_token(hidden_states, attention_mask) -> torch.Tensor:
        """从最后一个非 padding token 位置提取向量。

        模型训练时嵌入从该位置读取，mean pooling 会稀释语义信号。
        """
        flipped = attention_mask.flip(dims=[1])
        last_pos = flipped.argmax(dim=1)
        col = attention_mask.shape[1] - last_pos - 1
        row = torch.arange(hidden_states.shape[0], device=hidden_states.device)
        embedding = hidden_states[row, col].squeeze(0)
        norm = torch.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding
