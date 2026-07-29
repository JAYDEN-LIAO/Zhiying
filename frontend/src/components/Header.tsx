/* ════════════════════════════════════════════════════════════
   Header — 52px fixed top bar (mockup-dark style)
   ════════════════════════════════════════════════════════════ */

export function Header({
  isUploading,
  onUpload,
  statsBar,
}: {
  isUploading: boolean;
  onUpload: () => void;
  statsBar?: React.ReactNode;
}) {
  return (
    <header className="header">
      <div className="header-left">
        <img src="/cerno.svg" alt="Cerno" style={{ height: 32, width: "auto" }} />
      </div>
      <div className="flex items-center gap-3">
        {statsBar}
        <button className="header-upload" onClick={onUpload} disabled={isUploading}>
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeLinecap="round">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          {isUploading ? "上传中..." : "上传视频"}
        </button>
      </div>
    </header>
  );
}
