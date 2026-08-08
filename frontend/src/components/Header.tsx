/* ════════════════════════════════════════════════════════════
   Header — 52px fixed top bar with animated title + nav buttons
   （云智嵌入场景移除侧边栏，导航按钮上移 header。
     布局：左侧 logo/标题 | 视频名称(stats 对齐播放器右缘) | 右侧 按钮+开始
     按钮顺序：工作台 / 参数设置 / 历史记录 | 系统设置（前三为一组，设置单独））
   ════════════════════════════════════════════════════════════ */

export type PageView = "dashboard" | "settings";
export type PanelType = "params" | "history";

interface Props {
  isUploading: boolean;
  onUpload: () => void;
  currentPage: PageView;
  activePanel: PanelType | null;
  onNavigate: (page: PageView) => void;
  onTogglePanel: (panel: PanelType) => void;
  statsBar?: React.ReactNode;
}

export function Header({ isUploading, onUpload, currentPage, activePanel, onNavigate, onTogglePanel, statsBar }: Props) {
  return (
    <header className="header">
      {/* ── 左侧：logo + 标题 ── */}
      <div className="header-left">
        <img src="/zhiying.svg" alt="Zhiying" style={{ height: 36, width: "auto" }} />
        <div className="header-title relative w-[88px] h-5 overflow-hidden">
          <span
            className={`absolute inset-0 flex items-center transition-all duration-500 ease-out ${
              currentPage === "dashboard"
                ? "opacity-100 translate-y-0"
                : "opacity-0 -translate-y-full"
            }`}
          >
            工作台
          </span>
          <span
            className={`absolute inset-0 flex items-center transition-all duration-500 ease-out ${
              currentPage === "settings"
                ? "opacity-100 translate-y-0"
                : "opacity-0 translate-y-full"
            }`}
          >
            系统设置
          </span>
        </div>
      </div>

      {/* ── 中间：视频名称等 stats（flex:1 右对齐到播放器右缘） ── */}
      <div className={`header-stats-area transition-all duration-500 ease-out ${
        currentPage === "dashboard" ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-2 pointer-events-none"
      }`}>
        {statsBar}
      </div>

      {/* ── 右侧：导航按钮 + 开始（绝对定位靠右，不随 714px 内容区偏移） ── */}
      <nav className="header-nav">
        <button
          className={"header-nav-btn" + (currentPage === "dashboard" ? " active" : "")}
          title="工作台"
          onClick={() => onNavigate("dashboard")}
        >
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
          </svg>
        </button>
        <button
          className={"header-nav-btn" + (activePanel === "params" ? " active" : "")}
          title="参数设置"
          onClick={() => onTogglePanel("params")}
        >
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round">
            <line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" />
            <line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" />
            <line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" />
            <line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" />
            <line x1="17" y1="16" x2="23" y2="16" />
          </svg>
        </button>
        <button
          className={"header-nav-btn" + (activePanel === "history" ? " active" : "")}
          title="历史记录"
          onClick={() => onTogglePanel("history")}
        >
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
          </svg>
        </button>

        <div className="header-nav-div" />

        <button
          className={"header-nav-btn" + (currentPage === "settings" ? " active" : "")}
          title="系统设置"
          onClick={() => onNavigate("settings")}
        >
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
          </svg>
        </button>
      </nav>

      <button className="header-upload" onClick={onUpload} disabled={isUploading}>
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeLinecap="round">
          <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
        </svg>
        {isUploading ? "上传中..." : "开始"}
      </button>
    </header>
  );
}
