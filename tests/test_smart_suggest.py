"""
tests/test_smart_suggest.py
═══════════════════════════════════════════════════════════
智能参数推荐纯逻辑单元测试（零 DB / 零 GPU / 零真实 ffmpeg）。

覆盖：
  - BUG：批量推荐帧向量错位回归 —— 中间视频某帧解码失败时，
    不得把下一个视频的向量算进当前视频（跨视频污染）。
  - 场景文本向量缓存：同模型只编码一次 + 模型配置变化时失效。
  - majority voting / 低置信度阈值跳过。

用 FakeEmbedder + monkeypatch ffmpeg 抽帧 / PIL 解码，不触碰真实模型。
"""

import io

import numpy as np
import pytest
from PIL import Image

import services.smart_suggest as ss


# ─────────────────────────────────────────────
# 测试替身
# ─────────────────────────────────────────────

class FakeEmbedder:
    """encode_images_batch 按图像 mean 颜色返回对应场景 unit 向量。

    text 侧直接返回由 _get_scene_text_vecs 的合并逻辑使用的向量；
    本测试主要走图像侧，text_vecs 通过 monkeypatch 注入固定值。
    """

    def __init__(self, img_to_vec):
        self.img_to_vec = img_to_vec
        self.encode_text_calls = 0

    async def encode_texts_batch(self, texts):
        return [np.array([0.5, 0.5], dtype=np.float32)] * len(texts)

    async def encode_text(self, text):
        self.encode_text_calls += 1
        return [0.5, 0.5]

    async def encode_images_batch(self, images):
        # 每帧一个 unit 向量，由 mean 颜色就近匹配（JPEG 压缩会有 ±1 偏差）
        vecs = []
        keys = list(self.img_to_vec.keys())
        for img in images:
            m = np.mean(img, axis=(0, 1))
            best = min(keys, key=lambda k: sum((m[i] - k[i]) ** 2 for i in range(3)))
            vecs.append(list(self.img_to_vec[best]))
        return vecs


def make_uniform_frame(rgb: tuple[int, int, int], marker: bytes = b"") -> bytes:
    """生成一张纯色 JPEG bytes（可附加标记，用于触发解码失败）。"""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), rgb).save(buf, "JPEG")
    return marker + buf.getvalue()


def patch_pil_open(monkeypatch, fail_marker: bytes):
    """让 PIL.Image.open 对含 fail_marker 的流抛错，其余走原逻辑。"""
    orig_open = Image.open

    def fake_open(fp, *a, **kw):
        data = fp.read(4)
        fp.seek(0)
        if data == fail_marker:
            raise ValueError("decode failed (test)")
        return orig_open(fp, *a, **kw)

    monkeypatch.setattr(Image, "open", fake_open)


# ─────────────────────────────────────────────
# 1. BUG 回归：批量帧向量错位
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_no_cross_video_contamination_when_frame_decode_fails(monkeypatch):
    """中间视频 B 的 3 帧全部解码失败。

    旧实现按「原始帧数」索引 all_vecs，会把 C 的向量算进 B（B 被误判为 indoor），
    并把 C 的向量偷光（C 反而报 no valid frames）。修复后：
      - A → document（红）
      - B → no valid frames（不应有 params）
      - C → indoor（蓝）
    """
    # 图像 mean 颜色 → 场景向量（unit 且正交）
    u_doc = np.array([1.0, 0.0], dtype=np.float32)
    u_ind = np.array([0.0, 1.0], dtype=np.float32)
    img_to_vec = {
        (255, 0, 0): u_doc,   # 红 → document
        (0, 0, 255): u_ind,   # 蓝 → indoor
    }
    embedder = FakeEmbedder(img_to_vec)

    # 注入固定场景文本向量
    async def _fake_text_vecs(embedder):
        return {"document": u_doc, "indoor": u_ind}
    monkeypatch.setattr(ss, "_get_scene_text_vecs", _fake_text_vecs)

    # B 帧带 FAIL 标记，解码必失败
    fail = b"FAIL"
    patch_pil_open(monkeypatch, fail)

    def fake_extract(video_path, duration):
        if "B" in str(video_path):
            return [make_uniform_frame((0, 0, 255), marker=fail) for _ in range(3)]
        if "A" in str(video_path):
            return [make_uniform_frame((255, 0, 0)) for _ in range(3)]
        return [make_uniform_frame((0, 0, 255)) for _ in range(3)]

    monkeypatch.setattr(ss, "_extract_frames", fake_extract)

    videos = [
        {"video_id": "A", "video_path": "A.mp4", "duration": 10.0},
        {"video_id": "B", "video_path": "B.mp4", "duration": 10.0},
        {"video_id": "C", "video_path": "C.mp4", "duration": 10.0},
    ]
    results = await ss.suggest_params_batch(embedder, videos)
    by_id = {r["video_id"]: r for r in results}

    assert len(results) == 3

    a = by_id["A"]
    assert a["scene_key"] == "document"
    assert a["params"] is not None

    b = by_id["B"]
    assert b["scene_key"] is None
    assert b["reason"] == "no valid frames"
    assert b["params"] is not None  # 兜底参数仍在（低置信默认）

    c = by_id["C"]
    assert c["scene_key"] == "indoor"
    assert c["params"] is not None


