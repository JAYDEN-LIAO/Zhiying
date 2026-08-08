"""pywebview 窗口的内嵌 HTML 页面 + js_api 桥。

主窗（SplashApi）起步展示启动状态，后端就绪后由 app.py load_url 跳到前端；
控制窗（LogApi）做日志面板 + 状态行 + 操作按钮。

这些页面是自包含的（无构建步骤），与 frontend/dist 完全解耦，满足"只加不改"。
"""
from __future__ import annotations

import os
import threading
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
  tick();
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
  tick();
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
    """主窗 splash 的 js_api。"""

    def __init__(self, ctx: Ctx) -> None:
        self._ctx = ctx

    def get_status(self) -> dict:
        s = app_state.get()
        return s


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
