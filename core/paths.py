"""项目根解析 — 源码模式与封装（PyInstaller 字节码包）统一入口。

封装模式：后端从 exe 的 _internal 字节码包 import，__file__ 指向 _internal，
由桌面壳启动器注入 `ZHIYING_PROJECT_ROOT`（= exe 所在目录，config/models/data/
.venv/vendor 都在那）。源码模式：Path(__file__) 推断（本项目惯例）。
"""
import os
from pathlib import Path


def project_root() -> Path:
    env = os.environ.get("ZHIYING_PROJECT_ROOT")
    if env:
        return Path(env)
    # core/paths.py → 项目根 = 上两级
    return Path(__file__).resolve().parent.parent
