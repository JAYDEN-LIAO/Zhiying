"""
plugins/captioner/qwen_api_captioner.py
═══════════════════════════════════════════════════════════
Qwen API 画面描述插件 — 通过 DashScope OpenAI 兼容接口调用 qwen-vl-max。

使用裸 httpx 请求（而非 openai 库），精确控制 UTF-8 编解码，
避免 openai 库内部 httpx 编码检测导致的中文乱码。
"""

import base64
import io
import json
import logging

import httpx
import numpy as np

from core.interfaces import BaseCaptioner

logger = logging.getLogger(__name__)


class QwenAPICaptioner(BaseCaptioner):
    """基于 DashScope qwen-vl-max API 的画面描述实现。

    Args:
        base_url: DashScope OpenAI 兼容端点。
        api_key: DashScope API Key。
        model_name: 模型名称，默认 "qwen-vl-max"。
        max_new_tokens: 默认最大生成长度。
    """

    def __init__(
        self,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key: str = "",
        model_name: str = "qwen-vl-max",
        max_new_tokens: int = 256,
        **kwargs,
    ):
        if not api_key:
            logger.warning("[QwenAPICaptioner] api_key is empty")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.default_max_tokens = max_new_tokens
        logger.info(
            "[QwenAPICaptioner] Ready: %s model=%s",
            base_url, model_name,
        )

    async def caption(
        self,
        keyframe: np.ndarray,
        prompt: str,
        max_new_tokens: int = 256,
    ) -> str:
        """对关键帧生成深度画面描述。

        Args:
            keyframe: (H, W, C) uint8。
            prompt: 由 prompt_loader 渲染好的完整提示词。
            max_new_tokens: 生成最大 token 数。

        Returns:
            中文描述字符串。
        """
        token_limit = max_new_tokens or self.default_max_tokens

        # ── numpy → base64 JPEG ──
        try:
            from PIL import Image as PILImage
            pil_image = PILImage.fromarray(keyframe)
            buffer = io.BytesIO()
            pil_image.save(buffer, format="JPEG", quality=85)
            base64_str = base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception as e:
            logger.exception("[QwenAPICaptioner] Image encoding failed")
            raise

        data_url = f"data:image/jpeg;base64,{base64_str}"

        # ── API 调用（裸 httpx，精确控制编码）──
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "max_tokens": token_limit,
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0)) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                )

                # 手动以 UTF-8 解码响应体，确保中文不乱码
                body = response.content.decode("utf-8")
                data = json.loads(body)

            content = data["choices"][0]["message"]["content"]
            if not content:
                logger.warning("[QwenAPICaptioner] Empty response")
                return ""
            # 调试：检查编码
            logger.debug(
                "[QwenAPICaptioner] content repr=%s first_50=%s",
                repr(content[:80]), content[:50],
            )
            return content.strip()

        except Exception as e:
            logger.exception("[QwenAPICaptioner] API call failed")
            raise
