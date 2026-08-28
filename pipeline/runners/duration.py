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


def _parse_hms(value: str) -> float | None:
    """解析 'HH:MM:SS.mmm' 形式的时长字符串（部分封装把时长写进 stream tag）。"""
    parts = value.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = (float(p) for p in parts)
        return h * 3600 + m * 60 + s
    except ValueError:
        return None


def extract_duration(info: dict) -> float | None:
    """多级回退提取时长：format.duration → video stream.duration → stream tag。

    返回 None 表示所有来源都拿不到时长（文件损坏/未完成写入/特殊封装），
    调用方应给出清晰错误而非断言 `format.duration` 必然存在。
    """
    fmt = info.get("format") or {}
    raw = fmt.get("duration")
    if raw:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass

    for s in info.get("streams") or []:
        if s.get("codec_type") != "video":
            continue
        raw = s.get("duration")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
        raw = (s.get("tags") or {}).get("DURATION")
        if raw:
            parsed = _parse_hms(raw)
            if parsed is not None:
                return parsed

    return None


class DurationRunner(OperationRunner):
    """ffprobe 时长探测执行器。"""

    async def run(self, pctx: PipelineContext) -> None:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            logger.warning("[DurationRunner] ffprobe not found, skipping")
            return

        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", pctx.ctx.file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if not stdout:
            # ffprobe 整段失败（文件缺失/不可读）——静默放行会让下游拿 None 时长崩出更隐晦的错
            raise RuntimeError(f"无法读取视频文件（ffprobe 无输出）：{pctx.ctx.file_path}")

        try:
            info = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"ffprobe 输出解析失败，文件可能损坏：{pctx.ctx.file_path}"
            ) from e

        duration = extract_duration(info)
        if duration is None:
            raise RuntimeError(
                "无法确定视频时长：容器与流均未提供 duration，文件可能损坏或未完成写入。"
                "常见于 NVR 录像导出、中断下载——请检查源文件后重新上传。"
            )

        # 媒体流首帧 PTS（format.start_time）。非 0 时管道时间戳必须平移到这里，
        # 否则与浏览器 currentTime（媒体时间轴）错位 → 检测框/搜索跳转整体偏移一个 start_time。
        # clamp 负值/NaN → 0（负 start_time 的媒体时间轴无一致映射，保守按 0 处理）。
        start_time = 0.0
        fmt = info.get("format") or {}
        raw_st = fmt.get("start_time")
        if raw_st:
            try:
                st = float(raw_st)
                if st >= 0:
                    start_time = st
            except (TypeError, ValueError):
                start_time = 0.0

        pctx.ctx.duration = duration
        pctx.ctx.start_time = start_time
        logger.info("[DurationRunner] Duration: %.1fs (start_time=%.3fs)", duration, start_time)
        if pctx.log:
            await pctx.log(f"视频时长：{duration:.1f}s")
