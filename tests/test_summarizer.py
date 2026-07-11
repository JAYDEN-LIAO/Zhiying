"""
plugins/summarizer/vllm_summarizer.py 单元测试
═════════════════════════════════════════════════════════════════
Mock AsyncOpenAI 客户端，验证摘要返回结构、键名、fallback JSON 解析。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.summarizer.vllm_summarizer import VLLMSummarizer
from core.exceptions import PipelineError


# ── 模拟 vLLM 助手 ───────────────────────────────────────────

def _mock_chat_completion(content: str):
    """构造模拟的 ChatCompletion 响应体。"""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


# ── 测试剧本 ──
SAMPLE_SCRIPT = """
[00:00-00:10] 开场画面，展示产品外观
[00:10-00:30] 主持人介绍产品功能
[00:30-01:00] 演示核心特性
"""

SAMPLE_SYSTEM_PROMPT = "你是分析助手。"
SAMPLE_USER_PROMPT = "请分析以下内容：{script}"

VALID_JSON = json.dumps({
    "one_liner": "这是一款创新产品的演示视频",
    "scenes_summary": [
        {
            "scene_index": 0,
            "start_sec": 0.0,
            "end_sec": 10.0,
            "description": "开场展示产品外观",
            "keywords": ["产品", "外观"],
        },
    ],
    "tags": ["科技", "产品"],
    "main_topics": ["产品功能"],
    "main_entities": ["产品X"],
})


class TestVLLMSummarizer:
    """VLLMSummarizer Mock 测试。"""

    @pytest.fixture
    def mock_openai(self):
        """替换 AsyncOpenAI 的 chat.completions.create 为 AsyncMock。"""
        with patch(
            "plugins.summarizer.vllm_summarizer.AsyncOpenAI"
        ) as mock_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock()
            mock_cls.return_value = mock_client
            yield mock_client

    async def test_summarize_returns_all_keys(self, mock_openai):
        """返回 dict 应包含全部 5 个必需键。"""
        mock_openai.chat.completions.create.return_value = _mock_chat_completion(VALID_JSON)

        summarizer = VLLMSummarizer()
        result = await summarizer.summarize(SAMPLE_SCRIPT, SAMPLE_SYSTEM_PROMPT, SAMPLE_USER_PROMPT)

        assert isinstance(result, dict)
        assert "one_liner" in result
        assert "scenes_summary" in result
        assert "tags" in result
        assert "main_topics" in result
        assert "main_entities" in result

    async def test_one_liner_nonempty(self, mock_openai):
        """one_liner 应为非空字符串。"""
        mock_openai.chat.completions.create.return_value = _mock_chat_completion(VALID_JSON)

        summarizer = VLLMSummarizer()
        result = await summarizer.summarize(SAMPLE_SCRIPT, SAMPLE_SYSTEM_PROMPT, SAMPLE_USER_PROMPT)

        assert isinstance(result["one_liner"], str)
        assert len(result["one_liner"].strip()) > 0

    async def test_scenes_summary_is_list(self, mock_openai):
        """scenes_summary 应为列表（允许为空）。"""
        empty_json = json.dumps({"one_liner": "x", "scenes_summary": [], "tags": [], "main_topics": [], "main_entities": []})
        mock_openai.chat.completions.create.return_value = _mock_chat_completion(empty_json)

        summarizer = VLLMSummarizer()
        result = await summarizer.summarize(SAMPLE_SCRIPT, SAMPLE_SYSTEM_PROMPT, SAMPLE_USER_PROMPT)

        assert isinstance(result["scenes_summary"], list)

    # ── Fallback 解析 ──

    async def test_code_fence_parsing(self, mock_openai):
        """```json 包裹的内容应被正确解析。"""
        fenced = f"```json\n{VALID_JSON}\n```"
        mock_openai.chat.completions.create.return_value = _mock_chat_completion(fenced)

        summarizer = VLLMSummarizer()
        result = await summarizer.summarize(SAMPLE_SCRIPT, SAMPLE_SYSTEM_PROMPT, SAMPLE_USER_PROMPT)

        assert result["one_liner"] == "这是一款创新产品的演示视频"
        assert len(result["scenes_summary"]) == 1

    async def test_plain_code_fence_parsing(self, mock_openai):
        """不含 json 标记的 ``` 包裹也应被解析。"""
        fenced = f"```\n{VALID_JSON}\n```"
        mock_openai.chat.completions.create.return_value = _mock_chat_completion(fenced)

        summarizer = VLLMSummarizer()
        result = await summarizer.summarize(SAMPLE_SCRIPT, SAMPLE_SYSTEM_PROMPT, SAMPLE_USER_PROMPT)

        assert result["one_liner"] == "这是一款创新产品的演示视频"

    # ── 错误处理 ──

    async def test_invalid_json_raises_error(self, mock_openai):
        """非 JSON 响应应抛出 PipelineError。"""
        mock_openai.chat.completions.create.return_value = _mock_chat_completion(
            "这不是有效的 JSON"
        )

        summarizer = VLLMSummarizer()
        with pytest.raises(PipelineError, match="Failed to parse"):
            await summarizer.summarize(SAMPLE_SCRIPT, SAMPLE_SYSTEM_PROMPT, SAMPLE_USER_PROMPT)
