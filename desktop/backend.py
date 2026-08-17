"""uvicorn 后端子进程管理：启动 / 日志管道 / 健康轮询 / 优雅关停 / 崩溃监测。

统一以 `python backend_launcher.py` 拉起（含父进程存活看门狗）：
  - 封装模式（exe 内，sys._MEIPASS 存在）：launcher 在 _internal，经
    ZHIYING_BACKEND_ROOT 指到字节码包 backend_pyc（客户端无明文源码）
  - 源码模式：launcher 在项目根，无 ZHIYING_BACKEND_ROOT → 从源码 import
不用 run.py（它带 reload=True）。端口经 ZHIYING_BACKEND_PORT 传入。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# Windows：exe 是 windowed（console=False），无控制台；spawn console 子进程（.venv python）
# 时系统会新建一个黑框终端（标题=解释器路径）。CREATE_NO_WINDOW 让子进程不分配控制台。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _backend_launcher(root: Path) -> tuple[Path, dict]:
    """后端子进程入口：封装模式用 _internal 的 launcher + 字节码包，源码模式用项目根 launcher。"""
    meipass = getattr(sys, "_MEIPASS", None)
    extra: dict = {}
    if meipass:
        meipass = Path(meipass)
        launcher = meipass / "backend_launcher.py"
        extra["ZHIYING_BACKEND_ROOT"] = str(meipass / "backend_pyc")  # 字节码包（藏源码）
    else:
        launcher = root / "backend_launcher.py"
    extra["ZHIYING_PROJECT_ROOT"] = str(root)
    return launcher, extra


def start_backend(root: Path, python: str, host: str, port: int, log) -> subprocess.Popen:
    """启动后端子进程（backend_launcher.py：uvicorn + 父进程存活看门狗）。

    启动器被强制结束时，后端在 ~3s 内自检父进程死亡并 os._exit(3)，避免遗留
    占用端口/显存的孤儿进程。
    """
    launcher, extra_env = _backend_launcher(root)
    cmd = [python, str(launcher)]
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "ZHIYING_PARENT_PID": str(os.getpid()),
        # 桌面端：让后端挂载桌面前端（frontend-desktop/dist），而非服务器前端
        "ZHIYING_FRONTEND": "desktop",
        "ZHIYING_BACKEND_HOST": host,
        "ZHIYING_BACKEND_PORT": str(port),
        **extra_env,
    }
    log.write("$ " + " ".join(cmd))
    proc = subprocess.Popen(
        cmd, cwd=str(root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        creationflags=_NO_WINDOW,
    )

    def _reader() -> None:
        for line in proc.stdout:
            log.write(line.rstrip())

    threading.Thread(target=_reader, daemon=True).start()
    return proc


def wait_health(host: str, port: int, log, timeout: int = 240) -> dict:
    """轮询 /health 直到 database=ok（后端就绪）。超时抛 TimeoutError。

    /health 在 DB 不可达时返回 503 —— 视为"后端已起、数据库未就绪"，继续等。
    """
    url = f"http://{host}:{port}/health"
    deadline = time.time() + timeout
    last_note = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                body = json.loads(r.read().decode("utf-8", "ignore"))
            if body.get("database") == "ok":
                return body
        except urllib.error.HTTPError as e:
            if e.code == 503:
                note = "后端已启动，等待数据库就绪…"
                if note != last_note:
                    log.write(note)
                    last_note = note
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"/health 未在 {timeout}s 内就绪（见日志）")


def stop_backend(proc: subprocess.Popen, log) -> None:
    """优雅关停：terminate → wait(10) → kill。

    Windows 下 terminate 即硬杀（无 SIGTERM 语义），uvicorn 无关键清理逻辑，可接受。
    """
    if proc.poll() is not None:
        return
    log.write("正在停止后端…")
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    if proc.poll() is not None:
        log.write(f"后端已停止 (exit {proc.returncode})")


def spawn_monitor(proc: subprocess.Popen, on_crash) -> threading.Thread:
    """后台线程等待子进程退出；非正常退出 → on_crash(rc)。"""
    def _monitor() -> None:
        rc = proc.wait()
        if rc != 0:
            on_crash(rc)

    t = threading.Thread(target=_monitor, daemon=True)
    t.start()
    return t
