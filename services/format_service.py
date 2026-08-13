"""
services/format_service.py
═══════════════════════════════════════════════════════════
视频格式兼容服务 — 容器标准化 + 编码代理转码。

所有 FFmpeg/FFprobe 调用均通过 asyncio.create_subprocess_exec 异步执行。
"""

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config_loader import load_config
from core.models import Video
from core.schemas import FormatInfo

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 浏览器原生兼容格式查找表
# ═══════════════════════════════════════════════════════════
# ASSUMPTION: 以下兼容性表基于 MDN 文档。每种组合需在目标浏览器中用 canPlayType() 实测验证。
# 验证清单见 docs/format-support-plan.md §15.4 待验证项 P1-P5。

_BROWSER_NATIVE_FORMATS = frozenset({
    ("mp4", "h264", "aac"),
    ("mp4", "h264", "mp3"),
    ("mp4", "h264", "none"),       # 静音视频
    ("webm", "vp9", "opus"),
    ("webm", "vp9", "vorbis"),
    ("webm", "vp9", "none"),
    ("webm", "av1", "opus"),
    ("webm", "av1", "none"),
    ("ogg", "theora", "vorbis"),
    ("ogg", "theora", "none"),
})

# 浏览器兼容的音频编码（在 MP4 容器中）
_BROWSER_SAFE_AUDIO = frozenset({"aac", "mp3", "none"})


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class StreamTarget:
    """视频流路由决策结果。"""
    file_path: str
    media_type: str
    source: str  # "original" | "remuxed" | "proxy"


# ═══════════════════════════════════════════════════════════
# FormatService
# ═══════════════════════════════════════════════════════════

