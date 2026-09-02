#!/usr/bin/env python3
"""智影视频分析 · 桌面启动器入口（形态 B）。

管理本地后端生命周期：检查模型齐全 → 起 Docker db → 起 uvicorn →
开 WebView2 主窗加载前端 dist → 控制窗日志面板 → 优雅关闭。

用法：
  python desktop/app.py              # GUI 启动
  python desktop/app.py --check      # 只做环境自检并打印报告（无需 pywebview）
  python desktop/app.py --no-window  # 无 GUI 冒烟（起 db + 后端，Ctrl+C 退出）

以 `python desktop/app.py` 运行时，sys.path[0]=desktop/，模块间用顶层同级导入。
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from state import State, app_state
from logs import LogSink
from checks import (project_root, install_script_name, read_server_config, check_config_file,
                    check_models, check_port, probe_health, environment_status, ready_summary, runtime_python,
                    sweep_orphan_backends)
import db as db_mod
import backend as backend_mod
from model_bootstrap import ModelBootstrap
import license_check as license_mod

ROOT = project_root()


# ────────────────────────────────────────────────────────────
# 命令行
# ────────────────────────────────────────────────────────────
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="智影桌面启动器")
    p.add_argument("--check", action="store_true", help="只做环境自检并打印报告（不启动）")
    p.add_argument("--status", action="store_true", help="打印环境就绪状态（逐项 OK/缺失，不启动）")
    p.add_argument("--no-window", action="store_true", help="无 GUI 冒烟（起 db + 后端，Ctrl+C 退出）")
    p.add_argument("--debug", action="store_true", help="pywebview 调试模式（devtools）")
    p.add_argument("--gui", default="auto", choices=["auto", "qt", "gtk", "edgechromium", "winforms"],
                   help="pywebview 后端（默认 auto 探测；Linux conda 缺 gi 时用 --gui qt）")
    p.add_argument("--log-dir", default=None, help="日志文件目录（默认 data/logs）")
    return p.parse_args(argv)


def _log_path(args) -> Path:
    d = Path(args.log_dir) if args.log_dir else ROOT / "data" / "logs"
    return d / "desktop.log"


def _embedding_profile(root: Path) -> str:
    """读 config.yaml 的 embedding_profile（2b/8b）；缺失默认 8b。"""
    try:
        for line in (root / "config" / "config.yaml").read_text(encoding="utf-8").splitlines():
            if "embedding_profile" in line and ":" in line:
                v = line.split(":", 1)[1].strip().strip('"\'')
                return v if v in ("2b", "8b") else "8b"
    except Exception:
        pass
    return "8b"


def _saved_proxy(root: Path) -> str:
    """读 install1/install2 记忆的代理（data/proxy.txt），首启下载默认使用。"""
    try:
        return (root / "data" / "proxy.txt").read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _wait_model_bootstrap(boot: ModelBootstrap, profile: str, proxy: str, log) -> bool:
    """进入 model_boot 状态并等模型下载完成。

    下载在后台线程跑（boot 实例同时暴露给 SplashApi，供前端点「重试」重新 start）。
    返回 True=下载完成可继续；False=失败/中止（调用方应等退出）。
    """
    boot.start(profile=profile, proxy=proxy)
    app_state.set(State.MODEL_BOOT, "模型未齐全，正在下载模型…", profile=profile)
    last_state = None
    while True:
        st = boot.status
        if st["state"] == "done":
            return True
        if st["state"] == "aborted":
            app_state.set(State.ERROR, "模型下载已取消",
                          detail="已停止下载，关闭启动器后可重新打开重试")
            return False
        if st["state"] == "failed" and last_state != "failed":
            app_state.set(State.MODEL_BOOT, "模型下载失败，请检查代理后重试",
                          detail=st["error"] or "下载失败", profile=profile)
        elif st["state"] == "running" and last_state != "running":
            app_state.set(State.MODEL_BOOT, "模型未齐全，正在下载模型…", profile=profile)
        last_state = st["state"]
        time.sleep(0.4)


def _cache_bust_url(url: str, version: str | None) -> str:
    """首页 URL 追加版本号查询参数，击穿 WebView2 持久化 HTTP 缓存。

    桌面壳 private_mode=False 使用持久化 WebView2 配置（%APPDATA%\\pywebview），
    跨版本复用会缓存旧 index.html + 旧 JS → 发版后窗口仍显示旧 UI（如素材库消失）。
    每次发版 version 变化 → index.html 强制重新拉取 → 内容哈希资产自然取新。"""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={version or ''}"


# ────────────────────────────────────────────────────────────
# --check：只做检查，不打 GUI
# ────────────────────────────────────────────────────────────
def run_check(args) -> int:
    log = LogSink(path=_log_path(args), echo=True)
    cfg = read_server_config(ROOT)
    exit_code = 0
    log.write(f"项目根: {ROOT}")
    log.write(f"config.yaml 存在: {cfg['config_exists']}   server: {cfg['host']}:{cfg['port']}")

    if not cfg["config_exists"]:
        log.write("[FAIL] 未找到 config/config.yaml —— 复制 config/config.yaml.example 并按机器修改")
        exit_code = max(exit_code, 1)

    models = check_models(ROOT)
    if models["error"]:
        log.write(f"[FAIL] 模型检查运行出错: {models['error']}")
        exit_code = max(exit_code, 1)
    elif not models["present"]:
        log.write("[FAIL] 未能解析模型检查输出（download_models.py 版本不兼容？）")
        exit_code = max(exit_code, 1)
    else:
        missing = [k for k, v in models["present"].items() if not v]
        for k in sorted(models["present"]):
            log.write(f"  模型 {k}: {'OK' if models['present'][k] else 'MISSING'}")
        if missing:
            log.write(f"[FAIL] 缺失模型: {', '.join(missing)} —— 运行: python deploy/download_models.py --component all")
            exit_code = max(exit_code, 2)
        else:
            log.write("  模型: 全部齐全")

    port_state = check_port(cfg["port"])
    if port_state["state"] == "free":
        log.write(f"  端口 {cfg['port']}: 空闲")
    elif port_state["state"] == "already_running":
        log.write(f"  端口 {cfg['port']}: 已有 Zhiying 在运行（启动器将直接复用）")
    else:
        log.write(f"[FAIL] 端口 {cfg['port']} 被其它程序占用 —— 修改 config.yaml server.port 后重试")
        exit_code = max(exit_code, 1)

    if db_mod.db_available(ROOT):
        log.write(f"  数据库后端: {db_mod.db_backend(ROOT)} 可用")
    else:
        log.write("[FAIL] 数据库后端不可用 —— 需 vendor/pg（内嵌）或 Docker Desktop（回退）")
        exit_code = max(exit_code, 1)

    log.write(f"自检完成，退出码 {exit_code}（0=全通过 1=环境问题 2=模型缺失）")
    return exit_code


# ────────────────────────────────────────────────────────────
# --no-window：无 GUI 冒烟（起 db + 后端，Ctrl+C 退出）
# ────────────────────────────────────────────────────────────
def run_headless(args) -> int:
    log = LogSink(path=_log_path(args), echo=True)
    cfg = read_server_config(ROOT)
    log.write("无窗口冒烟模式：起 db + 后端，Ctrl+C 退出")
    proc = None
    try:
        if not db_mod.db_available(ROOT):
            log.write("[FAIL] 数据库后端不可用 —— 需 vendor/pg（内嵌）或 Docker Desktop（回退）")
            return 1
        log.write("启动数据库容器…")
        if not db_mod.start_db(ROOT, log):
            log.write("[FAIL] docker compose up -d db 失败")
            return 1
        if not db_mod.wait_db_healthy(ROOT, log):
            log.write("[FAIL] 数据库容器未 healthy")
            return 1
        if sweep_orphan_backends(cfg["port"], log):
            time.sleep(0.8)  # 等端口/句柄完全释放再启动
        log.write("启动后端…")
        proc = backend_mod.start_backend(ROOT, runtime_python(ROOT), "127.0.0.1", cfg["port"], log)
        health = backend_mod.wait_health("127.0.0.1", cfg["port"], log)
        log.write(f"后端就绪 http://127.0.0.1:{cfg['port']} (version {health.get('version')})")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.write("收到 Ctrl+C，正在退出…")
    except TimeoutError as e:
        log.write("[FAIL] " + str(e))
        return 1
    finally:
        if proc and proc.poll() is None:
            backend_mod.stop_backend(proc, log)
    return 0


# ────────────────────────────────────────────────────────────
# GUI 模式：pywebview（lazy import，--check 无需装 pywebview）
# ────────────────────────────────────────────────────────────
def run_gui(args) -> int:
    import webview  # lazy：--check / --no-window 不依赖它
    from webview_panel import Ctx, SplashApi, SPLASH_HTML

    # Linux 下 QtWebEngine 兼容性修复（QT_X11_NO_MITSHM + 禁 GPU 合成/沙箱）。
    # 实测部分 X/无 GPU 合成环境会段错误；setdefault 保证用户可自行覆盖。
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_X11_NO_MITSHM", "1")
        os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
        os.environ.setdefault(
            "QTWEBENGINE_CHROMIUM_FLAGS",
            "--no-sandbox --disable-gpu --disable-software-rasterizer --disable-gpu-compositing",
        )

    log = LogSink(path=_log_path(args))
    cfg = read_server_config(ROOT)
    host, port = "127.0.0.1", cfg["port"]
    url = f"http://{host}:{port}"

    runtime = {"proc": None, "stopping": False, "done": threading.Event()}

    def stop_backend() -> None:
        runtime["stopping"] = True
        proc = runtime["proc"]
        if proc and proc.poll() is None:
            backend_mod.stop_backend(proc, log)

    def request_shutdown() -> None:
        log.write("收到退出请求，正在停止后端…")
        app_state.set(State.STOPPING, "正在停止后端…")
        stop_backend()
        runtime["done"].set()
        try:
            main_window.destroy()
        except Exception:
            pass

    def on_backend_crash(rc: int) -> None:
        if runtime["stopping"]:
            return  # 正常关停，忽略
        log.write(f"后端进程异常退出 (code {rc})")
        app_state.set(State.ERROR, "后端进程异常退出",
                      detail=f"后端进程异常退出 (code {rc})，请关闭启动器后重新打开")

    ctx = Ctx(
        log=log, port=port, url=url,
        log_dir=str(log._path.parent) if log._path else None,
        stop_backend=stop_backend,
        request_shutdown=request_shutdown,
        on_backend_crash=on_backend_crash,
        already_running=False,
        model_boot=ModelBootstrap(ROOT, runtime_python(ROOT), log),
    )

    # v0.34 桌面重构：frameless 无边框 + shadow（Windows EdgeChromium 保留圆角/阴影），
    # 标题栏由前端自绘（drag-region + 窗口控制按钮经 js_api 桥接）。
    main_api = SplashApi(ctx)
    main_window = webview.create_window(
        "智影视频分析", html=SPLASH_HTML, width=1280, height=800, min_size=(1024, 700),
        js_api=main_api,
        frameless=True, shadow=True,
        # ⚠️ 必须显式关掉 easy_drag：pywebview 默认 True，会在全页面注入无条件 mousedown
        # 监听（customize.js「easy drag for edge chromium」）→ 正文区一拖就整个窗口被挪，
        # 且最大化态走裸 window.move() 无还原逻辑 → 全屏大窗被直接平移。
        # 拖拽统一由前端 TitleBar 自绘标题栏手动实现（最大化态先还原再跟随光标）。
        easy_drag=False,
        # 不用 confirm_close：那是 pywebview 原生 MessageBox（"Do you really want to quit?"），
        # 无法定制样式。关闭确认改由前端 TitleBar 主题化弹窗处理（确认后经 js_api quit() 退出）。
    )
    main_api.set_window(main_window)  # 注入窗口引用，供 minimize/toggle_maximize 等使用

    def _on_main_closed() -> None:
        log.write("主窗口已关闭，正在退出…")
        request_shutdown()

    main_window.events.closed += _on_main_closed

    def lifecycle() -> None:
        _lifecycle(runtime, ctx, cfg, log, main_window)

    # private_mode=False：让前端 localStorage（参数面板自定义参数）持久化。
    # 注意：pywebview 6.x 中 private_mode 是 start() 的全局参数，不在 create_window。
    start_kwargs = {"debug": args.debug, "private_mode": False}
    if args.gui != "auto":
        start_kwargs["gui"] = args.gui
    webview.start(lifecycle, **start_kwargs)

    # webview.start 返回 = 所有窗口已关闭，兜底清理
    if runtime["proc"] and runtime["proc"].poll() is None and not runtime["stopping"]:
        backend_mod.stop_backend(runtime["proc"], log)
    return 0


def _lifecycle(runtime, ctx, cfg, log, main_window) -> None:
    try:
        # ── License 校验（封装态启动即验，开发源码态跳过——同云侠 isDev 分支）──
        if getattr(sys, "frozen", False):
            app_state.set(State.CHECKING, "检查许可…")
            ok, msg, lic = license_mod.verify_license(ROOT, log)
            if not ok:
                raise RuntimeError("许可校验失败", msg)
            log.write(f"许可校验通过（licenseType={lic.get('license_type')}，"
                      f"有效期至 {license_mod.expired_date(lic) or '—'}）")

        app_state.set(State.CHECKING, "检查环境…")
        if not check_config_file(ROOT):
            raise RuntimeError("未找到 config/config.yaml",
                               f"请先运行部署脚本完成安装：deploy/{install_script_name()}（会生成并配置 config）")

        if sweep_orphan_backends(cfg["port"], log):
            time.sleep(0.8)  # 等端口/句柄完全释放再探测
        port_state = check_port(cfg["port"])
        if port_state["state"] == "conflict":
            raise RuntimeError(f"端口 {cfg['port']} 被其它程序占用",
                               "请修改 config.yaml 的 server.port 后重启启动器")
        already = port_state["state"] == "already_running"

        models = check_models(ROOT, runtime_python(ROOT))  # 冻结态 sys.executable 是 exe，必须用 venv python 跑模型校验
        missing = [k for k, v in models["present"].items() if not v] if models["present"] else None
        if models["error"]:
            raise RuntimeError("模型检查运行失败", f"错误: {models['error']}")
        if missing:
            # ── 首启模型引导（骨架包部署）：不抛错，进 model_boot 状态下载模型后继续 ──
            # 环境（.venv/依赖/配置）由安装器/deploy 脚本保证；此处只补模型 25GB。
            # 若连 .venv 都没有 → 说明压根没装环境，仍走安装脚本提示。
            if not (ROOT / ".venv" / "Scripts" / "python.exe").exists():
                raise RuntimeError(
                    "环境未安装",
                    f"缺少 .venv 虚拟环境。请先运行部署脚本完成安装：deploy/{install_script_name()}，然后重启启动器",
                )
            if not _wait_model_bootstrap(ctx.model_boot, _embedding_profile(ROOT),
                                         _saved_proxy(ROOT), log):
                runtime["done"].wait()
                return
            log.write("模型下载完成，继续启动…")
            app_state.set(State.CHECKING, "模型下载完成，继续启动…")
            # 下载后重新校验（download_models.py 自带校验，这里兜底），仍缺则报错退出
            models = check_models(ROOT, runtime_python(ROOT))
            missing = [k for k, v in models["present"].items() if not v] if models["present"] else None
            if missing:
                raise RuntimeError("模型校验未通过", "仍缺失: " + ", ".join(missing))

        if already:
            body = probe_health("127.0.0.1", cfg["port"]) or {}
            app_state.set(State.READY, "检测到已有后端，直接复用", port=cfg["port"],
                          version=body.get("version"))
            log.write(f"已有 Zhiying 在运行，直接打开 {ctx.url}")
            time.sleep(1.5)  # 让启动页把进度平滑推满 100% 并展示「正在进入」过渡后再切前端
            main_window.load_url(_cache_bust_url(ctx.url, body.get("version")))
            runtime["done"].wait()
            return

        if not db_mod.db_available(ROOT):
            raise RuntimeError("数据库后端不可用",
                               f"请先运行部署脚本完成安装（内嵌 PostgreSQL / Docker）：deploy/{install_script_name()}，然后重启启动器")
        app_state.set(State.DB_START, "启动数据库容器…")
        if not db_mod.start_db(ROOT, log):
            raise RuntimeError("启动数据库失败", "docker compose up -d db 失败，见控制窗日志")
        if not db_mod.wait_db_healthy(ROOT, log):
            raise RuntimeError("数据库未就绪", "数据库容器未在超时内 healthy，请检查 Docker Desktop")

        app_state.set(State.BACKEND_START, "启动后端…")
        proc = backend_mod.start_backend(ROOT, runtime_python(ROOT), "127.0.0.1", cfg["port"], log)
        runtime["proc"] = proc
        backend_mod.spawn_monitor(proc, ctx.on_backend_crash)
        health = backend_mod.wait_health("127.0.0.1", cfg["port"], log)
        app_state.set(State.READY, "后端就绪", port=cfg["port"], version=health.get("version"))
        log.write(f"后端就绪 {ctx.url} (version {health.get('version')})")
        time.sleep(1.5)  # 让启动页把进度平滑推满 100% 并展示「正在进入」过渡后再切前端
        main_window.load_url(_cache_bust_url(ctx.url, health.get("version")))

    except RuntimeError as e:
        detail = e.args[1] if len(e.args) > 1 else str(e)
        log.write("[ERROR] " + str(e.args[0]))
        app_state.set(State.ERROR, str(e.args[0]), detail=detail)
    except Exception as e:  # 兜底
        log.write("[ERROR] " + repr(e))
        app_state.set(State.ERROR, "启动失败", detail=repr(e))

    # 等待退出信号（主窗关闭 / 控制窗退出按钮）
    runtime["done"].wait()


# ────────────────────────────────────────────────────────────
# 环境状态（v0.33）：exe 纯产品演示，不含安装逻辑。
# 安装职责在 deploy/setup_windows.ps1（裸机→就绪）；exe 只检测就绪并启动，
# 未就绪则在 splash 明确提示缺什么 + 指向安装脚本。
# ────────────────────────────────────────────────────────────
def run_status(args) -> int:
    """打印环境就绪状态（逐项 OK/缺失，无 GUI）。"""
    print("智影桌面端 · 环境就绪状态")
    status = environment_status(ROOT)
    summary = ready_summary(status)
    for key, name, ok in summary["items"]:
        print(f"  {name:18} {'✓ OK' if ok else '✗ 缺失'}")
    print(f"\n{'✓ 全部就绪' if summary['ready'] else '✗ 未就绪'}  缺失: {', '.join(summary['missing']) or '(无)'}")
    if not summary["ready"]:
        print(f"请先运行部署脚本完成安装： deploy/{install_script_name()}")
    return 0 if summary["ready"] else 1


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.check:
        return run_check(args)
    if args.status:
        return run_status(args)
    if args.no_window:
        return run_headless(args)
    return run_gui(args)


if __name__ == "__main__":
    sys.exit(main())
