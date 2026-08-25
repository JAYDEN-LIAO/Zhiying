"""
core/storage_manager.py
═══════════════════════════════════════════════════════════
存储管理器 — 统一负责视频文件的路径解析、引用追踪与卫生清扫。

背景:
  删除视频记录只删 DB（repository.delete_video），磁盘文件从不清理，
  导致孤儿文件长期累积。本模块收敛所有落盘路径知识:

  1. 路径解析 —— 视频产生的每个文件的规范位置（相对/绝对混存收敛到项目根）
  2. 引用追踪 —— 从 videos 表三列(file_path/remuxed_path/proxy_path)
     派生引用集合，reuse 共享的文件天然被覆盖
  3. 删除清理 —— remove_video_artifacts: DB 删除后按引用判定清盘
  4. 清扫对账 —— sweep: 全量扫描磁盘 vs DB 引用，找出孤儿文件/目录/空组

路径判定原则（重要）:
  - 视频文件(video_dir): 按引用集合判定（reuse 共享 → 不能按文件名前缀）
  - 附属目录(thumbnails/audio/temp_chunks): 按 video_id ∈ videos 表判定。
    缩略图在 keyframe 阶段落盘、scene 行在 _persist 才入库，存在窗口期，
    绝不能按 scenes.keyframe_path 引用判断 —— 会误删活视频的缩略图。
"""

import os
import uuid
import shutil
import logging
from pathlib import Path

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from core.models import Video, VideoGroup
from core.paths import project_root

logger = logging.getLogger(__name__)

# 上传先落盘、DB 行后提交的窗口期保护（秒）: 比该值新的 video_dir 文件跳过清扫
UPLOAD_MTIME_GUARD_SEC = 600
# exports 临时文件 TTL（秒）: 超过该年龄的文件视为可回收（崩溃/未清理兜底）
EXPORTS_TTL_SEC = 24 * 3600


