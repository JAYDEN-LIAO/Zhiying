"""线程安全日志汇聚：环形缓冲 + 落盘 + 增量拉取。

后端子进程的 stdout 由 reader 线程喂进来；控制窗的 LogApi 用 get_since 增量拉取渲染。
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TextIO


class LogSink:
    """线程安全日志桶。最多保留 maxlen 条，超出丢弃最旧。"""

    def __init__(self, maxlen: int = 2000, path: Path | None = None, echo: bool = False) -> None:
        self._buf: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._written = 0  # 累计写入条数（单调，用于增量拉取）
        self._path = path
        self._echo = echo
        self._file: TextIO | None = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(path, "a", encoding="utf-8")

    def write(self, line: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        record = f"[{ts}] {line}"
        if self._echo:
            print(record, flush=True)
        with self._lock:
            self._buf.append(record)
            self._written += 1
            if self._file:
                try:
                    self._file.write(record + "\n")
                    self._file.flush()
                except OSError:
                    pass

    def get_since(self, index: int) -> tuple[int, list[str]]:
        """返回 (最新已写条数, 从 index 起的增量行)。

        若客户端落后于环形缓冲的最早记录（丢了旧行），直接给全缓冲补齐。
        """
        with self._lock:
            written = self._written
            buf = list(self._buf)
        oldest = written - len(buf)  # buf[0] 对应的全局序号
        if index >= written:
            return written, []
        if index >= oldest:
            return written, buf[index - oldest:]
        return written, buf

    def close(self) -> None:
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except OSError:
                    pass
                self._file = None
