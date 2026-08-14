"""pywebview 窗口的内嵌 HTML 页面 + js_api 桥。

主窗（SplashApi）起步展示毛玻璃启动页（标题/阶段进度条/实时日志），后端就绪后由
app.py load_url 跳到前端（load_url 后 js_api 仍指向本实例，前端可继续调
get_status/get_logs/get_system_stats 等）。启动日志经 `get_logs` 暴露给主窗，
不再有独立「启动日志」控制窗（v0.34 移除）。

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
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { height:100%; }
  body {
    font-family:"Microsoft YaHei", system-ui, -apple-system, sans-serif;
    background: linear-gradient(160deg, #e2edff 0%, #d5e4ff 30%, #c2d8ff 62%, #adc8ff 100%);
    color:#1e293b; display:flex; align-items:center; justify-content:center;
    overflow:hidden; position:relative;
  }
  /* 暗色：由 JS 读 localStorage 加 .dark（与前端 index.html 防闪烁同逻辑） */
  body.dark {
    background: linear-gradient(160deg, #1b212c 0%, #151921 45%, #10131a 100%);
    color:#e1e5ec;
  }
  /* 背景光斑：柔和层次，模拟前端渐变 */
  .deco { position:absolute; border-radius:50%; filter:blur(60px); opacity:.5; pointer-events:none; }
  .deco.a { width:420px; height:420px; background:#7a88f5; top:-120px; left:-80px; }
  .deco.b { width:360px; height:360px; background:#38bdf8; bottom:-140px; right:-60px; }
  body.dark .deco { opacity:.22; }
  /* 毛玻璃卡片 */
  .card {
    position:relative; z-index:2; width:560px; max-width:86vw;
    background:rgba(255,255,255,0.72);
    -webkit-backdrop-filter:blur(20px) saturate(1.4); backdrop-filter:blur(20px) saturate(1.4);
    border:1px solid rgba(255,255,255,0.6); border-radius:18px;
    box-shadow:0 24px 60px rgba(30,41,82,0.18);
    padding:34px 38px 30px; text-align:center;
  }
  body.dark .card {
    background:rgba(23,27,38,0.72);
    border:1px solid rgba(255,255,255,0.08);
    box-shadow:0 24px 60px rgba(0,0,0,0.5);
  }
  .logo { width:52px; height:52px; margin:0 auto 14px; border-radius:14px;
          background:linear-gradient(135deg,#4f7cff,#7a88f5); display:flex; align-items:center; justify-content:center;
          box-shadow:0 10px 24px rgba(79,124,255,.35); }
  .logo svg { width:28px; height:28px; }
  h1 { font-size:20px; font-weight:600; letter-spacing:.5px; }
  .stage { margin-top:22px; font-size:13px; font-weight:500; color:#4f7cff; min-height:18px; }
  body.dark .stage { color:#a5b0fb; }
  .bar { height:7px; border-radius:999px; background:rgba(100,116,139,.18); margin-top:10px; overflow:hidden; }
  body.dark .bar { background:rgba(255,255,255,.12); }
  .fill { height:100%; width:0; border-radius:999px; background:linear-gradient(90deg,#4f7cff,#7a88f5,#10b981);
          transition:width .45s ease; }
  .pct { font-size:11px; color:#94a3b8; margin-top:6px; font-family:Consolas,monospace; }
  body.dark .pct { color:#6b7280; }
  .err { color:#ef4444; font-size:12px; line-height:1.7; margin-top:12px; white-space:pre-wrap; text-align:left; display:none; }
  .foot { margin-top:22px; font-size:11px; color:#94a3b8; }
  .spin { animation:spin 1s linear infinite; }
  @keyframes spin { to { transform:rotate(360deg); } }
</style>
</head>
<body>
  <div class="deco a"></div>
  <div class="deco b"></div>
  <div class="card">
    <div class="logo">
      <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>
    </div>
    <h1>视频智能快速检索平台</h1>
    <div class="stage" id="stage">初始化…</div>
    <div class="bar"><div class="fill" id="fill"></div></div>
    <div class="pct" id="pct">0%</div>
    <div class="err" id="err"></div>
    <div class="foot">首次启动需加载模型与本地服务，约需 1–3 分钟</div>
  </div>
<script>
  /* 暗色：与前端 index.html 防闪烁同逻辑 */
  try { if (localStorage.getItem('zhiying-theme') === 'dark') document.body.classList.add('dark'); } catch (e) {}

  var NAMES = {"init":"初始化","checking":"环境检查","db_start":"启动数据库容器","backend_start":"加载模型与服务",
               "ready":"就绪","stopping":"正在停止","stopped":"已停止","error":"出错了"};
  /* 阶段基础进度：模型加载前各阶段只占前 10%，模型加载段（backend_start）映射 10%→90% */
  var BASE = {"init":2, "checking":4, "db_start":7, "backend_start":10};
  var since = 0;
  var modelPct = 0;      // 模型加载 tqdm 实时进度 0-100（从日志 "Loading weights: X%" 解析）
  var lastState = null;

  function setProgress(p) {
    p = Math.max(0, Math.min(100, p));
    document.getElementById('fill').style.width = p + '%';
    document.getElementById('pct').textContent = Math.round(p) + '%';
  }
  // tqdm 进度行解析（兼容 \r 累积在同一行：取最后一段再匹配）
  function parseModelProgress(line) {
    var seg = line.split('\\r');
    var m = seg[seg.length - 1].match(/Loading weights:\\s*(\\d+)%/);
    if (m) { modelPct = Math.max(modelPct, parseInt(m[1], 10)); return true; }
    return false;
  }
  function updateProgress() {
    if (!lastState) return;
    if (lastState.state === 'ready') { setProgress(100); return; }
    if (lastState.state === 'error') { setProgress(BASE[lastState.state] != null ? BASE[lastState.state] : 50); return; }
    // 模型加载段 = 10% → 90%（tqdm 进度 0-100 映射）；其余阶段占前 10%
    if (lastState.state === 'backend_start') setProgress(10 + Math.round(modelPct * 0.8));
    else setProgress(BASE[lastState.state] != null ? BASE[lastState.state] : 5);
  }

  function tick() {
    pywebview.api.get_status().then(function (s) {
      var stage = document.getElementById('stage');
      var err = document.getElementById('err');
      lastState = s;
      if (s.state === 'ready') {
        stage.textContent = '✓ 就绪 · 版本 ' + (s.version || '') + '，正在进入…';
      } else if (s.state === 'error') {
        stage.textContent = '启动失败';
        err.style.display = 'block';
        err.textContent = s.detail || s.message || '启动失败，请查看 data/logs 后重启';
      } else {
        stage.textContent = (NAMES[s.state] || s.state) + (s.message ? ' · ' + s.message : '');
        err.style.display = 'none';
      }
      updateProgress();
    }).catch(function () {});
    pywebview.api.get_logs(since).then(function (r) {
      if (r && r.next > since) {
        var lines = r.lines || [];
        for (var i = 0; i < lines.length; i++) parseModelProgress(lines[i]);
        since = r.next;
        updateProgress();
      }
    }).catch(function () {});
    setTimeout(tick, 300);  // 链式轮询：上次返回后再发下次，避免 pywebview 回调覆盖竞态
  }
  function run() {
    // pywebview 对象是页面加载完成后才注入的；在此之前的调用会同步抛 TypeError，
    // 且该异常发生在 setTimeout(tick) 之前 → 轮询整条死掉（启动页空白即此因）。
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
    """主窗 js_api：起步毛玻璃启动页 + 真实前端共用（load_url 后桥接仍指向本实例）。

    扩展能力（v0.34 桌面重构）：
    - 启动状态：get_status（阶段/文案/版本/错误 detail）+ get_logs（启动实时日志增量，
      原控制窗 LogApi 迁入，随日志窗移除）
    - 窗口控制：minimize / toggle_maximize / is_maximized / quit —— frameless 标题栏按钮
    - 系统监控：get_system_stats —— 侧栏 CPU/内存/GPU/网络（psutil + nvidia-smi，纯桌面壳，不动后端）
    - 最近更新：get_recent_commits —— TitleBar「最近更新」下拉（项目根 git log）
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

    def get_logs(self, since: int) -> dict:
        """启动实时日志增量拉取（原控制窗 LogApi 迁入）：返回 {next, lines}。"""
        idx, lines = self._ctx.log.get_since(int(since or 0))
        return {"next": idx, "lines": lines}

    # ── 窗口控制（frameless 标题栏按钮）──────────────────────────
    def minimize(self) -> None:
        if self._window:
            self._window.minimize()

    def toggle_maximize(self) -> bool:
        w = self._window
        if not w:
            return self._maximized
        if self.is_maximized():
            w.restore()
            self._maximized = False
        else:
            w.maximize()
            self._maximized = True
        return self._maximized

    def is_maximized(self) -> bool:
        """查询主窗是否最大化：优先读真实窗体状态（winforms BrowserView 的 WindowState），
        读不到再退回本地 _maximized 标志。

        pywebview 无 is_maximized 公开接口；真实状态能覆盖系统快捷键（Win+方向键 / 拖到屏顶）
        最大化/还原导致的标志失步。注意：真实窗体挂载在 `window.native`（winforms.py 里
        `pywebview_window.native = self` 注入的 BrowserView 实例），不是 `window.gui`
        （那是整个 winforms 模块，没有 WindowState 属性）——此前读 .gui 恒拿不到 →
        一直退回陈旧标志 → 最大化后图标不更新、再点无反应（用户反馈的 bug）。
        """
        try:
            from System.Windows.Forms import FormWindowState  # type: ignore[import-not-found]
            for attr in ("native", "gui"):  # native=BrowserView 实例；gui 兜底兼容其它后端
                bv = getattr(self._window, attr, None)
                if bv is not None and getattr(bv, "WindowState", None) is not None:
                    return bool(bv.WindowState == FormWindowState.Maximized)
        except Exception:
            pass
        return self._maximized

    def move(self, x: int, y: int) -> None:
        """移动主窗到屏幕坐标（frameless 手动拖拽：普通态直接跟随，最大化态先还原再跟随）。"""
        if self._window:
            try:
                self._window.move(x, y)
            except Exception:
                pass

    def quit(self) -> None:
        # 从 GUI 线程触发退出：停后端 + 关窗
        threading.Thread(target=self._ctx.request_shutdown, daemon=True).start()

    def get_recent_commits(self, n: int = 5) -> list[dict]:
        """TitleBar「最近更新」下拉：项目根 git log 最近 n 条提交（纯本地，git log 不联网）。

        桌面壳跑在项目根（exe 部署处），git 随 update.bat 安装必然可用。
        返回 [{hash, date, subject}, ...]；任何异常返回空列表（浏览器 dev 无 pywebview 时前端不调用）。

        ⚠️ 编码坑（已修）：git log 输出 commit message 恒为 UTF-8（git 不做 locale 转换），
        而 Windows 中文系统 locale 是 GBK——若依赖 text=True 的默认编码（=系统 locale），
        GBK 严格解码 UTF-8 中文 → UnicodeDecodeError → except 吞掉返回空 → 下拉显示
        「无提交记录」。必须显式 encoding="utf-8"（errors="replace" 兜底防极端字节）。
        分隔符用 %x1f（0x1F 单位分隔符，commit message 中不可能出现），避免 subject
        含 `|` 时被 split("|", 2) 截断显示。
        """
        try:
            from checks import project_root
            proc = subprocess.run(
                ["git", "-C", str(project_root()), "log", f"-{int(n)}", "--date=format:%Y-%m-%d %H:%M",
                 "--pretty=format:%h%x1f%ad%x1f%s"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return []
            out = []
            for line in proc.stdout.strip().splitlines():
                h, d, s = line.split("\x1f", 2)
                out.append({"hash": h, "date": d, "subject": s})
            return out
        except Exception:
            return []

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
