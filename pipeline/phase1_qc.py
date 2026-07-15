"""
pipeline/phase1_qc.py
═══════════════════════════════════════════════════════════
Phase 1: 前置拆解。

执行顺序:
  1. 音频抽取 + 语音转录
  2. 镜头分割 → 填充 Scene 列表
"""

import asyncio
import json
import logging
import os
import shutil

from core.interfaces import VideoContext, Scene as SceneData
from core.status_tracker import StatusTracker
from core.models import Video
from utils.video_util import extract_audio

logger = logging.getLogger(__name__)


class Phase1QC:
    """Phase 1 执行器 — 音频抽取 / 镜头分割。"""

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
        await self._get_duration()
        await self._run_audio_transcription()
        await self._run_segmentation()

    async def _get_duration(self) -> None:
        """通过 ffprobe 获取视频时长。"""
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            proc = await asyncio.create_subprocess_exec(
                ffprobe, "-v", "quiet", "-print_format", "json",
                "-show_format", self.ctx.file_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if stdout:
                info = json.loads(stdout)
                self.ctx.duration = float(info["format"]["duration"])

    # ──────────────────────────────────────────────────────
    # a. 音频抽取 + 转录
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
