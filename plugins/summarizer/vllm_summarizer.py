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
            PipelineError: API 调用失败或 JSON 解析失败。
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                raise PipelineError("vLLM returned empty response content")

            return self._parse_json(content)

        except PipelineError:
            raise
        except Exception as e:
            logger.exception("[VLLMSummarizer] API call failed")
            raise PipelineError(f"vLLM summarizer failed: {e}") from e

    @staticmethod
    def _parse_json(content: str) -> dict:
        """尝试解析 JSON，处理 ```json ... ``` 包裹等常见情况。"""
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

        # 全部失败
        raise PipelineError(
            f"Failed to parse vLLM response as JSON. "
            f"Response preview: {content[:300]}"
        )
