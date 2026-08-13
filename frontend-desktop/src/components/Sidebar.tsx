/* ════════════════════════════════════════════════════════════
   Sidebar — w-56 浅蓝分组导航 + 底部系统监控（v0.34 桌面重构）
   4 页模型：文件库 / 视频解析 / 任务中心 / 系统设置（照智影 v2 demo）
   ════════════════════════════════════════════════════════════ */

import { IconFolder, IconVideo, IconTask, IconGear } from "./icons";
import { SystemMonitor } from "./SystemMonitor";

export type Page = "files" | "workbench" | "tasks" | "settings";

const NAV: { key: Page; label: string; group: string; icon: React.ReactNode }[] = [
  { key: "files", label: "文件库", group: "业务", icon: <IconFolder /> },
  { key: "workbench", label: "视频解析", group: "业务", icon: <IconVideo /> },
  { key: "tasks", label: "任务中心", group: "业务", icon: <IconTask /> },
  { key: "settings", label: "系统设置", group: "系统", icon: <IconGear /> },
];

export function Sidebar({
  page,
  onNavigate,
  counts,
}: {
  page: Page;
  onNavigate: (p: Page) => void;
  counts?: { files?: number; tasks?: number };
}) {
  const groups = Array.from(new Set(NAV.map((n) => n.group)));
  return (
    <aside className="sidebar">
      <nav className="sb-nav">
        {groups.map((g) => (
          <div key={g}>
            <div className="sb-group-label">{g}</div>
            {NAV.filter((n) => n.group === g).map((item) => {
              const count = item.key === "files" ? counts?.files
                : item.key === "tasks" ? counts?.tasks : undefined;
              return (
                <button
                  key={item.key}
                  className={"sb-nav-item" + (page === item.key ? " active" : "")}
                  onClick={() => onNavigate(item.key)}
                  title={item.label}
                >
                  {item.icon}
                  <span>{item.label}</span>
                  {count !== undefined && count > 0 && <span className="sb-count">{count}</span>}
                </button>
              );
            })}
          </div>
        ))}
      </nav>
      <SystemMonitor />
    </aside>
  );
}
