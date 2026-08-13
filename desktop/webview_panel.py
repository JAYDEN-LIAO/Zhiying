"""pywebview 窗口的内嵌 HTML 页面 + js_api 桥。

主窗（SplashApi）起步展示启动状态，后端就绪后由 app.py load_url 跳到前端；
控制窗（LogApi）做日志面板 + 状态行 + 操作按钮。

这些页面是自包含的（无构建步骤），与 frontend/dist 完全解耦，满足"只加不改"。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass
from typing import Callable

from state import app_state

# 记录各阶段的中文文案（state → 说明）
_STATE_TEXT = {
    "init": "初始化",
    "checking": "环境检查",
    "db_start": "启动数据库",
    "backend_start": "启动后端",
    "ready": "就绪",
    "stopping": "正在停止",
    "stopped": "已停止",
    "error": "出错了",
}

SPLASH_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<style>
  body { margin:0; font-family:"Microsoft YaHei", system-ui, sans-serif;
         background:linear-gradient(160deg,#0f2027,#203a43,#2c5364); color:#e2e8f0;
         display:flex; align-items:center; justify-content:center; height:100vh; }
  .box { text-align:center; max-width:560px; padding:0 24px; }
  .spinner { width:44px; height:44px; margin:0 auto 18px; border:4px solid rgba(255,255,255,.15);
             border-top-color:#38bdf8; border-radius:50%; animation:spin 1s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
  h1 { font-size:20px; margin:0 0 6px; letter-spacing:.5px; }
  .stage { font-size:13px; color:#7dd3fc; margin-bottom:14px; }
  .msg { font-size:12px; color:#94a3b8; line-height:1.7; white-space:pre-wrap; }
  .err { color:#fca5a5; font-size:12px; line-height:1.7; white-space:pre-wrap; }
  .foot { margin-top:22px; font-size:11px; color:#475569; }
</style>
</head>
<body>
  <div class="box">
    <div class="spinner"></div>
    <h1>智影视频分析</h1>
    <div class="stage" id="stage">初始化…</div>
    <div class="msg" id="msg"></div>
    <div class="err" id="err" style="display:none"></div>
    <div class="foot">桌面启动器正在启动本地服务，首次启动约需 30s–60s</div>
  </div>
<script>
  var last = null;
  function tick() {
    pywebview.api.get_status().then(function (s) {
      var stage = document.getElementById('stage');
      var msg = document.getElementById('msg');
      var err = document.getElementById('err');
      var names = {"init":"初始化","checking":"环境检查","db_start":"启动数据库",
                   "backend_start":"启动后端","ready":"就绪","stopping":"正在停止",
                   "stopped":"已停止","error":"出错了"};
      stage.textContent = "状态：" + (names[s.state] || s.state);
      if (s.state === 'ready') {
        stage.textContent = "状态：就绪 → 即将打开界面";
        setTimeout(function () { stage.textContent = "状态：就绪"; }, 2000);
      }
      if (s.state === 'error') {
        err.style.display = 'block';
        err.textContent = s.detail || s.message || '';
        msg.style.display = 'none';
      } else {
        msg.textContent = s.message || '';
      }
      if (s.state === 'ready' && s.version) {
        msg.textContent = "后端已就绪 · 版本 " + s.version;
      }
    }).catch(function () {});
    setTimeout(tick, 300);  // 链式轮询：上次返回后再发下次，避免 pywebview 回调覆盖竞态
  }
  function run() {
    // pywebview 对象是页面加载完成后才注入的；在此之前的调用会同步抛 TypeError，
    // 且该异常发生在 setTimeout(tick) 之前 → 轮询整条死掉（日志窗口空白即此因）。
    // 等 pywebviewready 事件启动；兜底 setTimeout 防事件已错过。
    if (!window.pywebview || !pywebview.api) { setTimeout(run, 200); return; }
    tick();
  }
  window.addEventListener('pywebviewready', run);
  setTimeout(run, 500);
</script>
</body>
</html>
"""

