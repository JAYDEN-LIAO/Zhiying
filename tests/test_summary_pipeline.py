"""
tests/test_summary_pipeline.py
═══════════════════════════════════════════════════════════
摘要链路纯逻辑单元测试（零 DB / 零 GPU）— 覆盖 v0.33 重构：
  - effective_summary_mode 映射（BUG-1 修复）
  - caption 单场景失败降级 + 并发 + with_context 顺序（CONFIG-1/C1/C2 修复）
  - _caption_config 从 params 子层读（CONFIG-1 配置穿透修复）
  - summary _build_script 输入预算截断（C7 修复）
  - text_encode 批量编码（C3 修复）
  - resolve_encode_profile 兜底统一（C6 修复）

runner 只写 ctx 内存对象，不碰 DB → 无需 SQLite/pgvector。
"""

import numpy as np
import pytest
from types import SimpleNamespace

from core.interfaces import VideoContext, Scene
from core.prompt_loader import PromptLoader
from pipeline.runners.base import effective_summary_mode, resolve_encode_profile
from pipeline.runners.caption import CaptionRunner
from pipeline.runners.summary import SummaryRunner
from pipeline.runners.text_encode import TextEncodeRunner


# ──────────────────────────────────────────────────────────
# 测试替身
# ──────────────────────────────────────────────────────────

class FakeTracker:
    """记录 update 调用的假 tracker（async update 签名对齐 StatusTracker）。"""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def update(self, phase: str, **kwargs):
        self.calls.append((phase, kwargs))


class FakeCaptioner:
    """假 captioner：记录调用，可指定某些调用抛异常（fail_from=自该调用序号起持续失败）。"""

    def __init__(self, fail_from: int | None = None, fail_calls: set[int] | None = None):
        self.calls: list[tuple[list, str, int]] = []  # (frames, prompt, max_new_tokens)
        self.fail_from = fail_from
        self.fail_calls = fail_calls or set()

    async def caption(self, frames, prompt, max_new_tokens=256):
        idx = len(self.calls)
        self.calls.append((frames, prompt, max_new_tokens))
        if idx in self.fail_calls or (self.fail_from is not None and idx >= self.fail_from):
            raise RuntimeError(f"api error on call {idx}")
        return f"描述-{idx}"


class FakeEmbedder:
    """假 embedder：记录批量/单条文本编码调用次数。"""

    def __init__(self):
        self.batch_calls = 0
        self.single_calls = 0

    async def encode_texts_batch(self, texts):
        self.batch_calls += 1
        return [[0.1] * 4 for _ in texts]

    async def encode_text(self, text):
        self.single_calls += 1
        return [0.1] * 4


# ──────────────────────────────────────────────────────────
# 构造辅助
# ──────────────────────────────────────────────────────────

def default_config() -> dict:
    return {
        "pipeline": {
            "default_encode_profile": "balanced",
            "encode_profiles": {
                "balanced": {"encode_width": 504, "encode_height": 336, "encode_batch_size": 512},
                "fast": {"encode_width": 336, "encode_height": 224, "encode_batch_size": 512},
            },
        },
        "plugins": {
            "captioner": {"params": {"max_new_tokens": 512, "with_context": False, "concurrency": 4}},
            "summarizer": {"max_input_chars": 12000},
        },
    }


def make_scene(index: int, caption: str = "", ocr: str = "", transcript: str = "",
               frames: list | None = None) -> Scene:
    s = Scene(scene_id=index, scene_index=index, start_sec=index * 10.0, end_sec=index * 10.0 + 9.0)
    if frames is not None:
        s.keyframes = frames
    if caption:
        s.caption = caption
    if ocr:
        s.ocr_text = ocr
    if transcript:
        s.aligned_transcript = transcript
    return s


def make_pctx(scenes: list[Scene], captioner=None, embedder=None, config: dict | None = None):
    return SimpleNamespace(
        video=SimpleNamespace(summary_enabled=True, summary_mode="vlm_llm", encode_profile=None),
        ctx=VideoContext(video_id="x", file_path="x.mp4", scenes=scenes),
        config=config if config is not None else default_config(),
        plugins={"captioner": captioner} if captioner else {},
        tracker=FakeTracker(),
        prompt_loader=PromptLoader(),
        shared_embedder=embedder,
        embedder_lock=None,
        frame_queue=None,
        db_session_factory=None,
    )


def fake_frame() -> list[np.ndarray]:
    return [np.zeros((10, 10, 3), dtype=np.uint8)]


