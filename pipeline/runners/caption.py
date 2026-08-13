"""
pipeline/runners/caption.py
═══════════════════════════════════════════════════════════
场景描述 runner — 双模式策略（native_video / vlm_llm）。

native_video: Qwen2.5-VL-7B 本地 GPU 直接观看视频片段 → 结构化 JSON
vlm_llm:      Qwen-VL-Max API 看图说话 → 自然语言描述

重构要点（v0.33）：
  - 配置穿透：with_context / max_new_tokens / concurrency 从 captioner.params 子层读
    （原从顶层读，实际值在 params → 恒不生效；video.caption_with_context 已废弃）
  - 单场景失败降级：轻量重试 1 次后跳过该场景，不拖垮整个管道
  - 并发：with_context=False（默认）→ Semaphore 限流并发；
           with_context=True → 顺序执行（prompt 依赖上一场景 caption，需保序）
"""

import asyncio
import json as json_mod
import logging
import os
import re

from pipeline.runners.base import OperationRunner, PipelineContext, effective_summary_mode

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 512
_DEFAULT_CONCURRENCY = 4


def _parse_caption_json(raw: str) -> dict | None:
    """从模型输出中提取结构化 JSON。"""
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


class CaptionRunner(OperationRunner):
    """场景描述执行器 — 策略模式路由双模式 + 并发限流 + 单场景降级。"""

    async def run(self, pctx: PipelineContext) -> None:
        captioner = pctx.plugins.get("captioner")
        scenes = pctx.ctx.scenes

        if captioner is None or not scenes:
            logger.info("[CaptionRunner] Captioner disabled or no scenes, skipping")
            return

        # 摘要未开 → caption 无下游消费者，跳过（caption 只服务 summary）
        if not pctx.video.summary_enabled:
            logger.info("[CaptionRunner] Skipping: summary disabled")
            return

        mode = effective_summary_mode(pctx.video, pctx.config)

        # vlm_llm 模式需要切换 captioner backend
        if mode == "vlm_llm":
            await self._ensure_api_captioner(pctx)
            captioner = pctx.plugins.get("captioner")
            if captioner is None:
                logger.error("[CaptionRunner] Failed to load API captioner")
                return

        with_context, max_tokens, concurrency = self._caption_config(pctx)

        if mode == "vlm_llm":
            await self._run_vlm_llm(pctx, captioner, scenes, with_context, max_tokens, concurrency)
        else:
            await self._run_native_video(pctx, captioner, scenes, with_context, max_tokens)

        captioned = sum(1 for s in scenes if s.caption)
        logger.info("[CaptionRunner] Captioned %d/%d scenes", captioned, len(scenes))
        if pctx.log:
            await pctx.log(f"画面描述完成：{captioned}/{len(scenes)} 个场景")

    # ── 配置读取（CONFIG-1 根治：从 params 子层读；video.caption_with_context 已废弃）──

    @staticmethod
    def _caption_config(pctx) -> tuple[bool, int, int]:
        """返回 (with_context, max_new_tokens, concurrency)。

        with_context=True 时并发强制 1（prompt 依赖上一场景 caption，需顺序）。
        """
        cfg = pctx.config.get("plugins", {}).get("captioner", {})
        params = cfg.get("params") or {}
        with_context = bool(params.get("with_context", False))
        max_tokens = int(params.get("max_new_tokens", _DEFAULT_MAX_TOKENS))
        concurrency = 1 if with_context else int(params.get("concurrency", _DEFAULT_CONCURRENCY))
        return with_context, max_tokens, concurrency

    # ── 单场景调用：轻量重试 1 次 + 失败降级返回 None（不抛）──

    async def _caption_scene(self, captioner, scene, frames, prompt, max_tokens) -> str | None:
        for attempt in range(2):
            try:
                return await captioner.caption(frames, prompt, max_new_tokens=max_tokens)
            except Exception as e:
                logger.warning(
                    "[CaptionRunner] Scene %d caption failed (attempt %d/2): %s",
                    scene.scene_index, attempt + 1, e,
                )
                if attempt == 0:
                    await asyncio.sleep(1.0)
        return None

    # ── vlm_llm: API 看图说话（with_context=False 并发 / True 顺序）──

    async def _run_vlm_llm(
        self, pctx, captioner, scenes,
        with_context: bool, max_tokens: int, concurrency: int,
    ) -> None:
        total = len(scenes)
        if total == 0:
            return
        await pctx.tracker.update("caption", sub_progress=0.0)
        done = 0

        async def _one(i: int, scene) -> None:
            nonlocal done
            frames = getattr(scene, "caption_frames", None) or scene.keyframes
            if not frames:
                return
            prompt = self._build_vlm_prompt(pctx, scenes, i, with_context)
            raw = await self._caption_scene(captioner, scene, frames, prompt, max_tokens)
            if raw:
                scene.caption = raw
                scene.structured_caption = None
            done += 1
            await pctx.tracker.update(
                "caption",
                sub_progress=done / total,
                description=f"正在描述第 {done}/{total} 个场景",
            )

        if with_context:
            # 顺序执行：场景 i 的 prompt 依赖 scenes[i-1].caption
            for i, scene in enumerate(scenes):
                await _one(i, scene)
        else:
            sem = asyncio.Semaphore(concurrency)

            async def _guarded(i: int, scene) -> None:
                async with sem:
                    await _one(i, scene)

            await asyncio.gather(*(_guarded(i, s) for i, s in enumerate(scenes)))

        # prev_caption 回填（无论开关，供存储 / 摘要 / 文本搜索）
        for i, scene in enumerate(scenes):
            if i > 0:
                scene.prev_caption = scenes[i - 1].caption

    def _build_vlm_prompt(self, pctx, scenes, i: int, with_context: bool) -> str:
        pl = pctx.prompt_loader
        if with_context and i > 0 and scenes[i - 1].caption:
            return (
                pl.get("caption_vlm_with_context", prev_caption=scenes[i - 1].caption or "无")
                if pl else ""
            )
        return pl.get("caption_vlm") if pl else ""

    # ── native_video: 本地模型直接看视频片段 → 结构化 JSON ──

    async def _run_native_video(
        self, pctx, captioner, scenes, with_context: bool, max_tokens: int,
    ) -> None:
        total = len(scenes)
        await pctx.tracker.update("caption", sub_progress=0.0)

        for i, scene in enumerate(scenes):
            captioner.video_path = pctx.ctx.file_path
            captioner.scene_start = scene.start_sec
            captioner.scene_end = scene.end_sec

            prompt = self._build_prompt(i, scenes, with_context, pctx)
            raw = await self._caption_scene(captioner, scene, [], prompt, max_tokens)

            if raw is not None:
                parsed = _parse_caption_json(raw)
                if parsed is not None:
                    scene.structured_caption = parsed
                    scene.caption = parsed.get("description", raw)
                else:
                    scene.caption = raw
                    scene.structured_caption = None

            if i > 0:
                scene.prev_caption = scenes[i - 1].caption

            await pctx.tracker.update(
                "caption",
                sub_progress=(i + 1) / total,
                description=f"正在描述第 {i + 1}/{total} 个场景",
            )

    # ── 辅助 ──

    def _build_prompt(self, i: int, scenes, with_context: bool, pctx) -> str:
        pl = pctx.prompt_loader
        if with_context and i > 0:
            prev = scenes[i - 1]
            prev_desc = (
                (prev.structured_caption or {}).get("description")
                or prev.caption
            )
            if prev_desc and pl:
                return pl.get("caption_with_context", prev_caption=prev_desc)
        return pl.get("caption_default") if pl else ""

    async def _ensure_api_captioner(self, pctx) -> None:
        """vlm_llm 模式：加载 API captioner 替换 local captioner。

        端点 / 模型名 / 密钥 / max_new_tokens 均取自有效配置
        （config.yaml + settings.json 设置页覆盖），不硬编码。
        不污染 pctx.config（操作副本），只在 pctx.plugins 中替换。
        """
        from plugins.factory import load_plugin
        import copy

        api_cfg = copy.deepcopy(pctx.config)
        cap_cfg = api_cfg.setdefault("plugins", {}).setdefault("captioner", {})
        cap_cfg["backend"] = "qwen_api"
        params = cap_cfg.get("params") or {}
        cap_cfg["params"] = {
            "base_url": params.get(
                "base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
            "api_key": params.get("api_key") or os.environ.get("DASHSCOPE_API_KEY", ""),
            "model_name": params.get("model_name", "qwen-vl-max"),
            "max_new_tokens": params.get("max_new_tokens", _DEFAULT_MAX_TOKENS),
            "with_context": params.get("with_context", False),
            "concurrency": params.get("concurrency", _DEFAULT_CONCURRENCY),
        }
        api_captioner = await load_plugin(api_cfg, "captioner")
        if api_captioner:
            pctx.plugins["captioner"] = api_captioner
