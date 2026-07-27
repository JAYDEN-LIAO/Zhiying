"""
pipeline/runners/caption.py
═══════════════════════════════════════════════════════════
场景描述 runner — 双模式策略（native_video / vlm_llm）。

native_video: Qwen2.5-VL-7B 本地 GPU 直接观看视频片段 → 结构化 JSON
vlm_llm:      Qwen-VL-Max API 看图说话 → 自然语言描述

提取自 pipeline/phase4_caption.py
"""

import json as json_mod
import logging
import os
import re

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


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
    """场景描述执行器 — 策略模式路由双模式。"""

    async def run(self, pctx: PipelineContext) -> None:
        captioner = pctx.plugins.get("captioner")
        scenes = pctx.ctx.scenes

        if captioner is None or not scenes:
            logger.info("[CaptionRunner] Captioner disabled or no scenes, skipping")
            return

        # 摘要未开 → caption 无下游消费者，跳过（caption 只服务 summary）
        # 不论场景数量，caption 模型加载 + 逐场景推理都是白白浪费
        if not pctx.video.summary_enabled:
            logger.info("[CaptionRunner] Skipping: summary disabled")
            return
            return

        mode = getattr(pctx.video, "summary_mode", "native_video")

        # vlm_llm 模式需要切换 captioner backend
        if mode == "vlm_llm":
            await self._ensure_api_captioner(pctx)
            captioner = pctx.plugins.get("captioner")
            if captioner is None:
                logger.error("[CaptionRunner] Failed to load API captioner")
                return

        if mode == "vlm_llm":
            await self._run_vlm_llm(pctx, captioner, scenes)
        else:
            await self._run_native_video(pctx, captioner, scenes)

        captioned = sum(1 for s in scenes if s.caption)
        logger.info("[CaptionRunner] Captioned %d/%d scenes", captioned, len(scenes))

    # ── 双模式策略 ──

    async def _run_native_video(self, pctx, captioner, scenes) -> None:
        """native_video: 模型直接观看视频片段 → 结构化 JSON。"""
        total = len(scenes)
        await pctx.tracker.update("caption", sub_progress=0.0)

        cfg = pctx.config.get("plugins", {}).get("captioner", {})
        with_context = cfg.get("with_context", False)
        max_tokens = cfg.get("max_new_tokens", 512)

        for i, scene in enumerate(scenes):
            captioner.video_path = pctx.ctx.file_path
            captioner.scene_start = scene.start_sec
            captioner.scene_end = scene.end_sec

            prompt = self._build_prompt(i, scenes, with_context, pctx)
            raw = await captioner.caption([], prompt, max_new_tokens=max_tokens)
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

    async def _run_vlm_llm(self, pctx, captioner, scenes) -> None:
        """vlm_llm: API 看图说话 → 自然语言描述。"""
        total = len(scenes)
        await pctx.tracker.update("caption", sub_progress=0.0)

        cfg = pctx.config.get("plugins", {}).get("captioner", {})
        with_context = cfg.get("with_context", False)
        max_tokens = cfg.get("max_new_tokens", 512)

        pl = pctx.prompt_loader
        for i, scene in enumerate(scenes):
            frames = getattr(scene, "caption_frames", None) or scene.keyframes
            if not frames:
                continue

            if with_context and i > 0 and scenes[i - 1].caption:
                prompt = pl.get(
                    "caption_vlm_with_context",
                    prev_caption=scenes[i - 1].caption or "无",
                ) if pl else ""
            else:
                prompt = pl.get("caption_vlm") if pl else ""

            scene.caption = await captioner.caption(
                frames, prompt, max_new_tokens=max_tokens,
            )
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

        不污染 pctx.config（操作副本），只在 pctx.plugins 中替换。
        """
        from plugins.factory import load_plugin
        import copy

        api_cfg = copy.deepcopy(pctx.config)
        api_cfg["plugins"]["captioner"]["backend"] = "qwen_api"
        api_cfg["plugins"]["captioner"]["params"] = {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": os.environ.get("DASHSCOPE_API_KEY", ""),
            "model_name": "qwen-vl-max",
        }
        api_captioner = await load_plugin(api_cfg, "captioner")
        if api_captioner:
            pctx.plugins["captioner"] = api_captioner
