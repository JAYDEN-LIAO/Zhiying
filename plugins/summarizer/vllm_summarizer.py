"""
plugins/summarizer/vllm_summarizer.py
═══════════════════════════════════════════════════════════
vLLM 摘要生成插件。

使用 openai AsyncOpenAI 客户端（纯异步 HTTP，无需 asyncio.to_thread）。
vLLM 部署于独立服务端口（默认 8010），提供 /v1/chat/completions 接口。
"""

import json
import logging
import os

from openai import AsyncOpenAI

from core.interfaces import BaseSummarizer
from core.exceptions import PipelineError

logger = logging.getLogger(__name__)


class VLLMSummarizer(BaseSummarizer):
    """基于 vLLM OpenAI 兼容 API 的结构化摘要生成。

    Args:
        base_url: vLLM 服务地址（含 /v1 路径）。
        model_name: 部署的模型名称。
        max_tokens: 生成最大 token 数。
        temperature: 采样温度。
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8010/v1",
        model_name: str = "Qwen2.5-7B-Instruct",
        max_tokens: int = 2048,
        temperature: float = 0.1,
        api_key: str = "not-needed",
        **kwargs,
    ):
        # 兜底：配置里的占位 key 无效时回退到环境变量（前端设置页注入）
        if not api_key or api_key in ("placeholder", "not-needed"):
            api_key = os.environ.get("DEEPSEEK_API_KEY") or "not-needed"
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        logger.info(
            "[VLLMSummarizer] Connected to %s model=%s", base_url, model_name,
        )

    async def summarize(
        self,
        script: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """生成结构化 JSON 摘要。

        user_prompt 已在调用侧渲染完成（含剧本与时序信息），
                       本层直接使用不再做 format。

        Args:
            script: 按时间排列的完整视频剧本（兼容接口，不再嵌入 prompt）。
            system_prompt: 系统角色提示词。
            user_prompt: 用户提示词（已渲染完毕）。

        Returns:
            {
                "one_liner": str,
                "scenes_summary": [{"scene_index", "start_sec", "end_sec", "description", "keywords"}],
                "tags": [str],
                "main_topics": [str],
                "main_entities": [str],
            }

        Raises:
            PipelineError: API 调用失败或 JSON 解析失败（调用方 SummaryRunner
                会兜底回退本地聚合，不因摘要拖垮整个管道）。

        截断根治：
          - finish_reason == "length"（响应被 max_tokens 截断）→ 自动以更大预算
            重试，最多 3 次（max_tokens 翻倍：2048 → 4096 → 8192，上限 16384）；
          - 重试仍截断 → _parse_json 走截断修复（补闭合引号/括号）尽力恢复结构。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        max_tokens = self.max_tokens
        for attempt in range(1, 4):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                if not content:
                    raise PipelineError("vLLM returned empty response content")

                truncated = finish_reason == "length"
                if truncated and attempt < 3:
                    logger.warning(
                        "[VLLMSummarizer] Response truncated at max_tokens=%d "
                        "(finish_reason=length), retrying with %d",
                        max_tokens, min(max_tokens * 2, 16384),
                    )
                    max_tokens = min(max_tokens * 2, 16384)
                    continue

                return self._parse_json(content, truncated=truncated)

            except PipelineError:
                raise
            except Exception as e:
                logger.exception("[VLLMSummarizer] API call failed")
                raise PipelineError(f"vLLM summarizer failed: {e}") from e

    @staticmethod
    def _parse_json(content: str, truncated: bool = False) -> dict:
        """尝试解析 JSON，处理 ```json ... ``` 包裹 / 截断修复等常见情况。"""
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 包裹
        if "```json" in content:
            start = content.index("```json") + 7
            end = content.index("```", start) if "```" in content[start:] else len(content)
            content = content[start:end].strip()
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass

        # 尝试提取 ``` ... ``` 包裹
        if content.startswith("```") and content.endswith("```"):
            inner = content.strip("`").strip()
            try:
                return json.loads(inner)
            except json.JSONDecodeError:
                pass

        # 截断修复（finish_reason=length）：补闭合引号 + 补齐括号，尽力恢复结构
        if truncated:
            repaired = VLLMSummarizer._repair_truncated_json(content)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

        # 全部失败
        raise PipelineError(
            f"Failed to parse vLLM response as JSON. "
            f"Response preview: {content[:300]}"
        )

    @staticmethod
    def _repair_truncated_json(content: str) -> str:
        """修复被 max_tokens 截断的 JSON：闭合未完成的字符串 + 补齐未闭合括号。"""
        s = content.rstrip()

        # 1. 字符串被截断（奇数个未转义引号）→ 补一个闭合引号
        quotes_open = False
        escaped = False
        for ch in s:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quotes_open = not quotes_open
        if quotes_open:
            s += '"'

        # 2. 补齐未闭合括号（忽略字符串内部的括号）
        stack: list[str] = []
        pairs = {")": "(", "]": "[", "}": "{"}
        closer = {"(": ")", "[": "]", "{": "}"}
        in_str = False
        escaped = False
        for ch in s:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch in "([{":
                stack.append(ch)
            elif ch in ")]}":
                if stack and stack[-1] == pairs[ch]:
                    stack.pop()
        for opener in reversed(stack):
            s += closer[opener]

        return s