class FormatService:
    """视频格式探测、容器标准化、编码代理转码。

    所有重操作（ffprobe/ffmpeg）通过 asyncio subprocess 异步执行。
    """

    def __init__(self, config: dict, db_session_factory: async_sessionmaker[AsyncSession]):
        self.config = config
        self.db_session_factory = db_session_factory

    @property
    def _video_dir(self) -> str:
        """视频目录（动态读取，设置页改存储路径后 remux/proxy 即时落新路径）。"""
        return load_config().get("storage", {}).get("video_dir", "data/videos")

    # ── 探测 ─────────────────────────────────────────────

    async def probe(self, video_path: str) -> FormatInfo:
        """ffprobe 异步探测视频格式信息。

        Raises:
            FileNotFoundError: 文件不存在。
            RuntimeError: ffprobe 失败（残缺文件/加密等）。
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode(errors="replace")[:500]
            raise RuntimeError(
                f"ffprobe failed (code {proc.returncode}): {error_msg}"
            )

        data = json.loads(stdout.decode())

        # 提取视频流和音频流
        video_stream = None
        audio_stream = None
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and video_stream is None:
                video_stream = s
            elif s.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = s

        if video_stream is None:
            raise ValueError("No video stream found — audio-only files are not supported")

        fmt = data.get("format", {})

        return FormatInfo(
            container_format=self._classify_container(fmt.get("format_name", "")),
            video_codec=self._classify_codec(video_stream.get("codec_name", "")),
            audio_codec=audio_stream.get("codec_name") if audio_stream else None,
            has_audio=audio_stream is not None,
            width=video_stream.get("width"),
            height=video_stream.get("height"),
            duration=float(fmt.get("duration", 0)) if fmt.get("duration") else None,
            bit_rate=int(fmt.get("bit_rate", 0)) if fmt.get("bit_rate") else None,
            frame_rate=self._parse_frame_rate(video_stream),
        )

    # ── 分类辅助函数（委托给共享的 utils.metadata 实现）───

    @staticmethod
    def _classify_container(raw: str) -> str:
        """将 ffprobe format_name 归一化为简短标识。"""
        from utils.metadata import classify_container
        return classify_container(raw) or raw

    @staticmethod
    def _classify_codec(raw: str) -> str:
        """将 ffprobe codec_name 归一化为简短标识。"""
        from utils.metadata import classify_codec
        return classify_codec(raw) or raw

    @staticmethod
    def _parse_frame_rate(stream: dict) -> float | None:
        """从 ffprobe stream 信息中解析帧率。"""
        rfr = stream.get("r_frame_rate", "")
        if rfr and "/" in rfr:
            try:
                num, den = rfr.split("/")
                den_f = float(den)
                if den_f != 0:
                    return float(num) / den_f
            except (ValueError, ZeroDivisionError):
                pass
        avg = stream.get("avg_frame_rate", "")
        if avg and "/" in avg:
            try:
                num, den = avg.split("/")
                den_f = float(den)
                if den_f != 0:
                    return float(num) / den_f
            except (ValueError, ZeroDivisionError):
                pass
        return None

    # ── 浏览器原生格式检测 ───────────────────────────────

    @staticmethod
    def _is_browser_native(info: FormatInfo) -> bool:
        """判断容器+编码+音频组合是否浏览器原生支持，无需任何处理。

        ASSUMPTION: 兼容性表基于 MDN 文档。每种组合需在目标浏览器实测验证。
        """
        audio_key = info.audio_codec if info.has_audio else "none"
        return (info.container_format, info.video_codec, audio_key) in _BROWSER_NATIVE_FORMATS

    @staticmethod
    def _needs_audio_transcode(info: FormatInfo) -> bool:
        """判断音频编码在 MP4 容器中是否需要转为 AAC。"""
        if not info.has_audio:
            return False
        return info.audio_codec not in _BROWSER_SAFE_AUDIO

    # ── 容器标准化 (Remux) ───────────────────────────────

    async def remux_to_mp4(
        self, video_path: str, video_id: uuid.UUID, info: FormatInfo | None = None,
    ) -> str | None:
        """流复制 remux 到 MP4 容器，音频非兼容时同步转 AAC 128k。

        Args:
            info: 已探测的 FormatInfo（可选，避免重复 probe）。

        Returns:
            remux 后文件路径，或 None（无需 remux）。
        """
        output_path = os.path.join(self._video_dir, f"{video_id}_remuxed.mp4")

        # 如果 remux 文件已存在 → 跳过
        if os.path.exists(output_path):
            logger.info("[FormatService] Remuxed file exists, skipping: %s", output_path)
            return output_path

        # 获取格式信息（未提供则探测）
        if info is None:
            info = await self.probe(video_path)

        # 同步转音频参数
        if self._needs_audio_transcode(info):
            audio_args = ["-c:a", "aac", "-b:a", "128k"]
            logger.info("[FormatService] Remux + audio transcode to AAC: %s", video_path)
        else:
            audio_args = ["-c:a", "copy"]
            logger.info("[FormatService] Remux (stream copy): %s", video_path)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", video_path,
            "-c:v", "copy",
            *audio_args,
            "-movflags", "+faststart",
            "-map", "0:v:0",         # 第一个视频流
            "-map", "0:a:0?",        # 第一个音频流（可选）
            output_path,
        ]

        logger.info("[FFmpeg] remux: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode(errors="replace")[:500]
            logger.error("[FormatService] Remux failed: %s", error_msg)
            # 标记错误到 DB
            await self._update_format_error(video_id, f"Remux failed: {error_msg}")
            return None

        # 验证 remux 输出
        try:
            await self.probe(output_path)
        except Exception as e:
            logger.error("[FormatService] Remuxed file unreadable: %s", e)
            await self._update_format_error(video_id, f"Remux validation failed: {e}")
            return None

        logger.info("[FormatService] Remux complete: %s", output_path)
        return output_path

    # ── 编码代理转码 (Proxy) ─────────────────────────────

    async def transcode_proxy(
        self, video_path: str, video_id: uuid.UUID,
        info: FormatInfo | None = None,
    ) -> str | None:
        """NVENC H.264 代理转码，异步执行，持续更新 progress。

        Args:
            info: 已探测的 FormatInfo（避免重复 probe）。

        Returns:
            proxy 文件路径，或 None（转码失败/已降级）。
        """
        output_path = os.path.join(self._video_dir, f"{video_id}_proxy.mp4")

        # 已存在 → 跳过
        if os.path.exists(output_path):
            logger.info("[FormatService] Proxy file exists, skipping: %s", output_path)
            await self._update_proxy_status(video_id, "ready", 1.0, output_path)
            return output_path

        await self._update_proxy_status(video_id, "processing", 0.0)

        # 获取视频时长用于进度计算
        duration = info.duration if info and info.duration else 0.0

        # 检查 NVENC 可用性
        nvenc_available = await self._check_nvenc()
        if nvenc_available:
            cmd = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-c:v", "h264_nvenc",
                "-preset", "p4",
                "-cq", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                "-progress", "pipe:1",
                "-nostats",
                output_path,
            ]
        else:
            logger.warning("[FormatService] NVENC not available, falling back to CPU x264")
            cmd = [
                "ffmpeg",
                "-y",
                "-i", video_path,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                "-progress", "pipe:1",
                "-nostats",
                output_path,
            ]

        logger.info("[FFmpeg] proxy transcode: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # 异步读取 progress 输出（独占 stdout）
        progress_task = asyncio.create_task(
            self._read_transcode_progress(proc.stdout, video_id, duration)
        )
        # 单独读取 stderr（避免 communicate() 与 progress reader 抢 stdout）
        stderr_task = asyncio.create_task(proc.stderr.read())

        await proc.wait()
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass
        stderr_bytes = await stderr_task

        if proc.returncode != 0:
            error_msg = stderr_bytes.decode(errors="replace")[:500]
            logger.error("[FormatService] Proxy transcode failed: %s", error_msg)
            await self._update_proxy_status(video_id, "failed", 0.0)
            return None

        await self._update_proxy_status(video_id, "ready", 1.0, output_path)
        logger.info("[FormatService] Proxy complete: %s", output_path)
        return output_path

    async def _read_transcode_progress(
        self, stdout: asyncio.StreamReader, video_id: uuid.UUID, duration: float,
    ) -> None:
        """解析 ffmpeg -progress pipe:1 输出，更新 proxy_progress。"""
        last_update = 0.0
        while True:
            try:
                line = await asyncio.wait_for(stdout.readline(), timeout=10.0)
            except asyncio.TimeoutError:
                continue
            if not line:
                break

            text = line.decode(errors="replace").strip()
            if text.startswith("out_time_us="):
                try:
                    us = int(text.split("=")[1])
                    sec = us / 1_000_000.0
                    if duration > 0:
                        progress = min(sec / duration, 0.99)
                        # 仅每 5% 或每 30s 更新一次 DB
                        if progress - last_update >= 0.05:
                            await self._update_proxy_status(video_id, "processing", progress)
                            last_update = progress
                except (ValueError, IndexError):
                    pass

    async def _check_nvenc(self) -> bool:
        """检查 h264_nvenc 编码器是否可用。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-encoders",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            return b"h264_nvenc" in stdout
        except Exception:
            return False

    # ── 流媒体路由 ──────────────────────────────────────

    async def get_stream_target(
        self, video_id: uuid.UUID, hevc_ok: bool,
    ) -> StreamTarget | None:
        """根据格式信息 + 客户端 HEVC 能力，选择最佳可播文件。

        Returns:
            StreamTarget，或 None（proxy 未就绪时）。
        """
        async with self.db_session_factory() as session:
            result = await session.execute(
                select(
                    Video.file_path,
                    Video.remuxed_path,
                    Video.proxy_path,
                    Video.proxy_status,
                    Video.container_format,
                    Video.video_codec,
                    Video.audio_codec,
                    Video.has_audio,
                ).where(Video.id == video_id)
            )
            row = result.one_or_none()

        if row is None:
            raise FileNotFoundError(f"Video not found: {video_id}")

        # 先用已有 format 信息做快速路径判断
        if row.container_format and row.video_codec:
            info = FormatInfo(
                container_format=row.container_format,
                video_codec=row.video_codec,
                audio_codec=row.audio_codec,
                has_audio=row.has_audio or False,
            )
            # 1. 浏览器原生格式 → 直出
            if self._is_browser_native(info):
                return StreamTarget(
                    file_path=row.file_path,
                    media_type=self._mime_for(info.container_format),
                    source="original",
                )

        # 1.5 MP4 容器 + HEVC + hevcOk → 原文件直出
        # （Safari/Electron 硬解，无需 remux/proxy。浏览器已声明 HEVC 能力）
        if (row.container_format == "mp4" and row.video_codec == "hevc"
                and hevc_ok and os.path.exists(row.file_path)):
            return StreamTarget(
                file_path=row.file_path,
                media_type="video/mp4",
                source="original",
            )

        # 2. 有 remuxed 文件 → 使用（编码兼容的前提下）
        if row.remuxed_path and os.path.exists(row.remuxed_path):
            if row.video_codec == "h264":
                return StreamTarget(
                    file_path=row.remuxed_path,
                    media_type="video/mp4",
                    source="remuxed",
                )
            if row.video_codec == "hevc" and hevc_ok:
                return StreamTarget(
                    file_path=row.remuxed_path,
                    media_type="video/mp4",
                    source="remuxed",
                )

        # 3. 需要 proxy
        if row.video_codec in ("hevc", "av1", "wmv3", "mpeg4", "prores") or row.container_format in ("wmv",):
            if row.proxy_path and os.path.exists(row.proxy_path):
                return StreamTarget(
                    file_path=row.proxy_path,
                    media_type="video/mp4",
                    source="proxy",
                )
            # 无 proxy 且客户端不支持 HEVC → 按需触发转码
            if row.proxy_status == "none" and not hevc_ok:
                source_path = row.file_path
                if source_path and os.path.exists(source_path):
                    logger.info(
                        "[FormatService] Lazy proxy trigger for %s (non-HEVC client)",
                        video_id,
                    )
                    asyncio.create_task(self.transcode_proxy(source_path, video_id))
                return None
            # proxy 未就绪（正在生成中或已失败）
            return None

        # 4. 兜底：格式信息尚未探测完成（异步任务进行中）
        if row.container_format is None and row.remuxed_path is None:
            logger.info(
                "[FormatService] Format not probed yet for %s, returning 202",
                video_id,
            )
            return None  # 触发 202，前端轮询后重试

        # 5. 兜底：有 remuxed 就用，否则原始文件
        file_path = row.remuxed_path or row.file_path
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Stream file not found: {file_path}")

        return StreamTarget(
            file_path=file_path,
            media_type="video/mp4",
            source="remuxed" if row.remuxed_path else "original",
        )

    @staticmethod
    def _mime_for(container: str) -> str:
        """容器格式 → MIME type。"""
        mime_map = {
            "mp4": "video/mp4",
            "webm": "video/webm",
            "ogg": "video/ogg",
        }
        return mime_map.get(container, "video/mp4")

    # ── DB 更新辅助 ─────────────────────────────────────

    async def _update_proxy_status(
        self, video_id: uuid.UUID, status: str, progress: float,
        proxy_path: str | None = None,
    ) -> None:
        """更新视频的 proxy 状态和进度。"""
        try:
            async with self.db_session_factory() as session:
                values = {"proxy_status": status, "proxy_progress": progress}
                if proxy_path:
                    values["proxy_path"] = proxy_path
                await session.execute(
                    update(Video).where(Video.id == video_id).values(**values)
                )
                await session.commit()
        except Exception as e:
            logger.error("[FormatService] Failed to update proxy status: %s", e)

    async def _update_format_error(self, video_id: uuid.UUID, error: str) -> None:
        """标记视频格式处理失败。"""
        try:
            async with self.db_session_factory() as session:
                await session.execute(
                    update(Video)
                    .where(Video.id == video_id)
                    .values(proxy_status="failed")
                )
                await session.commit()
        except Exception as e:
            logger.error("[FormatService] Failed to update format error: %s", e)

    # ── 公开 API（供路由使用）─────────────────────────────

    async def probe_and_save(self, video_id: uuid.UUID, file_path: str) -> FormatInfo | None:
        """同步探测格式并立即写入 DB（<100ms），供 upload handler 调用。

        让 stream 端点在上传后立刻能做出路由决策，
        无需等待异步 remux/proxy 完成。
        """
        try:
            info = await self.probe(file_path)
            await self._save_format_info(video_id, info)
            return info
        except Exception as e:
            logger.warning("[FormatService] probe_and_save failed for %s: %s", video_id, e)
            return None

    # ── 完整格式处理流程 ─────────────────────────────────

    async def process_format(self, video_id: uuid.UUID, file_path: str) -> None:
        """上传后异步格式处理：probe → remux → proxy（如需）。

        通过 asyncio.create_task() 调用，不阻塞上传 API。
        失败时写入 DB 错误信息，不抛异常。
        注意：probe 在 upload handler 中已同步完成，此处直接读 DB。
        """
        try:
            # 从 DB 读取已探测的格式信息
            async with self.db_session_factory() as session:
                result = await session.execute(
                    select(Video.container_format, Video.video_codec,
                           Video.audio_codec, Video.has_audio)
                    .where(Video.id == video_id)
                )
                row = result.one_or_none()

            if row is None or not row.container_format:
                # probe 未完成（不应发生），回退到完整流程
                info = await self.probe(file_path)
                await self._save_format_info(video_id, info)
            else:
                info = FormatInfo(
                    container_format=row.container_format,
                    video_codec=row.video_codec or "unknown",
                    audio_codec=row.audio_codec,
                    has_audio=row.has_audio or False,
                )

            logger.info(
                "[FormatService] Processing: %s container=%s codec=%s audio=%s",
                video_id, info.container_format, info.video_codec, info.audio_codec,
            )

            # 浏览器原生格式？跳过一切
            if self._is_browser_native(info):
                logger.info("[FormatService] Browser-native format, no processing: %s", video_id)
                return

            # 容器标准化（不是 MP4 → remux）
            needs_remux = info.container_format not in ("mp4", "webm", "ogg")
            if needs_remux:
                remuxed = await self.remux_to_mp4(file_path, video_id, info)
                if remuxed:
                    await self._save_remuxed_path(video_id, remuxed)
                else:
                    logger.warning(
                        "[FormatService] Remux failed for %s, Pipeline will use original", video_id
                    )

            # 编码兼容代理 — 全部按需生成
            # remux 后的文件是 MP4/HEVC，HEVC 浏览器直读
            # 非 HEVC 浏览器首次请求时 get_stream_target 按需触发 proxy

        except Exception as e:
            logger.exception("[FormatService] format processing failed for %s: %s", video_id, e)
            await self._update_format_error(video_id, str(e))

    async def _save_format_info(self, video_id: uuid.UUID, info: FormatInfo) -> None:
        """将 FormatInfo 写入 Video 记录。"""
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == video_id)
                .values(
                    container_format=info.container_format,
                    video_codec=info.video_codec,
                    audio_codec=info.audio_codec,
                    has_audio=info.has_audio,
                    duration=info.duration,  # v0.34: 上传探测即写时长（此前只有管道才写→未处理时为空）
                )
            )
            await session.commit()

    async def _save_remuxed_path(self, video_id: uuid.UUID, path: str) -> None:
        """将 remuxed_path 写入 Video 记录。"""
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == video_id)
                .values(remuxed_path=path)
            )
            await session.commit()

    async def _save_proxy_path(self, video_id: uuid.UUID, path: str) -> None:
        """将 proxy_path 写入 Video 记录。"""
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == video_id)
                .values(proxy_path=path)
            )
            await session.commit()
