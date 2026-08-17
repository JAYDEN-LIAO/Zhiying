"""
services/export_service.py
═══════════════════════════════════════════════════════════
导出业务逻辑 — 视频片段 / 帧 / 追踪轨迹 / 缩略图。

ExportService 只负责文件/FFmpeg 操作，不直接访问数据库。
DB 查询在路由层完成，数据传入服务方法。
"""

import io
import logging
import os
import uuid
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from utils.video_util import export_video_segment, extract_keyframe_at, extract_keyframe_to_memory

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 命名工具
# ═══════════════════════════════════════════════════════════

def format_ts(sec: float) -> str:
    """格式化秒为用于文件名的字符串: 01h34m44s"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}h{m:02d}m{s:02d}s"


def sanitize_filename(name: str) -> str:
    """移除文件名中不安全字符，保留字母数字和常见符号。"""
    import re
    return re.sub(r'[<>:"/\\|?*]', "_", name)


class ExportService:
    """导出服务 — 视频片段裁剪 / 关键帧 / 追踪轨迹 / 缩略图打包。"""

    def __init__(self, config: dict):
        self.config = config
        from core.paths import project_root
        project_root = project_root()
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
    ) -> str:
        """导出视频片段（流复制，极速）。

        Returns:
            导出文件路径。
        """
        output_path = str(self.export_dir / f"clip_{uuid.uuid4().hex[:12]}.mp4")

        await export_video_segment(
            video_path=video_path,
            start_sec=start_sec,
            end_sec=end_sec,
            output_path=output_path,
            reencode=False,
        )
        return output_path

    # ═══════════════════════════════════════════════════════
    # 单帧导出（用户手动输入 start == end 时使用）
    # ═══════════════════════════════════════════════════════

    async def export_single_frame(
        self,
        video_path: str,
        timestamp: float,
    ) -> str:
        """导出单帧 JPEG。

        Returns:
            JPEG 文件路径。
        """
        output_path = str(self.export_dir / f"frame_{uuid.uuid4().hex[:12]}.jpg")
        await extract_keyframe_at(video_path, timestamp, output_path)
        return output_path

    # ═══════════════════════════════════════════════════════
    # 追踪轨迹分段导出 → zip
    # ═══════════════════════════════════════════════════════

    async def export_track_segments_zip(
        self,
        video_path: str,
        video_name: str,
        track_id: int,
        segments: list[dict],
        class_name: str,
        per_segment_detections: list[list[dict]] | None = None,
        video_resolution: tuple[int, int] | None = None,
        draw_bbox: bool = False,
    ) -> str:
        """导出 track 的每段时间片段为独立 mp4，打包成 zip。

        Args:
            video_path:              输入视频路径。
            video_name:              视频名称（不含扩展名，用于 zip 命名）。
            track_id:                ByteTrack 追踪 ID。
            segments:                时间片段列表 [{start, end}, ...]。
            class_name:              COCO 类别名。
            per_segment_detections:  每段的检测框数据（与 segments 等长）。None 则不画框。
            video_resolution:        视频分辨率 (w, h)。
            draw_bbox:               是否画 bbox。

        Returns:
            zip 文件路径。
        """
        export_id = uuid.uuid4().hex[:12]
        safe_name = sanitize_filename(video_name)
        zip_path = str(self.export_dir / f"{safe_name}_track{track_id}_{export_id}.zip")

        temp_clips: list[str] = []
        segment_count = len(segments)

        for i, seg in enumerate(segments):
            start_sec = max(0.0, seg["start"] - 1.0)
            end_sec = seg["end"] + 1.0

            seg_dets = (per_segment_detections[i] if per_segment_detections
                        and i < len(per_segment_detections) else [])

            video_filters: str | None = None
            reencode = False
            if draw_bbox and seg_dets and video_resolution:
                video_filters = self._build_bbox_filter(seg_dets, video_resolution)
                reencode = True

            # 用时间戳命名内部文件
            ts_start = format_ts(seg["start"])
            ts_end = format_ts(seg["end"])
            clip_name = f"track{track_id}_{ts_start}_{ts_end}.mp4"
            clip_path = str(self.export_dir / f"trackseg_{export_id}_{i:04d}.mp4")

            await export_video_segment(
                video_path=video_path,
                start_sec=start_sec,
                end_sec=end_sec,
                output_path=clip_path,
                reencode=reencode,
                video_filters=video_filters,
            )
            temp_clips.append((clip_path, clip_name))

        # 打包为 zip，内部路径保留时间戳文件名
        def _write_zip() -> None:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for clip_path, arcname in temp_clips:
                    zf.write(clip_path, arcname=arcname)

        import asyncio
        await asyncio.to_thread(_write_zip)
        logger.info("[Export] Track zip created: %s (%d segments)", zip_path, segment_count)

        # 清理临时 clip 文件
        for clip_path, _ in temp_clips:
            try:
                os.remove(clip_path)
            except OSError:
                pass

        return zip_path

    # ═══════════════════════════════════════════════════════
    # Track 物体缩略图导出（全尺寸裁剪图）
    # ═══════════════════════════════════════════════════════

    async def export_track_thumbnail(
        self,
        video_path: str,
        timestamp: float,
        bbox: dict,
    ) -> str:
        """提取 track 指定时间点的物体裁剪图，返回全尺寸 JPEG。

        Args:
            video_path:  输入视频路径。
            timestamp:   时间戳（秒）。
            bbox:        归一化 bbox {x1, y1, x2, y2}。

        Returns:
            JPEG 文件路径。
        """
        frame = await extract_keyframe_to_memory(video_path, timestamp)

        # 裁剪
        x1 = bbox.get("x1", 0)
        y1 = bbox.get("y1", 0)
        x2 = bbox.get("x2", 1)
        y2 = bbox.get("y2", 1)
        h, w = frame.shape[:2]
        px1, py1 = max(0, int(x1 * w)), max(0, int(y1 * h))
        px2, py2 = min(w, int(x2 * w)), min(h, int(y2 * h))
        if px2 > px1 and py2 > py1:
            frame = frame[py1:py2, px1:px2]

        img = Image.fromarray(frame)
        output_path = str(self.export_dir / f"trackthumb_{uuid.uuid4().hex[:12]}.jpg")
        img.save(output_path, format="JPEG", quality=92)
        logger.info("[Export] Track thumbnail saved → %s", output_path)
        return output_path

    # ═══════════════════════════════════════════════════════
    # 缩略图导出（场景缩略图 zip）
    # ═══════════════════════════════════════════════════════

    async def export_thumbnails(self, thumbnail_paths: list[str], video_name: str = "thumbnails") -> str:
        """将已存在的缩略图文件打包为 zip。

        Args:
            thumbnail_paths: 缩略图文件路径列表。
            video_name:      zip 命名用的视频名称（不含扩展名）。

        Returns:
            zip 文件路径。
        """
        safe_name = sanitize_filename(video_name)
        export_id = uuid.uuid4().hex[:12]
        zip_path = str(self.export_dir / f"{safe_name}_thumbnails_{export_id}.zip")

        valid = [p for p in thumbnail_paths if os.path.exists(p)]
        if not valid:
            logger.warning("[Export] No valid thumbnail paths to zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED):
                pass
            return zip_path

        # zip 内重命名为 scene_{index}.jpg
        renamed: list[tuple[str, str]] = []
        for i, fp in enumerate(valid):
            arcname = f"scene_{i:04d}.jpg"
            renamed.append((fp, arcname))

        def _write_zip() -> None:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for fp, arcname in renamed:
                    zf.write(fp, arcname=arcname)

        import asyncio
        await asyncio.to_thread(_write_zip)
        logger.info("[Export] Thumbnails zip created: %s (%d files)", zip_path, len(renamed))
        return zip_path

    # ═══════════════════════════════════════════════════════
    # 内部工具 — drawbox 滤镜
    # ═══════════════════════════════════════════════════════

    def _build_bbox_filter(
        self,
        detections: list[dict],
        resolution: tuple[int, int],
    ) -> str:
        """构建 FFmpeg drawbox 滤镜链。

        使用 t=2（2px 粗边框）替代 t=fill（填充），配合低透明度填充，效果接近前端。
        """
        vid_w, vid_h = resolution
        if vid_w <= 0 or vid_h <= 0:
            return "null"

        sorted_dets = sorted(detections, key=lambda d: d["timestamp_sec"])
        if not sorted_dets:
            return "null"

        filter_parts: list[str] = []
        n = len(sorted_dets)

        for i, det in enumerate(sorted_dets):
            bbox = det["bbox"]
            ts = det["timestamp_sec"]

            px = max(0, int(bbox["x1"] * vid_w))
            py = max(0, int(bbox["y1"] * vid_h))
            pw = max(1, int((bbox["x2"] - bbox["x1"]) * vid_w))
            ph = max(1, int((bbox["y2"] - bbox["y1"]) * vid_h))

            next_ts = sorted_dets[i + 1]["timestamp_sec"] if i + 1 < n else ts + 0.1
            t_end = ts + (next_ts - ts) * 0.95 if i + 1 < n else ts + 0.2

            # t=fill 极淡填充底 + t=2 2px 边框（叠加两层 drawbox）
            fill = (
                f"drawbox=x={px}:y={py}:w={pw}:h={ph}:color=red@0.08:t=fill"
                f":enable='between(t,{ts:.3f},{t_end:.3f})'"
            )
            border = (
                f"drawbox=x={px}:y={py}:w={pw}:h={ph}:color=red@0.6:t=2"
                f":enable='between(t,{ts:.3f},{t_end:.3f})'"
            )
            filter_parts.append(fill)
            filter_parts.append(border)

        return ",".join(filter_parts)
