"""
pipeline/runners/transcription.py
═══════════════════════════════════════════════════════════
音频转录 runner — 抽取音频并执行语音识别。

提取自 pipeline/phase1_qc.py:_run_audio_transcription()
"""

import logging
import os

from pipeline.runners.base import OperationRunner, PipelineContext
from utils.video_util import extract_audio

logger = logging.getLogger(__name__)


class TranscribeRunner(OperationRunner):
    """音频转录执行器。"""

    async def run(self, pctx: PipelineContext) -> None:
        transcriber = pctx.plugins.get("transcriber")
        if transcriber is None:
            logger.info("[TranscribeRunner] Transcriber plugin disabled, skipping")
            return

        await pctx.tracker.update("transcription")

        artifact_dir = pctx.config.get("storage", {}).get(
            "artifact_dir", "/tmp/cerno/audio"
        )
        audio_dir = os.path.join(artifact_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        audio_path = os.path.join(audio_dir, f"{pctx.video.id}.wav")

        await extract_audio(pctx.ctx.file_path, audio_path)

        language = None if pctx.video.language == "auto" else pctx.video.language
        await pctx.tracker.update(
            "transcription",
            description=f"正在转录音频（目标语言: {pctx.video.language}）...",
        )
        result = await transcriber.transcribe(audio_path, language=language)

        pctx.ctx.transcript_full = result.get("full_text", "").strip()
        pctx.ctx.transcript_words = result.get("words", [])

        logger.info(
            "[TranscribeRunner] Done: text=%d chars words=%d",
            len(pctx.ctx.transcript_full), len(pctx.ctx.transcript_words),
        )