LOG_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<style>
  body { margin:0; font-family:Consolas, "Microsoft YaHei", monospace; background:#0b1220; color:#cbd5e1; font-size:12px; }
  #status { padding:8px 12px; background:#111a2e; border-bottom:1px solid #1e293b;
            display:flex; gap:16px; align-items:center; flex-wrap:wrap; }
  #status b { color:#7dd3fc; }
  #status .badge { padding:2px 8px; border-radius:10px; font-size:11px; background:#1e293b; }
  #status .badge.ok { background:#14532d; color:#86efac; }
  #status .badge.err { background:#7f1d1d; color:#fca5a5; }
  #status .badge.run { background:#1e3a5f; color:#7dd3fc; }
  #buttons { margin-left:auto; display:flex; gap:6px; }
  #buttons button { background:#1e293b; color:#e2e8f0; border:1px solid #334155;
                    border-radius:6px; padding:3px 10px; font-size:11px; cursor:pointer; }
  #buttons button:hover { background:#334155; }
  #log { padding:8px 12px; height:calc(100vh - 42px); overflow-y:auto; white-space:pre-wrap;
         word-break:break-all; line-height:1.5; }
  .ts { color:#64748b; }
</style>
</head>
<body>
  <div id="status">
    <span class="badge" id="badge">初始化</span>
    <span>状态：<b id="st">init</b></span>
    <span>版本：<b id="ver">–</b></span>
    <div id="buttons">
      <button onclick="openBrowser()">打开浏览器</button>
      <button onclick="openLogs()">日志目录</button>
      <button onclick="quit()">退出</button>
    </div>
  </div>
  <div id="log"></div>
<script>
  var since = 0;
  function esc(s) { return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
  function badge(kind, text) {
    var el = document.getElementById('badge');
    el.className = 'badge ' + kind;
    el.textContent = text;
  }
  function tick() {
    pywebview.api.get_status().then(function (s) {
      var names = {"init":"初始化","checking":"环境检查","db_start":"数据库","backend_start":"后端",
                   "ready":"运行中","stopping":"停止中","stopped":"已停止","error":"出错"};
      document.getElementById('st').textContent = names[s.state] || s.state;
      if (s.version) document.getElementById('ver').textContent = s.version;
      if (s.state === 'ready') badge('ok','运行中');
      else if (s.state === 'error') badge('err','出错');
      else if (s.state === 'checking' || s.state === 'db_start' || s.state === 'backend_start') badge('run','启动中');
      else badge('', names[s.state] || s.state);
      if (s.state === 'error' && s.detail) { append(s.detail, 'err'); }
    });
    pywebview.api.get_logs(since).then(function (r) {
      since = r.next;
      var box = document.getElementById('log');
      var nearBottom = (box.scrollHeight - box.scrollTop - box.clientHeight) < 60;
      (r.lines || []).forEach(function (ln) { append(ln); });
      if (nearBottom) box.scrollTop = box.scrollHeight;
    }).catch(function () {});
    setTimeout(tick, 500);  // 链式轮询：避免 pywebview 回调覆盖竞态
  }
  function append(line, cls) {
    var box = document.getElementById('log');
    var div = document.createElement('div');
    var m = line.match(/^(\\[[^\\]]*\\]) (.*)$/);
    div.innerHTML = (m ? '<span class="ts">'+esc(m[1])+'</span> '+esc(m[2]) : esc(line));
    if (cls === 'err') div.style.color = '#fca5a5';
    box.appendChild(div);
  }
  function openBrowser() { pywebview.api.open_browser(); }
  function openLogs() { pywebview.api.open_logs_dir(); }
  function quit() { if (confirm('确定退出智影桌面端？')) pywebview.api.shutdown(); }
  function run() {
    // 同 splash：pywebview 注入前调用会同步 TypeError 杀死 tick 链，窗口永远空白。
    if (!window.pywebview || !pywebview.api) { setTimeout(run, 200); return; }
    tick();
  }
  window.addEventListener('pywebviewready', run);
  setTimeout(run, 500);
</script>
</body>
</html>
"""


@dataclass
class Ctx:
    """app.py 注入的运行上下文，供 js_api 使用。"""
    log: object
    port: int
    url: str
    log_dir: str | None
    stop_backend: Callable[[], None]
    request_shutdown: Callable[[], None]
    on_backend_crash: Callable[[int], None]
    already_running: bool = False


class SplashApi:
    """主窗 js_api：起步 splash + 真实前端共用（load_url 后桥接仍指向本实例）。

    扩展能力（v0.34 桌面重构）：
    - 窗口控制：minimize / toggle_maximize / is_maximized / quit —— frameless 标题栏按钮
    - 系统监控：get_system_stats —— 侧栏 CPU/内存/GPU/网络（psutil + nvidia-smi，纯桌面壳，不动后端）
    """

    _GPU_REFRESH_SEC = 5.0  # nvidia-smi 子进程有成本，缓存 5s
    _NET_PREV_ATTR = "_net_prev"

    def __init__(self, ctx: Ctx) -> None:
        self._ctx = ctx
        self._window = None            # app.py 创建主窗后注入
        self._maximized = False        # pywebview 无 is_maximized 查询，本地标志跟踪
        self._gpu_cache: dict | None = None
        self._gpu_cache_at = 0.0
        self._net_prev: tuple | None = None
        self._net_prev_at = 0.0

    def set_window(self, window) -> None:
        """注入主窗引用（create_window 返回后调用）。"""
        self._window = window

    def get_status(self) -> dict:
        s = app_state.get()
        return s

    # ── 窗口控制（frameless 标题栏按钮）──────────────────────────
    def minimize(self) -> None:
        if self._window:
            self._window.minimize()

    def toggle_maximize(self) -> bool:
        w = self._window
        if not w:
            return self._maximized
        if self._maximized:
            w.restore()
            self._maximized = False
        else:
            w.maximize()
            self._maximized = True
        return self._maximized

    def is_maximized(self) -> bool:
        return self._maximized

    def quit(self) -> None:
        # 从 GUI 线程触发退出：停后端 + 关窗（同 LogApi.shutdown）
        threading.Thread(target=self._ctx.request_shutdown, daemon=True).start()

    # ── 系统监控（侧栏 CPU/内存/GPU/网络）────────────────────────
    def get_system_stats(self) -> dict:
        cpu = self._cpu_stats()
        mem = self._memory_stats()
        gpu = self._gpu_stats()
        net = self._net_stats()
        return {"cpu": cpu, "memory": mem, "gpu": gpu, "net": net, "ts": time.time()}

    @staticmethod
    def _cpu_stats() -> dict | None:
        try:
            import psutil
            # interval=None：按上次调用差值，不阻塞；首次返回 0.0
            return {"percent": round(psutil.cpu_percent(interval=None) or 0.0)}
        except Exception:
            return None

    @staticmethod
    def _memory_stats() -> dict | None:
        try:
            import psutil
            vm = psutil.virtual_memory()
            return {
                "percent": round(vm.percent),
                "used_gb": round(vm.used / 1024 ** 3, 1),
                "total_gb": round(vm.total / 1024 ** 3, 1),
            }
        except Exception:
            return None

    def _gpu_stats(self) -> dict | None:
        now = time.monotonic()
        if self._gpu_cache is not None and now - self._gpu_cache_at < self._GPU_REFRESH_SEC:
            return self._gpu_cache
        try:
            # CREATE_NO_WINDOW：exe 是无窗口壳(runw.exe)，不带此标志时子进程
            # 每次调用都会闪现一个黑控制台框（系统监控每 ~5s 调一次 → 频繁闪框）
            out = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if out.returncode != 0 or not out.stdout.strip():
                self._gpu_cache = None
                return None
            p = [x.strip() for x in out.stdout.strip().split(",")]
            if len(p) < 5:
                self._gpu_cache = None
                return None
            self._gpu_cache = {
                "name": p[4],
                "percent": max(0, min(100, int(round(float(p[0]))))),
                "used_mb": int(round(float(p[1]))),
                "total_mb": int(round(float(p[2]))),
                "temp_c": int(round(float(p[3]))),
            }
            self._gpu_cache_at = now
            return self._gpu_cache
        except Exception:
            self._gpu_cache = None
            return None

    def _net_stats(self) -> dict | None:
        try:
            import psutil
            cur = psutil.net_io_counters()
            now = time.monotonic()
            prev = self._net_prev
            self._net_prev = (cur.bytes_recv, cur.bytes_sent)
            if prev is None or now - self._net_prev_at <= 0:
                self._net_prev_at = now
                return {"down_bps": 0, "up_bps": 0}
            dt = now - self._net_prev_at
            self._net_prev_at = now
            return {
                "down_bps": max(0, int((cur.bytes_recv - prev[0]) / dt)),
                "up_bps": max(0, int((cur.bytes_sent - prev[1]) / dt)),
            }
        except Exception:
            return None


class LogApi:
    """控制窗（日志面板）的 js_api。"""

    def __init__(self, ctx: Ctx) -> None:
        self._ctx = ctx

    def get_status(self) -> dict:
        return app_state.get()

    def get_logs(self, since: int) -> dict:
        idx, lines = self._ctx.log.get_since(int(since or 0))
        return {"next": idx, "lines": lines}

    def open_browser(self) -> None:
        webbrowser.open(self._ctx.url)

    def open_logs_dir(self) -> None:
        d = self._ctx.log_dir
        if not d:
            return
        try:
            if os.name == "nt":
                os.startfile(d)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", d])
        except Exception:
            pass

    def shutdown(self) -> None:
        # 从 GUI 线程触发退出：停后端 + 关窗
        threading.Thread(target=self._ctx.request_shutdown, daemon=True).start()
