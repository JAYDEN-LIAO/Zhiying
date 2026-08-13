/* ════════════════════════════════════════════════════════════
   Sidebar — w-56 浅蓝渐变分组导航 + 底部系统监控（v0.34 桌面重构）
   导航：业务组（文件库/视频解析/任务中心）+ 系统设置组（4 子页：
   系统/模型参数/参数预设/API 密钥，照 demo Layout 二级菜单拆出）
   ════════════════════════════════════════════════════════════ */

import { IconFolder, IconVideo, IconTask, IconGear, IconSliders } from "./icons";
import { SystemMonitor } from "./SystemMonitor";
import type { SettingsTab } from "../AppContext";

export type Page = "files" | "workbench" | "tasks" | "settings";

interface NavItem {
  key: string;
  label: string;
  icon: React.ReactNode;
}

const BUSINESS: NavItem[] = [
  { key: "files", label: "案例库", icon: <IconFolder /> },
  { key: "workbench", label: "视频解析", icon: <IconVideo /> },
  { key: "tasks", label: "任务中心", icon: <IconTask /> },
];

const SETTINGS: { key: SettingsTab; label: string; icon: React.ReactNode }[] = [
  { key: "system", label: "系统设置", icon: <IconGear /> },
  { key: "model", label: "模型参数", icon: <IconSliders /> },
];

export function Sidebar({
  page,
  settingsTab,
  onNavigate,
  onNavigateSettings,
  counts,
}: {
  page: Page;
  settingsTab: SettingsTab;
  onNavigate: (p: Page) => void;
  onNavigateSettings: (tab: SettingsTab) => void;
  counts?: { files?: number; tasks?: number };
}) {
  return (
    <aside className="sidebar">
      <nav className="sb-nav">
        <div className="sb-group-label">业务</div>
        {BUSINESS.map((item) => {
          const count = item.key === "files" ? counts?.files : item.key === "tasks" ? counts?.tasks : undefined;
          return (
            <button
              key={item.key}
              className={"sb-nav-item" + (page === item.key ? " active" : "")}
              onClick={() => onNavigate(item.key as Page)}
              title={item.label}
            >
              {item.icon}
              <span>{item.label}</span>
              {count !== undefined && count > 0 && <span className="sb-count">{count}</span>}
            </button>
          );
        })}

        <div className="sb-group-label">设置</div>
        {SETTINGS.map((item) => (
          <button
            key={item.key}
            className={"sb-nav-item" + (page === "settings" && settingsTab === item.key ? " active" : "")}
            onClick={() => onNavigateSettings(item.key)}
            title={item.label}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <SystemMonitor />
    </aside>
  );
}
