"""
pipeline/runners/duration.py
═══════════════════════════════════════════════════════════
视频时长探测 runner — 通过 ffprobe 获取时长。

提取自 pipeline/phase1_qc.py:_get_duration()
"""

import asyncio
import json
import logging
import shutil

from pipeline.runners.base import OperationRunner, PipelineContext

logger = logging.getLogger(__name__)


class DurationRunner(OperationRunner):
    """ffprobe 时长探测执行器。"""

    async def run(self, pctx: PipelineContext) -> None:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            logger.warning("[DurationRunner] ffprobe not found, skipping")
            return

        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", pctx.ctx.file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if stdout:
            info = json.loads(stdout)
            pctx.ctx.duration = float(info["format"]["duration"])
            logger.info("[DurationRunner] Duration: %.1fs", pctx.ctx.duration)
