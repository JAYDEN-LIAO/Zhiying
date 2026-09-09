/* ════════════════════════════════════════════════════════════
   Sidebar — w-56 浅蓝渐变分组导航 + 底部系统监控（v0.34 桌面重构）
   导航：业务组（文件库/视频解析/任务中心）+ 系统设置组（4 子页：
   系统/模型参数/参数预设/API 密钥，照 demo Layout 二级菜单拆出）
   ════════════════════════════════════════════════════════════ */

import { IconFolder, IconVideo, IconSearch5, IconTask, IconGear, IconSliders, IconImage } from "./icons";
import { SystemMonitor } from "./SystemMonitor";
import type { SettingsTab } from "../AppContext";

export type Page = "files" | "workbench" | "search" | "tasks" | "settings" | "imagelib";

interface NavItem {
  key: string;
  label: string;
  icon: React.ReactNode;
}

const BUSINESS: NavItem[] = [
  { key: "files", label: "案例库", icon: <IconFolder /> },
  { key: "imagelib", label: "素材库", icon: <IconImage /> },
  { key: "search", label: "全局搜索", icon: <IconSearch5 /> },
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
  /* 案例库灰=仅上传未提交 / 任务中心 左→右=红(失败) 绿(新完成) 蓝(处理中,恒1) 黄(排队中) / 素材库=高优告警红点 */
  counts?: { files?: number; filesLabel?: string; running?: number; queued?: number; newCompleted?: number; failed?: number; imageLibAlert?: number };
}) {
  return (
    <aside className="sidebar">
      <nav className="sb-nav">
        <div className="sb-group-label">业务</div>
        {BUSINESS.map((item) => {
          const isFiles = item.key === "files";
          return (
            <button
              key={item.key}
              className={"sb-nav-item" + (page === item.key ? " active" : "")}
              onClick={() => onNavigate(item.key as Page)}
              title={item.label}
            >
              {item.icon}
              <span>{item.label}</span>
              {isFiles ? (
                /* 案例库：案例名（蓝色截断）+ 待处理视频数（灰色徽章）拆分为两个标签 */
                counts?.files != null && counts.files > 0 && (
                  <span className="sb-count-group">
                    {counts.filesLabel && (
                      <span className="sb-count sb-count-name" title={counts.filesLabel}>{counts.filesLabel}</span>
                    )}
                    <span className="sb-count sb-count-gray" title="待处理">{counts.files}</span>
                  </span>
                )
              ) : item.key === "tasks" ? (
                /* 任务中心四徽章，左→右 = 红(失败) 绿(新完成) 蓝(处理中) 黄(排队中) */
                <span className="sb-badges">
                  {counts?.failed != null && counts.failed > 0 && (
                    <span className="sb-count sb-count-red" title="处理失败">{counts.failed}</span>
                  )}
                  {counts?.newCompleted != null && counts.newCompleted > 0 && (
                    <span className="sb-count sb-count-green" title="新完成">{counts.newCompleted}</span>
                  )}
                  {counts?.running != null && counts.running > 0 && (
                    <span className="sb-count" title="处理中">{counts.running}</span>
                  )}
                  {counts?.queued != null && counts.queued > 0 && (
                    <span className="sb-count sb-count-yellow" title="排队中">{counts.queued}</span>
                  )}
                </span>
              ) : item.key === "imagelib" ? (
                /* 图片素材库：高优告警（如"在逃命中"）红点徽章 */
                counts?.imageLibAlert != null && counts.imageLibAlert > 0 && (
                  <span className="sb-dot-alert" title={`${counts.imageLibAlert} 条新高优告警`}>
                    <span className="pulse" />
                    {counts.imageLibAlert > 99 ? "99+" : counts.imageLibAlert}
                  </span>
                )
              ) : null}
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
