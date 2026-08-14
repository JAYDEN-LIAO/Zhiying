"""后端子进程入口：以编程方式运行 uvicorn，并带「父进程存活看门狗」。

启动器以 `python -m desktop.backend_child <port>` 拉起（cwd=项目根）。
若启动器被强制结束（任务管理器 End Task / 崩溃 / Ctrl+C 硬杀），
看门狗在 ~3s 内 os._exit(3)，确保后端进程退出、CPU/GPU 显存由 OS 自动释放——
不留占用 8011 + 显存的孤儿后端（Windows 用持有父进程句柄信号检测，免疫 PID 复用）。
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

# Windows：启动时以 SYNCHRONIZE 权限持有父进程句柄并一直保持打开。
# 父进程退出后该句柄转为「已信号」态；即便父 PID 后来被别的进程复用，
# 句柄仍指向原进程对象，检测不受 PID 复用影响 —— 这是 Windows 下可靠的
# 父进程存活检测（原 OpenProcess 探测会被 PID 复用骗过：父死后 PID 被顶替，
# OpenProcess 打到一个无关活进程 → 看门狗误判父还活着 → 孤儿后端永不退出）。
_PARENT_HANDLE = None
if os.name == "nt":
    import ctypes

    _SYNCHRONIZE = 0x00100000  # 等待进程对象进入 signaled 所需的最小访问权
    _PARENT_HANDLE = ctypes.windll.kernel32.OpenProcess(_SYNCHRONIZE, False, _PARENT_PID)


def _parent_alive() -> bool:
    """父进程（启动器）是否仍存活。"""
    if os.name == "nt":
        # 句柄打开失败（同用户 spawn 不会发生）→ 保守视为存活
        if not _PARENT_HANDLE:
            return True
        # WaitForSingleObject(handle, 0) == WAIT_OBJECT_0(0) → 父进程已退出（已信号）；
        # 否则（WAIT_TIMEOUT）→ 仍存活。
        return ctypes.windll.kernel32.WaitForSingleObject(_PARENT_HANDLE, 0) != 0
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