# ──────────────────────────────────────────────────────────
# 1. effective_summary_mode（BUG-1 映射修复）
# ──────────────────────────────────────────────────────────

def test_effective_summary_mode_native_with_qwen_api_maps_to_vlm_llm():
    video = SimpleNamespace(summary_mode="native_video")
    assert effective_summary_mode(video, {"plugins": {"captioner": {"backend": "qwen_api"}}}) == "vlm_llm"
    assert effective_summary_mode(video, {"plugins": {"captioner": {"backend": "qwen3_vl"}}}) == "native_video"
    assert effective_summary_mode(SimpleNamespace(summary_mode="vlm_llm"), {}) == "vlm_llm"


# ──────────────────────────────────────────────────────────
# 2. caption 单场景失败降级（C2）
# ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_caption_single_scene_failure_isolated():
    scenes = [make_scene(i, frames=fake_frame()) for i in range(3)]
    # 顺序执行（concurrency=1）保证调用序号与场景对应；场景 1 起持续失败（含重试）
    captioner = FakeCaptioner(fail_from=1)
    pctx = make_pctx(scenes, captioner=captioner)

    await CaptionRunner()._run_vlm_llm(pctx, captioner, scenes, False, 512, 1)

    # 持续失败的场景降级为 None，不抛；首个场景正常
    assert scenes[0].caption == "描述-0"
    assert scenes[1].caption is None
    assert scenes[2].caption is None
    # prev_caption 回填（即使中间场景失败也按前序 caption）
    assert scenes[1].prev_caption == "描述-0"
    assert scenes[2].prev_caption is None


# ──────────────────────────────────────────────────────────
# 3. caption 并发（C1）
# ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_caption_concurrent_all_captioned():
    scenes = [make_scene(i, frames=fake_frame()) for i in range(6)]
    captioner = FakeCaptioner()
    pctx = make_pctx(scenes, captioner=captioner)

    await CaptionRunner()._run_vlm_llm(pctx, captioner, scenes, False, 512, 4)

    assert all(s.caption for s in scenes)
    # 进度收敛到 1.0
    assert pctx.tracker.calls[-1][1]["sub_progress"] == 1.0


# ──────────────────────────────────────────────────────────
# 4. caption with_context 顺序 + 上下文注入（CONFIG-1 运行时）
# ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_caption_with_context_sequential_and_injects_prev():
    scenes = [make_scene(i, frames=fake_frame()) for i in range(3)]
    captioner = FakeCaptioner()
    pctx = make_pctx(scenes, captioner=captioner)

    await CaptionRunner()._run_vlm_llm(pctx, captioner, scenes, True, 512, 1)

    # 顺序执行：调用 0 无上下文，调用 1/2 的 prompt 注入上一场景描述
    assert "描述-0" in captioner.calls[1][1]
    assert "描述-1" in captioner.calls[2][1]


# ──────────────────────────────────────────────────────────
# 5. _caption_config 从 params 子层读（CONFIG-1 配置穿透修复）
# ──────────────────────────────────────────────────────────

def test_caption_config_reads_params_layer():
    pctx = SimpleNamespace(config={
        "plugins": {"captioner": {"params": {"max_new_tokens": 2048, "with_context": True, "concurrency": 9}}},
    })
    with_context, max_tokens, concurrency = CaptionRunner._caption_config(pctx)
    assert (with_context, max_tokens, concurrency) == (True, 2048, 1)  # with_context → 并发强制 1

    empty = SimpleNamespace(config={"plugins": {"captioner": {"params": {}}}})
    wc, mt, cc = CaptionRunner._caption_config(empty)
    assert (wc, mt, cc) == (False, 512, 4)  # 默认：关 + 512 + 4 并发


# ──────────────────────────────────────────────────────────
# 6. summary _build_script 输入预算（C7）
# ──────────────────────────────────────────────────────────

def test_summary_build_script_under_budget_unchanged():
    scenes = [make_scene(0, caption="画面描述A", ocr="文字B", transcript="台词C")]
    script, count = SummaryRunner._build_script(scenes, 10000)
    assert script == "[0.0-9.0] 画面:画面描述A 文字:文字B 台词:台词C"
    assert count == 1


def test_summary_build_script_truncates_transcript_first():
    scenes = [make_scene(0, caption="C" * 50, transcript="T" * 500)]
    budget = 100
    script, count = SummaryRunner._build_script(scenes, budget)
    assert len(script) <= budget
    # 画面描述保留完整，台词被截断（截断优先序：台词 → 文字 → 画面）
    assert "C" * 50 in script
    assert count == 1


