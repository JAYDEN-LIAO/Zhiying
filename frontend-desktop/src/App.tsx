/* ════════════════════════════════════════════════════════════
   App — 应用壳（v0.34 桌面重构）
   TitleBar(自定义窗口外框) + Sidebar(4 页导航) + 主区页面切换
   ──────────────────────────────────────────────────────────── */

import { AppProvider, useApp } from "./AppContext";
import { TitleBar } from "./components/TitleBar";
import { Sidebar } from "./components/Sidebar";
import { Workbench } from "./components/Workbench";
import { FileLibrary } from "./components/FileLibrary";
import { GlobalSearch } from "./components/GlobalSearch";
import { TaskCenter } from "./components/TaskCenter";
import { SettingsPage } from "./components/SettingsPage";

function Shell() {
  const { page, navigate, settingsTab, navigateSettings, pendingFileCount, queuedTaskCount, newCompletedCount, failedTaskCount, runningTaskCount } = useApp();

  /* 侧栏徽章：案例库灰=仅上传未提交；视频解析蓝=处理中(恒1)；任务中心 黄=排队中 绿=新完成 红=失败 */
  const counts = {
    files: pendingFileCount,
    workbench: runningTaskCount > 0 ? 1 : 0,
    queued: queuedTaskCount,
    newCompleted: newCompletedCount,
    failed: failedTaskCount,
  };

  return (
    <div className="app-shell">
      {/* 自定义窗口标题栏（frameless 拖拽区 + 窗口控制） */}
      <TitleBar />

      <div className="app-body">
        <Sidebar page={page} settingsTab={settingsTab} onNavigate={navigate} onNavigateSettings={navigateSettings} counts={counts} />

        <main className={"app-main" + (page === "files" || page === "workbench" || page === "search" || page === "tasks" || page === "settings" ? " app-main-flat" : "")}>
          {page === "files" && <FileLibrary />}
          {page === "workbench" && <Workbench />}
          {page === "search" && <GlobalSearch />}
          {page === "tasks" && <TaskCenter />}
          {page === "settings" && <SettingsPage section={settingsTab} onSectionChange={navigateSettings} />}
        </main>
      </div>
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
