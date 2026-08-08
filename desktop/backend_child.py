"""后端子进程入口：以编程方式运行 uvicorn，并带「父进程存活看门狗」。

启动器以 `python -m desktop.backend_child <port>` 拉起（cwd=项目根）。
若启动器被强制结束（任务管理器 End Task / 崩溃 / Ctrl+C 硬杀），
看门狗在 ~3s 内 os._exit(3)，确保后端进程退出、CPU/GPU 显存由 OS 自动释放——
不留占用 8011 + 显存的孤儿后端。
正常优雅关停（launcher stop_backend）不受影响：SIGTERM → uvicorn 自行退出。
"""
from __future__ import annotations

import os
import sys
import threading
import time

import uvicorn

_HOST = "127.0.0.1"  # 桌面端后端永远只绑定本机
_PARENT_PID = int(os.environ.get("ZHIYING_PARENT_PID") or os.getppid())
_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8011


def _parent_alive() -> bool:
    """父进程（启动器）是否仍存活。"""
    if os.name == "nt":
        import ctypes

        # OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION=0x1000, inherit=False, pid)
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, _PARENT_PID)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(_PARENT_PID, 0)
        return True
    except ProcessLookupError:
        return False  # 父进程已不存在
    except PermissionError:
        return True  # 存在但无权探测 → 视为存活


def _watchdog() -> None:
    while True:
        time.sleep(3)
        if not _parent_alive():
            # 启动器已死：立即自杀，释放显存/端口
            os._exit(3)


def main() -> None:
    threading.Thread(target=_watchdog, daemon=True).start()
    uvicorn.run("main:app", host=_HOST, port=_PORT, log_level="info")


if __name__ == "__main__":
    main()
