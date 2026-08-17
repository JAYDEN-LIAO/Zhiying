"""后端子进程启动器（封装模式）— 从字节码包 import main:app 并起 uvicorn。

由桌面壳用 .venv python 运行本文件。环境变量：
  ZHIYING_BACKEND_ROOT : 字节码包目录（= exe 的 _internal/backend_pyc，无明文源码）
  ZHIYING_PROJECT_ROOT : 应用根（= exe 所在目录；config/models/data/.venv/vendor 在那）
  ZHIYING_BACKEND_HOST / ZHIYING_BACKEND_PORT
本文件本身是纯启动逻辑（几行，无业务代码），客户端可读无害。
"""
import os
import sys

_root = os.environ.get("ZHIYING_BACKEND_ROOT")
if _root:
    sys.path.insert(0, _root)
# 让 core.paths.project_root() 在封装模式拿到 exe 所在目录
os.environ["ZHIYING_PROJECT_ROOT"] = os.environ.get("ZHIYING_PROJECT_ROOT", "")

import uvicorn


def main() -> None:
    host = os.environ.get("ZHIYING_BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("ZHIYING_BACKEND_PORT", "8011"))
    uvicorn.run("main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
