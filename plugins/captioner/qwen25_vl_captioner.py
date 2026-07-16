"""
plugins/captioner/qwen25_vl_captioner.py
═══════════════════════════════════════════════════════════
Qwen2.5-VL 7B 本地视频理解 Captioner。

与 Qwen-VL-Max API 不同，此插件直接加载本地 4-bit 量化模型，
输入视频片段 → 原生视频理解 → 场景描述。

无需逐帧推导，模型内部自检多帧抽取与时间序列理解。

配置示例（config.yaml）:
  captioner:
    backend: "qwen25_vl"
    params:
      model_name: "models/models/Qwen2.5-VL-7B-Instruct-GPTQ-Int4"
      max_new_tokens: 512
      min_pixels: 200704
      max_pixels: 1003520
"""

import asyncio
import logging
import os
import tempfile
import uuid

import numpy as np

from core.interfaces import BaseCaptioner
from core.exceptions import PluginLoadError

logger = logging.getLogger(__name__)


class Qwen25VLCaptioner(BaseCaptioner):
    """基于 Qwen2.5-VL 7B 的本地视频理解描述器。

    直接接受视频文件路径 + 起止时间，让模型原生理解视频片段，
    而非逐帧截图后拼凑。

    Args:
        model_name: 模型路径或 HuggingFace ID（建议使用 GPTQ-Int4 量化版）。
        max_new_tokens: 生成最大 token 数。
        min_pixels: 最小像素数，控制显存。
        max_pixels: 最大像素数，控制显存。
    """

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-VL-7B-Instruct-GPTQ-Int4",
        max_new_tokens: int = 512,
        min_pixels: int = 200704,
        max_pixels: int = 1003520,
        **kwargs,
    ):
        self.model_name = model_name
        self.max_new_tokens = max_new_tokens
        self.min_pixels = min_pixels
        self.max_pixels = max_pixels
        self._model = None
        self._processor = None

        # 由 Phase4Caption 在执行前注入（轻量胶水，不影响接口）
        self.video_path: str | None = None
        self.scene_start: float | None = None
        self.scene_end: float | None = None

    # ──────────────────────────────────────────────────────
    # 公开接口
    # ──────────────────────────────────────────────────────

    async def caption(
        self,
        keyframes: list[np.ndarray],
        prompt: str,
        max_new_tokens: int | None = None,
    ) -> str:
        """对视频片段生成描述。

        Args:
            keyframes: 忽略（模型直接从 video_path 读取视频）。
            prompt: 提示词。
            max_new_tokens: 覆盖实例默认值。

        Returns:
            视频片段的自然语言描述。
        """
        # 延迟加载（首次调用时加载模型）
        if self._model is None:
            await self._load_model()

        if self.video_path is None:
            logger.warning("[Qwen25VLCaptioner] video_path not set, falling back to empty caption")
            return ""

        start = self.scene_start or 0.0
        end = self.scene_end or 0.0
        clip_dur = end - start
        if clip_dur <= 0:
            return ""

        # 创建临时视频片段（-c copy 流复制，原始画质）
        temp_dir = tempfile.mkdtemp(prefix="qwen25vl_")
        clip_path = os.path.join(temp_dir, f"clip_{uuid.uuid4().hex}.mp4")
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", self.video_path,
                "-t", str(clip_dur),
                "-c", "copy",
                clip_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0 or not os.path.exists(clip_path):
                return ""

            # Qwen2.5-VL 视频推理
            result = await asyncio.to_thread(
                self._sync_infer, clip_path, prompt, max_new_tokens,
            )
            return result
        finally:
            try:
                os.remove(clip_path)
            except OSError:
                pass
            try:
                os.rmdir(temp_dir)
            except OSError:
                pass

    def unload(self) -> None:
        """释放 GPU 显存，为同设备上的其他模型让路。"""
        if self._model is not None:
            import gc
            import torch
            self._model.cpu()
            del self._model
            self._processor = None
            self._model = None
            gc.collect()
            torch.cuda.empty_cache()

    # ──────────────────────────────────────────────────────
    # 私有：模型生命周期
    # ──────────────────────────────────────────────────────

    async def _load_model(self) -> None:
        """异步加载模型到 GPU（asyncio.to_thread 投递线程池）。"""
        logger.info("[Qwen25VLCaptioner] Loading %s ...", self.model_name)
        try:
            await asyncio.to_thread(self._sync_load_model)
            logger.info("[Qwen25VLCaptioner] Model loaded on GPU")
        except Exception as e:
            raise PluginLoadError(
                f"Failed to load Qwen2.5-VL-7B: {e}"
            ) from e

    def _sync_load_model(self) -> None:
        """同步加载模型（在线程池中执行）。

        支持 AWQ / GPTQ / BNB 4-bit 三种量化格式，自动适配。
        """
        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor

        self._processor = AutoProcessor.from_pretrained(
            self.model_name,
            min_pixels=self.min_pixels,
            max_pixels=self.max_pixels,
        )

        # 先检查是否为预量化模型（AWQ / GPTQ 格式）
        import json, os
        config_path = os.path.join(self.model_name, "config.json")
        is_pre_quantized = False
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = json.load(f)
            qcfg = cfg.get("quantization_config") or {}
            is_pre_quantized = qcfg.get("quant_method") in ("awq", "gptq")

        if is_pre_quantized:
            # AWQ / GPTQ 预量化模型：transformers 原生加载
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                self.model_name,
                device_map="auto",
                torch_dtype="auto",
            )
        else:
            # 原版模型：用 bitsandbytes 4-bit 量化加载
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                self.model_name,
                device_map="auto",
                load_in_4bit=True,
                bnb_4bit_compute_dtype="float16",
            )
        self._model.eval()

    def _sync_infer(
        self,
        clip_path: str,
        prompt: str,
        max_new_tokens: int | None,
    ) -> str:
        """同步视频推理（在线程池中执行）。"""
        from qwen_vl_utils import process_vision_info

        max_tokens = max_new_tokens or self.max_new_tokens

        messages = [
            {"role": "user", "content": [
                {"type": "video", "video": clip_path, "nframes": 16},
                {"type": "text", "text": prompt},
            ]},
        ]

        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
        )
        image_inputs, video_inputs, video_kwargs = process_vision_info(
            messages, return_video_kwargs=True,
        )

        inputs = self._processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
            **video_kwargs,
        )
        inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

        generated_ids = self._model.generate(**inputs, max_new_tokens=max_tokens)
        trimmed = [
            out_ids[len(in_ids):]
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output = self._processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=True,
        )
        return (output[0] if output else "").strip()
