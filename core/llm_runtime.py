"""
core/llm_runtime.py
═══════════════════════════════════════════════════════════
小 LLM 共享单例（Qwen2.5-3B-Instruct + LoRA adapter）。

职责：
  - 全局唯一加载 base model + LoRA adapter（不重复加载，节省显存）
  - 通过 gpu_lock 串行化所有前向（与 YOLO/Embedder 互斥）
  - 提供 generate() 公共入口供多个 service 共用

使用方：
  - services/query_rewrite_service.py（query 改写）
  - services/detection_struct_service.py（YOLO 检测结果结构化）

设计：
  - Service Locator 模式，懒加载（首次调用 .get() 才加载）
  - 加载失败返回 None（不阻塞生产），上层 service 自己判空兜底
  - unload() 释放显存（用于切换 LoRA adapter 或暂时让位给其他模型）

显存预算（部署端 16GB 客户机）：
  - base Qwen2.5-3B FP16 ≈ 6GB
  - LoRA adapter ≈ 50MB
  - 总占用 ≈ 6GB
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_BASE_MODEL = "models/Qwen/Qwen2.5-3B-Instruct"
DEFAULT_ADAPTER_PATH = "models/Qwen2.5-3B-Instruct-zhiying-lora"


class LLMRuntime:
    """Qwen2.5-3B + LoRA 共享单例。"""

    _instance: Optional["LLMRuntime"] = None
    _lock = asyncio.Lock()

    def __init__(
        self,
        base_model_path: str = DEFAULT_BASE_MODEL,
        adapter_path: str | None = DEFAULT_ADAPTER_PATH,
        device: str = "cuda",
        torch_dtype: str = "bfloat16",
    ):
        self.base_model_path = base_model_path
        self.adapter_path = adapter_path
        self.device = device
        self.torch_dtype = torch_dtype

        self._tokenizer = None
        self._model = None
        self._adapter_loaded = False

    @classmethod
    async def get(
        cls,
        base_model_path: str = DEFAULT_BASE_MODEL,
        adapter_path: str | None = DEFAULT_ADAPTER_PATH,
    ) -> "LLMRuntime | None":
        """获取单例（懒加载）。加载失败返回 None（不阻塞生产）。"""
        if cls._instance is not None:
            return cls._instance

        async with cls._lock:
            if cls._instance is not None:
                return cls._instance

            # 二次校验：路径是否存在
            if not Path(base_model_path).exists():
                logger.warning(
                    f"[LLMRuntime] 底座模型不存在：{base_model_path}，跳过加载"
                )
                return None

            instance = cls(base_model_path, adapter_path)
            try:
                await instance._load()
                cls._instance = instance
                logger.info(
                    f"[LLMRuntime] 初始化完成：base={base_model_path}, adapter={adapter_path}"
                )
                return instance
            except Exception as e:
                logger.error(f"[LLMRuntime] 加载失败：{e}")
                return None

    async def _load(self):
        """加载 base + LoRA adapter（线程池执行，避免阻塞事件循环）"""
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
        import torch

        await asyncio.to_thread(self._sync_load)

    def _sync_load(self):
        """同步加载（在线程池中执行）"""
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel

        self._tokenizer = AutoTokenizer.from_pretrained(self.base_model_path)

        dtype_map = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }
        torch_dtype = dtype_map.get(self.torch_dtype, torch.bfloat16)

        self._model = AutoModelForCausalLM.from_pretrained(
            self.base_model_path,
            torch_dtype=torch_dtype,
            device_map=self.device,
        )

        # 加载 LoRA adapter（如果存在）
        if self.adapter_path and Path(self.adapter_path).exists():
            self._model = PeftModel.from_pretrained(self._model, self.adapter_path)
            self._adapter_loaded = True
            logger.info(f"[LLMRuntime] LoRA adapter 已加载：{self.adapter_path}")
        else:
            logger.info(
                f"[LLMRuntime] 未加载 LoRA adapter（{self.adapter_path} 不存在）"
            )

        self._model.eval()

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        max_new_tokens: int = 256,
        temperature: float = 0.0,
    ) -> str:
        """生成文本。

        Args:
            system_prompt: 系统 prompt
            user_message: 用户消息
            max_new_tokens: 最大生成 token 数
            temperature: 0 = 贪心（推荐 query 改写用），>0 = 采样

        Returns:
            生成的文本
        """
        if self._model is None:
            raise RuntimeError("LLMRuntime 未加载，请先调用 LLMRuntime.get()")

        # 与其他模型共享 gpu_lock（避免并发 GPU 故障）
        from core.gpu_lock import gpu_lock

        async with gpu_lock:
            return await asyncio.to_thread(
                self._sync_generate, system_prompt, user_message, max_new_tokens, temperature
            )

    def _sync_generate(
        self,
        system_prompt: str,
        user_message: str,
        max_new_tokens: int,
        temperature: float,
    ) -> str:
        """同步生成（在线程池中执行）"""
        import torch

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._tokenizer(text, return_tensors="pt").to(self._model.device)

        gen_kwargs = {"max_new_tokens": max_new_tokens}
        if temperature > 0:
            gen_kwargs["do_sample"] = True
            gen_kwargs["temperature"] = temperature
        else:
            gen_kwargs["do_sample"] = False

        with torch.no_grad():
            outputs = self._model.generate(**inputs, **gen_kwargs)

        output_ids = outputs[0][inputs["input_ids"].shape[1]:]
        result = self._tokenizer.decode(output_ids, skip_special_tokens=True).strip()
        return result

    def unload(self):
        """释放显存。"""
        if self._model is not None:
            import gc
            import torch

            del self._model
            self._model = None
            self._tokenizer = None
            self._adapter_loaded = False
            gc.collect()
            torch.cuda.empty_cache()
            logger.info("[LLMRuntime] 已释放显存")

    @classmethod
    def reset(cls):
        """重置单例（用于测试或切换 adapter）。"""
        if cls._instance is not None:
            cls._instance.unload()
            cls._instance = None
