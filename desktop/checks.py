"""环境检查：config / 模型 / 端口 / Docker / Python / 依赖 / ffmpeg / 前端 dist。

刻意不 import core.* —— 避免拉起 torch/transformers 等重依赖。
config.yaml 用 pyyaml 直读；模型检查复用 deploy/download_models.py --verify-only。
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

import psutil  # 桌面壳依赖；轻量，非 torch 类重依赖

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8011
MODEL_ROOT = "models"

_COMPONENT_RE = re.compile(r"^(\w+)\s*\([^)]*\):\s*(OK|MISSING|INCOMPLETE)", re.IGNORECASE)

# 后端关键依赖（用于"环境是否就绪"的轻量探测；不搞全量 pip list）
_REQUIRED_MODULES = ["fastapi", "uvicorn", "sqlalchemy", "torch", "transformers", "yaml", "httpx", "PIL", "pgvector", "aiosqlite"]

# Windows 无窗 exe spawn console 子进程（venv python / docker）会弹黑框终端 → 禁止分配新控制台。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller 冻结：分发把 exe + _internal/ 放到项目根，exe 所在目录即项目根。
        # __file__ 此时指向 bundle 内（_internal/app.py），按它推导不可靠。
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def install_script_name() -> str:
    """部署脚本文件名（平台感知）：Windows → setup_windows.ps1，其它 → setup_linux.sh。"""
    return "setup_windows.ps1" if sys.platform.startswith("win") else "setup_linux.sh"


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
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, creationflags=_NO_WINDOW)
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


def _is_launcher(proc) -> bool:
    """判断进程是否为智影桌面启动器：冻结壳 exe，或开发态 `python <...>/app.py`。

    后端（backend_child）的父进程在合法情形下必然是两者之一；其它进程 → 判定父已死/PID 被复用。
    """
    try:
        name = proc.name()
        if name in ("智影桌面端", "智影桌面端.exe"):
            return True
        if name in ("python", "python.exe", "python3"):
            return any(c.replace("\\", "/").endswith("app.py") for c in proc.cmdline())
        return False
    except Exception:
        return False


def _has_live_launcher_ancestor(ppid, max_hops=5) -> bool:
    """从后端父进程起，沿父链向上找「仍存活的智影桌面启动器」。

    实测 `.venv\\Scripts\\python.exe` 是重定向器：壳 → 重定向器 → 真解释器 三层，
    后端（真解释器）的父进程可能是重定向器而非壳本身，故必须沿链向上找。
    找到存活启动器 → 受管（不清扫）；链断裂（父已死 / PID 被复用成无关进程）
    或走完 max_hops 仍无启动器 → 判孤儿，应清扫。
    """
    cur = ppid
    for _ in range(max_hops):
        if not cur:
            return False
        try:
            proc = psutil.Process(cur)
            if not proc.is_running():
                return False
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
            return False
        if _is_launcher(proc):
            return True
        cur = proc.ppid()
    return False


def sweep_orphan_backends(port: int, log=None) -> int:
    """启动前清理「父进程已死/非启动器」的遗留孤儿后端子进程，返回清理数量。

    backend_child 看门狗（持有父进程句柄信号检测）正常不产生孤儿；此处兜底清理
    旧版本代码遗留的孤儿，防止其占住端口被误复用，或锁住 _internal 里 DLL
    （曾引发部署拷贝嵌套 + 误报杀软）。仅杀 command line 含 desktop.backend_child
    且端口匹配的进程，绝不误伤其它 python。
    """
    killed = 0
    for proc in psutil.process_iter(["pid", "ppid", "cmdline"]):
        try:
            cl = proc.info.get("cmdline") or []
            if not any("desktop.backend_child" in c for c in cl):
                continue
            if str(port) not in cl:
                continue
            if not _has_live_launcher_ancestor(proc.info.get("ppid")):
                if log:
                    log.write(f"  清理遗留孤儿后端 PID {proc.info.get('pid')}（父进程链无存活启动器）")
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return killed


def check_docker() -> dict:
    """Docker 引擎是否可用（docker info 退出码）。"""
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=15,
                              creationflags=_NO_WINDOW)
        return {"ok": proc.returncode == 0}
    except Exception:
        return {"ok": False}


# ────────────────────────────────────────────────────────────
# v0.33 环境感知（就绪检测用；exe 纯启动器，安装职责在 deploy 安装脚本）
# ────────────────────────────────────────────────────────────

def find_python(root: Path) -> dict:
    """找可复用的 Python：优先项目 .venv，其次系统 python/py。

    返回 {"found", "path", "version", "source"}。source ∈ venv / system / none。
    """
    for venv_name in (".venv/Scripts/python.exe", ".venv/bin/python"):
        p = root / venv_name
        if p.exists():
            return {"found": True, "path": str(p), "version": _py_version(str(p)), "source": "venv"}
    for cand in ("python", "python3", "py"):
        p = shutil.which(cand)
        if p:
            ver = _py_version(p)
            if ver:
                return {"found": True, "path": p, "version": ver, "source": "system"}
    return {"found": False, "path": None, "version": None, "source": None}


def _py_version(python: str) -> str | None:
    try:
        proc = subprocess.run([python, "--version"], capture_output=True, text=True, timeout=10,
                              creationflags=_NO_WINDOW)
        return (proc.stdout or proc.stderr or "").strip() or None
    except Exception:
        return None


def check_venv(root: Path) -> dict:
    """项目 .venv 是否存在（含解释器）。"""
    for venv_name in (".venv/Scripts/python.exe", ".venv/bin/python"):
        p = root / venv_name
        if p.exists():
            return {"exists": True, "path": str(p)}
    return {"exists": False, "path": None}


def runtime_python(root: Path) -> str:
    """后端子进程的解释器：优先项目 .venv。

    冻结（PyInstaller exe）后 sys.executable 是 exe 本身、不是 python，
    必须用 .venv 里的 python 来 `-m desktop.backend_child` 拉起后端。
    开发态 sys.executable 本就是 venv python，等价。
    """
    venv = check_venv(root)
    if venv["exists"]:
        return venv["path"]
    return sys.executable


def check_deps(python: str | None = None) -> dict:
    """用指定 python 探测关键后端依赖是否已装（importlib 轻量探测）。"""
    python = python or sys.executable
    probe = (
        "import importlib.util;"
        f"mods={_REQUIRED_MODULES!r};"
        "print(','.join(m for m in mods if importlib.util.find_spec(m)))"
    )
    try:
        proc = subprocess.run([python, "-c", probe], capture_output=True, text=True, timeout=30,
                              creationflags=_NO_WINDOW)
        found = {m for m in (proc.stdout or "").strip().split(",") if m}
    except Exception:
        found = set()
    missing = [m for m in _REQUIRED_MODULES if m not in found]
    return {"present": sorted(found), "missing": missing, "all_ok": not missing}


def check_ffmpeg() -> dict:
    """ffmpeg 是否在 PATH。"""
    p = shutil.which("ffmpeg")
    return {"found": bool(p), "path": p}


def check_frontend_dist(root: Path) -> dict:
    """桌面前端 dist 是否已构建。"""
    return {"ready": (root / "frontend-desktop" / "dist" / "index.html").exists()}


def environment_status(root: Path) -> dict:
    """一次性收集全部环境就绪状态（供 --status / 启动前判断）。

    轻量探测为主；模型走完整 verify（download_models.py --verify-only）。
    """
    python = find_python(root)
    models = check_models(root, python["path"] or sys.executable)
    return {
        "config": check_config_file(root),
        "frontend": check_frontend_dist(root)["ready"],
        "python": python,
        "venv": check_venv(root),
        "deps": check_deps(python["path"] or sys.executable),
        "models": models["present"],
        "models_ok": bool(models["present"]) and all(models["present"].values()),
        "ffmpeg": check_ffmpeg()["found"],
        "docker": check_docker()["ok"],
    }


def ready_summary(status: dict) -> dict:
    """把 environment_status 压缩成"逐项 OK/缺失"列表，供 --status / splash 展示。"""
    items = [
        ("config", "config/config.yaml", status["config"]),
        ("frontend", "桌面前端 dist", status["frontend"]),
        ("python", "Python 解释器", status["python"]["found"]),
        ("venv", ".venv 虚拟环境", status["venv"]["exists"]),
        ("deps", "后端依赖", status["deps"]["all_ok"]),
        ("models", "模型", status["models_ok"]),
        ("ffmpeg", "ffmpeg", status["ffmpeg"]),
        ("docker", "Docker", status["docker"]),
    ]
    ready = all(ok for _, _, ok in items)
    missing = [name for _, name, ok in items if not ok]
    return {"ready": ready, "items": items, "missing": missing}
