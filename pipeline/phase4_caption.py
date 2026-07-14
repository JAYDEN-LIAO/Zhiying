"""
pipeline/phase4_caption.py
═══════════════════════════════════════════════════════════
Phase 4: 多帧时序深度理解 + 多帧融合向量编码。

升级点：
  1. 每场景多帧序列 → VLM 多图输入 → 带时序变化的描述
  2. 多帧编码 → mean pooling 融合 → scene 级时序向量
"""

import logging

import numpy as np

from core.interfaces import VideoContext
from core.status_tracker import StatusTracker
from core.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


class Phase4Caption:
    """Phase 4 执行器 — 多帧时序理解 + 向量编码。"""

    def __init__(
        self,
        ctx: VideoContext,
        plugins: dict,
        config: dict,
        tracker: StatusTracker,
        prompt_loader: PromptLoader,
    ):
        self.ctx = ctx
        self.plugins = plugins
        self.config = config
        self.tracker = tracker
        self.pl = prompt_loader

    async def execute(self) -> None:
        """执行多帧深度描述与向量编码。"""
        captioner = self.plugins.get("captioner")
        embedder = self.plugins.get("embedder")
        scenes = self.ctx.scenes
        total = len(scenes)

        if not scenes:
            logger.info("[Phase4] No scenes to caption, skipping")
            return

        plugin_cfg = self.config.get("plugins", {}).get("captioner", {})
        with_context = plugin_cfg.get("with_context", False)
        max_new_tokens = plugin_cfg.get("max_new_tokens", 512)

        # ── a. 多帧深度描述 ──
        if captioner is not None:
            await self.tracker.update("phase_4_caption")

            for i, scene in enumerate(scenes):
                frames = getattr(scene, "_caption_frames", scene.keyframes)
                if not frames:
                    logger.debug("[Phase4] scene %d has no keyframes, skipping", i)
                    continue

                if with_context and i > 0 and scenes[i - 1].caption:
                    prompt = self.pl.get("caption_with_context",
                        prev_caption=scenes[i - 1].caption or "无",
                        ocr_text=scene.ocr_text or "无",
                        transcript=scene.aligned_transcript or "无",
                    )
                else:
                    prompt = self.pl.get("caption_default")

                scene.caption = await captioner.caption(
                    frames, prompt,
                    max_new_tokens=max_new_tokens,
                )

                if i > 0:
                    scene.prev_caption = scenes[i - 1].caption

                await self.tracker.update(
                    "phase_4_caption",
                    progress=0.50 + 0.25 * ((i + 1) / total),
                    description=f"正在描述第 {i + 1}/{total} 个场景",
                )

            captioned = sum(1 for s in scenes if s.caption)
            logger.info("[Phase4] Captioned %d/%d scenes (multi-frame)", captioned, total)

        # ── b. 场景向量编码 — 已废弃 ──
        # scene.embedding 不再作为搜索召回路，编码移至 _encode_frames。
