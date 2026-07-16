"""
pipeline/phase4_caption.py
═══════════════════════════════════════════════════════════
Phase 4: 场景描述 — 双路径路由。

native_video (default):
  Qwen2.5-VL 本地模型直接观看视频片段 → 结构化 JSON
  {description, keywords, objects, actions, scene_type, lighting}
  scene.caption ← description（搜索用）
  scene.structured_caption ← 完整 JSON（Phase 5 聚合用）

vlm_llm (legacy):
  Qwen API 看图说话（3-7 帧代表帧）→ 自然语言描述
  scene.caption ← 纯文本描述
  Phase 5 调用 LLM summarizer 拼凑摘要
"""

import json as json_mod
import logging
import re

from core.interfaces import VideoContext
from core.status_tracker import StatusTracker
from core.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


def _parse_caption_json(raw: str) -> dict | None:
    """从模型输出中提取结构化 JSON。支持直接 JSON / ```json``` 包裹。"""
    if not raw or not raw.strip():
        return None
    for pattern in [
        None,
        r'```json\s*([\s\S]*?)\s*```',
        r'```\s*(\{[\s\S]*?\})\s*```',
    ]:
        candidate = raw
        if pattern is not None:
            match = re.search(pattern, raw)
            if not match:
                continue
            candidate = match.group(1)
        try:
            result = json_mod.loads(candidate)
            if isinstance(result, dict) and "description" in result:
                return result
        except (json_mod.JSONDecodeError, TypeError):
            continue
    return None


class Phase4Caption:
    """Phase 4 执行器 — 双路径场景描述。"""

    def __init__(
        self,
        ctx: VideoContext,
        plugins: dict,
        config: dict,
        tracker: StatusTracker,
        prompt_loader: PromptLoader,
        summary_mode: str = "native_video",
    ):
        self.ctx = ctx
        self.plugins = plugins
        self.config = config
        self.tracker = tracker
        self.pl = prompt_loader
        self.summary_mode = summary_mode

    async def execute(self) -> None:
        captioner = self.plugins.get("captioner")
        scenes = self.ctx.scenes if hasattr(self.ctx, "scenes") else []

        if captioner is None or not scenes:
            logger.info("[Phase4] Captioner disabled or no scenes, skipping")
            return

        cfg = self.config.get("plugins", {}).get("captioner", {})
        with_context = cfg.get("with_context", False)
        max_tokens = cfg.get("max_new_tokens", 512)

        if self.summary_mode == "vlm_llm":
            await self._run_vlm_llm(captioner, scenes, with_context, max_tokens)
        else:
            await self._run_native_video(captioner, scenes, with_context, max_tokens)

        captioned = sum(1 for s in scenes if s.caption)
        logger.info("[Phase4] Captioned %d/%d scenes", captioned, len(scenes))

    # ──────────────────────────────────────────────────────
    # native_video 路径
    # ──────────────────────────────────────────────────────

    async def _run_native_video(self, captioner, scenes, with_context, max_tokens):
        """本地 Qwen2.5-VL：串行，模型直接观看视频片段 → 结构化 JSON。"""
        await self.tracker.update("phase_4_caption")
        total = len(scenes)

        for i, scene in enumerate(scenes):
            captioner.video_path = self.ctx.file_path
            captioner.scene_start = scene.start_sec
            captioner.scene_end = scene.end_sec

            prompt = self._build_prompt(i, scenes, with_context)

            raw = await captioner.caption([], prompt, max_new_tokens=max_tokens)
            parsed = _parse_caption_json(raw)

            if parsed is not None:
                scene.structured_caption = parsed
                scene.caption = parsed.get("description", raw)
            else:
                scene.caption = raw
                scene.structured_caption = None

            if i > 0:
                scene.prev_caption = scenes[i - 1].caption

            await self.tracker.update(
                "phase_4_caption",
                progress=0.50 + 0.25 * ((i + 1) / total),
                description=f"正在描述第 {i + 1}/{total} 个场景",
            )

    # ──────────────────────────────────────────────────────
    # vlm_llm 路径
    # ──────────────────────────────────────────────────────

    async def _run_vlm_llm(self, captioner, scenes, with_context, max_tokens):
        """传统 VLM 看图说话：逐场景抽帧 → API → 自然语言描述。"""
        await self.tracker.update("phase_4_caption")
        total = len(scenes)

        for i, scene in enumerate(scenes):
            frames = getattr(scene, "_caption_frames", None) or scene.keyframes
            if not frames:
                continue

            if with_context and i > 0 and scenes[i - 1].caption:
                prompt = self.pl.get(
                    "caption_vlm_with_context",
                    prev_caption=scenes[i - 1].caption or "无",
                )
            else:
                prompt = self.pl.get("caption_vlm")

            scene.caption = await captioner.caption(
                frames, prompt, max_new_tokens=max_tokens,
            )
            scene.structured_caption = None

            if i > 0:
                scene.prev_caption = scenes[i - 1].caption

            await self.tracker.update(
                "phase_4_caption",
                progress=0.50 + 0.25 * ((i + 1) / total),
                description=f"正在描述第 {i + 1}/{total} 个场景",
            )

    # ──────────────────────────────────────────────────────
    # 辅助
    # ──────────────────────────────────────────────────────

    def _build_prompt(self, i: int, scenes, with_context: bool) -> str:
        if with_context and i > 0:
            prev = scenes[i - 1]
            prev_desc = (
                (prev.structured_caption or {}).get("description")
                or prev.caption
            )
            if prev_desc:
                return self.pl.get("caption_with_context", prev_caption=prev_desc)
        return self.pl.get("caption_default")
