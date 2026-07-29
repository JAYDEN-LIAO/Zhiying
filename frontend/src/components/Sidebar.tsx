/* ════════════════════════════════════════════════════════════
   Sidebar — 52px dark gradient navigation (mockup-dark style)
   ════════════════════════════════════════════════════════════ */

import { IconDashboard, IconSliders, IconHistory, IconGear } from "./icons";

export type PageView = "dashboard" | "settings";
export type PanelType = "params" | "history";

export function Sidebar({
  currentPage,
  activePanel,
  onNavigate,
  onTogglePanel,
}: {
  currentPage: PageView;
  activePanel: PanelType | null;
  onNavigate: (page: PageView) => void;
  onTogglePanel: (panel: PanelType) => void;
}) {
  return (
    <aside className="sidebar">
      {/* Spacer where logo would be */}
      <div style={{ width: 26, height: 26, marginBottom: 18, flexShrink: 0 }} />

      <nav className="sb-nav">
        {/* Dashboard page */}
        <button
          className={"sb-btn" + (currentPage === "dashboard" ? " active" : "")}
          onClick={() => onNavigate("dashboard")}
        >
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
          </svg>
        </button>

        {/* Divider */}
        <div className="sb-div" />

        {/* Panel toggles — only visible on dashboard page */}
        <div className={`overflow-hidden transition-all duration-300 ease-out ${
          currentPage === "dashboard" ? "max-h-28" : "max-h-0"
        }`}>
          <div className={`flex flex-col gap-[8px] transition-all duration-300 ease-out ${
            currentPage === "dashboard" ? "translate-y-0 opacity-100" : "-translate-y-full opacity-0"
          }`}>
            {/* Params panel toggle */}
            <button
              className={"sb-btn" + (activePanel === "params" ? " active" : "")}
              onClick={() => onTogglePanel("params")}
              title="参数设置"
            >
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round">
                <line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" />
                <line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" />
                <line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" />
                <line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" />
                <line x1="17" y1="16" x2="23" y2="16" />
              </svg>
            </button>

            {/* History panel toggle */}
            <button
              className={"sb-btn" + (activePanel === "history" ? " active" : "")}
              onClick={() => onTogglePanel("history")}
              title="历史记录"
            >
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
              </svg>
            </button>
          </div>
        </div>
      </nav>

      {/* Settings (bottom) */}
      <div className="sb-bottom">
        <button
          className={"sb-btn" + (currentPage === "settings" ? " active" : "")}
          onClick={() => onNavigate("settings")}
          title="系统设置"
        >
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
          </svg>
        </button>
      </div>
    </aside>
  );
}
