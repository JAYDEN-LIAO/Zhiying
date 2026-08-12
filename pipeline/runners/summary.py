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
from pipeline.runners.base import OperationRunner, PipelineContext, effective_summary_mode

logger = logging.getLogger(__name__)


class SummaryRunner(OperationRunner):
    """摘要生成执行器 — 策略模式路由双模式。"""

    async def run(self, pctx: PipelineContext) -> None:
        await pctx.tracker.update("summary")

        scenes = pctx.ctx.scenes
        if not scenes:
            logger.info("[SummaryRunner] No scenes, skipping")
            return

        mode = effective_summary_mode(pctx.video, pctx.config)

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
            # 构建总摘要：遍历所有场景，提取时间+关键词，非模型拼接
            scene_briefs: list[str] = []
            for s in scenes_summary:
                start_str = f"{int(s['start_sec'] // 60):02d}:{int(s['start_sec'] % 60):02d}"
                # 取前 3 个关键词作为场景速写
                kws = s.get("keywords", [])[:3]
                brief = start_str
                if kws:
                    brief += " " + "、".join(kws)
                scene_briefs.append(brief)

            chain = " → ".join(scene_briefs)
            label = "个场景" if len(scene_briefs) == 1 else "个片段"
            one_liner = f"{len(scenes_summary)} {label}：{chain}"

            # 追加全局标签作为补充
            top_tags = [k for k, _ in kw_counter.most_common(3)]
            if top_tags:
                one_liner += f" ｜{'、'.join(top_tags)}"
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

        budget = self._input_budget(pctx)
        script, scene_count = self._build_script(scenes, budget)
        if not script.strip():
            logger.info("[SummaryRunner] No content to summarize, skipping")
            return

        await pctx.tracker.update(
            "summary",
            description=f"正在生成摘要（{scene_count} 个场景）...",
        )

        pl = pctx.prompt_loader
        system_prompt = pl.get_raw("summary_system") if pl else ""
        user_prompt = (
            pl.get("summary_user", caption_timeline=script)
            if pl else script
        )

        logger.info("[SummaryRunner] Summarizing %d scenes via LLM...", scene_count)
        try:
            raw = await summarizer.summarize(script, system_prompt, user_prompt)
        except Exception as e:
            # 摘要属 best-effort：LLM 失败（API / 截断 / 解析）→ 回退本地聚合，
            # 绝不因摘要失败拖垮整个管道（摘要本就是可降级产物）
            logger.warning("[SummaryRunner] LLM summary failed (%s), falling back to native aggregator", e)
            await self._run_aggregate(pctx, scenes)
            return
        await self._validate_and_store(pctx, raw)

    # ── 剧本构建 + 输入预算（v0.33 防长视频上下文溢出）──

    @staticmethod
    def _input_budget(pctx) -> int:
        """摘要 LLM 输入预算（字符数）— 超长剧本时截断，防上下文溢出。"""
        cfg = pctx.config.get("plugins", {}).get("summarizer", {})
        return int(cfg.get("max_input_chars", 12000))

    @classmethod
    def _build_script(cls, scenes: list[Scene], budget_chars: int) -> tuple[str, int]:
        """把场景描述拼成剧本 + 返回有内容的场景数；超预算时按 台词 → 文字 → 画面 优先级截尾。

        不超预算 → 输出与旧逻辑字节级一致。场景数用于日志/进度描述（caption 内换行不计入）。
        """
        entries: list[dict] = []
        for s in scenes:
            caption = (s.caption or "").strip()
            ocr = (s.ocr_text or "").strip()
            transcript = (s.aligned_transcript or "").strip()
            if not caption and not ocr and not transcript:
                continue
            entries.append({
                "start": s.start_sec, "end": s.end_sec,
                "caption": caption, "ocr": ocr, "transcript": transcript,
            })

        def render() -> str:
            return "\n".join(cls._entry_line(e) for e in entries)

        script = render()
        if len(script) <= budget_chars:
            return script, len(entries)

        # 超预算：按 transcript → ocr → caption 优先级逐条截尾（循环至满足预算）。
        # 截断保留 "…" 后缀，多砍 1 字符保证净减 exactly over，避免超预算漏进下一优先级。
        for field in ("transcript", "ocr", "caption"):
            for e in entries:
                if len(script) <= budget_chars:
                    return script, len(entries)
                if not e[field]:
                    continue
                while len(script) > budget_chars and e[field]:
                    over = len(script) - budget_chars
                    if len(e[field]) > over:
                        e[field] = e[field][:len(e[field]) - over - 1] + "…"
                    else:
                        e[field] = ""
                    script = render()
        return script, len(entries)

    @staticmethod
    def _entry_line(e: dict) -> str:
        parts = [f"[{e['start']:.1f}-{e['end']:.1f}]"]
        if e["caption"]:
            parts.append(f"画面:{e['caption']}")
        if e["ocr"]:
            parts.append(f"文字:{e['ocr']}")
        if e["transcript"]:
            parts.append(f"台词:{e['transcript']}")
        return " ".join(parts)

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
        # fallback 也构建多场景总摘要
        if len(items) == 1:
            fallback_one = f"{len(items)} 个场景：{ (items[0]['description'] or '')[:40] }"
        else:
            briefs = []
            for it in items:
                ts = f"{int(it['start_sec'] // 60):02d}:{int(it['start_sec'] % 60):02d}"
                briefs.append(ts)
            fallback_one = f"{len(items)} 个片段：" + " → ".join(briefs)
        return {
            "one_liner": fallback_one,
            "scenes_summary": items, "tags": [], "main_topics": [], "main_entities": [],
        }