@pytest.mark.asyncio
async def test_batch_normal_all_frames_decode_ok(monkeypatch):
    """全帧解码正常时，各视频归属互不串扰（基础回归）。"""
    u_doc = np.array([1.0, 0.0], dtype=np.float32)
    u_ind = np.array([0.0, 1.0], dtype=np.float32)
    embedder = FakeEmbedder({
        (255, 0, 0): u_doc,
        (0, 0, 255): u_ind,
    })
    async def _fake_text_vecs(embedder):
        return {"document": u_doc, "indoor": u_ind}
    monkeypatch.setattr(ss, "_get_scene_text_vecs", _fake_text_vecs)

    def fake_extract(video_path, duration):
        if "A" in str(video_path):
            return [make_uniform_frame((255, 0, 0)) for _ in range(3)]
        return [make_uniform_frame((0, 0, 255)) for _ in range(3)]

    monkeypatch.setattr(ss, "_extract_frames", fake_extract)

    videos = [
        {"video_id": "A", "video_path": "A.mp4", "duration": 10.0},
        {"video_id": "B", "video_path": "B.mp4", "duration": 10.0},
    ]
    results = await ss.suggest_params_batch(embedder, videos)
    by_id = {r["video_id"]: r for r in results}
    assert by_id["A"]["scene_key"] == "document"
    assert by_id["B"]["scene_key"] == "indoor"


# ─────────────────────────────────────────────
# 2. 场景文本向量缓存
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scene_text_cache_reuses_and_invalidates(monkeypatch):
    """同模型只批量编码一次；模型配置变化时缓存失效重算。"""
    ss._invalidate_scene_cache()

    class CountingEmbedder(FakeEmbedder):
        def __init__(self, img_to_vec):
            super().__init__(img_to_vec)
            self.batch_calls = 0

        async def encode_texts_batch(self, texts):
            self.batch_calls += 1
            return [np.array([1.0, 0.0], dtype=np.float32)] * len(texts)

    e = CountingEmbedder({})
    # 提供稳定的模型身份
    e.processor = type("P", (), {"name_or_path": "model-a"})()
    e.encode_size = (336, 224)
    e._quantization = "none"

    v1 = await ss._get_scene_text_vecs(e)
    assert v1
    assert e.batch_calls == 1

    # 同模型再次调用 → 命中缓存，不再编码
    v2 = await ss._get_scene_text_vecs(e)
    assert e.batch_calls == 1
    assert v1 is v2

    # 模型配置变化（encode_size 不同）→ 缓存键变化 → 重新编码
    e2 = CountingEmbedder({})
    e2.processor = type("P", (), {"name_or_path": "model-a"})()
    e2.encode_size = (224, 224)
    e2._quantization = "none"
    v3 = await ss._get_scene_text_vecs(e2)
    assert e2.batch_calls == 1
    assert v3 is not v1

    ss._invalidate_scene_cache()


# ─────────────────────────────────────────────
# 3. 低置信度阈值 / 空输入
# ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_suggest_params_batch_embedder_none():
    results = await ss.suggest_params_batch(None, [{"video_id": "X"}])
    assert results[0]["reason"] == "embedder unavailable"
    assert results[0]["scene_key"] is None
    assert results[0]["params"] is not None  # 兜底参数，保证有产出


@pytest.mark.asyncio
async def test_suggest_params_batch_low_confidence_skips(monkeypatch):
    """置信度低于阈值时不推荐场景，但仍给保守兜底参数（params 非 None）。"""
    u = np.array([1.0, 0.0], dtype=np.float32)
    async def _fake_text_vecs(embedder):
        return {"traffic": u}
    monkeypatch.setattr(ss, "_get_scene_text_vecs", _fake_text_vecs)
    # 让 embedder 返回与场景向量仅 0.2 的相似度 → 低置信
    weak = np.array([0.2, 0.98], dtype=np.float32)
    embedder = FakeEmbedder({(100, 100, 100): weak})

    def fake_extract(video_path, duration):
        return [make_uniform_frame((100, 100, 100)) for _ in range(3)]

    monkeypatch.setattr(ss, "_extract_frames", fake_extract)

    results = await ss.suggest_params_batch(
        embedder, [{"video_id": "X", "video_path": "X.mp4", "duration": 10.0}],
    )
    assert results[0]["scene_key"] is None
    assert results[0]["reason"] == "low confidence"
    assert results[0]["params"] is not None
    assert results[0]["params"]["detection_enabled"] is True
    assert results[0]["params"]["ocr_enabled"] is False


@pytest.mark.asyncio
async def test_suggest_params_batch_no_frames(monkeypatch):
    """全部视频抽不到帧 → 返回 all frame extract failed，但仍给兜底参数。"""
    embedder = FakeEmbedder({})
    async def _fake_text_vecs(embedder):
        return {"traffic": np.array([1.0, 0.0])}
    monkeypatch.setattr(ss, "_get_scene_text_vecs", _fake_text_vecs)
    monkeypatch.setattr(ss, "_extract_frames", lambda video_path, duration: [])
    results = await ss.suggest_params_batch(embedder, [{"video_id": "X", "video_path": "X.mp4"}])
    assert results[0]["reason"] == "all frame extract failed"
    assert results[0]["params"] is not None