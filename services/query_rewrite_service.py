"""
services/query_rewrite_service.py
═══════════════════════════════════════════════════════════
Query 改写服务 — 基于 Qwen2.5-3B + LoRA 的 query 扩写。

核心职责：
  - 接受用户原始自然语言 query
  - 调用微调后的 3B LLM 改写为 3-5 个等价检索表达式
  - 返回 query 列表（包含原 query），供 7 路检索联合召回

调用方：
  - api/search_routes.py::search_semantic（搜索入口）
  - 任何想做 query 增强的检索服务

失败兜底：
  - LLM 未加载/失败 → 返回 [原 query]（不影响生产）
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 默认 prompt（与训练时的 inference_system_prompt 完全一致）
DEFAULT_SYSTEM_PROMPT = """你是视频检索领域的专家标注员。你的任务是将用户的自然语言 query 改写为 3-5 个等价的检索表达式。

改写要覆盖以下维度：
1. 字面表述：保留原 query 的核心意思
2. 同义近义词：用相关领域的同义词替换
3. 英文翻译：如果原 query 是中文，提供 1-2 个英文版本
4. 更短的关键字形式：去掉停用词，只保留核心检索词

输出要求：
- 每行一个表达式，不要编号
- 不要其他解释、说明、标签
- 不要用 markdown 代码块包裹
- 改写要符合监控/交通领域的真实表述习惯

现在请处理用户给定的 query。"""


class QueryRewriteService:
    """Query 改写服务（懒加载 LLMRuntime，失败兜底）。"""

    def __init__(
        self,
        base_model_path: str | None = None,
        adapter_path: str | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_new_tokens: int = 256,
        min_rewrites: int = 1,
    ):
        self._base_model_path = base_model_path
        self._adapter_path = adapter_path
        self._system_prompt = system_prompt
        self._max_new_tokens = max_new_tokens
        self._min_rewrites = min_rewrites
        self._runtime = None  # 懒加载

    async def _ensure_runtime(self):
        """懒加载 LLMRuntime（首次调用时）"""
        if self._runtime is not None:
            return self._runtime
        from core.llm_runtime import LLMRuntime

        self._runtime = await LLMRuntime.get(
            base_model_path=self._base_model_path or "models/Qwen/Qwen2.5-3B-Instruct",
            adapter_path=self._adapter_path or "models/Qwen2.5-3B-Instruct-zhiying-lora",
        )
        return self._runtime

    async def rewrite(self, query: str) -> list[str]:
        """改写 query，返回包含原 query 的列表。

        Args:
            query: 用户原始 query

        Returns:
            改写后的 query 列表（第一项始终是原 query，至少 1 项）
        """
        if not query or not query.strip():
            return [query] if query else []

        runtime = await self._ensure_runtime()
        if runtime is None:
            # LLM 不可用 → 返回原 query
            logger.debug(f"[QueryRewrite] LLM 不可用，返回原 query：{query}")
            return [query]

        try:
            user_msg = f"原 query：{query}\n\n改写："
            result = await runtime.generate(
                system_prompt=self._system_prompt,
                user_message=user_msg,
                max_new_tokens=self._max_new_tokens,
                temperature=0.0,  # 贪心解码，结果稳定
            )
        except Exception as e:
            logger.warning(f"[QueryRewrite] LLM 推理失败：{e}，返回原 query")
            return [query]

        # 解析：每行一个改写
        rewrites = []
        for line in result.split("\n"):
            line = line.strip()
            # 过滤空行、编号行（1. 2. 等）、markdown 标记
            if not line:
                continue
            if line.startswith(("-", "*", "•", "#")):
                line = line.lstrip("-*•# ").strip()
            if line and line != query:
                rewrites.append(line)

        # 兜底：至少返回原 query
        if not rewrites:
            return [query]

        # 限制数量
        rewrites = rewrites[:5]
        return [query] + rewrites

    async def rewrite_batch(self, queries: list[str]) -> list[list[str]]:
        """批量改写"""
        return [await self.rewrite(q) for q in queries]
