"""
plugins/captioner/qwen3_vl_captioner.py
═══════════════════════════════════════════════════════════
Qwen3-VL 8B 本地视频理解 Captioner。

Qwen3-VL 相比 Qwen2.5-VL 的核心升级：
  - 256K 上下文窗口（vs 128K）
  - 120fps 高帧率支持（vs 更低上限）
  - Thinking 模式（因果推理，适合行为分析）
  - SigLIP-2 vision encoder（更好的小物体细节）
  - VideoLLM-Bench: 73.5（vs 61.2）

配置示例（config.yaml）:
  captioner:
    backend: "qwen3_vl"
    params:
      model_name: "Qwen/Qwen3-VL-8B-Instruct"
      max_new_tokens: 2048
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


class Qwen3VLCaptioner(BaseCaptioner):
    """基于 Qwen3-VL 的本地视频理解描述器。

    Args:
        model_name: 模型路径或 HuggingFace ID。
        max_new_tokens: 生成最大 token 数。
        min_pixels: 最小像素数，控制显存。
        max_pixels: 最大像素数，控制显存。
    """

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-VL-8B-Instruct",
        max_new_tokens: int = 2048,
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
        self._load_lock = asyncio.Lock()

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
        """对视频片段生成描述（native_video 模式：模型直接看视频）。"""
        if self._model is None:
            async with self._load_lock:
                if self._model is None:
                    await self._load_model()

        if self.video_path is None:
            logger.warning("[Qwen3VLCaptioner] video_path not set, falling back to empty caption")
            return ""

        start = self.scene_start or 0.0
        end = self.scene_end or 0.0
        clip_dur = end - start
        if clip_dur <= 0:
            return ""

        temp_dir = tempfile.mkdtemp(prefix="qwen3vl_")
        clip_path = os.path.join(temp_dir, f"clip_{uuid.uuid4().hex}.mp4")
        try:
            # -ss 在 -i 之前: 输入级 seek，精准到帧；-c copy 降级到最近关键帧时
            # -avoid_negative_ts 保证输出时间戳从 0 开始，避免播放器兼容问题
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", self.video_path,
                "-t", str(clip_dur),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                clip_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0 or not os.path.exists(clip_path):
                return ""

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
        """释放 GPU 显存。"""
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
    # 模型生命周期
    # ──────────────────────────────────────────────────────

    async def preload(self) -> None:
        """预加载模型到 GPU（启动时调用，避免首次 caption() 卡顿）。"""
        if self._model is None:
            async with self._load_lock:
                if self._model is None:
                    await self._load_model()

    async def _load_model(self) -> None:
        logger.info("[Qwen3VLCaptioner] Loading %s ...", self.model_name)
        try:
            await asyncio.to_thread(self._sync_load_model)
            logger.info("[Qwen3VLCaptioner] Model loaded on GPU")
        except Exception as e:
            raise PluginLoadError(
                f"Failed to load Qwen3-VL: {e}"
            ) from e

    def _sync_load_model(self) -> None:
        """同步加载模型（在线程池中执行）。

        优先检查预量化格式（AWQ/GPTQ），否则用 bf16 加载。
        GB10 128 GB 统一内存 → bf16 直接跑无压力。
        """
        from transformers import Qwen3VLForConditionalGeneration, AutoProcessor

        self._processor = AutoProcessor.from_pretrained(
            self.model_name,
            min_pixels=self.min_pixels,
            max_pixels=self.max_pixels,
            trust_remote_code=True,
        )

        # 检查是否为预量化模型
        import json
        config_path = os.path.join(self.model_name, "config.json")
        is_pre_quantized = False
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = json.load(f)
            qcfg = cfg.get("quantization_config") or {}
            is_pre_quantized = qcfg.get("quant_method") in ("awq", "gptq")

        if is_pre_quantized:
            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                self.model_name,
                device_map="auto",
                torch_dtype="auto",
                trust_remote_code=True,
            )
        else:
            # bf16 全精度（GB10 128 GB 轻松容纳）
            import torch
            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                self.model_name,
                device_map="auto",
                torch_dtype=torch.bfloat16,
                trust_remote_code=True,
            )
        self._model.eval()

    def _sync_infer(
        self,
        clip_path: str,
        prompt: str,
        max_new_tokens: int | None,
    ) -> str:
        """同步视频推理（在线程池中执行）。

        用 cv2 抽帧 → 临时 JPEG → image 列表传给模型。
        避免 torchvision/decodec 的 video 读取后端兼容问题（aarch64）。
        """
        import cv2
        import tempfile as _tmp
        from PIL import Image as _PILImage
        from qwen_vl_utils import process_vision_info

        max_tokens = max_new_tokens or self.max_new_tokens
        nframes = 16

        # cv2 抽帧
        cap = cv2.VideoCapture(clip_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        indices = [int(total_frames * i / nframes) for i in range(nframes)]
        frames: list[np.ndarray] = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret and frame is not None:
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        cap.release()

        if not frames:
            return ""

        # 帧 → 临时 JPEG（process_vision_info 需要文件路径或 PIL Image）
        tmp_paths: list[str] = []
        for frame in frames:
            tmp = _tmp.NamedTemporaryFile(suffix=".jpg", delete=False)
            _PILImage.fromarray(frame).save(tmp, format="JPEG", quality=85)
            tmp_paths.append(tmp.name)

        try:
            image_content = [{"type": "image", "image": p} for p in tmp_paths]
            messages = [
                {"role": "user", "content": image_content + [
                    {"type": "text", "text": prompt},
                ]},
            ]

            text = self._processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
            )
            image_inputs, _ = process_vision_info(messages)

            inputs = self._processor(
                text=[text],
                images=image_inputs,
                padding=True,
                return_tensors="pt",
            )
            inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

            generated_ids = self._model.generate(**inputs, max_new_tokens=max_tokens)
            if isinstance(generated_ids, dict):
                output_ids = generated_ids["sequences"]
            elif hasattr(generated_ids, "sequences"):
                output_ids = generated_ids.sequences
            else:
                output_ids = generated_ids
            input_ids = inputs["input_ids"]
            trimmed = [
                out_ids[len(in_ids):]
                for in_ids, out_ids in zip(input_ids, output_ids)
            ]
            output = self._processor.batch_decode(
                trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=True,
            )
            return (output[0] if output else "").strip()
        finally:
            for p in tmp_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
