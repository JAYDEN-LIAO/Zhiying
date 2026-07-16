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
    ):
        self.config = config
        self.db_session_factory = db_session_factory
        self.video = video

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
        """加载算法插件（embedder 除外，由 _encode_frames 延迟加载）。

        embedder（2B ~5GB）与 caption 模型（7B 4bit ~5GB）在 8GB GPU 上
        无法共存，因此 embedder 不在初始化时加载——等 Phase 4 结束后、
        _encode_frames 需要时才加载，此时 caption 模型已释放。
        """
        categories = [
            "transcriber", "segmenter", "detector",
            "ocr", "captioner", "summarizer", "grounding",
        ]
        for cat in categories:
            self.plugins[cat] = await load_plugin(self.config, cat)

    # ──────────────────────────────────────────────────────
    # 入口
    # ──────────────────────────────────────────────────────

    async def run(self) -> None:
        """按阶段顺序执行全流程，根据视频参数开关门控各阶段。

        各阶段门控规则（来自 L2/L3 参数）:
          vision_enabled=OFF  → 跳过关键帧、描述、编码
          audio_enabled=OFF   → 跳过转录、对齐（在 phase1/3 内部检查）
          caption_enabled=OFF → 跳过描述、摘要（摘要依赖描述）
          summary_enabled=OFF → 跳过摘要
          search_index_enabled=OFF → 跳过帧/块/文本编码
        """
        v = self.video  # shorthand

        try:
            await self._set_processing()
            await self.initialize()

            await self._phase1()

            if v.vision_enabled:
                await self._extract_keyframes()
            else:
                logger.info("[Pipeline] vision_enabled=false, skipping keyframe extraction")

            await self._phase3()

            if v.vision_enabled and v.caption_enabled:
                await self._phase4()
                # 释放 caption 模型显存，为后面的 embedder 腾出空间
                cap = self.plugins.get("captioner")
                if hasattr(cap, "unload"):
                    cap.unload()
            else:
                logger.info("[Pipeline] caption_enabled=false, skipping captioning")

            if v.summary_enabled and v.caption_enabled:
                await self._phase5()
            else:
                logger.info("[Pipeline] summary_enabled=false, skipping summarization")

            await self._persist()

            # _encode_frames 在 persist 后单独执行（不影响摘要）
            if v.search_index_enabled and v.vision_enabled:
                try:
                    await self._encode_frames()
                except Exception as e:
                    logger.warning("[Pipeline] Frame/chunk encoding failed: %s", e)
            else:
                logger.info("[Pipeline] search_index_enabled=false, skipping encoding")

            await self.tracker.mark_completed()
            logger.info("[Pipeline] video %s completed", self.video.id)

        except Exception as e:
            logger.exception("[Pipeline] video %s failed: %s", self.video.id, e)
            await self.tracker.mark_failed(str(e))

    async def _load_scenes_from_db(self) -> None:
        """从 DB 加载已有场景数据到 ctx.scenes（增量用）。"""
        from sqlalchemy import select
        from core.models import Scene as SceneModel
        from core.interfaces import Scene as SceneData

        async with self.db_session_factory() as session:
            result = await session.execute(
                select(SceneModel)
                .where(SceneModel.video_id == self.video.id)
                .order_by(SceneModel.scene_index)
            )
            db_scenes = result.scalars().all()

        for s in db_scenes:
            scene = SceneData(
                scene_id=s.scene_index,
                scene_index=s.scene_index,
                start_sec=s.start_sec,
                end_sec=s.end_sec,
                keyframe_path=s.keyframe_path,
                caption=s.caption,
                ocr_text=s.ocr_text,
                aligned_transcript=s.aligned_transcript,
            )
            self.ctx.scenes.append(scene)

        # 填充 prev_caption
        for i in range(1, len(self.ctx.scenes)):
            self.ctx.scenes[i].prev_caption = self.ctx.scenes[i - 1].caption

        logger.info("[Pipeline] Loaded %d scenes from DB for incremental run", len(self.ctx.scenes))

    async def run_incremental(self, added_modalities: set[str]) -> None:
        """增量运行：对已处理完成的视频补跑指定阶段。

        Args:
            added_modalities: {'summary'} / {'search_index'} / {'summary', 'search_index'}
        """
        v = self.video
        need_summary = 'summary' in added_modalities
        need_search = 'search_index' in added_modalities

        try:
            await self._set_processing()
            await self.initialize()
            await self._load_scenes_from_db()

            # ── 补跑摘要 ──
            if need_summary and v.caption_enabled:
                logger.info("[Incremental] Running summary for video %s", self.video.id)
                await self._phase5()

            # ── 补跑搜索索引 ──
            if need_search and v.vision_enabled:
                logger.info("[Incremental] Running search index for video %s", self.video.id)

                # 清理旧编码数据（防重入）
                from sqlalchemy import delete as sa_delete
                from core.models import FrameEmbedding, Chunk
                async with self.db_session_factory() as session:
                    await session.execute(
                        sa_delete(FrameEmbedding).where(FrameEmbedding.video_id == self.video.id)
                    )
                    await session.execute(
                        sa_delete(Chunk).where(Chunk.video_id == self.video.id)
                    )
                    await session.execute(
                        update(Scene)
                        .where(Scene.video_id == self.video.id)
                        .values(text_embedding=None)
                    )
                    await session.commit()

                await self._extract_keyframes()
                await self._encode_frames()

            if need_summary:
                await self._persist_summary_only()

            await self.tracker.mark_completed()
            logger.info("[Incremental] video %s completed", self.video.id)

        except Exception as e:
            logger.exception("[Incremental] video %s failed: %s (reverting to completed)", self.video.id, e)
            # 增量失败不破坏原始数据，恢复为 completed
            async with self.db_session_factory() as session:
                await session.execute(
                    update(Video)
                    .where(Video.id == self.video.id)
                    .values(status=VideoStatus.COMPLETED, error_message=f"Incremental failed: {e}")
                )
                await session.commit()

    async def _persist_summary_only(self) -> None:
        """仅写入摘要（增量用）。"""
        if self.ctx.summary:
            from core.repository import save_video_artifacts
            async with self.db_session_factory() as session:
                await save_video_artifacts(
                    session,
                    self.video.id,
                    summary=self.ctx.summary,
                )

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
        total_scenes = len(scenes)
        for i, scene in enumerate(scenes):
            await self.tracker.update(
                None,
                progress=0.15 + 0.05 * (i / total_scenes),
                description=f"正在抽取第 {i + 1}/{total_scenes} 个场景的关键帧",
            )
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
            # 延迟加载：Phase 4（caption 模型）已结束，GPU 空闲，可加载 embedder
            logger.info("[Pipeline] Lazy-loading embedder for frame encoding ...")
            embedder = await load_plugin(self.config, "embedder")
            if embedder is None:
                return
            self.plugins["embedder"] = embedder

        scenes = self.ctx.scenes
        if not scenes:
            return

        logger.info("[Pipeline] Encoding frame embeddings & chunks ...")

        total_enc = sum(1 for s in scenes if s.keyframes and s.frame_timestamps)
        enc_idx = 0
        for scene in scenes:
            if not scene.keyframes or not scene.frame_timestamps:
                continue

            enc_idx += 1
            await self.tracker.update(
                "completed",
                description=f"正在编码第 {enc_idx}/{total_enc} 个场景的帧向量",
            )

            # ── a. 帧级路：batch 编码（默认 4 帧一批，比逐帧快 2-3x）──
            _BATCH_SIZE = 4
            frame_rows: list[dict] = []
            frame_items = list(zip(scene.frame_timestamps, scene.keyframes))
            _cf_indices = set()
            if scene._caption_frames:
                num_cf = min(len(frame_items), len(scene._caption_frames))
                step = max(1, len(frame_items) // num_cf)
                _cf_indices = {k * step for k in range(num_cf)}

            for i in range(0, len(frame_items), _BATCH_SIZE):
                batch = frame_items[i:i + _BATCH_SIZE]
                batch_frames = [b[1] for b in batch]
                batch_times = [b[0] for b in batch]

                try:
                    embs = await embedder.encode_images_batch(batch_frames)
                except Exception:
                    logger.warning("[Pipeline] Batch encode failed, falling back to single-frame")
                    embs = []
                    for f in batch_frames:
                        try:
                            embs.append(await embedder.encode_image(f))
                        except Exception:
                            embs.append(None)

                for j, (t, emb) in enumerate(zip(batch_times, embs)):
                    if not emb:
                        continue
                    frame_rows.append({
                        "video_id": self.video.id,
                        "scene_index": scene.scene_index,
                        "timestamp_sec": t,
                        "embedding": emb,
                        "is_keyframe": (i + j) in _cf_indices,
                    })
            if frame_rows:
                async with self.db_session_factory() as session:
                    await bulk_insert_frames(session, frame_rows)

            # ── b. chunk 路（由 config pipeline.chunk_encoding 控制开关）──
            chunk_enabled = self.config.get("pipeline", {}).get("chunk_encoding", False)
            if chunk_enabled:
                await self._encode_scene_chunks(scene, embedder)
            else:
                duration = scene.end_sec - scene.start_sec
                if duration > 5:
                    logger.debug(
                        "[Pipeline] Chunk encoding disabled by config, "
                        "skipping scene %d (%.1fs-%.1fs)",
                        scene.scene_index, scene.start_sec, scene.end_sec,
                    )

            # ── c. 文本语义路：encode_text(caption + ocr + transcript) → text_embedding → 持久化 ──
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

        # ---- 4. 保存摘要制品 ----
        if self.ctx.summary:
            async with self.db_session_factory() as session:
                await save_video_artifacts(
                    session,
                    self.video.id,
                    summary=self.ctx.summary,
                )

    async def _encode_scene_chunks(
        self, scene, embedder,
    ) -> None:
        """对单个 scene 执行 chunk 编码（流复制 → 预处理 → encode_video）。

        两步 ffmpeg:
          1. -c copy 流复制截取原始质量片段
          2. 预处理：480p 5fps CRF 23（控制模型输入量，保留足够画质）
        """
        duration = scene.end_sec - scene.start_sec
        if duration <= 5:
            return

        from core.repository import bulk_insert_chunks

        temp_dir = os.path.join(
            self.config.get("storage", {}).get(
                "artifact_dir", "data/artifacts",
            ),
            "temp_chunks", str(self.video.id),
        )
        os.makedirs(temp_dir, exist_ok=True)
        chunk_rows: list[dict] = []

        async def _encode_one(
            start: float, end: float, chunk_idx: int,
        ) -> dict | None:
            clip_dur = end - start
            # Step 1: -c copy 流复制，零质量损失
            raw_path = os.path.join(temp_dir, f"chunk_{chunk_idx}_raw.mp4")
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-ss", str(start),
                "-i", self.ctx.file_path,
                "-t", str(clip_dur),
                "-c", "copy",
                raw_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0 or not os.path.exists(raw_path):
                return None

            # Step 2: 预处理缩放到 480p 5fps（控制模型输入量）
            pre_path = os.path.join(temp_dir, f"chunk_{chunk_idx}.mp4")
            pp_proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", raw_path,
                "-vf", "scale=-2:480,fps=5",
                "-c:v", "libx264", "-crf", "23",
                "-an",
                pre_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await pp_proc.communicate()
            try:
                os.remove(raw_path)
            except OSError:
                pass
            if pp_proc.returncode != 0 or not os.path.exists(pre_path):
                return None

            try:
                emb = await embedder.encode_video(
                    pre_path, fps=1.0, max_frames=32,
                )
            except Exception as e:
                logger.warning(
                    "[Pipeline] Chunk encoding failed @ %.1f-%.1f: %s",
                    start, end, e,
                )
                return None
            finally:
                try:
                    os.remove(pre_path)
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

        # ── 自适应窗口 ──
        # ≤5s: 不切；>5s~≤60s: 窗口=时长/2, 步长=窗口/2; >60s: 窗口=30s, 步长=15s
        if duration <= 60:
            window_sec = duration / 2.0
            step_sec = window_sec / 2.0
        else:
            window_sec = 30.0
            step_sec = 15.0

        if window_sec >= duration:
            row = await _encode_one(scene.start_sec, scene.end_sec, 0)
            if row:
                chunk_rows.append(row)
        else:
            idx = 0
            pos = scene.start_sec
            while pos + window_sec <= scene.end_sec:
                row = await _encode_one(
                    pos, min(pos + window_sec, scene.end_sec), idx,
                )
                if row:
                    chunk_rows.append(row)
                    idx += 1
                pos += step_sec

        if chunk_rows:
            async with self.db_session_factory() as session:
                await bulk_insert_chunks(session, chunk_rows)
            logger.info(
                "[Pipeline] Encoded %d chunks for scene %d",
                len(chunk_rows), scene.scene_index,
            )
