"""后端子进程启动器（统一入口，封装/源码双模式）+ 父进程存活看门狗。

由桌面壳用 .venv python 运行本文件。环境变量：
  ZHIYING_BACKEND_ROOT : 字节码包目录（封装模式 = exe _internal/backend_pyc，无明文源码；
                         源码模式不设 → 从当前目录 import 源码）
  ZHIYING_PROJECT_ROOT : 应用根（= exe 所在目录 / 项目根；config/models/data/.venv 在那）
  ZHIYING_BACKEND_HOST / ZHIYING_BACKEND_PORT
  ZHIYING_PARENT_PID   : 父进程（启动器）PID —— 看门狗用
本文件是纯启动/看门狗逻辑（无业务代码），客户端可读无害。
看门狗移植自 desktop/backend_child.py：父进程被强杀（End Task/崩溃）后 ~3s 内
os._exit(3)，不留占用端口/显存的孤儿后端（Windows 持父进程句柄，免疫 PID 复用）。
"""
from __future__ import annotations

import os
import sys
import threading
import time

_root = os.environ.get("ZHIYING_BACKEND_ROOT")
if _root:
    sys.path.insert(0, _root)
# 封装模式下让 core.paths.project_root() 拿到应用根（exe 所在目录）
os.environ["ZHIYING_PROJECT_ROOT"] = os.environ.get("ZHIYING_PROJECT_ROOT", "")

import uvicorn

_HOST = os.environ.get("ZHIYING_BACKEND_HOST", "127.0.0.1")
_PORT = int(os.environ.get("ZHIYING_BACKEND_PORT", "8011"))
_PARENT_PID = int(os.environ.get("ZHIYING_PARENT_PID") or os.getppid())

# Windows：以 SYNCHRONIZE 权限持有父进程句柄并一直保持打开（免疫 PID 复用）。
_PARENT_HANDLE = None
if os.name == "nt":
    import ctypes

    _SYNCHRONIZE = 0x00100000
    _PARENT_HANDLE = ctypes.windll.kernel32.OpenProcess(_SYNCHRONIZE, False, _PARENT_PID)


def _parent_alive() -> bool:
    if os.name == "nt":
        if not _PARENT_HANDLE:
            return True
        return ctypes.windll.kernel32.WaitForSingleObject(_PARENT_HANDLE, 0) != 0
    try:
        os.kill(_PARENT_PID, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _watchdog() -> None:
    while True:
        time.sleep(3)
        if not _parent_alive():
            os._exit(3)


def main() -> None:
    threading.Thread(target=_watchdog, daemon=True).start()
    uvicorn.run("main:app", host=_HOST, port=_PORT, log_level="info")


if __name__ == "__main__":
    main()