class StorageManager:
    """统一管理视频文件的生命周期。

    轻量类（非 DI 框架）: 在 main.py lifespan 实例化一次挂到
    app.state.storage_manager，CLI 脚本自行构造。
    """

    def __init__(self, config: dict):
        self.config = config
        self._project_root = project_root()

    # ──────────────────────────────────────────────
    # 路径解析
    # ──────────────────────────────────────────────

    def _resolve(self, p: str) -> str:
        """将存储路径收敛到项目根下的绝对路径（处理相对/绝对混存）。"""
        path = Path(p)
        if not path.is_absolute():
            path = self._project_root / path
        return str(path.resolve())

    def video_dir(self) -> str:
        return self._resolve(
            self.config.get("storage", {}).get("video_dir", "data/videos")
        )

    def artifact_dir(self) -> str:
        return self._resolve(
            self.config.get("storage", {}).get("artifact_dir", "data/artifacts")
        )

    def thumbnail_dir(self, video_id: uuid.UUID) -> str:
        return os.path.join(self.artifact_dir(), "thumbnails", str(video_id))

    def audio_path(self, video_id: uuid.UUID) -> str:
        return os.path.join(self.artifact_dir(), "audio", f"{video_id}.wav")

    def temp_chunks_dir(self, video_id: uuid.UUID) -> str:
        return os.path.join(self.artifact_dir(), "temp_chunks", str(video_id))

    def export_dir(self) -> str:
        return os.path.join(self.artifact_dir(), "exports")

    def subject_photo_dir(self, subject_id: uuid.UUID) -> str:
        """素材库底库照片目录（v0.6，图片素材库）— 按目标一人一目录。"""
        return os.path.join(self.artifact_dir(), "subject_photos", str(subject_id))

    # ──────────────────────────────────────────────
    # 引用追踪（派生自 videos 表，不加新表）
    # ──────────────────────────────────────────────

    async def all_referenced_paths(self, session: AsyncSession) -> set[str]:
        """所有活视频引用的文件路径集合（三列归一化后的并集）。

        reuse 共享: 多条记录引用同一 file_path → 并集天然覆盖，
        任一记录仍存活即视为被引用。
        """
        result = await session.execute(
            select(Video.file_path, Video.remuxed_path, Video.proxy_path)
        )
        refs: set[str] = set()
        for row in result.all():
            for p in (row.file_path, row.remuxed_path, row.proxy_path):
                if p:
                    refs.add(self._resolve(p))
        return refs

    async def all_video_ids(self, session: AsyncSession) -> set[uuid.UUID]:
        """活视频 id 集合 — 用于附属目录(缩略图/音频/chunk)的孤儿判定。"""
        result = await session.execute(select(Video.id))
        return {row[0] for row in result.all()}

    # ──────────────────────────────────────────────
    # 删除清理（DB 删除 commit 之后调用）
    # ──────────────────────────────────────────────

    async def remove_video_artifacts(
        self,
        session: AsyncSession,
        video_id: uuid.UUID,
        file_path: str,
        remuxed_path: str | None,
        proxy_path: str | None,
        source_owned: bool = True,
    ) -> int:
        """按引用判定删除视频的全部磁盘产物，返回释放字节数。

        必须在视频记录删除并 commit 后调用。每个操作独立 try/except:
        FileNotFoundError 吞掉（幂等），其余仅记日志 —— 不抛出
        （DB 行已删，文件清理失败不应让删除接口返回失败）。

        source_owned=False 时跳过 unlink 原始源文件（平台共享文件就地引用，
        归平台所有，Zhiying 不负责删除；remux/proxy 仍按引用清理）。
        """
        freed = 0
        referenced = await self.all_referenced_paths(session)

        # 1. 三个视频文件路径（reuse 共享 → 引用集合内才保留）
        for path in (file_path, remuxed_path, proxy_path):
            if not path:
                continue
            # 平台共享源文件归平台所有，Zhiying 不删除
            if path == file_path and not source_owned:
                continue
            norm = self._resolve(path)
            if norm in referenced:
                continue
            freed += self._safe_unlink(norm)

        # 2. 附属目录/文件（按 video_id 判定，无共享，直接清理）
        freed += self._safe_rmtree(self.thumbnail_dir(video_id))
        freed += self._safe_unlink(self.audio_path(video_id))
        freed += self._safe_rmtree(self.temp_chunks_dir(video_id))

        if freed:
            logger.info(
                "[StorageManager] Removed artifacts for video %s: %.1f MB",
                video_id, freed / 1e6,
            )
        return freed

    # ──────────────────────────────────────────────
    # 清扫对账
    # ──────────────────────────────────────────────

    async def sweep(self, session: AsyncSession, dry_run: bool = True) -> dict:
        """全量扫描磁盘 vs DB 引用，找出并（可选）清理所有孤儿资源。

        Returns:
            dict: 每类孤儿的数量与可释放字节；dry_run=False 时实际执行删除。
        """
        referenced = await self.all_referenced_paths(session)
        video_ids = await self.all_video_ids(session)

        report: dict = {
            "dry_run": dry_run,
            "categories": {},
            "total_bytes_reclaimable": 0,
        }

        # 1. video_dir 孤儿文件（扁平文件，mtime 保护防上传竞态）
        vdir = self.video_dir()
        orphan_files: list[str] = []
        if os.path.isdir(vdir):
            now = _now()
            for name in os.listdir(vdir):
                path = os.path.join(vdir, name)
                if not os.path.isfile(path):
                    continue
                norm = self._resolve(path)
                if norm in referenced:
                    continue
                try:
                    if now - os.path.getmtime(path) < UPLOAD_MTIME_GUARD_SEC:
                        continue
                except OSError:
                    continue
                orphan_files.append(path)
        self._record(report, "video_files", orphan_files, dry_run=dry_run)

        # 2. 附属目录孤儿（thumbnails/audio/temp_chunks 按 video_id 判定）
        self._sweep_artifact_dirs(report, "thumbnails", video_ids, dry_run=dry_run)
        self._sweep_audio(report, video_ids, dry_run=dry_run)
        self._sweep_artifact_dirs(report, "temp_chunks", video_ids, dry_run=dry_run)

        # 3. exports TTL 临时文件
        self._sweep_exports(report, dry_run=dry_run)

        # 4. 空组
        await self._sweep_empty_groups(report, session, dry_run=dry_run)

        report["total_bytes_reclaimable"] = sum(
            c.get("bytes", 0) for c in report["categories"].values()
        )
        return report

    # ── sweep 内部辅助 ──

    def _sweep_artifact_dirs(
        self, report: dict, subdir: str, video_ids: set[uuid.UUID], dry_run: bool,
    ) -> None:
        base = os.path.join(self.artifact_dir(), subdir)
        targets: list[str] = []
        if os.path.isdir(base):
            for name in os.listdir(base):
                path = os.path.join(base, name)
                if not os.path.isdir(path):
                    continue
                try:
                    vid = uuid.UUID(name)
                except ValueError:
                    continue
                if vid in video_ids:
                    continue
                targets.append(path)
        self._record(report, f"{subdir}_dirs", targets, dry_run=dry_run)

    def _sweep_audio(self, report: dict, video_ids: set[uuid.UUID], dry_run: bool) -> None:
        base = os.path.join(self.artifact_dir(), "audio")
        targets: list[str] = []
        if os.path.isdir(base):
            for name in os.listdir(base):
                if not name.endswith(".wav"):
                    continue
                path = os.path.join(base, name)
                if not os.path.isfile(path):
                    continue
                try:
                    vid = uuid.UUID(name[:-4])
                except ValueError:
                    continue
                if vid in video_ids:
                    continue
                targets.append(path)
        self._record(report, "audio_files", targets, dry_run=dry_run)

    def _sweep_exports(self, report: dict, dry_run: bool) -> None:
        base = self.export_dir()
        targets: list[str] = []
        if os.path.isdir(base):
            now = _now()
            for name in os.listdir(base):
                path = os.path.join(base, name)
                if not os.path.isfile(path):
                    continue
                try:
                    if now - os.path.getmtime(path) >= EXPORTS_TTL_SEC:
                        targets.append(path)
                except OSError:
                    continue
        self._record(report, "exports_ttl", targets, dry_run=dry_run)

    async def _sweep_empty_groups(
        self, report: dict, session: AsyncSession, dry_run: bool,
    ) -> None:
        result = await session.execute(
            select(VideoGroup.id)
            .outerjoin(Video, Video.group_id == VideoGroup.id)
            .group_by(VideoGroup.id)
            .having(func.count(Video.id) == 0)
        )
        group_ids = [row[0] for row in result.all()]
        report["categories"]["empty_groups"] = {
            "count": len(group_ids),
            "bytes": 0,
            "items": [str(g) for g in group_ids],
        }
        if group_ids and not dry_run:
            await session.execute(
                delete(VideoGroup).where(VideoGroup.id.in_(group_ids))
            )
            await session.commit()
            logger.info("[StorageManager] Sweep removed %d empty groups", len(group_ids))

    # ── 记录与执行 ──

    def _record(self, report: dict, category: str, paths: list[str], dry_run: bool) -> None:
        """统计该类目孤儿；dry_run=False 时才实际删除。

        注意: dry_run=True 时绝不能触碰文件 —— 这里只测量，不删除。
        """
        total = 0
        for path in paths:
            if dry_run:
                total += _measure(path)
            else:
                total += self._safe_rmtree(path)
        report["categories"][category] = {
            "count": len(paths),
            "bytes": total,
            "items": paths,
        }
        if paths:
            verb = "WOULD DELETE" if dry_run else "deleted"
            logger.info(
                "[StorageManager] Sweep %s %s: %d items (%.1f MB)",
                verb, category, len(paths), total / 1e6,
            )

    # ── 底层安全删除 ──

    @staticmethod
    def _safe_unlink(path: str) -> int:
        if not path or not os.path.exists(path):
            return 0
        size = 0
        try:
            size = os.path.getsize(path)
            os.remove(path)
        except FileNotFoundError:
            return 0
        except OSError as e:
            logger.warning("[StorageManager] Failed to remove %s: %s", path, e)
            return 0
        return size

    @staticmethod
    def _safe_rmtree(path: str) -> int:
        """删除文件或目录，返回释放字节数；缺失/失败均不抛出。"""
        if not path or not os.path.exists(path):
            return 0
        size = 0
        try:
            if os.path.isdir(path):
                size = _dir_size(path)
                shutil.rmtree(path)
            else:
                size = os.path.getsize(path)
                os.remove(path)
        except FileNotFoundError:
            return 0
        except OSError as e:
            logger.warning("[StorageManager] Failed to remove %s: %s", path, e)
            return 0
        return size

    # ── 用量概览（GET /maintenance/storage 用） ──

    async def storage_usage(self, session: AsyncSession) -> dict:
        """各目录总用量 + 当前孤儿可回收量（dry-run 摘要）。"""
        sweep_report = await self.sweep(session, dry_run=True)
        dirs = ["video_dir", "artifact_dir", "thumbnails", "audio", "temp_chunks", "exports"]
        usage = {"sweep": sweep_report, "dirs": {}}
        mapping = {
            "video_dir": self.video_dir(),
            "artifact_dir": self.artifact_dir(),
            "thumbnails": os.path.join(self.artifact_dir(), "thumbnails"),
            "audio": os.path.join(self.artifact_dir(), "audio"),
            "temp_chunks": os.path.join(self.artifact_dir(), "temp_chunks"),
            "exports": self.export_dir(),
        }
        for label, path in mapping.items():
            usage["dirs"][label] = _dir_stats(path)
        return usage


# ──────────────────────────────────────────────
# 模块级辅助
# ──────────────────────────────────────────────

def _now() -> float:
    import time
    return time.time()


def _dir_size(path: str) -> int:
    """递归计算目录字节数（稀疏文件按 st_size 近似）。"""
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
    except OSError:
        return 0
    return total


def _measure(path: str) -> int:
    """仅测量文件/目录大小，不做任何删除（dry-run 用）。"""
    if not os.path.exists(path):
        return 0
    if os.path.isdir(path):
        return _dir_size(path)
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _dir_stats(path: str) -> dict:
    if not os.path.isdir(path):
        return {"exists": False, "size_bytes": 0, "file_count": 0}
    return {
        "exists": True,
        "size_bytes": _dir_size(path),
        "file_count": sum(len(fs) for _r, _d, fs in os.walk(path)),
    }
