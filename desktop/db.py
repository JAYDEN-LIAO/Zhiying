"""数据库服务管理 — 内嵌便携 PostgreSQL（vendor/pg，优先）或 Docker compose（回退）。

内嵌模式（封装交付）：用 `vendor/pg/bin` 下的 initdb/pg_ctl 管理本地 postgres 进程
  - 数据目录 <root>/data/pgdata（首次 initdb，随后 pg_ctl start/stop）
  - 监听 127.0.0.1:<config database.uri 端口，默认 5432>，用户 zhiying，trust 认证
  - 首次启动自动建 `zhiying` 库（后端 init_db 负责建表）
Docker 模式（开发机回退）：无 vendor/pg 时走 docker compose up db。
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

# Windows 无窗 exe spawn console 子进程（docker.exe / pg_ctl）会弹黑框终端 → 禁止分配新控制台。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

CONTAINER = "zhiying_postgres"
COMPOSE_FILE = "docker-compose.yaml"

_EXT = ".exe" if os.name == "nt" else ""
_PG_DATA_REL = "data/pgdata"
_PG_LOG_REL = "data/pg.log"


# ─────────────────────────────────────────────
# 后端判定
# ─────────────────────────────────────────────

def _pg_bin(root: Path, name: str) -> Path:
    return root / "vendor" / "pg" / "bin" / (name + _EXT)


def db_backend(root: Path) -> str:
    """'embedded'（vendor/pg 便携 postgres 存在）/ 'docker'（回退）。"""
    return "embedded" if _pg_bin(root, "pg_ctl").exists() else "docker"


def _pg_port(root: Path) -> int:
    """从 config/config.yaml 的 database.uri 解析端口（默认 5432）。"""
    try:
        import yaml
        cfg = yaml.safe_load((root / "config" / "config.yaml").read_text(encoding="utf-8"))
        uri = (cfg.get("database") or {}).get("uri") or ""
        m = re.search(r":(\d+)/[^/]+$", uri)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 5432


def docker_available() -> bool:
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=15,
                              creationflags=_NO_WINDOW)
        return proc.returncode == 0
    except Exception:
        return False


def db_available(root: Path) -> bool:
    """数据库后端是否可用：内嵌 pg（vendor/pg）或 docker 任一可用即 True。"""
    if db_backend(root) == "embedded":
        return _pg_bin(root, "pg_ctl").exists()
    return docker_available()


# ─────────────────────────────────────────────
# 内嵌 postgres（vendor/pg + pg_ctl）
# ─────────────────────────────────────────────

def _run(cmd: list[str], log, timeout: int) -> bool:
    log.write("$ " + " ".join(str(c) for c in cmd))
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            creationflags=_NO_WINDOW,
        )
        for line in proc.stdout:
            log.write(line.rstrip())
        proc.wait(timeout=timeout)
        return proc.returncode == 0
    except Exception as e:
        log.write(f"执行失败: {e}")
        return False


def _initdb_if_needed(root: Path, log) -> bool:
    data = _pg_data(root)
    if (data / "PG_VERSION").is_file():
        return True  # 已初始化
    data.mkdir(parents=True, exist_ok=True)
    log.write("首次初始化 PostgreSQL 数据目录…")
    return _run(
        [str(_pg_bin(root, "initdb")), "-D", str(data), "-U", "zhiying",
         "-E", "UTF8", "--auth=trust", "--no-locale"],
        log, timeout=120,
    )


def _ensure_pg_conf(root: Path) -> None:
    """追加监听地址 + 端口覆盖（initdb 生成的 postgresql.conf 末尾追加，后者生效）。"""
    data = _pg_data(root)
    conf = data / "postgresql.conf"
    marker = "# Zhiying desktop overrides"
    if conf.exists() and marker in conf.read_text(encoding="utf-8", errors="ignore"):
        return
    port = _pg_port(root)
    with conf.open("a", encoding="utf-8") as f:
        f.write(f"\n{marker}\nlisten_addresses = '127.0.0.1'\nport = {port}\n"
                f"unix_socket_directories = '{data}'\n")


def _psql(root: Path, port: int, db: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(_pg_bin(root, "psql")), "-h", "127.0.0.1", "-p", str(port), "-U", "zhiying",
         "-d", db, "-tAc", sql],
        capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW,
    )


def _create_db_if_needed(root: Path, port: int, log) -> None:
    r = _psql(root, port, "postgres", "SELECT 1 FROM pg_database WHERE datname='zhiying'")
    if r.stdout.strip() == "1":
        return
    log.write("创建数据库 zhiying …")
    _psql(root, port, "postgres", "CREATE DATABASE zhiying")


def _start_embedded(root: Path, log, timeout: int) -> bool:
    if not _initdb_if_needed(root, log):
        log.write("[FAIL] initdb 失败")
        return False
    _ensure_pg_conf(root)
    data = _pg_data(root)
    logfile = root / _PG_LOG_REL
    logfile.parent.mkdir(parents=True, exist_ok=True)
    if not _run([str(_pg_bin(root, "pg_ctl")), "-D", str(data), "-l", str(logfile), "start", "-w"],
                log, timeout=timeout):
        log.write("[FAIL] pg_ctl start 失败，详见 data/pg.log")
        return False
    _create_db_if_needed(root, _pg_port(root), log)
    log.write("内嵌 PostgreSQL 已启动")
    return True


# ─────────────────────────────────────────────
# 对外接口（app.py 调用）
# ─────────────────────────────────────────────

def start_db(root: Path, log, timeout: int = 180) -> bool:
    """启动数据库：内嵌 pg（vendor/pg）或 docker compose。"""
    if db_backend(root) == "embedded":
        return _start_embedded(root, log, timeout)
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


def db_container_health(root: Path) -> str:
    """Docker 容器健康状态：healthy / starting / unhealthy / ''。"""
    try:
        proc = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        )
    except Exception:
        return ""
    out = (proc.stdout or "").strip()
    return out if proc.returncode == 0 else ""


def wait_db_healthy(root: Path, log, timeout: int = 120) -> bool:
    """轮询数据库就绪（内嵌 pg_isready / docker healthy）；超时返回 False。"""
    backend = db_backend(root)
    if backend == "embedded":
        port = _pg_port(root)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                proc = subprocess.run(
                    [str(_pg_bin(root, "pg_isready")), "-h", "127.0.0.1", "-p", str(port), "-U", "zhiying"],
                    capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
                )
            except Exception:
                proc = None
            if proc is not None and proc.returncode == 0:
                log.write("内嵌 PostgreSQL 已就绪")
                return True
            time.sleep(1)
        log.write(f"等待内嵌 PostgreSQL 就绪超时（{timeout}s），详见 data/pg.log")
        return False

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


def stop_db(root: Path, log) -> bool:
    """停止数据库（内嵌 pg_ctl stop；docker 由 compose down 交给应用退出流程）。"""
    if db_backend(root) == "embedded":
        return _run([str(_pg_bin(root, "pg_ctl")), "-D", str(_pg_data(root)), "stop", "-m", "fast"],
                    log, timeout=60)
    return True


def _pg_data(root: Path) -> Path:
    return root / _PG_DATA_REL
