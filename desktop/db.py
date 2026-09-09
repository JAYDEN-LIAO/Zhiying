"""数据库服务管理 — 内嵌便携 PostgreSQL（vendor/pg，优先）或 Docker compose（回退）。

内嵌模式（封装交付）：用 `vendor/pg/bin` 下的 initdb/pg_ctl 管理本地 postgres 进程
  - 数据目录 <root>/data/pgdata（首次 initdb，随后 pg_ctl start/stop）
  - 监听 127.0.0.1:<本实例端口>，用户 zhiying，trust 认证
  - 端口每实例终身固定（data/db_port.txt）：config 端口（默认 5432）空闲才用，
    被其它程序/其他 Zhiying 实例占用则自动换空闲端口 —— 根治多安装同抢 5432 串库
    （8b/2b 档位不同、表维度不同，串库 = 向量维度错配炸管道）
  - 首次启动自动建 `zhiying` 库（后端 init_db 负责建表）
Docker 模式（开发机回退）：无 vendor/pg 时走 docker compose up db（固定映射 config 端口）。
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path

# Windows 无窗 exe spawn console 子进程（docker.exe / pg_ctl）会弹黑框终端 → 禁止分配新控制台。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

CONTAINER = "zhiying_postgres"
COMPOSE_FILE = "docker-compose.yaml"

_EXT = ".exe" if os.name == "nt" else ""
_PG_DATA_REL = "data/pgdata"
_PG_LOG_REL = "data/pg.log"
_DB_PORT_REL = "data/db_port.txt"


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


# ── 每实例端口（根治多安装/残留进程同抢 5432 串库）──────────

def _persisted_port(root: Path) -> int | None:
    """data/db_port.txt 记录的本实例端口（首次启动落盘，终身不变）。"""
    try:
        return int((root / _DB_PORT_REL).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _persist_port(root: Path, port: int) -> None:
    p = root / _DB_PORT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(port), encoding="utf-8")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _our_pg_running(root: Path, log) -> bool:
    """本实例 pgdata 的 postgres 是否在运行（pg_ctl status 按 pgdata/postmaster.pid 判定）。

    只认本实例数据目录——别的 Zhiying 实例 / 系统其它 PG 占着端口不算「我们的在运行」，
    这是复用与 stop 的安全边界（绝不误判、误杀别人的 PG）。
    """
    return _run([str(_pg_bin(root, "pg_ctl")), "-D", str(_pg_data(root)), "status"], log, timeout=15)


def _conf_port(root: Path) -> int | None:
    """读本实例 postgresql.conf 里生效的 port 行（initdb 默认是注释行，不匹配）。"""
    try:
        text = (_pg_data(root) / "postgresql.conf").read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^port\s*=\s*(\d+)", text, re.M)
        return int(m.group(1)) if m else None
    except OSError:
        return None


def resolve_db_port(root: Path, log) -> int:
    """解析本实例 PostgreSQL 端口（内嵌模式；结果落盘 data/db_port.txt 终身固定）。

    优先级：
      1. data/db_port.txt 已有记录 → 直接用；
      2. 本实例 pg 残留进程还在跑（如上次强杀）→ 沿用其 conf 端口；
      3. config database.uri 的端口（默认 5432）空闲 → 用它；
      4. 被其它程序/其他 Zhiying 实例占用 → 从 5433 起扫空闲端口。
    任何情况下绝不复用一个我们无法证明属于自己的已占端口（防串库）。
    Docker 回退模式不适用（compose 固定映射），直接返回 config 端口。
    """
    if db_backend(root) != "embedded":
        return _pg_port(root)
    persisted = _persisted_port(root)
    if persisted:
        return persisted
    if _our_pg_running(root, log):
        port = _conf_port(root) or _pg_port(root)
        log.write(f"[db] 本实例 PostgreSQL 残留进程在跑，沿用端口 {port}")
        _persist_port(root, port)
        return port
    cfg_port = _pg_port(root)
    if _port_free(cfg_port):
        _persist_port(root, cfg_port)
        return cfg_port
    for port in range(cfg_port + 1, cfg_port + 137):
        if _port_free(port):
            log.write(f"[db] 端口 {cfg_port} 被其它程序/其他实例占用"
                      f"（可能另有 Zhiying 安装），本实例改用 {port}（终身固定，见 data/db_port.txt）")
            _persist_port(root, port)
            return port
    raise RuntimeError(f"{cfg_port + 1}-{cfg_port + 136} 均无空闲端口，无法启动内嵌 PostgreSQL")


def db_uri_for_backend(root: Path, log) -> str:
    """后端连接 URI：config database.uri 的端口替换为本实例端口（供 POSTGRES_URI env 注入）。

    外部数据库（host 非 localhost）原样返回；docker 回退模式端口即 config 端口，替换为等值。
    """
    uri = ""
    try:
        import yaml
        cfg = yaml.safe_load((root / "config" / "config.yaml").read_text(encoding="utf-8"))
        uri = (cfg.get("database") or {}).get("uri") or ""
    except Exception:
        pass
    m = re.search(r"@([^:/@]+):(\d+)/", uri)
    if not m:
        # config 无有效 uri → 按内嵌默认拼一个（仅本机实例）
        return f"postgresql+asyncpg://zhiying:zhiying@127.0.0.1:{resolve_db_port(root, log)}/zhiying"
    if m.group(1) not in ("localhost", "127.0.0.1", "::1"):
        return uri  # 外部数据库，不动
    port = resolve_db_port(root, log)
    return re.sub(r"(@[^:/@]+:)\d+(/)", lambda x: f"{x.group(1)}{port}{x.group(2)}", uri, count=1)


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
    tmp_path = None
    try:
        # 用临时文件代替 PIPE：pg_ctl 启动的 postgres 会继承 PIPE 写端，
        # `for line in proc.stdout` 会永不 EOF 卡死（postgres 一直持有管道）。文件方案不受影响。
        tmp = tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8")
        tmp_path = tmp.name
        proc = subprocess.Popen(
            cmd, stdout=tmp, stderr=subprocess.STDOUT, text=True,
            creationflags=_NO_WINDOW,
        )
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            log.write(f"[timeout] {timeout}s 超时，已终止")
            tmp.close()
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False
        tmp.close()
        # 用系统本地编码读（pg_ctl 输出是系统代码页，如中文 Windows = GBK；UTF-8 会解码成乱码再触发 print 编码错误）
        with open(tmp_path, errors="replace") as f:
            for line in f:
                log.write(line.rstrip())
        try:
            os.remove(tmp_path)
        except OSError:
            pass
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


def _ensure_pg_conf(root: Path, port: int) -> None:
    """追加/更新监听地址 + 实例端口（initdb 生成的 postgresql.conf 末尾追加，后者生效）。"""
    data = _pg_data(root)
    conf = data / "postgresql.conf"
    marker = "# Zhiying desktop overrides"
    if conf.exists():
        text = conf.read_text(encoding="utf-8", errors="ignore")
        if marker in text:
            # 端口可能随实例端口解析变化（如首次启动时 5432 被占改用 5433）→ 原地更新 port 行
            new_text = re.sub(r"(^port\s*=\s*)\d+", lambda m: f"{m.group(1)}{port}", text, count=1, flags=re.M)
            if new_text != text:
                conf.write_text(new_text, encoding="utf-8")
            return
    with conf.open("a", encoding="utf-8") as f:
        # ⚠️ 路径必须用正斜杠：PG 配置解析器把单引号里的 `\` 当转义剥掉（'D:\data' → 'D:data'）
        f.write(f"\n{marker}\nlisten_addresses = '127.0.0.1'\nport = {port}\n"
                f"unix_socket_directories = '{data.as_posix()}'\n")


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
    port = resolve_db_port(root, log)
    _ensure_pg_conf(root, port)
    data = _pg_data(root)
    logfile = root / _PG_LOG_REL
    logfile.parent.mkdir(parents=True, exist_ok=True)
    # 只复用「本实例 pgdata 的」残留进程（pg_ctl status 判定）；端口被别人占时
    # resolve_db_port 已让位换端口 —— 绝不连去一个来路不明的已监听端口（防串库）
    if _our_pg_running(root, log):
        log.write("内嵌 PostgreSQL 已在运行（复用本实例残留进程）")
    elif not _port_free(port):
        log.write(f"[FAIL] 本实例端口 {port} 被其它程序占用且不是本实例的 PostgreSQL"
                  f"（data/db_port.txt 终身固定）——请释放该端口后重试")
        return False
    elif not _run([str(_pg_bin(root, "pg_ctl")), "-D", str(data), "-l", str(logfile), "start", "-w"],
                  log, timeout=timeout):
        log.write("[FAIL] pg_ctl start 失败，详见 data/pg.log")
        return False
    else:
        log.write(f"内嵌 PostgreSQL 已启动（端口 {port}）")
    _create_db_if_needed(root, port, log)
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
        port = resolve_db_port(root, log)
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
