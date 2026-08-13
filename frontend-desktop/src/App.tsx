/* ════════════════════════════════════════════════════════════
   App — 应用壳（v0.34 桌面重构）
   TitleBar(自定义窗口外框) + Sidebar(4 页导航) + 主区页面切换
   ──────────────────────────────────────────────────────────── */

import { AppProvider, useApp } from "./AppContext";
import { TitleBar } from "./components/TitleBar";
import { Sidebar } from "./components/Sidebar";
import { Workbench } from "./components/Workbench";
import { FileLibrary } from "./components/FileLibrary";
import { TaskCenter } from "./components/TaskCenter";
import { SettingsPage } from "./components/SettingsPage";

function Shell() {
  const { page, navigate, settingsTab, navigateSettings, videos, dragActive } = useApp();

  const counts = {
    files: videos.length,
    tasks: videos.filter((v) => v.status === "processing" || v.status === "pending").length,
  };

  return (
    <div className="app-shell">
      {/* 自定义窗口标题栏（frameless 拖拽区 + 窗口控制） */}
      <TitleBar />

      <div className="app-body">
        <Sidebar page={page} settingsTab={settingsTab} onNavigate={navigate} onNavigateSettings={navigateSettings} counts={counts} />

        <main className={"app-main" + (page === "files" || page === "workbench" ? " app-main-flat" : "")}>
          {page === "files" && <FileLibrary />}
          {page === "workbench" && <Workbench />}
          {page === "tasks" && <TaskCenter />}
          {page === "settings" && <SettingsPage section={settingsTab} onSectionChange={navigateSettings} />}
        </main>
      </div>

      {/* 拖拽上传遮罩（窗口级） */}
      {dragActive && (
        <div className="drop-overlay">
          <div className="drop-box">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <div className="t1">松开以上传视频</div>
            <div className="t2">支持单个或多个视频 · MP4 / MOV / AVI / MKV / WEBM</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
