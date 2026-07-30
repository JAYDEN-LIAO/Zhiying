/* ════════════════════════════════════════════════════════════
   Header — 52px fixed top bar with animated title
   ════════════════════════════════════════════════════════════ */

interface Props {
  isUploading: boolean;
  onUpload: () => void;
  currentPage: "dashboard" | "settings";
  statsBar?: React.ReactNode;
}

export function Header({ isUploading, onUpload, currentPage, statsBar }: Props) {
  return (
    <header className="header">
      <div className="header-left">
        <img src="/cerno.svg" alt="Cerno" style={{ height: 36, width: "auto" }} />
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
      <div className="header-stats-area">
        {statsBar}
      </div>
      <button className="header-upload" onClick={onUpload} disabled={isUploading}>
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeLinecap="round">
          <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
        </svg>
        {isUploading ? "上传中..." : "上传视频"}
      </button>
    </header>
  );
}
