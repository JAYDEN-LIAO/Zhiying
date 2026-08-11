"""Docker compose db 服务管理（根目录 docker-compose.yaml 的 db 服务）。"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

# Windows 无窗 exe spawn console 子进程（docker.exe）会弹黑框终端 → 一律禁止分配新控制台。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

CONTAINER = "zhiying_postgres"
COMPOSE_FILE = "docker-compose.yaml"


def docker_available() -> bool:
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=15,
                              creationflags=_NO_WINDOW)
        return proc.returncode == 0
    except Exception:
        return False


def db_container_health(root: Path) -> str:
    """返回容器健康状态：healthy / starting / unhealthy / ''（未找到或 docker 不可用）。"""
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        )
    except Exception:
        return ""
    out = (proc.stdout or "").strip()
    return out if proc.returncode == 0 else ""


def start_db(root: Path, log, timeout: int = 180) -> bool:
    """docker compose up -d db。输出逐行进日志。"""
    cmd = ["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "db"]
    log.write("$ " + " ".join(cmd))
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(root),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=_NO_WINDOW,
        )
        for line in proc.stdout:
            log.write(line.rstrip())
        proc.wait(timeout=timeout)
        return proc.returncode == 0
    except Exception as e:
        log.write(f"启动数据库容器失败: {e}")
        return False


def wait_db_healthy(root: Path, log, timeout: int = 120) -> bool:
    """轮询容器健康直到 healthy；超时返回 False。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = db_container_health(root)
        if status == "healthy":
            log.write("数据库容器已就绪 (healthy)")
            return True
        if status == "unhealthy":
            log.write("数据库容器状态为 unhealthy，继续等待…")
        time.sleep(5)
    log.write(f"等待数据库容器 healthy 超时（{timeout}s），请检查 Docker Desktop")
    return False
