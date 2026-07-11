"""
pipeline/phase5_summary.py
═══════════════════════════════════════════════════════════
Phase 5: 全局升华摘要 — 视频剧本 → LLM 结构化摘要。

执行逻辑:
  1. 遍历 scenes，构建剧本字符串
  2. 从 prompt_loader 获取 system / user prompt
  3. 调用 summarizer.summarize() → ctx.summary
  4. 使用 VideoSummary schema 校验
"""

import logging

from core.interfaces import VideoContext
from core.status_tracker import StatusTracker
from core.prompt_loader import PromptLoader
from core.schemas import VideoSummary

logger = logging.getLogger(__name__)


class Phase5Summary:
    """Phase 5 执行器 — LLM 结构化摘要生成。"""

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
        """生成全局摘要。"""
        await self.tracker.update("phase_5_summary")

        summarizer = self.plugins.get("summarizer")
        if summarizer is None:
            logger.info("[Phase5] Summarizer disabled, skipping")
            return

        if not self.ctx.scenes:
            logger.info("[Phase5] No scenes to summarize, skipping")
            return

        # ── 构建剧本字符串 ──
        script_lines: list[str] = []
        for scene in self.ctx.scenes:
            caption = scene.caption or ""
            ocr = scene.ocr_text or ""
            transcript = scene.aligned_transcript or ""

            if not caption and not ocr and not transcript:
                continue

            line = (
                f"[{scene.start_sec:.1f}-{scene.end_sec:.1f}] "
                f"画面:{caption} "
                f"文字:{ocr} "
                f"台词:{transcript}"
            )
            script_lines.append(line)

        script = "\n".join(script_lines)
        if not script.strip():
            logger.info("[Phase5] No content to summarize, skipping")
            return

        # ── 获取 prompt ──
        system_prompt = self.pl.get_raw("summary_system")
        user_prompt = self.pl.get(
            "summary_user",
            caption_timeline=script,
            transcript_text=self.ctx.transcript_full or "",
        )

        # ── LLM 推理 ──
        logger.info(
            "[Phase5] Summarizing %d scenes (%d chars)...",
            len(script_lines), len(script),
        )
        raw_summary = await summarizer.summarize(
            script, system_prompt, user_prompt,
        )

        # ── 校验 ──
        try:
            validated = VideoSummary.model_validate(raw_summary)
            self.ctx.summary = validated.model_dump()
        except Exception as e:
            logger.warning("[Phase5] Summary validation failed: %s", e)
            self.ctx.summary = raw_summary

        await self.tracker.update("phase_5_summary", progress=0.90)
        one_liner = (self.ctx.summary or {}).get("one_liner", "")[:80]
        logger.info("[Phase5] Summary done: %s", one_liner)
