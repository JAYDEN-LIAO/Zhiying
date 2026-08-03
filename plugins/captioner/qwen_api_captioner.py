"""
plugins/captioner/qwen_api_captioner.py
═══════════════════════════════════════════════════════════
Qwen API 画面描述插件 — 通过 DashScope OpenAI 兼容接口调用 qwen-vl-max。

支持多帧时序输入：传入一组关键帧序列，VLM 同时看到画面变化过程。
"""

import base64
import io
import json
import logging
import os

import httpx
import numpy as np

from core.interfaces import BaseCaptioner

logger = logging.getLogger(__name__)


class QwenAPICaptioner(BaseCaptioner):
    """基于 DashScope qwen-vl-max API 的画面描述实现。

    支持传入单帧或多帧关键帧序列。多帧时 VLM 同时看到所有帧，
    能理解动作变化与过程描述。

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
        # 兜底：配置里的占位 key 无效时回退到环境变量（前端设置页注入）
        if not api_key or api_key == "placeholder":
            api_key = os.environ.get("DASHSCOPE_API_KEY", "")
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
        keyframes: list[np.ndarray],
        prompt: str,
        max_new_tokens: int = 256,
    ) -> str:
        """对一组关键帧生成深度画面描述。

        多帧时按时间顺序拼接，VLM 同时看到所有帧以理解动作变化。

        Args:
            keyframes: 关键帧序列，每帧 (H, W, C) uint8。单帧也传入 list。
            prompt: 由 prompt_loader 渲染好的完整提示词。
            max_new_tokens: 生成最大 token 数。

        Returns:
            中文描述字符串。
        """
        token_limit = max_new_tokens or self.default_max_tokens

        # ── numpy → base64 JPEG（逐帧编码）──
        image_urls: list[dict] = []
        try:
            from PIL import Image as PILImage
            for frame in keyframes:
                pil_image = PILImage.fromarray(frame)
                buffer = io.BytesIO()
                pil_image.save(buffer, format="JPEG", quality=85)
                base64_str = base64.b64encode(buffer.getvalue()).decode("ascii")
                image_urls.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"},
                })
        except Exception as e:
            logger.exception("[QwenAPICaptioner] Image encoding failed")
            raise

        # ── 构建 content 数组：文本在前，多图在后 ──
        content: list[dict] = [{"type": "text", "text": prompt}, *image_urls]

        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content}],
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

                body = response.content.decode("utf-8")
                data = json.loads(body)

            content = data["choices"][0]["message"]["content"]
            if not content:
                logger.warning("[QwenAPICaptioner] Empty response")
                return ""
            return content.strip()

        except Exception as e:
            logger.exception("[QwenAPICaptioner] API call failed")
            raise
