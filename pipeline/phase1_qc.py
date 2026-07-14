"""
pipeline/phase1_qc.py
═══════════════════════════════════════════════════════════
Phase 1: 前置质检与拆解。

执行顺序:
  1. QC 检测（黑屏 / 静音 / 过曝）
  2. 音频抽取 + 语音转录
  3. 镜头分割 → 填充 Scene 列表
"""

import asyncio
import logging
import os

from core.interfaces import VideoContext, Scene as SceneData
from core.status_tracker import StatusTracker
from core.models import Video
from utils.video_util import extract_audio

logger = logging.getLogger(__name__)


class Phase1QC:
    """Phase 1 执行器 — 质检 / 音频 / 分割。"""

    def __init__(
        self,
        ctx: VideoContext,
        plugins: dict,
        config: dict,
        tracker: StatusTracker,
        video: Video,
    ):
        self.ctx = ctx
        self.plugins = plugins
        self.config = config
        self.tracker = tracker
        self.video = video

    async def execute(self) -> None:
        """执行 Phase 1 全流程。"""
        await self._run_qc()
        await self._run_audio_transcription()
        await self._run_segmentation()

    # ──────────────────────────────────────────────────────
    # a. 质量检测
    # ──────────────────────────────────────────────────────

    async def _run_qc(self) -> None:
        """QC 检测：黑屏 / 静音 / 过曝。"""
        await self.tracker.update("phase_1_qc")
        qc = self.plugins.get("qc")
        if qc is None:
            logger.info("[Phase1] QC plugin disabled, skipping")
            return

        result = await qc.check(self.ctx)
        self.ctx.qc_result = result
        self.ctx.duration = result.get("estimated_duration")

        black_count = len(result.get("black_segments", []))
        silent_count = len(result.get("silent_segments", []))
        await self.tracker.update("phase_1_qc", description=f"质检完成: 检测到 {black_count} 段黑屏、{silent_count} 段静音")

        logger.info(
            "[Phase1] QC done: duration=%.1fs black=%d silent=%d valid=%s",
            self.ctx.duration or 0,
            black_count, silent_count,
            result.get("is_valid"),
        )

    # ──────────────────────────────────────────────────────
    # b. 音频抽取 + 转录
    # ──────────────────────────────────────────────────────

    async def _run_audio_transcription(self) -> None:
        """抽取音频并执行语音转录。"""
        if not self.video.audio_enabled:
            logger.info("[Phase1] Audio transcription disabled by config")
            return

        transcriber = self.plugins.get("transcriber")
        if transcriber is None:
            logger.info("[Phase1] Transcriber plugin disabled, skipping")
            return

        await self.tracker.update("phase_1_audio")

        # 确定音频临时路径
        artifact_dir = self.config.get("storage", {}).get(
            "artifact_dir", "/tmp/cerno/audio"
        )
        audio_dir = os.path.join(artifact_dir, "audio")
        os.makedirs(audio_dir, exist_ok=True)
        audio_path = os.path.join(audio_dir, f"{self.video.id}.wav")

        # 抽取音频（16kHz 单声道 WAV）
        await extract_audio(self.ctx.file_path, audio_path)

        # 转录
        language = None if self.video.language == "auto" else self.video.language
        await self.tracker.update("phase_1_audio", description=f"正在转录音频（目标语言: {self.video.language}）...")
        result = await transcriber.transcribe(audio_path, language=language)

        self.ctx.transcript_full = result.get("full_text", "").strip()
        self.ctx.transcript_words = result.get("words", [])

        text_len = len(self.ctx.transcript_full)
        word_count = len(self.ctx.transcript_words)
        logger.info(
            "[Phase1] Transcription done: text=%d chars words=%d lang=%s",
            text_len, word_count, result.get("language", "unknown"),
        )

    # ──────────────────────────────────────────────────────
    # c. 镜头分割
    # ──────────────────────────────────────────────────────

    async def _run_segmentation(self) -> None:
        """镜头分割 → 填充 ctx.scenes。"""
        await self.tracker.update("phase_1_segment")
        segmenter = self.plugins.get("segmenter")
        if segmenter is None:
            logger.info("[Phase1] Segmenter plugin disabled, skipping")
            return

        sample_fps = self.config.get("pipeline", {}).get("sample_fps", 1.0)
        raw_scenes = await segmenter.segment(
            self.ctx.file_path, sample_fps=sample_fps,
        )

        # 转换为 dataclass Scene 列表
        scenes: list[SceneData] = []
        for raw in raw_scenes:
            scene = SceneData(
                scene_id=len(scenes),       # 临时 ID，DB 写时会用自增主键
                scene_index=raw.get("scene_index", len(scenes)),
                start_sec=raw.get("start_sec", 0.0),
                end_sec=raw.get("end_sec", 0.0),
                keyframe=raw.get("keyframe"),
            )
            scenes.append(scene)

        self.ctx.scenes = scenes
        await self.tracker.update("phase_1_segment", description=f"镜头分割完成: 共 {len(scenes)} 个场景")
        logger.info("[Phase1] Segmentation done: %d scenes", len(scenes))
