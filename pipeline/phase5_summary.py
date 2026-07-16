"""
pipeline/phase5_summary.py
═══════════════════════════════════════════════════════════
Phase 5: 摘要生成 — 双路径路由。

native_video:
  纯 Python 聚合器 — 遍历 scenes.structured_caption，
  Counter 频率统计 + 去重 → VideoSummary

vlm_llm:
  LLM 拼凑 — 将所有 scene.caption 拼成剧本 →
  summarizer API (DeepSeek) → 结构化 JSON → VideoSummary
"""

import logging
from collections import Counter

from core.interfaces import VideoContext, Scene
from core.status_tracker import StatusTracker
from core.schemas import VideoSummary

logger = logging.getLogger(__name__)


class Phase5Summary:
    """Phase 5 执行器 — 双路径摘要。"""

    def __init__(
        self,
        ctx: VideoContext,
        plugins: dict,
        config: dict,
        tracker: StatusTracker,
        prompt_loader=None,
        summary_mode: str = "native_video",
    ):
        self.ctx = ctx
        self.plugins = plugins
        self.config = config
        self.tracker = tracker
        self.pl = prompt_loader
        self.summary_mode = summary_mode

    async def execute(self) -> None:
        await self.tracker.update("phase_5_summary")

        scenes = self.ctx.scenes
        if not scenes:
            logger.info("[Phase5] No scenes, skipping")
            return

        if self.summary_mode == "vlm_llm":
            await self._run_llm(scenes)
        else:
            await self._run_aggregate(scenes)

    # ──────────────────────────────────────────────────────
    # native_video: 纯 Python 聚合
    # ──────────────────────────────────────────────────────

    async def _run_aggregate(self, scenes: list[Scene]) -> None:
        structured = [s for s in scenes if s.structured_caption]
        if not structured:
            logger.warning("[Phase5] No structured captions, using fallback")
            self.ctx.summary = self._fallback_summary(scenes)
            return

        await self.tracker.update(
            "phase_5_summary",
            description=f"正在聚合 {len(structured)} 个场景的结构化数据...",
        )
        summary = self._aggregate(scenes, structured)
        await self._validate_and_store(summary)

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

    # ──────────────────────────────────────────────────────
    # vlm_llm: LLM 拼凑摘要
    # ──────────────────────────────────────────────────────

    async def _run_llm(self, scenes: list[Scene]) -> None:
        summarizer = self.plugins.get("summarizer")
        if summarizer is None:
            logger.warning("[Phase5] Summarizer plugin not loaded, skipping")
            self.ctx.summary = self._fallback_summary(scenes)
            return

        # 构建剧本
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
            logger.info("[Phase5] No content to summarize, skipping")
            return

        await self.tracker.update(
            "phase_5_summary",
            description=f"正在生成摘要（{len(lines)} 个场景）...",
        )

        system_prompt = self.pl.get_raw("summary_system") if self.pl else ""
        user_prompt = (
            self.pl.get("summary_user", caption_timeline=script)
            if self.pl
            else script
        )

        logger.info("[Phase5] Summarizing %d scenes via LLM...", len(lines))
        raw = await summarizer.summarize(script, system_prompt, user_prompt)
        await self._validate_and_store(raw)

    # ──────────────────────────────────────────────────────
    # 共用
    # ──────────────────────────────────────────────────────

    async def _validate_and_store(self, summary: dict | None) -> None:
        if summary is None:
            return
        try:
            validated = VideoSummary.model_validate(summary)
            self.ctx.summary = validated.model_dump()
        except Exception as e:
            logger.warning("[Phase5] Validation failed: %s", e)
            self.ctx.summary = None

        await self.tracker.update("phase_5_summary", progress=0.90)
        one_liner = (summary or {}).get("one_liner", "")[:80]
        logger.info("[Phase5] Summary done: %s", one_liner)

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
