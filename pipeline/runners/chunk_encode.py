"""
pipeline/runners/chunk_encode.py
═══════════════════════════════════════════════════════════
Chunk 编码 runner — 场景内滑动窗口，-c copy + 480p 5fps 预处理 → encode_video。

提取自 pipeline/engine.py:_encode_scene_chunks()
"""

import asyncio
import logging
import os

from pipeline.runners.base import OperationRunner, PipelineContext
from core.repository import bulk_insert_chunks

logger = logging.getLogger(__name__)


class ChunkEncodeRunner(OperationRunner):
    """滑动窗口 chunk 编码执行器 — 自适应窗口 + 两步 FFmpeg。"""

    async def run(self, pctx: PipelineContext) -> None:
        embedder = pctx.shared_embedder or pctx.plugins.get("embedder")
        if embedder is None:
            logger.warning("[ChunkEncodeRunner] No embedder available, skipping")
            return

        scenes = pctx.ctx.scenes
        if not scenes:
            return

        total = len(scenes)
        await pctx.tracker.update("chunk_encode", sub_progress=0.0)
        logger.info("[ChunkEncodeRunner] Encoding chunk embeddings ...")

        temp_dir = os.path.join(
            pctx.config.get("storage", {}).get("artifact_dir", "data/artifacts"),
            "temp_chunks", str(pctx.video.id),
        )
        os.makedirs(temp_dir, exist_ok=True)

        for i, scene in enumerate(scenes):
            await self._encode_scene_chunks(scene, embedder, pctx, temp_dir)
            await pctx.tracker.update("chunk_encode", sub_progress=(i + 1) / total)

        logger.info("[ChunkEncodeRunner] Done")

    async def _encode_scene_chunks(self, scene, embedder, pctx, temp_dir) -> None:
        duration = scene.end_sec - scene.start_sec
        if duration <= 5:
            return

        chunk_rows: list[dict] = []

        # 自适应窗口
        if duration <= 60:
            window_sec = duration / 2.0
            step_sec = window_sec / 2.0
        else:
            window_sec = 30.0
            step_sec = 15.0

        if window_sec >= duration:
            row = await self._encode_one(
                scene.start_sec, scene.end_sec, 0,
                embedder, temp_dir, pctx,
            )
            if row:
                chunk_rows.append(row)
        else:
            idx = 0
            pos = scene.start_sec
            while pos + window_sec <= scene.end_sec:
                row = await self._encode_one(
                    pos, min(pos + window_sec, scene.end_sec), idx,
                    embedder, temp_dir, pctx,
                )
                if row:
                    chunk_rows.append(row)
                    idx += 1
                pos += step_sec

        if chunk_rows:
            async with pctx.db_session_factory() as session:
                await bulk_insert_chunks(session, chunk_rows)
            logger.info(
                "[ChunkEncodeRunner] Encoded %d chunks for scene %d",
                len(chunk_rows), scene.scene_index,
            )

    async def _encode_one(
        self, start: float, end: float, chunk_idx: int,
        embedder, temp_dir, pctx,
    ) -> dict | None:
        clip_dur = end - start
        # Step 1: -c copy 流复制
        raw_path = os.path.join(temp_dir, f"chunk_{chunk_idx}_raw.mp4")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", pctx.ctx.file_path,
            "-t", str(clip_dur),
            "-c", "copy",
            raw_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode != 0 or not os.path.exists(raw_path):
            return None

        # Step 2: 预处理 480p 5fps
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
            emb = await embedder.encode_video(pre_path, fps=1.0, max_frames=32)
        except Exception as e:
            logger.warning(
                "[ChunkEncodeRunner] encode_video failed @ %.1f-%.1f: %s", start, end, e,
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
            "video_id": pctx.video.id,
            "scene_index": scene.scene_index if hasattr(scene, "scene_index") else 0,
            "chunk_index": chunk_idx,
            "start_sec": start,
            "end_sec": end,
            "embedding": emb,
        }