def test_summary_build_script_count_ignores_newlines_in_caption():
    # caption 内换行不得计入场景数（回归：曾用 script.count("\\n") 虚高）
    scenes = [make_scene(0, caption="第一段。\n第二段。\n第三段。"),
              make_scene(1, caption="另一段描述")]
    script, count = SummaryRunner._build_script(scenes, 10000)
    assert count == 2


# ──────────────────────────────────────────────────────────
# 7. text_encode 批量（C3）
# ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_text_encode_uses_batch_method():
    scenes = [make_scene(0, caption="cap0"), make_scene(1, caption="cap1"), make_scene(2)]
    embedder = FakeEmbedder()
    pctx = make_pctx(scenes, embedder=embedder)

    await TextEncodeRunner().run(pctx)

    assert embedder.batch_calls == 1
    assert embedder.single_calls == 0
    assert scenes[0].text_embedding == [0.1] * 4
    assert scenes[1].text_embedding == [0.1] * 4
    assert scenes[2].text_embedding is None  # 无文本 → 不编码


@pytest.mark.asyncio
async def test_text_encode_falls_back_to_single_when_no_batch():
    class OldEmbedder:
        def __init__(self):
            self.single_calls = 0

        async def encode_text(self, text):
            self.single_calls += 1
            return [0.1] * 4

    scenes = [make_scene(0, caption="cap0"), make_scene(1, caption="cap1")]
    embedder = OldEmbedder()
    pctx = make_pctx(scenes, embedder=embedder)

    await TextEncodeRunner().run(pctx)

    assert embedder.single_calls == 2
    assert scenes[0].text_embedding == [0.1] * 4


# ──────────────────────────────────────────────────────────
# 8. resolve_encode_profile 兜底统一（C6）
# ──────────────────────────────────────────────────────────

def test_resolve_encode_profile_fallback_unified():
    video = SimpleNamespace(encode_profile=None)
    p = resolve_encode_profile({}, video)  # 空 config → 兜底 balanced
    assert (p.encode_width, p.encode_height, p.encode_batch_size) == (504, 336, 512)


def test_resolve_encode_profile_uses_video_and_config():
    config = {
        "pipeline": {
            "encode_profiles": {"fast": {"encode_width": 336, "encode_height": 224, "encode_batch_size": 512}},
        },
    }
    video = SimpleNamespace(encode_profile="fast")
    p = resolve_encode_profile(config, video)
    assert p.target_size == (336, 224)
    assert p.encode_batch_size == 512


# ──────────────────────────────────────────────────────────
# 9. segmentation 目标场景数上限（max_scenes）
# ──────────────────────────────────────────────────────────

from pipeline.runners.segmentation import SegmentRunner


def test_max_scenes_default_and_from_config():
    assert SegmentRunner._max_scenes({}) == 6
    assert SegmentRunner._max_scenes({"pipeline": {"max_scenes": 3}}) == 3


@pytest.mark.asyncio
async def test_fixed_count_segmentation_six_scenes():
    scenes = await SegmentRunner._fixed_count_segmentation(3600, 6)
    assert len(scenes) == 6
    assert scenes[0].start_sec == 0.0
    assert scenes[1].start_sec == 600.0
    assert scenes[-1].end_sec == 3600.0


def test_merge_to_max_caps_scene_count_and_keeps_coverage():
    # 构造 25 个 TransNetV2 场景，总时长 600s（每段 24s）
    scenes = [Scene(scene_id=i, scene_index=i, start_sec=i * 24.0, end_sec=(i + 1) * 24.0)
              for i in range(25)]
    merged = SegmentRunner._merge_to_max(scenes, 600, 6)
    assert 1 < len(merged) <= 6
    # 合并后仍完整覆盖全视频
    assert merged[0].start_sec == 0.0
    assert merged[-1].end_sec == 600.0
    # 场景连续无重叠
    for prev, cur in zip(merged, merged[1:]):
        assert prev.end_sec == cur.start_sec


def test_merge_to_max_leaves_short_list_untouched():
    scenes = [Scene(scene_id=i, scene_index=i, start_sec=i * 10.0, end_sec=(i + 1) * 10.0)
              for i in range(3)]
    merged = SegmentRunner._merge_to_max(scenes, 30, 6)
    assert len(merged) == 3
    assert merged[0].start_sec == 0.0
    assert merged[-1].end_sec == 30.0
