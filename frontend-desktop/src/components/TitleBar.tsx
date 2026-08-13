/* ════════════════════════════════════════════════════════════
   TitleBar — 自定义窗口标题栏（v0.34 桌面重构）
   frameless 模式下由前端自绘：Logo + 产品名 + 版本徽章 + 窗口控制。
   拖拽区 = .pywebview-drag-region（pywebview 原生支持，对应 zhiy.html
   的 .draggable/-webkit-app-region）。窗口按钮置于拖拽区外（sibling），
   避免点击触发拖拽。浏览器 dev（无 pywebview）时隐藏窗口按钮。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useState } from "react";
import { api } from "../services/api";

declare global {
  interface Window {
    pywebview?: {
      api: {
        minimize?: () => void;
        toggle_maximize?: () => Promise<boolean>;
        is_maximized?: () => boolean;
        quit?: () => void;
      };
    };
  }
}

export function TitleBar() {
  const [version, setVersion] = useState<string | null>(null);
  const [isMax, setIsMax] = useState(false);
  const inPywebview = !!window.pywebview;

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
  const onClose = () => pv?.quit?.();

  return (
    <header className="titlebar">
      {/* 拖拽区（pywebview-drag-region）—— Logo/标题/徽章区域可拖动窗口 */}
      <div className="pywebview-drag-region tb-drag">
        <div className="tb-logo">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <polygon points="6 3 20 12 6 21 6 3" />
          </svg>
        </div>
        <span className="tb-title">智影视频分析</span>
        {version && <span className="tb-badge">v{version}</span>}
      </div>

      {/* 窗口控制按钮（sibling，非拖拽区） */}
      {inPywebview && (
        <div className="tb-win">
          <button className="tb-win-btn" onClick={onMin} title="最小化" aria-label="最小化">
            <svg width="13" height="13" viewBox="0 0 14 14">
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
        </div>
      )}
    </header>
  );
}
