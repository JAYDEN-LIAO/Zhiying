"""
services/export_service.py
═══════════════════════════════════════════════════════════
导出业务逻辑 — 视频片段 / 帧 / 追踪轨迹 / 缩略图。

ExportService 只负责文件/FFmpeg 操作，不直接访问数据库。
DB 查询在路由层完成，数据传入服务方法。
"""

import logging
import os
import uuid
import zipfile
from pathlib import Path

from utils.video_util import export_video_segment, extract_keyframe_at, extract_keyframe_to_memory

logger = logging.getLogger(__name__)


class ExportService:
    """导出服务 — 视频片段裁剪 / 关键帧 / 追踪轨迹 / 缩略图打包。"""

    def __init__(self, config: dict):
        self.config = config
        project_root = Path(__file__).resolve().parent.parent
        artifact_dir = config.get("storage", {}).get("artifact_dir", "data/artifacts")
        self.export_dir = project_root / artifact_dir / "exports"
        self.export_dir.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════════════════════════
    # 视频片段导出
    # ═══════════════════════════════════════════════════════

    async def export_clip(
        self,
        video_path: str,
        start_sec: float,
        end_sec: float,
        output_format: str = "mp4",
    ) -> str:
        """导出视频片段（流复制，极速）。

        Returns:
            导出文件路径。
        """
        ext = f".{output_format}"
        output_path = str(self.export_dir / f"clip_{uuid.uuid4().hex[:12]}{ext}")

        await export_video_segment(
            video_path=video_path,
            start_sec=start_sec,
            end_sec=end_sec,
            output_path=output_path,
            reencode=False,
        )
        return output_path

    # ═══════════════════════════════════════════════════════
    # 帧导出
    # ═══════════════════════════════════════════════════════

    async def export_frames(
        self,
        video_path: str,
        timestamps: list[float],
        output_format: str = "jpg",
    ) -> str:
        """提取指定时间点的帧，打包为 zip。

        Returns:
            zip 文件路径。
        """
        export_id = uuid.uuid4().hex[:12]
        tmp_dir = self.export_dir / f"frames_{export_id}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        ext = f".{output_format}"
        frame_paths: list[str] = []

        for i, ts in enumerate(timestamps):
            out_path = str(tmp_dir / f"frame_{i:04d}_at_{ts:.1f}s{ext}")
            await extract_keyframe_at(video_path, ts, out_path)
            frame_paths.append(out_path)

        zip_path = str(self.export_dir / f"frames_{export_id}.zip")
        await self._zip_files(frame_paths, zip_path, prefix=f"frames_{export_id}")

        # 清理临时目录
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

        return zip_path

    # ═══════════════════════════════════════════════════════
    # 追踪轨迹导出
    # ═══════════════════════════════════════════════════════

    async def export_track_clip(
        self,
        video_path: str,
        track_data: dict,
        detections: list[dict],
        video_resolution: tuple[int, int],
        draw_bbox: bool = True,
    ) -> str:
        """导出追踪轨迹视频片段，可选 bbox 叠加。

        Args:
            video_path:       输入视频路径。
            track_data:       Track 摘要 {track_id, class_name, first_seen, last_seen}。
            detections:       FrameDetection 列表 [{timestamp_sec, bbox{x1,y1,x2,y2}}]。
            video_resolution: (width, height) 像素分辨率。
            draw_bbox:        是否在视频上绘制 bbox。

        Returns:
            导出文件路径。
        """
        first_seen = track_data["first_seen"]
        last_seen = track_data["last_seen"]
        class_name = track_data["class_name"]
        track_id = track_data["track_id"]

        # 添加 1 秒余量
        start_sec = max(0.0, first_seen - 1.0)
        end_sec = last_seen + 1.0

        export_id = uuid.uuid4().hex[:12]
        output_path = str(
            self.export_dir / f"track_{class_name}_{track_id}_{export_id}.mp4"
        )

        # 构建 drawbox 滤镜链
        video_filters: str | None = None
        if draw_bbox and detections:
            video_filters = self._build_bbox_filter(detections, video_resolution)

        await export_video_segment(
            video_path=video_path,
            start_sec=start_sec,
            end_sec=end_sec,
            output_path=output_path,
            reencode=draw_bbox,
            video_filters=video_filters,
        )
        return output_path

    # ═══════════════════════════════════════════════════════
    # 缩略图导出
    # ═══════════════════════════════════════════════════════

    async def export_thumbnails(self, thumbnail_paths: list[str]) -> str:
        """将已存在的缩略图文件打包为 zip。

        Args:
            thumbnail_paths: 缩略图文件路径列表。

        Returns:
            zip 文件路径。
        """
        export_id = uuid.uuid4().hex[:12]
        zip_path = str(self.export_dir / f"thumbnails_{export_id}.zip")

        valid = [p for p in thumbnail_paths if os.path.exists(p)]
        if not valid:
            logger.warning("[Export] No valid thumbnail paths to zip")
            # 创建空 zip
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED):
                pass
            return zip_path

        await self._zip_files(valid, zip_path, prefix="thumbnails")
        return zip_path

    # ═══════════════════════════════════════════════════════
    # 内部工具
    # ═══════════════════════════════════════════════════════

    def _build_bbox_filter(
        self,
        detections: list[dict],
        resolution: tuple[int, int],
    ) -> str:
        """构建 FFmpeg drawbox 滤镜链。

        每个检测帧的 bbox 通过 enable='between(t, ...)' 控制时间窗口。
        相邻时间戳之间线性插值（使用 drawbox 的时间表达式）。
        """
        vid_w, vid_h = resolution
        if vid_w <= 0 or vid_h <= 0:
            return "null"

        import asyncio as _asyncio  # noqa: F401 (used only if we run sync)

        # 按时间排序
        sorted_dets = sorted(detections, key=lambda d: d["timestamp_sec"])
        if not sorted_dets:
            return "null"

        filter_parts: list[str] = []
        n = len(sorted_dets)

        for i, det in enumerate(sorted_dets):
            bbox = det["bbox"]
            ts = det["timestamp_sec"]

            # 归一化坐标 → 像素坐标
            px = max(0, int(bbox["x1"] * vid_w))
            py = max(0, int(bbox["y1"] * vid_h))
            pw = max(1, int((bbox["x2"] - bbox["x1"]) * vid_w))
            ph = max(1, int((bbox["y2"] - bbox["y1"]) * vid_h))

            # 时间窗口：从当前帧到下一帧（或 +0.1s）
            next_ts = sorted_dets[i + 1]["timestamp_sec"] if i + 1 < n else ts + 0.1
            # 让每个 bbox 覆盖到下一帧开始（避免闪烁）
            t_end = ts + (next_ts - ts) * 0.9 if i + 1 < n else ts + 0.2

            filter_parts.append(
                f"drawbox=x={px}:y={py}:w={pw}:h={ph}:color=red@0.5:t=fill"
                f":enable='between(t,{ts:.3f},{t_end:.3f})'"
            )

        return ",".join(filter_parts)

    async def _zip_files(
        self,
        file_paths: list[str],
        zip_path: str,
        prefix: str = "",
    ) -> None:
        """将文件列表打包为一个 zip。

        文件在 zip 内以 ``{prefix}/{basename}`` 路径存储。
        """
        import asyncio

        def _write_zip() -> None:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp in file_paths:
                    arcname = os.path.basename(fp)
                    if prefix:
                        arcname = f"{prefix}/{arcname}"
                    zf.write(fp, arcname=arcname)

        await asyncio.to_thread(_write_zip)
        logger.info("[Export] Zipped %d files → %s", len(file_paths), zip_path)
