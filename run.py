"""本地开发启动入口 — 按 config.yaml 的 server 段绑定 host/port。

`uvicorn main:app` 的端口只认 CLI `--port`，不读 config.yaml 的
`server.port`——直接用 uvicorn 启动会与前端 vite 代理（读同一份配置）
错位。本入口让"配置即真相"：

    python run.py        # → 绑定 config.yaml server.host:server.port，reload 模式

生产部署用 `start.sh` / systemd（`uvicorn main:app --port 8011`），不走本文件。
"""
import uvicorn

from core.config_loader import load_config


def _server_bind() -> tuple[str, int]:
    """从 config.yaml 读取 server 段的 host/port（兼容 dict 与 pydantic model）。"""
    cfg = load_config()
    server = getattr(cfg, "server", None) or {}
    host = getattr(server, "host", None) or server.get("host", "0.0.0.0")
    port = getattr(server, "port", None) or server.get("port", 8011)
    return host, port


if __name__ == "__main__":
    host, port = _server_bind()
    print(f"[run.py] binding {host}:{port} (from config.yaml server section)")
    uvicorn.run("main:app", host=host, port=port, reload=True)
