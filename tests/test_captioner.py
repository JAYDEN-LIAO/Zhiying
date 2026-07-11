"""
plugins/captioner/qwen_vl_captioner.py 单元测试
═════════════════════════════════════════════════════════════════
Mock 底层 transformers 模型，验证 caption() 输出格式、一致性与 max_new_tokens 传参。
"""
import numpy as np
import torch
from unittest.mock import MagicMock, patch

import pytest

from plugins.captioner.qwen_vl_captioner import QwenVLCaptioner


@pytest.fixture
def test_image():
    return np.full((100, 200, 3), 128, dtype=np.uint8)


class TestQwenVLCaptioner:

    @staticmethod
    def _setup_mocks(mock_model_fp, mock_proc_fp, decode_output="默认描述文本"):
        mock_model = MagicMock()
        mock_processor = MagicMock()
        mock_model_fp.return_value = mock_model
        mock_proc_fp.return_value = mock_processor

        # 链式 .to() 返回自身
        mock_model.to.return_value = mock_model
        mock_processor.to.return_value = mock_processor

        # processor(...).to(device) → 返回真实 dict，支持 **input 解包
        mock_processor.return_value.to.return_value = {
            "input_ids": torch.tensor([[1, 2, 3]]),
        }

        mock_model.generate.return_value = torch.tensor([[101, 102, 103]])
        mock_processor.batch_decode.return_value = [decode_output]
        return mock_model, mock_processor

    @patch("transformers.Qwen2_5_VLForConditionalGeneration.from_pretrained")
    @patch("transformers.AutoProcessor.from_pretrained")
    async def test_caption_returns_nonempty_string(
        self, mock_proc_fp, mock_model_fp, test_image,
    ):
        self._setup_mocks(mock_model_fp, mock_proc_fp,
                          decode_output="画面中是一张纯色测试图片。")
        captioner = QwenVLCaptioner(model_name="mock", device="cpu")
        result = await captioner.caption(test_image, "请描述这张图片。")
        assert isinstance(result, str) and len(result) > 0

    @patch("transformers.Qwen2_5_VLForConditionalGeneration.from_pretrained")
    @patch("transformers.AutoProcessor.from_pretrained")
    async def test_caption_consistency(self, mock_proc_fp, mock_model_fp, test_image):
        fixed = "确定性输出文本用于编辑距离验证"
        self._setup_mocks(mock_model_fp, mock_proc_fp, decode_output=fixed)
        captioner = QwenVLCaptioner(model_name="mock", device="cpu")
        r1 = await captioner.caption(test_image, "请描述这张图片。")
        r2 = await captioner.caption(test_image, "请描述这张图片。")
        assert r1 == r2
        edit_dist = sum(a != b for a, b in zip(r1, r2)) + abs(len(r1) - len(r2))
        assert edit_dist / max(len(r1), len(r2), 1) < 0.5

    @patch("transformers.Qwen2_5_VLForConditionalGeneration.from_pretrained")
    @patch("transformers.AutoProcessor.from_pretrained")
    async def test_max_new_tokens_respected(self, mock_proc_fp, mock_model_fp, test_image):
        mock_model, _ = self._setup_mocks(mock_model_fp, mock_proc_fp)
        captioner = QwenVLCaptioner(model_name="mock", device="cpu")
        await captioner.caption(test_image, "描述", max_new_tokens=50)

        args, kwargs = mock_model.generate.call_args
        assert kwargs.get("max_new_tokens") == 50, (
            f"generate 应收到 max_new_tokens=50，实际 {kwargs}"
        )

    @patch("transformers.Qwen2_5_VLForConditionalGeneration.from_pretrained")
    @patch("transformers.AutoProcessor.from_pretrained")
    async def test_grayscale_image_handled(self, mock_proc_fp, mock_model_fp):
        self._setup_mocks(mock_model_fp, mock_proc_fp)
        gray = np.full((50, 80), 200, dtype=np.uint8)
        captioner = QwenVLCaptioner(model_name="mock", device="cpu")
        result = await captioner.caption(gray, "描述")
        assert isinstance(result, str)
