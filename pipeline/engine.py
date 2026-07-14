"""
pipeline/engine.py
═══════════════════════════════════════════════════════════
五阶段认知 Pipeline 编排器。

作为后台任务被 FastAPI 调用（BackgroundTasks.add_task），
通过 PipelineEngine.run() 入口执行全流程。
"""

import asyncio
import logging
import os

import numpy as np

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.interfaces import VideoContext
from core.models import Video, Scene, VideoStatus
from core.status_tracker import StatusTracker
from core.prompt_loader import get_prompt_loader
from core.repository import bulk_insert_scenes, save_video_artifacts
from plugins.factory import load_plugin

logger = logging.getLogger(__name__)


class PipelineEngine:
    """五阶段认知工作流编排器。

    设计原则:
      - 每一阶段依赖前一阶段的产出
      - 各阶段之间通过 VideoContext 传递数据
      - 每阶段完成时调用 StatusTracker 更新进度
    """

    def __init__(
        self,
        config: dict,
        db_session_factory: async_sessionmaker[AsyncSession],
        video: Video,
        shared_embedder=None,
    ):
        self.config = config
        self.db_session_factory = db_session_factory
        self.video = video
        self.shared_embedder = shared_embedder

        self.tracker = StatusTracker(
            video_id=str(video.id),
            db_session_factory=db_session_factory,
        )
        self.ctx = VideoContext(
            video_id=str(video.id),
            file_path=video.file_path,
        )
        self.prompt_loader = get_prompt_loader()
        self.plugins: dict[str, object] = {}

    # ──────────────────────────────────────────────────────
    # 插件加载
    # ──────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """加载所有 9 类算法插件（可能为 None=被禁用）。

        若提供了共享 embedder（由 app.state 统一管理），
        则跳过 load_plugin 直接复用，避免每视频重新加载 4GB 模型。
        """
        categories = [
            "qc", "transcriber", "segmenter", "detector",
            "ocr", "captioner", "embedder", "summarizer", "grounding",
        ]
        for cat in categories:
            if cat == "embedder" and self.shared_embedder is not None:
                self.plugins["embedder"] = self.shared_embedder
                continue
            self.plugins[cat] = await load_plugin(self.config, cat)

    # ──────────────────────────────────────────────────────
    # 入口
    # ──────────────────────────────────────────────────────

    async def run(self) -> None:
        """按阶段顺序执行全流程。

        Phase 2（检测/OCR）当前跳过，Demo 阶段仅启用:
          Phase 1 → 关键帧抽取 → Phase 3 → Phase 4 → Phase 5 → Persist
        """
        try:
            await self._set_processing()
            await self.initialize()

            await self._phase1()
            await self._extract_keyframes()
            await self._phase3()
            await self._phase4()
            await self._phase5()
            await self._persist()

            await self.tracker.mark_completed()
            logger.info("[Pipeline] video %s completed", self.video.id)

            # 帧和 chunk 编码（纯搜索用，不影响摘要，完成后执行）
            try:
                await self._encode_frames()
            except Exception as e:
                logger.warning("[Pipeline] Frame/chunk encoding failed: %s", e)

        except Exception as e:
            logger.exception("[Pipeline] video %s failed: %s", self.video.id, e)
            await self.tracker.mark_failed(str(e))

    async def _set_processing(self) -> None:
        """修改视频状态为 processing。"""
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video.id)
                .values(status=VideoStatus.PROCESSING)
            )
            await session.commit()

    # ──────────────────────────────────────────────────────
    # 各阶段
    # ──────────────────────────────────────────────────────

    async def _phase1(self) -> None:
        """Phase 1: 前置质检 + 音频抽取 + 镜头分割。"""
        from pipeline.phase1_qc import Phase1QC
        engine = Phase1QC(
            ctx=self.ctx,
            plugins=self.plugins,
            config=self.config,
            tracker=self.tracker,
            video=self.video,
        )
        await engine.execute()

    async def _extract_keyframes(self) -> None:
        """关键帧抽取 — Phase 1 后、Phase 4 前执行。

        按 1fps 逐帧抽取，全部存入 scene 帧池。
        三条消费链路复用同一批帧：
          ① 帧级路 → encode_image → frame_embeddings 表
          ② chunk路 → encode_video → chunks 表
          ③ VLM 路 → 选 3-7 帧 → caption
        """
        from utils.video_util import extract_keyframe_to_memory

        scenes = self.ctx.scenes
        if not scenes:
            logger.info("[Pipeline] No scenes to extract keyframes from")
            return

        logger.info("[Pipeline] Extracting frame pool @ 1fps ...")
        for i, scene in enumerate(scenes):
            duration = scene.end_sec - scene.start_sec

            # ── 1fps 逐帧抽取 ──
            timestamps = list(range(
                int(scene.start_sec), int(scene.end_sec),
            ))
            if not timestamps:
                timestamps = [scene.start_sec + 0.1]

            frames: list[np.ndarray] = []
            frame_times: list[float] = []
            for t in timestamps:
                try:
                    frame = await extract_keyframe_to_memory(
                        self.ctx.file_path, t,
                    )
                    if frame is not None:
                        frames.append(frame)
                        frame_times.append(t)
                except Exception as e:
                    logger.warning(
                        "[Pipeline] Frame extraction failed @ %.1f: %s", t, e,
                    )

            if not frames:
                continue

            scene.keyframes = frames
            scene.frame_timestamps = frame_times
            scene.keyframe = frames[len(frames) // 2]  # 中点帧

            # ── VLM caption 代表帧（均匀选 3-7 帧） ──
            num_cf = min(len(frames), 7)
            step = max(1, len(frames) // num_cf)
            scene._caption_frames = [frames[k * step] for k in range(num_cf)]

            # ── 保存 scene 缩略图 ──
            try:
                from PIL import Image
                thumb_dir = os.path.join(
                    self.config.get("storage", {}).get(
                        "artifact_dir", "data/artifacts",
                    ),
                    "thumbnails", str(self.video.id),
                )
                os.makedirs(thumb_dir, exist_ok=True)
                thumb_path = os.path.join(
                    thumb_dir, f"scene_{scene.scene_index:04d}.jpg",
                )
                Image.fromarray(scene.keyframe).save(thumb_path, "JPEG", quality=80)
                scene.keyframe_path = thumb_path
            except Exception as e:
                logger.warning(
                    "[Pipeline] Thumbnail save failed for scene %d: %s", i, e,
                )

        total_frames = sum(len(s.keyframes) for s in scenes if s.keyframes)
        logger.info("[Pipeline] Frame pool: %d frames @ 1fps", total_frames)

    async def _encode_frames(self) -> None:
        """帧池编码 — 帧级路 + chunk 路。

        在 Phase 4（VLM caption）之后执行，
        复用了 _extract_keyframes 的帧池。
        """
        from core.repository import bulk_insert_frames, bulk_insert_chunks

        embedder = self.plugins.get("embedder")
        if embedder is None:
            return

        scenes = self.ctx.scenes
        if not scenes:
            return

        logger.info("[Pipeline] Encoding frame embeddings & chunks ...")

        for scene in scenes:
            if not scene.keyframes or not scene.frame_timestamps:
                continue

            # ── a. 帧级路：逐帧 encode_image ──
            frame_rows: list[dict] = []
            for t, frame in zip(scene.frame_timestamps, scene.keyframes):
                emb = await embedder.encode_image(frame)
                if not emb:
                    continue
                frame_rows.append({
                    "video_id": self.video.id,
                    "scene_index": scene.scene_index,
                    "timestamp_sec": t,
                    "embedding": emb,
                    "is_keyframe": any(
                        frame is cf for cf in (scene._caption_frames or [])
                    ),
                })
            if frame_rows:
                async with self.db_session_factory() as session:
                    await bulk_insert_frames(session, frame_rows)

            # ── b. chunk 路：原生视频编码（通过 temp clip + process_vision_info）──
            duration = scene.end_sec - scene.start_sec
            chunk_rows: list[dict] = []

            async def _encode_chunk_clip(
                start: float, end: float, chunk_idx: int,
            ) -> dict | None:
                """创建 temp clip → encode_video → 清理 → 返回 chunk row。"""
                clip_dur = end - start
                if clip_dur < 5:
                    return None

                temp_dir = os.path.join(
                    self.config.get("storage", {}).get(
                        "artifact_dir", "data/artifacts",
                    ),
                    "temp_chunks", str(self.video.id),
                )
                os.makedirs(temp_dir, exist_ok=True)
                clip_path = os.path.join(
                    temp_dir, f"chunk_{chunk_idx}.mp4",
                )

                # ffmpeg 截取片段（-ss 在 -i 之后 → 精确定位，避免关键帧边界花屏）
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y",
                    "-i", self.ctx.file_path,
                    "-ss", str(start),
                    "-t", str(clip_dur),
                    "-vf", "scale=-2:480,fps=2",  # 480p 2fps — chunk 向量质量和效率平衡
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    "-an",
                    clip_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()

                if proc.returncode != 0 or not os.path.exists(clip_path):
                    return None

                try:
                    emb = await embedder.encode_video(
                        clip_path, fps=1.0, max_frames=20,
                    )
                except Exception as e:
                    logger.warning(
                        "[Pipeline] Chunk encoding failed @ %.1f-%.1f: %s",
                        start, end, e,
                    )
                    return None
                finally:
                    try:
                        os.remove(clip_path)
                    except OSError:
                        pass

                if not emb:
                    return None
                return {
                    "video_id": self.video.id,
                    "scene_index": scene.scene_index,
                    "chunk_index": chunk_idx,
                    "start_sec": start,
                    "end_sec": end,
                    "embedding": emb,
                }

            # ── b. chunk 路：自适应窗口 ──
            # ≤5s: 不切；>5s~≤60s: 窗口=时长/2, 步长=窗口/2; >60s: 窗口=30s, 步长=15s
            if duration > 5:
                if duration <= 60:
                    window_sec = duration / 2.0
                    step_sec = window_sec / 2.0
                else:
                    window_sec = 30.0
                    step_sec = 15.0

                if window_sec >= duration:
                    # 仅 1 个窗口
                    row = await _encode_chunk_clip(
                        scene.start_sec, scene.end_sec, 0,
                    )
                    if row:
                        chunk_rows.append(row)
                else:
                    idx = 0
                    pos = scene.start_sec
                    while pos + window_sec <= scene.end_sec:
                        row = await _encode_chunk_clip(
                            pos, min(pos + window_sec, scene.end_sec), idx,
                        )
                        if row:
                            chunk_rows.append(row)
                            idx += 1
                        pos += step_sec

            if chunk_rows:
                async with self.db_session_factory() as session:
                    await bulk_insert_chunks(session, chunk_rows)

            # ── c. 文本语义路：encode_text(caption) → text_embedding → 持久化 ──
            if scene.caption:
                text_emb = await embedder.encode_text(scene.caption)
                if text_emb:
                    scene.text_embedding = text_emb
                    async with self.db_session_factory() as session:
                        await session.execute(
                            update(Scene)
                            .where(
                                Scene.video_id == self.video.id,
                                Scene.scene_index == scene.scene_index,
                            )
                            .values(text_embedding=text_emb)
                        )
                        await session.commit()

        logger.info("[Pipeline] Frame encoding done")

    async def _phase3(self) -> None:
        """Phase 3: 模态交叉对齐（转录 → 场景）。"""
        from pipeline.phase3_alignment import Phase3Alignment
        engine = Phase3Alignment(
            ctx=self.ctx,
            plugins=self.plugins,
            config=self.config,
            tracker=self.tracker,
        )
        await engine.execute()

    async def _phase4(self) -> None:
        """Phase 4: 记忆窗口深度描述 + 向量编码。"""
        try:
            from pipeline.phase4_caption import Phase4Caption
        except ImportError:
            logger.warning("[Pipeline] Phase4Caption not implemented, skipping")
            return
        engine = Phase4Caption(
            ctx=self.ctx,
            plugins=self.plugins,
            config=self.config,
            tracker=self.tracker,
            prompt_loader=self.prompt_loader,
        )
        await engine.execute()

    async def _phase5(self) -> None:
        """Phase 5: 全局 LLM 摘要。"""
        try:
            from pipeline.phase5_summary import Phase5Summary
        except ImportError:
            logger.warning("[Pipeline] Phase5Summary not implemented, skipping")
            return
        engine = Phase5Summary(
            ctx=self.ctx,
            plugins=self.plugins,
            config=self.config,
            tracker=self.tracker,
            prompt_loader=self.prompt_loader,
        )
        await engine.execute()

    # ──────────────────────────────────────────────────────
    # 持久化
    # ──────────────────────────────────────────────────────

    async def _persist(self) -> None:
        """将 VideoContext 中的数据写入数据库。

        使用 repository 函数（bulk_insert_scenes / save_video_artifacts）
        和直接 ORM add（transcript）分步写入，每步独立提交。
        """
        # ---- 1. 视频字段（duration） ----
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video.id)
                .values(duration=self.ctx.duration)
            )
            await session.commit()

        # ---- 2. 批量写入 scenes ----
        if self.ctx.scenes:
            scenes_data = [
                {
                    "scene_index": s.scene_index,
                    "start_sec": s.start_sec,
                    "end_sec": s.end_sec,
                    "keyframe_path": s.keyframe_path,
                    "embedding": s.embedding,
                    "text_embedding": s.text_embedding,
                    "ocr_text": s.ocr_text,
                    "aligned_transcript": s.aligned_transcript,
                    "caption": s.caption,
                    "prev_caption": s.prev_caption,
                    "entities": s.entities,
                }
                for s in self.ctx.scenes
            ]
            async with self.db_session_factory() as session:
                await bulk_insert_scenes(session, self.video.id, scenes_data)

        # ---- 3. 写入 transcript ----
        if self.ctx.transcript_full:
            from core.models import Transcript as TranscriptModel
            async with self.db_session_factory() as session:
                session.add(TranscriptModel(
                    video_id=self.video.id,
                    full_text=self.ctx.transcript_full,
                    words=self.ctx.transcript_words,
                ))
                await session.commit()

        # ---- 4. 保存 QC 结果与摘要制品 ----
        if self.ctx.qc_result or self.ctx.summary:
            async with self.db_session_factory() as session:
                await save_video_artifacts(
                    session,
                    self.video.id,
                    qc_result=self.ctx.qc_result or None,
                    summary=self.ctx.summary,
                )
