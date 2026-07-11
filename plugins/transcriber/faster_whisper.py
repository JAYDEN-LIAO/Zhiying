"""
plugins/transcriber/faster_whisper.py
═══════════════════════════════════════════════════════════
faster-whisper 语音转录插件。

模型推理（model.transcribe）是同步 CPU/GPU 密集型调用，
必须使用 asyncio.to_thread() 包裹，避免阻塞事件循环。
"""

import asyncio
import logging

from core.interfaces import BaseTranscriber
from core.exceptions import PluginLoadError

logger = logging.getLogger(__name__)


class FasterWhisperTranscriber(BaseTranscriber):
    """基于 faster-whisper 的语音转录实现。

    Args:
        model_path: 模型名称或路径（如 "systran/faster-whisper-tiny"）。
        device: 推理设备 ("cpu" / "cuda")。
        compute_type: 精度类型 ("int8" / "float16" / "float32")。
    """

    def __init__(
        self,
        model_path: str = "systran/faster-whisper-tiny",
        device: str = "cpu",
        compute_type: str = "int8",
        **kwargs,
    ):
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise PluginLoadError(
                "faster-whisper package not installed. "
                "Run: pip install faster-whisper"
            ) from e

        self._model = WhisperModel(
            model_path,
            device=device,
            compute_type=compute_type,
        )
        self.model_path = model_path
        logger.info(
            "[FasterWhisper] Loaded model=%s device=%s compute=%s",
            model_path, device, compute_type,
        )

    async def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
    ) -> dict:
        """对音频文件执行语音识别。

        Args:
            audio_path: WAV 音频路径（16kHz 单声道）。
            language: 语言代码（None=自动检测, "zh"/"en"/"ja" 等）。

        Returns:
            {
                "full_text": str,
                "language": str,
                "duration": float,
                "words": [{"word": str, "start": float, "end": float, "confidence": float}],
            }
        """
        try:
            segments, info = await asyncio.to_thread(
                self._sync_transcribe,
                audio_path,
                language,
            )
        except Exception as e:
            logger.exception("[FasterWhisper] Transcription failed")
            raise

        duration = info.duration if info else 0.0
        detected_lang = info.language if info else (language or "unknown")

        full_text_parts: list[str] = []
        all_words: list[dict] = []

        for seg in segments:
            full_text_parts.append(seg.text)
            if seg.words:
                for w in seg.words:
                    all_words.append({
                        "word": w.word,
                        "start": w.start,
                        "end": w.end,
                        "confidence": w.probability,
                    })

        result = {
            "full_text": " ".join(full_text_parts).strip(),
            "language": detected_lang,
            "duration": duration,
            "words": all_words,
        }

        logger.info(
            "[FasterWhisper] Transcribed: lang=%s duration=%.1fs words=%d",
            detected_lang, duration, len(all_words),
        )
        return result

    def _sync_transcribe(self, audio_path: str, language: str | None):
        """同步转录调用 — 在线程池中执行。"""
        return self._model.transcribe(
            audio_path,
            language=language,
            word_timestamps=True,
            vad_filter=True,
        )
