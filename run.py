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
      1. POSTGRES_URI 显式指定（外部数据库）→ 跳过自举；
      2. 内嵌模式：本实例端口（data/db_port.txt，终身固定）已在监听 → 复用；
         否则 start_db 内置端口解析（config 端口空闲才用，被占自动让位）——
         绝不盲目连默认端口上已监听的来路不明 PG（多安装串库会向量维度错配炸管道）；
      3. Docker 回退模式：config 端口已在监听 → 复用；否则 compose up；
      4. 否则明确报错。
    最后把本进程 POSTGRES_URI 钉到实例库（core 读 env 优先于 config database.uri）。
    """
    if os.environ.get("POSTGRES_URI"):
        print("[db] POSTGRES_URI 显式指定（外部数据库），跳过自举")
        return 0

    from desktop.db import (
        db_available,
        db_backend,
        db_uri_for_backend,
        resolve_db_port,
        start_db,
        wait_db_healthy,
    )

    root = Path(__file__).resolve().parent
    if not db_available(root):
        print("[db] 无可用数据库后端：需内嵌 postgres（vendor/pg）或启动 Docker Desktop")
        return 1
    backend = db_backend(root)
    log = _ConsoleLog()

    if backend == "embedded":
        try:
            port = resolve_db_port(root, log)
        except RuntimeError as e:
            print(f"[db] {e}")
            return 1
        print(f"[db] 数据库后端: {backend}（实例端口 {port}）...")
        # 复用/启动/让位逻辑都在 start_db 内（pg_ctl status 只认本实例 pgdata 的进程）
        if not start_db(root, log):
            print("[db] 数据库启动失败（详见上方日志）")
            return 1
        if not wait_db_healthy(root, log):
            print(f"[db] 数据库未在超时内就绪（{backend}）")
            return 1
    else:
        cfg = load_config()
        uri = (cfg.get("database") or {}).get("uri") or ""
        m = re.search(r"@([^:/@]+):(\d+)/", uri)
        host, port = (m.group(1), int(m.group(2))) if m else ("localhost", 5432)
        probe_host = "::1" if host == "::1" else "127.0.0.1"
        if _port_open(probe_host, port):
            print(f"[db] {probe_host}:{port} 已有数据库在监听 — 直接复用")
        else:
            print(f"[db] 启动数据库后端: {backend} ...")
            if not start_db(root, log):
                print("[db] 数据库启动失败（详见上方日志）")
                return 1
            if not wait_db_healthy(root, log):
                print(f"[db] 数据库未在超时内就绪（{backend}）")
                return 1

    os.environ["POSTGRES_URI"] = db_uri_for_backend(root, log)
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
