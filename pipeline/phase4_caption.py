"""
pipeline/phase4_caption.py
═══════════════════════════════════════════════════════════
Phase 4: 多帧时序深度理解 + 向量编码。

当 with_context=False 时，各场景的 caption API 调用
通过 asyncio.Semaphore 有界并发执行，大幅缩短总耗时。
"""

import asyncio
import logging

import numpy as np

from core.interfaces import VideoContext
from core.status_tracker import StatusTracker
from core.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)

# Caption 最大并发数（受限于 API QPS 限制）
_CAPTION_CONCURRENCY = 3


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

        if captioner is None:
            logger.info("[Phase4] Captioner disabled, skipping")
            return

        await self.tracker.update("phase_4_caption")
        sem = asyncio.Semaphore(_CAPTION_CONCURRENCY)
        completed = 0

        async def _caption_one(i: int, scene) -> None:
            """对单个场景执行描述，带并发控制。"""
            # 为原生视频理解 captioner 注入场景上下文（不影响 API captioner）
            if hasattr(captioner, "video_path"):
                captioner.video_path = self.ctx.file_path
                captioner.scene_start = scene.start_sec
                captioner.scene_end = scene.end_sec

            frames = getattr(scene, "_caption_frames", scene.keyframes)
            if not frames:
                return

            # 上下文模式：前一场景 caption 已就绪时才使用
            if with_context and i > 0 and scenes[i - 1].caption:
                prompt = self.pl.get("caption_with_context",
                    prev_caption=scenes[i - 1].caption or "无",
                    ocr_text=scene.ocr_text or "无",
                    transcript=scene.aligned_transcript or "无",
                )
            else:
                prompt = self.pl.get("caption_default")

            async with sem:
                scene.caption = await captioner.caption(
                    frames, prompt,
                    max_new_tokens=max_new_tokens,
                )

            if i > 0:
                scene.prev_caption = scenes[i - 1].caption

            completed += 1
            await self.tracker.update(
                "phase_4_caption",
                progress=0.50 + 0.25 * (completed / total),
                description=f"正在描述第 {completed}/{total} 个场景",
            )

        # 有上下文依赖 → 串行（每个场景依赖前一场景的 caption 结果）
        # 无上下文依赖 → 有界并发（asyncio.Semaphore 控制 QPS）
        if with_context:
            for i, scene in enumerate(scenes):
                await _caption_one(i, scene)
        else:
            await asyncio.gather(*[_caption_one(i, s) for i, s in enumerate(scenes)])

        captioned = sum(1 for s in scenes if s.caption)
        logger.info("[Phase4] Captioned %d/%d scenes (multi-frame)", captioned, total)
