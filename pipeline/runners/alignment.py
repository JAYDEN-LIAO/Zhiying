"""
pipeline/runners/alignment.py
═══════════════════════════════════════════════════════════
转录-场景对齐 runner — 将 word 级时间戳按时间窗口分配到场景。

提取自 pipeline/phase3_alignment.py
"""

import logging

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class AlignRunner(OperationRunner):
    """转录-场景对齐执行器 — 双指针算法按时间戳分配。"""

    async def run(self, pctx: PipelineContext) -> None:
        scenes = pctx.ctx.scenes
        words = pctx.ctx.transcript_words

        if not scenes:
            logger.info("[AlignRunner] No scenes to align, skipping")
            return

        if not words:
            logger.info("[AlignRunner] No transcript words to align, skipping")
            return

        await pctx.tracker.update("alignment")

        word_idx = 0
        total_words = len(words)
        total_scenes = len(scenes)

        for scene in scenes:
            scene_text_parts: list[str] = []
            while word_idx < total_words:
                w = words[word_idx]
                word_start = w.get("start", 0.0)

                if scene.start_sec <= word_start < scene.end_sec:
                    scene_text_parts.append(w.get("word", ""))
                    word_idx += 1
                elif word_start < scene.start_sec:
                    word_idx += 1
                    continue
                else:
                    break

            if scene_text_parts:
                scene.aligned_transcript = " ".join(scene_text_parts)

        # 剩余 words 追加到最后一个 scene
        if word_idx < total_words and scenes:
            remaining = [w.get("word", "") for w in words[word_idx:]]
            if remaining:
                tail = " ".join(remaining)
                existing = scenes[-1].aligned_transcript or ""
                scenes[-1].aligned_transcript = (existing + " " + tail).strip()

        total_aligned = sum(1 for s in scenes if s.aligned_transcript)
        await pctx.tracker.update(
            "alignment",
            description=f"对齐完成: {total_aligned}/{total_scenes} 个场景已分配转录文本",
        )
        logger.info(
            "[AlignRunner] Done: %d/%d scenes have transcript",
            total_aligned, total_scenes,
        )
