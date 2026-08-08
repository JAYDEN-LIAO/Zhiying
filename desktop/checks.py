"""环境检查：config / 模型 / 端口 / Docker。

刻意不 import core.* —— 避免拉起 torch/transformers 等重依赖。
config.yaml 用 pyyaml 直读；模型检查复用 deploy/download_models.py --verify-only。
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8011
MODEL_ROOT = "models"

_COMPONENT_RE = re.compile(r"^(\w+)\s*\([^)]*\):\s*(OK|MISSING|INCOMPLETE)", re.IGNORECASE)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def read_server_config(root: Path) -> dict:
    """读 config/config.yaml 的 server 段；缺失/异常时给默认 127.0.0.1:8011。"""
    cfg_path = root / "config" / "config.yaml"
    if not cfg_path.exists():
        return {"host": DEFAULT_HOST, "port": DEFAULT_PORT, "config_exists": False}
    host, port = DEFAULT_HOST, DEFAULT_PORT
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        server = raw.get("server") or {}
        host = server.get("host", DEFAULT_HOST)
        port = int(server.get("port", DEFAULT_PORT))
    except Exception:
        pass
    return {"host": host, "port": port, "config_exists": True}


def check_config_file(root: Path) -> bool:
    return (root / "config" / "config.yaml").exists()


def check_models(root: Path, python: str | None = None) -> dict:
    """跑 download_models.py --verify-only，返回各组件 OK 状态。

    返回 {"present": {component: bool}, "exit_code": int, "error": str|None}。
    """
    python = python or sys.executable
    script = root / "deploy" / "download_models.py"
    cmd = [python, str(script), "--component", "all", "--model-root", str(root / MODEL_ROOT), "--verify-only"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:  # 超时 / 找不到 python 等
        return {"present": {}, "exit_code": -1, "error": str(e)}
    present: dict[str, bool] = {}
    for line in (proc.stdout or "").splitlines():
        m = _COMPONENT_RE.match(line.strip())
        if m:
            present[m.group(1).lower()] = m.group(2).upper() == "OK"
    return {"present": present, "exit_code": proc.returncode, "error": None}


def probe_health(host: str, port: int) -> dict | None:
    """探测 http://host:port/health，返回 JSON body；连不上返回 None。"""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return None


def check_port(port: int, host: str = DEFAULT_HOST) -> dict:
    """探测 host:port 占用状态：free / already_running / conflict。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect((host, port))
        occupied = True
    except OSError:
        occupied = False
    finally:
        s.close()
    if not occupied:
        return {"state": "free"}
    body = probe_health(host, port)
    if body and body.get("service") == "zhiying":
        return {"state": "already_running", "health": body}
    return {"state": "conflict"}


def check_docker() -> dict:
    """Docker 引擎是否可用（docker info 退出码）。"""
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=15)
        return {"ok": proc.returncode == 0}
    except Exception:
        return {"ok": False}
