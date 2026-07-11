"""
plugins/embedder/qwen_vl_embedder.py 单元测试
═════════════════════════════════════════════════════════════════
Mock 底层 transformers 模型，验证向量维度、L2 归一化、一致性、图文维度一致。
"""
import numpy as np
import torch
from unittest.mock import MagicMock, patch

import pytest

from plugins.embedder.qwen_vl_embedder import QwenVLEmbedder


# ── 768 维单位向量（L2 范数 = 1.0） ──
_UNIT_768 = np.random.default_rng(42).normal(size=768).astype(np.float64)
_UNIT_768 /= np.linalg.norm(_UNIT_768)


def _make_hidden_state():
    """形状 (1, 64, 768) 的 last_hidden_state，mean pooling 后 ≈ 单位向量。"""
    data = np.tile(
        np.array(_UNIT_768, dtype=np.float32), (64, 1)
    ) + np.random.default_rng(0).normal(0, 0.01, (64, 768)).astype(np.float32)
    return torch.tensor(data, dtype=torch.float32).unsqueeze(0)


@pytest.fixture
def test_image():
    return np.full((100, 200, 3), 100, dtype=np.uint8)


class TestQwenVLEmbedder:

    @staticmethod
    def _setup_mocks(mock_model_fp, mock_proc_fp):
        mock_model = MagicMock()
        mock_processor = MagicMock()
        mock_model_fp.return_value = mock_model
        mock_proc_fp.return_value = mock_processor

        # 链式 .to() 返回自身
        mock_model.to.return_value = mock_model
        mock_processor.to.return_value = mock_processor

        # processor(...).to(device) → 真实 dict，支持 **input 解包
        mock_processor.return_value.to.return_value = {
            "input_ids": torch.tensor([[1]]),
            "attention_mask": torch.tensor([[1]]),
        }

        # model(**inputs) → outputs.last_hidden_state 为真实 tensor
        mock_outputs = MagicMock()
        mock_outputs.last_hidden_state = _make_hidden_state()
        mock_model.return_value = mock_outputs

        return mock_model, mock_processor

    @patch("transformers.AutoModel.from_pretrained")
    @patch("transformers.AutoProcessor.from_pretrained")
    async def test_encode_image_returns_768_dim(
        self, mock_proc_fp, mock_model_fp, test_image,
    ):
        self._setup_mocks(mock_model_fp, mock_proc_fp)
        embedder = QwenVLEmbedder(model_name="mock", device="cpu")
        vec = await embedder.encode_image(test_image)
        assert isinstance(vec, list)
        assert len(vec) == 768

    @patch("transformers.AutoModel.from_pretrained")
    @patch("transformers.AutoProcessor.from_pretrained")
    async def test_l2_norm_close_to_one(
        self, mock_proc_fp, mock_model_fp, test_image,
    ):
        self._setup_mocks(mock_model_fp, mock_proc_fp)
        embedder = QwenVLEmbedder(model_name="mock", device="cpu")
        vec = np.array(await embedder.encode_image(test_image))
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 0.01, f"L2 范数 {norm} 应 ≈ 1.0"

    @patch("transformers.AutoModel.from_pretrained")
    @patch("transformers.AutoProcessor.from_pretrained")
    async def test_encode_image_consistency(
        self, mock_proc_fp, mock_model_fp, test_image,
    ):
        self._setup_mocks(mock_model_fp, mock_proc_fp)
        embedder = QwenVLEmbedder(model_name="mock", device="cpu")
        v1 = np.array(await embedder.encode_image(test_image))
        v2 = np.array(await embedder.encode_image(test_image))
        cos_sim = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
        assert cos_sim > 0.99, f"余弦相似度 {cos_sim} 应 > 0.99"

    @patch("transformers.AutoModel.from_pretrained")
    @patch("transformers.AutoProcessor.from_pretrained")
    async def test_encode_text_returns_768_dim(self, mock_proc_fp, mock_model_fp):
        self._setup_mocks(mock_model_fp, mock_proc_fp)
        embedder = QwenVLEmbedder(model_name="mock", device="cpu")
        vec = await embedder.encode_text("一只猫")
        assert len(vec) == 768

    @patch("transformers.AutoModel.from_pretrained")
    @patch("transformers.AutoProcessor.from_pretrained")
    async def test_image_and_text_same_dimension(
        self, mock_proc_fp, mock_model_fp, test_image,
    ):
        self._setup_mocks(mock_model_fp, mock_proc_fp)
        embedder = QwenVLEmbedder(model_name="mock", device="cpu")
        img_vec = await embedder.encode_image(test_image)
        txt_vec = await embedder.encode_text("一只猫")
        assert len(img_vec) == len(txt_vec) == 768
