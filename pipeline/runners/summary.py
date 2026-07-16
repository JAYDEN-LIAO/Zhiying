"""
pipeline/runners/summary.py
═══════════════════════════════════════════════════════════
摘要生成 runner — 双模式策略（native_video 聚合 / vlm_llm LLM 拼凑）。

native_video: 纯 Python 聚合器（Counter 频率统计 + 去重）
vlm_llm:      LLM 拼凑（DeepSeek API）

提取自 pipeline/phase5_summary.py
"""

import logging
from collections import Counter

from core.interfaces import Scene
from core.schemas import VideoSummary
from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class SummaryRunner(OperationRunner):
    """摘要生成执行器 — 策略模式路由双模式。"""

    async def run(self, pctx: PipelineContext) -> None:
        await pctx.tracker.update("summary")

        scenes = pctx.ctx.scenes
        if not scenes:
            logger.info("[SummaryRunner] No scenes, skipping")
            return

        mode = getattr(pctx.video, "summary_mode", "native_video")

        if mode == "vlm_llm":
            await self._run_llm(pctx, scenes)
        else:
            await self._run_aggregate(pctx, scenes)

    # ── native_video: 纯 Python 聚合 ──

    async def _run_aggregate(self, pctx, scenes: list[Scene]) -> None:
        structured = [s for s in scenes if s.structured_caption]
        if not structured:
            logger.warning("[SummaryRunner] No structured captions, using fallback")
            pctx.ctx.summary = self._fallback_summary(scenes)
            return

        await pctx.tracker.update(
            "summary",
            description=f"正在聚合 {len(structured)} 个场景的结构化数据...",
        )
        summary = self._aggregate(scenes, structured)
        await self._validate_and_store(pctx, summary)

    @staticmethod
    def _aggregate(all_scenes: list[Scene], structured: list[Scene]) -> dict:
        all_kw: list[str] = []
        all_obj: list[str] = []
        all_types: list[str] = []
        scenes_summary: list[dict] = []

        for s in structured:
            sc = s.structured_caption
            desc = sc.get("description", s.caption or "")
            kw = sc.get("keywords", [])
            obj = sc.get("objects", [])
            st = sc.get("scene_type", "")

            scenes_summary.append({
                "scene_index": s.scene_index,
                "start_sec": s.start_sec,
                "end_sec": s.end_sec,
                "description": desc,
                "keywords": kw,
            })
            all_kw.extend(kw)
            all_obj.extend(obj)
            if st:
                all_types.append(st)

        kw_counter = Counter(all_kw)
        obj_counter = Counter(all_obj)
        tags = [k for k, c in kw_counter.most_common(5) if c >= 1]
        topics = [k for k, _ in kw_counter.most_common(3)]
        entities = [o for o, _ in obj_counter.most_common(1)]

        if scenes_summary:
            types_str = "、".join(list(dict.fromkeys(all_types))[:2])
            one_liner = (
                f"共 {len(scenes_summary)} 个场景"
                + (f"（{types_str}）" if types_str else "")
                + f"：{scenes_summary[0]['description'][:80]}..."
            )
        else:
            one_liner = ""

        return {
            "one_liner": one_liner,
            "scenes_summary": scenes_summary,
            "tags": tags,
            "main_topics": topics,
            "main_entities": entities,
        }

    # ── vlm_llm: LLM 拼凑 ──

    async def _run_llm(self, pctx, scenes: list[Scene]) -> None:
        summarizer = pctx.plugins.get("summarizer")
        if summarizer is None:
            logger.warning("[SummaryRunner] Summarizer plugin not loaded, using fallback")
            pctx.ctx.summary = self._fallback_summary(scenes)
            return

        lines: list[str] = []
        for s in scenes:
            caption = (s.caption or "").strip()
            ocr = (s.ocr_text or "").strip()
            transcript = (s.aligned_transcript or "").strip()
            if not caption and not ocr and not transcript:
                continue
            parts = [f"[{s.start_sec:.1f}-{s.end_sec:.1f}]"]
            if caption:
                parts.append(f"画面:{caption}")
            if ocr:
                parts.append(f"文字:{ocr}")
            if transcript:
                parts.append(f"台词:{transcript}")
            lines.append(" ".join(parts))

        script = "\n".join(lines)
        if not script.strip():
            logger.info("[SummaryRunner] No content to summarize, skipping")
            return

        await pctx.tracker.update(
            "summary",
            description=f"正在生成摘要（{len(lines)} 个场景）...",
        )

        pl = pctx.prompt_loader
        system_prompt = pl.get_raw("summary_system") if pl else ""
        user_prompt = (
            pl.get("summary_user", caption_timeline=script)
            if pl else script
        )

        logger.info("[SummaryRunner] Summarizing %d scenes via LLM...", len(lines))
        raw = await summarizer.summarize(script, system_prompt, user_prompt)
        await self._validate_and_store(pctx, raw)

    # ── 共用 ──

    async def _validate_and_store(self, pctx, summary: dict | None) -> None:
        if summary is None:
            return
        try:
            validated = VideoSummary.model_validate(summary)
            pctx.ctx.summary = validated.model_dump()
        except Exception as e:
            logger.warning("[SummaryRunner] Validation failed: %s", e)
            pctx.ctx.summary = None

        await pctx.tracker.update("summary")
        one_liner = (summary or {}).get("one_liner", "")[:80]
        logger.info("[SummaryRunner] Done: %s", one_liner)

    @staticmethod
    def _fallback_summary(scenes: list[Scene]) -> dict:
        captioned = [s for s in scenes if s.caption]
        if not captioned:
            return {"one_liner": "", "scenes_summary": [], "tags": [], "main_topics": [], "main_entities": []}
        items = [
            {"scene_index": s.scene_index, "start_sec": s.start_sec, "end_sec": s.end_sec,
             "description": (s.caption or "")[:200], "keywords": []}
            for s in captioned
        ]
        return {
            "one_liner": f"共 {len(items)} 个场景：{(captioned[0].caption or '')[:80]}...",
            "scenes_summary": items, "tags": [], "main_topics": [], "main_entities": [],
        }
