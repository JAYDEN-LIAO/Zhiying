"""
pipeline/runners/text_encode.py
═══════════════════════════════════════════════════════════
文本语义编码 runner — 攒批 encode_texts_batch(caption+ocr+transcript) → scenes.text_embedding。

v0.33 重构：从逐场景串行 encode_text 改为先攒批、一次批量前向
（对齐 frame 路径的 encode_images_batch），老 embedder 无批量方法时逐条回退。

写入 ctx（内存），由 engine._persist() 统一入库。
"""

import logging

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class TextEncodeRunner(OperationRunner):
    """文本语义编码执行器 — 攒批拼接 caption + OCR + transcript 后批量编码。"""

    async def run(self, pctx: PipelineContext) -> None:
        embedder = pctx.shared_embedder or pctx.plugins.get("embedder")
        if embedder is None:
            logger.warning("[TextEncodeRunner] No embedder available, skipping")
            return

        scenes = pctx.ctx.scenes
        if not scenes:
            return

        # ── 先攒批：拼接各场景文本，一次批量编码 ──
        texts: list[str] = []
        indexes: list[int] = []
        for i, scene in enumerate(scenes):
            text_parts = []
            if scene.caption:
                text_parts.append(scene.caption)
            if scene.ocr_text:
                text_parts.append(f"OCR: {scene.ocr_text}")
            if scene.aligned_transcript:
                text_parts.append(f"音频: {scene.aligned_transcript}")
            if text_parts:
                texts.append(" | ".join(text_parts))
                indexes.append(i)

        if not texts:
            logger.info("[TextEncodeRunner] No text to encode, skipping")
            return

        total = len(scenes)
        await pctx.tracker.update("text_encode", sub_progress=0.0)
        logger.info("[TextEncodeRunner] Encoding %d scene text embeddings (batch)", len(texts))

        lock = getattr(pctx, "embedder_lock", None)
        if lock:
            await lock.acquire()
        try:
            if hasattr(embedder, "encode_texts_batch"):
                embs = await embedder.encode_texts_batch(texts)
            else:
                # 防御：老 embedder 无批量方法 → 逐条回退
                embs = [await embedder.encode_text(t) for t in texts]
        finally:
            if lock:
                lock.release()

        for idx, emb in zip(indexes, embs):
            if emb:
                scenes[idx].text_embedding = emb

        await pctx.tracker.update("text_encode", sub_progress=1.0)
        logger.info("[TextEncodeRunner] Done: %d scenes encoded", len(texts))
