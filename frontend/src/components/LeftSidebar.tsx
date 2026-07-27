/* ════════════════════════════════════════════════════════════
   LeftSidebar — extracted from Dashboard.tsx (lines 196-285)
   ════════════════════════════════════════════════════════════ */

import { IconDashboard, IconSliders, IconHistory, IconGear } from "./icons";

export type PageView = "dashboard" | "settings";
export type PanelType = "params" | "history";

export function LeftSidebar({
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
    <aside
      className="w-16 bg-[#1a65e1] rounded-t-[32px] rounded-b-[32px] flex flex-col items-center pt-6 pb-4 z-10 flex-shrink-0 h-full shadow-[2px_0_16px_rgba(0,0,0,0.15)]"
    >
      {/* ── Page Navigation (blue) + Panel Toggles (green) ── */}
      <nav className="flex-1 flex flex-col gap-4 w-full px-2">
        {/* 工作台 — blue page nav */}
        <button
          onClick={() => onNavigate("dashboard")}
          className={"w-full aspect-square rounded-xl flex items-center justify-center transition-colors relative " + (currentPage === "dashboard" ? "text-white" : "text-white/70 hover:text-white")}
        >
          {currentPage === "dashboard" && <div className="absolute left-0 top-1/3 h-1/3 w-[3px] rounded-full bg-white" />}
          <div className="w-8 h-8 rounded-lg flex items-center justify-center">
            <IconDashboard />
          </div>
        </button>

        {/* 折叠按钮区：仅工作台页展开 */}
        <div className={`overflow-hidden transition-all duration-300 ease-out ${
          currentPage === "dashboard" ? "max-h-28" : "max-h-0"
        }`}>
          <div className={`flex flex-col gap-4 transition-all duration-300 ease-out ${
            currentPage === "dashboard" ? "translate-y-0 opacity-100" : "-translate-y-full opacity-0"
          }`}>
          {/* 参数设置 — green panel toggle */}
          <button
            onClick={() => onTogglePanel("params")}
            className={"w-full aspect-square rounded-xl flex items-center justify-center transition-colors relative " + (activePanel === "params" ? "text-white" : "text-white/70 hover:text-white")}
          >
            {activePanel === "params" && <div className="absolute left-0 top-1/3 h-1/3 w-[3px] rounded-full bg-emerald-300" />}
            <div className="w-8 h-8 rounded-lg flex items-center justify-center">
              <IconSliders />
            </div>
          </button>

          {/* 历史记录 — green panel toggle */}
          <button
            onClick={() => onTogglePanel("history")}
            className={"w-full aspect-square rounded-xl flex items-center justify-center transition-colors relative " + (activePanel === "history" ? "text-white" : "text-white/70 hover:text-white")}
          >
            {activePanel === "history" && <div className="absolute left-0 top-1/3 h-1/3 w-[3px] rounded-full bg-emerald-300" />}
            <div className="w-8 h-8 rounded-lg flex items-center justify-center">
              <IconHistory />
            </div>
          </button>
        </div>
        </div>
      </nav>

      {/* ── 系统设置 — blue page nav (bottom) ── */}
      <div className="mt-auto flex flex-col items-center">
        <button
          onClick={() => onNavigate("settings")}
          className={"w-10 h-10 rounded-full flex items-center justify-center transition-colors relative " + (currentPage === "settings" ? "text-white" : "text-white/70 hover:text-white")}
        >
          {currentPage === "settings" && <div className="absolute left-0 top-1/3 h-1/3 w-[3px] rounded-full bg-white" />}
          <div className="w-8 h-8 rounded-lg flex items-center justify-center">
            <IconGear />
          </div>
        </button>
      </div>
    </aside>
  );
}
