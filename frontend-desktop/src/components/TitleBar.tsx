/* ════════════════════════════════════════════════════════════
   TitleBar — 自定义窗口标题栏（v0.34 桌面重构）
   frameless 模式下由前端自绘：Logo + 产品名 + 版本徽章 + 窗口控制。
   拖拽 = 手动（onMouseDown → SplashApi.move 跟随），替代原生
   -webkit-app-region: drag（原生对最大化窗拖拽行为不可控）。
   最大化态先还原再跟随光标（桌面惯例「拖动缩小跟随」）。
   窗口按钮置于拖拽区外（sibling），避免点击触发拖拽。
   浏览器 dev（无 pywebview）时隐藏窗口按钮。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../services/api";
import { useDownloader } from "../services/downloads";
import { IconDownload, IconInfo, IconSun, IconMoon } from "./icons";
import { AboutDialog } from "./AboutDialog";
import { useApp } from "../AppContext";

declare global {
  interface Window {
    pywebview?: {
      api: {
        minimize?: () => void;
        toggle_maximize?: () => Promise<boolean>;
        is_maximized?: () => Promise<boolean>;
        quit?: () => void;
        move?: (x: number, y: number) => void;
      };
    };
  }
}

export function TitleBar() {
  const { runningTaskCount } = useApp();
  const [version, setVersion] = useState<string | null>(null);
  const [isMax, setIsMax] = useState(false);
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  // pywebview 桥是异步注入的（React 挂载时可能未就绪）→ 用 state + pywebviewready 事件监听
  const [inPywebview, setInPywebview] = useState(false);

  /* ── 主题：太阳/月亮切换（localStorage 持久化，html.dark 类驱动 CSS 变量翻转） ── */
  const [dark, setDark] = useState<boolean>(() => localStorage.getItem("zhiying-theme") === "dark");
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("zhiying-theme", dark ? "dark" : "light");
  }, [dark]);
  const toggleTheme = () => setDark((d) => !d);

  /* ── 关于：i 按钮 → AboutDialog（产品型号/当前版本/检查升级/用户手册/服务截止时间） ── */
  const [aboutOpen, setAboutOpen] = useState(false);

  /* ── 下载管理：图标入口（进行中数量徽标）→ DownloadManager 弹窗 ── */
  const { activeCount: downloading, setOpen: setDownloadsOpen } = useDownloader();

  useEffect(() => {
    const check = () => { if (window.pywebview?.api) setInPywebview(true); };
    check();
    window.addEventListener("pywebviewready", check);
    return () => window.removeEventListener("pywebviewready", check);
  }, []);

  // 窗口被系统级方式最大化/还原（Win+方向键 / 拖到屏顶）时，本地 isMax 会与后端失步 →
  // 监听 resize（WebView 随窗体缩放会触发）同步真实最大化状态，保证图标/双击行为正确
  useEffect(() => {
    const onResize = () => {
      const api = window.pywebview?.api;
      if (!api?.is_maximized) return;
      api.is_maximized().then((m) => setIsMax(!!m)).catch(() => {});
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    api.getHealth()
      .then((h) => { if (h?.version) setVersion(h.version); })
      .catch(() => {});
  }, []);

  const pv = window.pywebview?.api;
  const onMin = () => pv?.minimize?.();
  const onMax = async () => {
    if (pv?.toggle_maximize) {
      setIsMax(await pv.toggle_maximize());
    }
  };
  // 关闭：有处理中任务 → 弹主题化确认框（替代 pywebview 原生 MessageBox）；无 → 直接退出不提示
  const onClose = () => {
    if (runningTaskCount > 0) setShowCloseConfirm(true);
    else doQuit();
  };
  const doQuit = () => {
    setShowCloseConfirm(false);
    pv?.quit?.();
  };

  /* ── 手动拖拽窗口（替代原生 drag-region，支持最大化态「先还原再跟随光标」）── */
  const dragRef = useRef<{ startX: number; startY: number; baseX: number; baseY: number } | null>(null);

  const onDragStart = async (e: React.MouseEvent) => {
    if (e.button !== 0 || !pv?.move) return;  // 非左键或无桥（浏览器 dev）不处理
    e.preventDefault();
    let baseX = window.screenX;
    let baseY = window.screenY;
    // ⚠️ js_api 桥返回 Promise，必须 await —— 此前误当同步布尔（恒为真），导致每次拖拽都先
    // toggle 一次：还原态拖拽被再次最大化 → 「整个大页面直接拖动了」（测试反馈的 bug 根因）。
    const isMax = !!(await pv.is_maximized?.());
    if (isMax) {
      // 最大化：先还原，再把窗口移到光标下方（光标落在标题栏约 1/3 宽处），随后跟随拖动
      await pv.toggle_maximize?.();
      setIsMax(false);
      const targetX = Math.round(e.screenX - window.innerWidth * 0.33);
      const targetY = Math.round(e.screenY - 24);
      pv.move(targetX, targetY);
      baseX = targetX;
      baseY = targetY;
    }
    dragRef.current = { startX: e.screenX, startY: e.screenY, baseX, baseY };

    const onMove = (ev: MouseEvent) => {
      const d = dragRef.current;
      if (!d) return;
      pv.move?.(d.baseX + (ev.screenX - d.startX), d.baseY + (ev.screenY - d.startY));
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  return (
    <>
    <header className="titlebar">
      {/* 拖拽区 —— 手动拖拽窗口（最大化态先还原再跟随光标）；双击切换最大化/还原 */}
      <div
        className="tb-drag"
        onMouseDown={onDragStart}
        onDoubleClick={() => { void onMax(); }}
      >
        <div className="tb-logo">
          <img src="/zhiying_logo.png" alt="智影" width="15" height="15" />
        </div>
        <span className="tb-title">视频智能快速检索平台</span>
        {version && <span className="tb-badge">v{version}</span>}
      </div>

      {/* 标题栏按钮（sibling，非拖拽区）：关于(i) + 下载 + 主题切换 恒显示；窗口控制仅 pywebview */}
      <div className="tb-win">
        {/* i：关于弹窗 */}
        <button className="tb-win-btn" onClick={() => setAboutOpen(true)} title="关于" aria-label="关于">
          <IconInfo />
        </button>

        {/* 下载管理 */}
        <button className="tb-win-btn relative" onClick={() => setDownloadsOpen(true)} title="下载管理" aria-label="下载管理">
          <IconDownload />
          {downloading > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-[14px] h-[14px] px-0.5 rounded-full bg-[#4f7cff] text-white text-[9px] leading-[14px] text-center font-semibold">
              {downloading > 9 ? "9+" : downloading}
            </span>
          )}
        </button>

        {/* 主题切换 */}
        <button className="tb-win-btn" onClick={toggleTheme} title={dark ? "切换到亮色主题" : "切换到暗色主题"} aria-label="切换主题">
          {dark ? <IconSun /> : <IconMoon />}
        </button>

        {/* 窗口控制（仅 pywebview 桌面端） */}
        {inPywebview && (<>
          <button className="tb-win-btn" onClick={onMin} title="最小化" aria-label="最小化">
            <svg width="12" height="12" viewBox="0 0 14 14">
              <line x1="2" y1="7" x2="12" y2="7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
          <button className="tb-win-btn" onClick={onMax} title={isMax ? "还原" : "最大化"} aria-label="最大化/还原">
            {isMax ? (
              <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4">
                <rect x="2.2" y="3.6" width="8.2" height="8.2" rx="1" />
                <path d="M5 2.6h6.2a1.2 1.2 0 011.2 1.2V10" />
              </svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4">
                <rect x="2.4" y="2.4" width="9.2" height="9.2" rx="1.2" />
              </svg>
            )}
          </button>
          <button className="tb-win-btn close" onClick={onClose} title="关闭" aria-label="关闭">
            <svg width="12" height="12" viewBox="0 0 14 14">
              <line x1="3.2" y1="3.2" x2="10.8" y2="10.8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
              <line x1="10.8" y1="3.2" x2="3.2" y2="10.8" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
        </>)}
      </div>
    </header>

    {/* 关闭确认弹窗（替代 pywebview 原生 MessageBox，主题化） */}
    {showCloseConfirm && createPortal(
      <div className="g-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setShowCloseConfirm(false); }}>
        <div className="g-modal" style={{ width: 400 }}>
          <div className="g-card-hd">
            <span className="g-card-tt">退出确认</span>
          </div>
          <div className="p-5">
            <div className="text-gray-600" style={{ fontSize: 14 }}>
              当前有任务正在运行，退出即中断
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
              <button className="q-btn" onClick={() => setShowCloseConfirm(false)}>取消</button>
              <button className="q-btn q-btn-danger" onClick={doQuit}>退出</button>
            </div>
          </div>
        </div>
      </div>,
      document.body,
    )}

    {/* 关于弹窗 */}
    <AboutDialog open={aboutOpen} onClose={() => setAboutOpen(false)} version={version} />
    </>
  );
}
