"""
pipeline/phase3_alignment.py
═══════════════════════════════════════════════════════════
Phase 3: 模态交叉对齐 — 将 transcript_words 按时间戳切分到每个 Scene。

执行逻辑:
  for each word in transcript_words:
      查找所属 scene（start_sec ≤ word.start < end_sec）
      追加到 scene.aligned_transcript
"""

import logging

from core.interfaces import VideoContext
from core.status_tracker import StatusTracker

logger = logging.getLogger(__name__)


class Phase3Alignment:
    """Phase 3 执行器 — 转录词级时间戳与场景的对齐。"""

    def __init__(
        self,
        ctx: VideoContext,
        plugins: dict,
        config: dict,
        tracker: StatusTracker,
    ):
        self.ctx = ctx
        self.plugins = plugins
        self.config = config
        self.tracker = tracker

    async def execute(self) -> None:
        """将 transcript_words 按时间戳分配到每个 Scene。"""
        await self.tracker.update("phase_3_align")

        scenes = self.ctx.scenes
        words = self.ctx.transcript_words

        if not scenes:
            logger.info("[Phase3] No scenes to align, skipping")
            return

        if not words:
            logger.info("[Phase3] No transcript words to align, skipping")
            return

        # 使用双指针遍历（两个列表均按时间升序）
        word_idx = 0
        total_words = len(words)
        total_scenes = len(scenes)

        for scene in scenes:
            scene_text_parts: list[str] = []

            # 收集属于当前时间窗口的 words
            while word_idx < total_words:
                w = words[word_idx]
                word_start = w.get("start", 0.0)
                word_end = w.get("end", 0.0)

                # word 完全在当前 scene 窗口内
                if scene.start_sec <= word_start < scene.end_sec:
                    scene_text_parts.append(w.get("word", ""))
                    word_idx += 1
                # word 跨越了 scene 边界 → 划入当前 scene 并继续
                elif word_start < scene.start_sec:
                    word_idx += 1
                    continue
                # word 已进入后续 scene → 跳出
                else:
                    break

            if scene_text_parts:
                scene.aligned_transcript = " ".join(scene_text_parts)

        # 将最后剩余的 words 追加到最后一个 scene
        if word_idx < total_words and scenes:
            remaining = [w.get("word", "") for w in words[word_idx:]]
            if remaining:
                tail = " ".join(remaining)
                existing = scenes[-1].aligned_transcript or ""
                scenes[-1].aligned_transcript = (existing + " " + tail).strip()

        total_aligned = sum(
            1 for s in scenes if s.aligned_transcript
        )
        logger.info(
            "[Phase3] Alignment done: %d/%d scenes have transcript",
            total_aligned, total_scenes,
        )
