"""desktop/downloads.py — 应用内下载管理（壳侧）。

桌面端导出/下载不再走系统浏览器：WebView2 会把 window.open 转交外部浏览器
（OPEN_EXTERNAL_LINKS_IN_BROWSER 默认开），blob + <a download> 又被
ALLOW_DOWNLOADS=False 静默取消——两路都不是好体验。改为前端把「接口路径 +
文件名」交给壳（js_api），壳先弹 Windows 保存框（记住上次目录），再线程内
流式拉本地后端写盘；进度/状态由前端经 get_downloads 轮询，渲染下载管理弹窗。

职责边界：壳只负责「选位置 + 下载 + 进度」；弹窗 UI / 触发点全在前端。
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 64 * 1024

# 状态（中文直出，前端原样显示）
RUNNING, DONE, FAILED, CANCELLED = "下载中", "已完成", "失败", "已取消"


@dataclass
class DownloadJob:
    id: int
    name: str
    path: str                    # 所选保存路径
    status: str
    total: int = 0               # 字节（Content-Length，未知为 0）
    done: int = 0
    error: str = ""
    # 重试所需原始参数
    port: int = 0
    api_path: str = ""
    method: str = "GET"
    body: bytes | None = None


class DownloadManager:
    def __init__(self, root: Path, log) -> None:
        self._root = root
        self._log = log
        self._window = None      # set_window 注入（保存框要用）
        self._jobs: dict[int, DownloadJob] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def set_window(self, window) -> None:
        self._window = window

    # ── 保存框 + 上次目录 ─────────────────────────────────────
    def _dir_file(self) -> Path:
        return self._root / "data" / "export_dir.txt"

    def _last_dir(self) -> str:
        try:
            return self._dir_file().read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def remember_dir(self, p: Path) -> None:
        try:
            self._dir_file().parent.mkdir(parents=True, exist_ok=True)
            self._dir_file().write_text(str(p.parent), encoding="utf-8")
        except OSError:
            pass

    def ask_save_path(self, name: str) -> str | None:
        """弹 Windows 保存框。取消 → None。"""
        if not self._window:
            return None
        try:
            import webview
            result = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=self._last_dir() or None,
                save_filename=name,
            )
        except Exception as e:
            self._log.write(f"[下载] 保存框调起失败: {e}")
            return None
        if isinstance(result, (list, tuple)):
            result = result[0] if result else None
        return str(result) if result else None

    # ── 任务编排 ─────────────────────────────────────────────
    def _new_job(self, name: str) -> DownloadJob:
        with self._lock:
            self._seq += 1
            job = DownloadJob(id=self._seq, name=name, path="", status=RUNNING)
            self._jobs[job.id] = job
            return job

    def enqueue(self, name: str, api_path: str, port: int,
                method: str = "GET", body: bytes | None = None) -> dict:
        """入口：弹保存框 → 用户选定后线程下载。返回 job 快照（含 id）。"""
        import urllib.parse
        safe_name = Path(urllib.parse.unquote(name)).name or f"download_{int(time.time())}"
        job = self._new_job(safe_name)
        job.port, job.api_path, job.method, job.body = port, api_path, method, body
        target = self.ask_save_path(safe_name)
        if not target:
            job.status = CANCELLED
            return self.snapshot(job.id)
        job.path = target
        self._remember_dir(Path(target))
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return self.snapshot(job.id)

    def retry(self, job_id: int) -> dict:
        """失败/取消任务重试：换新 job 复用原参数（弹框重选位置）。"""
        with self._lock:
            old = self._jobs.get(int(job_id))
        if not old:
            return {}
        return self.enqueue(old.name, old.api_path, old.port, old.method, old.body)

    def clear(self, job_id: int) -> None:
        """清除一条已终结（完成/失败/取消）的任务记录；进行中的不清。"""
        with self._lock:
            job = self._jobs.get(int(job_id))
            if job and job.status != RUNNING:
                self._jobs.pop(job.id, None)

    def _run(self, job: DownloadJob) -> None:
        import urllib.error
        import urllib.request

        url = f"http://127.0.0.1:{job.port}{job.api_path}"
        try:
            req = urllib.request.Request(url, data=job.body, method=job.method)
            if job.body is not None:
                req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=300) as resp:
                cl = resp.headers.get("Content-Length")
                job.total = int(cl) if cl and cl.isdigit() else 0
                tmp = job.path + ".part"
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(_CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
                        job.done += len(chunk)
                Path(tmp).replace(job.path)
            job.status = DONE
            self._log.write(f"[下载] {job.name} → {job.path}（{job.done} 字节）")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode("utf-8")).get("detail", "")
            except Exception:
                pass
            job.status = FAILED
            job.error = detail or f"HTTP {e.code}"
            self._log.write(f"[下载] {job.name} 失败: {job.error}")
        except Exception as e:
            job.status = FAILED
            job.error = str(e)
            self._log.write(f"[下载] {job.name} 失败: {e}")
            # 清理半成品
            try:
                Path(job.path + ".part").unlink(missing_ok=True)
            except OSError:
                pass

    # ── 快照（前端轮询）──────────────────────────────────────
    def snapshot(self, job_id: int | None = None) -> dict:
        with self._lock:
            jobs = [self._jobs[job_id]] if job_id else list(self._jobs.values())
            return {
                "jobs": [
                    {"id": j.id, "name": j.name, "path": j.path, "status": j.status,
                     "total": j.total, "done": j.done, "error": j.error}
                    for j in sorted(jobs, key=lambda x: -x.id)
                ]
            }


def open_containing_dir(path: str) -> tuple[bool, str]:
    """资源管理器定位到文件所在目录（Windows explorer /select）。"""
    try:
        subprocess.Popen(["explorer", "/select,", str(path)])
        return True, ""
    except Exception as e:
        return False, str(e)
