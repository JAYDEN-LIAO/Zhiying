"""本地开发启动入口 — 按 config.yaml 的 server 段绑定 host/port。

`uvicorn main:app` 的端口只认 CLI `--port`，不读 config.yaml 的
`server.port`——直接用 uvicorn 启动会与前端 vite 代理（读同一份配置）
错位。本入口让"配置即真相"：

    python run.py        # → 绑定 config.yaml server.host:server.port，reload 模式

生产部署用 `start.sh` / systemd（`uvicorn main:app --port 8011`），不走本文件。
"""
import os
import re
import socket
from pathlib import Path

import uvicorn

from core.config_loader import load_config


def _server_bind() -> tuple[str, int]:
    """从 config.yaml 读取 server 段的 host/port（兼容 dict 与 pydantic model）。"""
    cfg = load_config()
    server = getattr(cfg, "server", None) or {}
    host = getattr(server, "host", None) or server.get("host", "0.0.0.0")
    port = getattr(server, "port", None) or server.get("port", 8011)
    return host, port


class _ConsoleLog:
    """适配 desktop/db.py 的 log 接口（write(str)），直接打印到控制台。"""

    def write(self, msg: str) -> None:
        print(msg)


def _port_open(host: str, port: int) -> bool:
    """TCP 探测端口是否有进程在监听（postgres 接受连接即视为就绪）。"""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _ensure_database() -> int:
    """开发启动前确保数据库就绪（0=就绪，非 0=失败退出）。

    与桌面启动器 desktop/db.py 同优先级：
      1. 有效 URI 端口已在监听 → 直接复用（docker 已起 / 系统 PG / 内嵌已起）；
      2. 否则本机有 vendor/pg（内嵌便携 postgres）→ 启动内嵌；
      3. 否则 Docker daemon 可用 → docker compose up -d db；
      4. 否则明确报错。
    有效 URI 解析与 core/db.py 同源（env POSTGRES_URI → config database.uri → 兜底）。
    """
    cfg = load_config()
    uri = (
        os.environ.get("POSTGRES_URI")
        or (cfg.get("database") or {}).get("uri")
        or "postgresql+asyncpg://zhiying:zhiying@localhost:5432/zhiying"
    )
    m = re.search(r"@([^:/@]+):(\d+)/", uri)
    host, port = (m.group(1), int(m.group(2))) if m else ("localhost", 5432)

    if host not in ("localhost", "127.0.0.1", "::1"):
        print(f"[db] 外部数据库 {host}:{port}（POSTGRES_URI / config 指定），跳过自举")
        return 0

    probe_host = "::1" if host == "::1" else "127.0.0.1"
    if _port_open(probe_host, port):
        print(f"[db] {probe_host}:{port} 已有数据库在监听 — 直接复用")
        return 0

    from desktop.db import db_available, db_backend, start_db, wait_db_healthy

    root = Path(__file__).resolve().parent
    if not db_available(root):
        print("[db] 无可用数据库后端：需内嵌 postgres（vendor/pg）或启动 Docker Desktop")
        return 1
    backend = db_backend(root)
    print(f"[db] 启动数据库后端: {backend} ...")
    log = _ConsoleLog()
    if not start_db(root, log):
        print("[db] 数据库启动失败（详见上方日志）")
        return 1
    if not wait_db_healthy(root, log):
        print(f"[db] 数据库未在超时内就绪（{backend}）")
        return 1
    return 0


if __name__ == "__main__":
    import sys

    if _ensure_database() != 0:
        sys.exit(1)

    host, port = _server_bind()
    print(f"[run.py] binding {host}:{port} (from config.yaml server section)")

    # Windows 禁用 reload：uvicorn reload=True → use_subprocess=True → SelectorEventLoop，
    # 而 Selector 不支持 asyncio.create_subprocess_exec（ffprobe/ffmpeg 全链路依赖子进程）
    # → NotImplementedError。桌面壳(backend_launcher)同样无 reload；后端加载 ~4GB embedder，
    # 热重载每次改码重载模型本就有害。Linux 保留热重载（Selector 支持子进程）。
    uvicorn.run("main:app", host=host, port=port, reload=(sys.platform != "win32"))
