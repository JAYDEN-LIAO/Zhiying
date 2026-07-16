"""
pipeline/runners/text_encode.py
═══════════════════════════════════════════════════════════
文本语义编码 runner — encode_text(caption+ocr+transcript) → ctx.scenes.text_embedding。

写入 ctx（内存），由 engine._persist() 统一入库。
"""

import logging

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class TextEncodeRunner(OperationRunner):
    """文本语义编码执行器 — 拼接 caption + OCR + transcript 后编码。"""

    async def run(self, pctx: PipelineContext) -> None:
        embedder = pctx.shared_embedder or pctx.plugins.get("embedder")
        if embedder is None:
            logger.warning("[TextEncodeRunner] No embedder available, skipping")
            return

        scenes = pctx.ctx.scenes
        if not scenes:
            return

        total = len(scenes)
        await pctx.tracker.update("text_encode", sub_progress=0.0)
        logger.info("[TextEncodeRunner] Encoding text embeddings ...")

        for i, scene in enumerate(scenes):
            text_parts = []
            if scene.caption:
                text_parts.append(scene.caption)
            if scene.ocr_text:
                text_parts.append(f"OCR: {scene.ocr_text}")
            if scene.aligned_transcript:
                text_parts.append(f"音频: {scene.aligned_transcript}")

            if text_parts:
                combined_text = " | ".join(text_parts)
                text_emb = await embedder.encode_text(combined_text)
                if text_emb:
                    scene.text_embedding = text_emb

            await pctx.tracker.update("text_encode", sub_progress=(i + 1) / total)

        logger.info("[TextEncodeRunner] Done")
