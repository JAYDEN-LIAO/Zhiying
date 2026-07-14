"""
plugins/captioner/qwen_vl_captioner.py
═══════════════════════════════════════════════════════════
Qwen2.5-VL 画面描述插件。

模型推理（model.generate）是同步 GPU 密集型调用，
必须使用 asyncio.to_thread() 包裹。
"""

import asyncio
import logging

import numpy as np
import torch

from core.interfaces import BaseCaptioner
from core.exceptions import PluginLoadError

logger = logging.getLogger(__name__)


class QwenVLCaptioner(BaseCaptioner):
    """基于 Qwen2.5-VL 的画面描述实现。

    同时兼容 HuggingFace 和 ModelScope 模型路径命名。

    Args:
        model_name: 模型名称或路径。
                     HF: "Qwen/Qwen2.5-VL-2B-Instruct"
                     MS: "Qwen/Qwen2.5-VL-2B-Instruct"
        device: 推理设备 ("cuda" / "cpu")。
        max_new_tokens: 默认最大生成长度。
        with_context: 是否启用上下文记忆窗口。
    """

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-VL-2B-Instruct",
        device: str = "cuda",
        max_new_tokens: int = 256,
        with_context: bool = False,
        **kwargs,
    ):
        try:
            from transformers import (
                Qwen2_5_VLForConditionalGeneration,
                AutoProcessor,
            )
        except ImportError as e:
            raise PluginLoadError(
                "transformers not installed. Run: pip install transformers"
            ) from e

        self.device = device
        self.default_max_new_tokens = max_new_tokens
        self.with_context = with_context

        logger.info("[QwenVLCaptioner] Loading model %s on %s ...", model_name, device)
        self.processor = AutoProcessor.from_pretrained(model_name)
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_name,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            device_map="auto" if device == "cuda" else None,
            low_cpu_mem_usage=True,
        ).to(device)
        self.model.eval()
        logger.info("[QwenVLCaptioner] Model loaded")

    async def caption(
        self,
        keyframes: list[np.ndarray],
        prompt: str,
        max_new_tokens: int = 256,
    ) -> str:
        """对一组关键帧生成深度画面描述。

        当前使用首个关键帧进行单帧描述，
        后续可扩展为多帧时序输入。

        Args:
            keyframes: 关键帧序列，每帧 (H, W, C) uint8。
            prompt: 由 prompt_loader 渲染好的完整提示词。
            max_new_tokens: 生成最大 token 数。

        Returns:
            中文描述字符串。
        """
        if not keyframes:
            logger.warning("[QwenVLCaptioner] No keyframes provided")
            return ""

        frame = keyframes[0]
        if frame.ndim == 2:
            frame = np.stack([frame] * 3, axis=-1)
        elif frame.shape[2] == 4:
            frame = frame[:, :, :3]

        token_limit = max_new_tokens or self.default_max_new_tokens

        try:
            output = await asyncio.to_thread(
                self._sync_generate, frame, prompt, token_limit
            )
            return output.strip()
        except Exception as e:
            logger.exception("[QwenVLCaptioner] Caption generation failed")
            raise

    def _sync_generate(
        self, keyframe: np.ndarray, prompt: str, max_new_tokens: int
    ) -> str:
        """同步推理 — 在线程池中执行。"""
        inputs = self.processor(
            text=[prompt],
            images=[keyframe],
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                num_beams=1,
            )

        output = self.processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
        )[0]

        # 剔除 prompt 部分（生成时是续写模式）
        # output 中可能包含用户输入的 prompt，需要清理
        if prompt in output:
            output = output.replace(prompt, "", 1).strip()

        return output
