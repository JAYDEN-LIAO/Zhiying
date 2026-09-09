/* ════════════════════════════════════════════════════════════
   App — 应用壳（v0.34 桌面重构）
   TitleBar(自定义窗口外框) + Sidebar(4 页导航) + 主区页面切换
   ──────────────────────────────────────────────────────────── */

import { AppProvider, useApp } from "./AppContext";
import { DownloadProvider } from "./services/downloads";
import { DownloadManager } from "./components/DownloadManager";
import { TitleBar } from "./components/TitleBar";
import { Sidebar } from "./components/Sidebar";
import { Workbench } from "./components/Workbench";
import { FileLibrary } from "./components/FileLibrary";
import { GlobalSearch } from "./components/GlobalSearch";
import { TaskCenter } from "./components/TaskCenter";
import { SettingsPage } from "./components/SettingsPage";
import { ImageLibrary } from "./components/ImageLibrary";

function Shell() {
  const { page, navigate, settingsTab, navigateSettings, queuedTaskCount, newCompletedCount, failedTaskCount, runningTaskCount, videos, caseGroups, selectedTree, imageLibAlertCount } = useApp();

  /* 案例库灰徽章 = 当前选中案例名（超长截取前 4 字）+ 该案例待处理视频数 */
  const selGid = selectedTree.startsWith("g:") ? selectedTree.slice(2) : null;
  const selGroup = selGid ? caseGroups.find((g) => g.groupId === selGid) : null;
  const selName = selGroup?.name ?? "";
  const selPending = selGid
    ? videos.filter((v) => v.group_id === selGid && v.status === "pending").length
    : 0;

  /* 侧栏徽章：案例库灰=仅上传未提交；任务中心 左→右=红(失败) 绿(新完成) 蓝(处理中,恒1) 黄(排队中)；素材库=高优告警红点 */
  const counts = {
    files: selPending,
    filesLabel: selName,
    running: runningTaskCount > 0 ? 1 : 0,
    queued: queuedTaskCount,
    newCompleted: newCompletedCount,
    failed: failedTaskCount,
    imageLibAlert: imageLibAlertCount,
  };

  return (
    <div className="app-shell">
      {/* 自定义窗口标题栏（frameless 拖拽区 + 窗口控制） */}
      <TitleBar />

      <div className="app-body">
        <Sidebar page={page} settingsTab={settingsTab} onNavigate={navigate} onNavigateSettings={navigateSettings} counts={counts} />

        <main className={"app-main" + (page === "files" || page === "workbench" || page === "search" || page === "tasks" || page === "settings" || page === "imagelib" ? " app-main-flat" : "")}>
          {page === "files" && <FileLibrary />}
          {/* Workbench 始终挂载（hide 保住搜索结果/选中状态），切页回来直接恢复 */}
          <div className={page === "workbench" ? "contents" : "hidden"}><Workbench /></div>
          {/* GlobalSearch 始终挂载（hide 保住搜索结果），切页回来直接恢复 */}
          <div className={page === "search" ? "contents" : "hidden"}><GlobalSearch /></div>
          {page === "tasks" && <TaskCenter />}
          {page === "settings" && <SettingsPage section={settingsTab} onSectionChange={navigateSettings} />}
          {page === "imagelib" && <ImageLibrary />}
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <DownloadProvider>
        <Shell />
        <DownloadManager />
      </DownloadProvider>
    </AppProvider>
  );
}
