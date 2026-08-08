"""生命周期状态机 + 线程安全全局状态。

桌面启动器的状态分两大类：
- 进程状态（State）：驱动主窗 splash 的展示与生命周期逻辑。
- 应用状态（AppState）：跨线程（生命周期循环 / pywebview js_api / 崩溃监测）共享。
"""
from __future__ import annotations

from enum import Enum
from threading import Lock


class State(str, Enum):
    INIT = "init"                  # 初始
    CHECKING = "checking"          # 环境检查
    DB_START = "db_start"          # docker compose up -d db
    BACKEND_START = "backend_start"  # 起 uvicorn 子进程
    READY = "ready"                # /health 200 且 database=ok
    STOPPING = "stopping"          # 优雅关停中
    STOPPED = "stopped"            # 已停止
    ERROR = "error"                # 出错（detail 带原因）


class AppState:
    """进程级单例，线程安全。SplashApi / LogApi / 生命周期循环共享。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._state = State.INIT
        self._message = "启动中…"
        self._meta: dict = {}

    def set(self, state: State, message: str = "", **meta) -> None:
        with self._lock:
            self._state = state
            if message:
                self._message = message
            self._meta.update(meta)

    def get(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "message": self._message,
                "port": self._meta.get("port"),
                "version": self._meta.get("version"),
                "detail": self._meta.get("detail"),
            }


app_state = AppState()
