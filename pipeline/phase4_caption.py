"""
pipeline/phase4_caption.py
═══════════════════════════════════════════════════════════
Phase 4: 记忆窗口深度画面描述 + 向量编码。

执行逻辑:
  for each scene:
    1. 构建 prompt（含上下文/OCR/转录）
    2. VLM 推理 → scene.caption
    3. 传递 prev_caption
    4. Embedder 编码 → scene.embedding
"""

import logging

from core.interfaces import VideoContext
from core.status_tracker import StatusTracker
from core.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


class Phase4Caption:
    """Phase 4 执行器 — 深度理解 + 向量编码。"""

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
        """执行深度描述与向量编码。"""
        captioner = self.plugins.get("captioner")
        embedder = self.plugins.get("embedder")
        scenes = self.ctx.scenes
        total = len(scenes)

        if not scenes:
            logger.info("[Phase4] No scenes to caption, skipping")
            return

        plugin_cfg = self.config.get("plugins", {}).get("captioner", {})
        with_context = plugin_cfg.get("with_context", False)
        max_new_tokens = plugin_cfg.get("max_new_tokens", 256)

        # ── a. 深度描述 ──
        if captioner is not None:
            await self.tracker.update("phase_4_caption")

            for i, scene in enumerate(scenes):
                if scene.keyframe is None:
                    logger.debug("[Phase4] scene %d has no keyframe, skipping", i)
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
                    scene.keyframe, prompt,
                    max_new_tokens=max_new_tokens,
                )

                if i > 0:
                    scene.prev_caption = scenes[i - 1].caption

                await self.tracker.update(
                    "phase_4_caption",
                    progress=0.50 + 0.25 * ((i + 1) / total),
                )

            captioned = sum(1 for s in scenes if s.caption)
            logger.info("[Phase4] Captioned %d/%d scenes", captioned, total)

        # ── b. 向量编码 ──
        if embedder is not None:
            await self.tracker.update("phase_4_embed")

            for i, scene in enumerate(scenes):
                if scene.keyframe is None:
                    continue
                scene.embedding = await embedder.encode_image(scene.keyframe)
                await self.tracker.update(
                    "phase_4_embed",
                    progress=0.75 + 0.10 * ((i + 1) / total),
                )

            embedded = sum(1 for s in scenes if s.embedding)
            logger.info("[Phase4] Embedded %d/%d scenes", embedded, total)
