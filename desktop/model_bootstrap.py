"""desktop/model_bootstrap.py — 首启模型下载引导（任务一·骨架包部署）。

check_models 检测到模型缺失时，桌面壳进入 State.MODEL_BOOT，由本模块在后台
线程跑 deploy/download_models.py 下载 25GB 模型，并对外暴露线程安全的进度轮询。

进度解析（download_models.py 输出约定）：
  - `\r[progress] <name> NN% ...`  → 当前组件下载百分比（回车刷新，同一行累积）
  - `[ok]` / `[skip] <name>`       → 组件下载完成（含 verify 格式 `组件: OK/...`）
  - `[error]` / 非零退出码         → 下载失败

代理：modelscope 直连；github 源组件需代理，由 UI 输入（或 data/proxy.txt 记忆）。
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from pathlib import Path

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 组件全集（与 download_models.py verify_all 的 labels 键一致）
_COMPONENTS = ("embedding", "yolo", "reid", "face", "plate", "segmenter")

_PROGRESS_RE = re.compile(r"\[progress\]\s*(\S+)\s*(\d+)\s*%")
_COMPLETE_RE = re.compile(r"\[(ok|skip)\]\s*(\S+)")
_VERIFY_RE = re.compile(r"^(\w+)\s*\([^)]*\):\s*(OK|MISSING|INCOMPLETE)", re.IGNORECASE)


def ensure_embedding_profile(root: Path, profile: str) -> None:
    """确保 config.yaml 的 embedding_profile 与下载档位一致（建表维度必须同步）。

    - config.yaml 缺失 → 从 config/config.yaml.example 复制生成。
    - 已有 → 就地改写 `embedding_profile:` 行为所选档位（2b/8b）。
    否则会出现在面板改了档位 → 下载 2B 模型但 backend 按 4096 维建表 → 向量插入失败。
    """
    profile = profile if profile in ("2b", "8b") else "8b"
    cfg_path = root / "config" / "config.yaml"
    if not cfg_path.exists():
        example = root / "config" / "config.yaml.example"
        if example.exists():
            try:
                cfg_path.parent.mkdir(parents=True, exist_ok=True)
                cfg_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception:
                return
        else:
            return
    try:
        lines = cfg_path.read_text(encoding="utf-8").splitlines(keepends=True)
        hit = False
        for i, line in enumerate(lines):
            if line.lstrip().startswith("embedding_profile"):
                indent = line[:len(line) - len(line.lstrip())]
                lines[i] = f"{indent}embedding_profile: {profile}\n"
                hit = True
                break
        if not hit:
            # 没有该行则追加到文件末尾（example 中必有，此分支仅防御）
            lines.append(f"\nembedding_profile: {profile}\n")
        cfg_path.write_text("".join(lines), encoding="utf-8")
    except Exception:
        pass


class ModelBootstrap:
    """后台下载模型，对外提供线程安全的状态快照。

    status: {
        "state": "idle"|"running"|"done"|"failed"|"aborted",
        "current": str,        # 当前组件名或状态文案
        "percent": int,        # 整体进度估计 0-100
        "components": {name: bool},  # 各组件是否已下载完成
        "error": str|None,
    }
    """

    def __init__(self, root: Path, python: str, log=None) -> None:
        self._root = root
        self._python = python
        self._log = log
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._status = self._fresh_status()

    def _fresh_status(self, state: str = "idle") -> dict:
        return {
            "state": state,
            "current": "" if state == "idle" else "准备中…",
            "percent": 0,
            "components": {c: False for c in _COMPONENTS},
            "error": None,
        }

    @property
    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self, profile: str = "8b", proxy: str = "") -> bool:
        """启动下载线程；已在跑返回 False。"""
        with self._lock:
            if self._status["state"] == "running":
                return False
            self._status = self._fresh_status("running")
            self._proc = None
        # 档位写回 config.yaml（建表维度与下载模型一致），失败不影响下载本身
        ensure_embedding_profile(self._root, profile)
        self._thread = threading.Thread(target=self._run, args=(profile, proxy), daemon=True)
        self._thread.start()
        return True

    def abort(self) -> None:
        """用户点「取消」：终止下载进程并置 aborted（生命周期据此进 ERROR 等退出）。"""
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        with self._lock:
            if self._status["state"] == "running":
                self._status["state"] = "aborted"

    def _set(self, **patch) -> None:
        with self._lock:
            self._status.update(patch)

    # ── 后台线程 ────────────────────────────────────────────
    def _run(self, profile: str, proxy: str) -> None:
        script = self._root / "deploy" / "download_models.py"
        cmd = [self._python, str(script), "--component", "all",
               "--embedding-profile", profile,
               "--model-root", str(self._root / "models")]
        env = dict(os.environ)
        proxy = (proxy or "").strip()
        if proxy:
            # github 源组件需要；modelscope 强制直连（download_models.py 内部处理）
            env["HTTP_PROXY"] = env["HTTPS_PROXY"] = proxy
            env["http_proxy"] = env["https_proxy"] = proxy
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=env, creationflags=_NO_WINDOW,
            )
        except Exception as e:  # 找不到 python / 脚本异常等
            self._finish("failed", f"无法启动模型下载进程: {e}")
            return
        with self._lock:
            self._proc = proc

        rc = self._drain(proc)
        if rc != 0:
            self._finish("failed", f"模型下载失败（退出码 {rc}），可检查代理后重试")
            return
        # 退出码 0 不代表全部组件 OK（可能部分被跳过但 verify 未过），按组件兜底判断
        with self._lock:
            missing = [c for c in _COMPONENTS if not self._status["components"].get(c)]
        if missing:
            self._finish("failed", "部分组件下载后校验未通过: " + ", ".join(missing))
            return
        self._finish("done", None)

    def _drain(self, proc: subprocess.Popen) -> int:
        """读 stdout 流，按 \\r/\\n 切分逐帧解析进度。"""
        buf = b""
        done = set()
        try:
            while True:
                chunk = proc.stdout.read(65536) if proc.stdout else b""
                if not chunk:
                    break
                buf += chunk
                while True:
                    nl = buf.find(b"\n")
                    if nl < 0:
                        break
                    raw = buf[:nl]
                    buf = buf[nl + 1:]
                    self._feed(raw, done)
        except Exception as e:
            self._set(error=f"读取下载进度失败: {e}")
        # EOF 尾部（最后一帧无换行）
        self._feed(buf, done)
        return proc.wait()

    def _feed(self, raw: bytes, done: set) -> None:
        for frame in raw.split(b"\r"):  # 回车刷新：同一条流里最后一段是当前进度
            line = frame.decode("utf-8", "replace").strip()
            if not line:
                continue
            self._handle(line, done)

    def _handle(self, line: str, done: set) -> None:
        if line.startswith("[error]"):
            self._set(error=line[len("[error]"):].strip())
            return
        m = _PROGRESS_RE.search(line)
        if m:
            name, pct = m.group(1), int(m.group(2))
            self._set(current=f"{name} {pct}%")
            with self._lock:
                self._status["percent"] = self._overall(done, pct)
            return
        m_complete = _COMPLETE_RE.search(line)   # [ok]/[skip] → 组件完成
        m_verify = _VERIFY_RE.match(line)        # "name (...): OK" → 仅 OK 才算完成
        if m_complete:
            name = m_complete.group(2).lower()
            if name in _COMPONENTS:
                done.add(name)
                with self._lock:
                    self._status["components"][name] = True
                    self._status["percent"] = self._overall(done, None)
                    self._status["current"] = f"{name} 完成"
            return
        if m_verify and m_verify.group(2).upper() == "OK":
            name = m_verify.group(1).lower()
            if name in _COMPONENTS:
                done.add(name)
                with self._lock:
                    self._status["components"][name] = True
                    self._status["percent"] = self._overall(done, None)
                    self._status["current"] = f"{name} 完成"
            return
        # 其它有意义的行（[download]/[skip] 消息等）——跳过，避免刷屏

    def _overall(self, done: set, cur_pct: int | None) -> int:
        """整体进度 = 已完成组件数 / 总数 + 当前组件百分比分摊到 1 个组件。"""
        total = len(_COMPONENTS)
        base = len(done) * 100.0 / total
        if cur_pct is not None and total:
            base += (cur_pct / 100.0) * (100.0 / total)
        return max(0, min(100, int(base)))

    def _finish(self, state: str, error: str | None) -> None:
        if self._log:
            self._log.write(f"模型下载完成，state={state}" if state == "done"
                            else f"模型下载未完成（{state}）：{error}")
        self._set(state=state, error=error, current="" if state == "done" else self._status["current"])
