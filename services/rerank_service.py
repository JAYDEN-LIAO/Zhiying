"""
services/rerank_service.py
═══════════════════════════════════════════════════════════
Reranker 服务 — 基于 bge-reranker-v2-m3 的检索重排序。

核心职责：
  - 接受 query + 候选结果列表
  - 用 bge-reranker-v2-m3 计算每个候选的相关性分数
  - 返回重排后的 top-k 列表

调用方：
  - pipeline/search_engine.py::search() 末尾追加（条件开关）

模型：
  - BAAI/bge-reranker-v2-m3（中文强，~2.3GB）

失败兜底：
  - Reranker 未加载/失败 → 返回原顺序，不阻塞检索
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class RerankService:
    """Reranker 服务（懒加载，失败兜底）。"""

    DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL,
        top_k: int = 10,
        max_length: int = 512,
    ):
        self._model_path = model_path
        self._top_k = top_k
        self._max_length = max_length
        self._model = None
        self._tokenizer = None

    async def _ensure_loaded(self):
        """懒加载 bge-reranker（首次调用时）"""
        if self._model is not None:
            return

        from pathlib import Path
        # 模型路径不存在时尝试默认 cache
        model_path = self._model_path
        if not Path(model_path).exists():
            # 尝试项目本地路径
            local_path = f"models/BAAI/bge-reranker-v2-m3"
            if Path(local_path).exists():
                model_path = local_path

        try:
            import asyncio
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            # 同步加载放到线程池
            await asyncio.to_thread(self._sync_load, model_path)
            logger.info(f"[Rerank] 模型加载完成：{model_path}")
        except Exception as e:
            logger.warning(f"[Rerank] 模型加载失败：{e}，rerank 不可用")
            self._model = None
            self._tokenizer = None

    def _sync_load(self, model_path: str):
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(model_path)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_path)
        self._model.eval()

    async def rerank(
        self,
        query: str,
        candidates: list[dict],
        content_key: str = "text",
    ) -> list[dict]:
        """对候选结果按 query 相关性重排。

        Args:
            query: 原始查询
            candidates: [{"text": str, "score": float, ...}, ...]
            content_key: candidates 中用于计算相关性的字段名

        Returns:
            重排后的 top-k 列表（按 rerank 分数降序）
        """
        if not query or not candidates:
            return candidates[:self._top_k]

        await self._ensure_loaded()
        if self._model is None:
            # 兜底：返回原顺序
            return candidates[:self._top_k]

        try:
            import asyncio
            from core.gpu_lock import gpu_lock

            async with gpu_lock:
                scores = await asyncio.to_thread(
                    self._sync_rerank, query, candidates, content_key
                )
        except Exception as e:
            logger.warning(f"[Rerank] 推理失败：{e}，返回原顺序")
            return candidates[:self._top_k]

        # 按 rerank 分数降序排
        ranked = sorted(
            zip(candidates, scores),
            key=lambda x: x[1],
            reverse=True,
        )[:self._top_k]
        return [c for c, s in ranked]

    def _sync_rerank(
        self, query: str, candidates: list[dict], content_key: str
    ) -> list[float]:
        """同步重排序（在线程池中执行）"""
        import torch

        pairs = []
        for c in candidates:
            content = c.get(content_key, "")
            if not content:
                content = str(c)
            pairs.append([query, content[: self._max_length * 2]])  # 粗略截断

        inputs = self._tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=self._max_length,
            return_tensors="pt",
        )

        with torch.no_grad():
            outputs = self._model(**inputs)
            # bge-reranker 输出单个相关性分数
            scores = outputs.logits.squeeze(-1).tolist()

        return scores
