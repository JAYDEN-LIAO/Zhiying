/* ════════════════════════════════════════════════════════════
   FileLibrary — 文件库（v0.34 桌面重构）
   视频文件管理：统计卡 + 视频列表（复用 HistoryPanelContent 的
   搜索/分组/删除/下钻）+ 上传入口。点击视频卡 → 跳工作台查看结果。
   ════════════════════════════════════════════════════════════ */

import { useState } from "react";
import { useApp } from "../AppContext";
import { HistoryPanelContent } from "./HistoryPanelContent";
import { IconPlus, IconFolder } from "./icons";

function StatCard({ cls, num, label, icon }: { cls: string; num: number; label: string; icon: React.ReactNode }) {
  return (
    <div className="stat-card">
      <div className={`stat-ic ${cls}`}>{icon}</div>
      <div>
        <div className="stat-num">{num}</div>
        <div className="stat-lbl">{label}</div>
      </div>
    </div>
  );
}

export function FileLibrary() {
  const { videos, videoGroups, selectedVideoId, openWorkbench, removeVideoState, handleUploadClick, isUploading } = useApp();
  const [drillGroupId, setDrillGroupId] = useState<string | null>(null);

  const completed = videos.filter((v) => v.status === "completed").length;
  const processing = videos.filter((v) => v.status === "processing" || v.status === "pending").length;
  const failed = videos.filter((v) => v.status === "failed").length;

  return (
    <div className="page-pad" style={{ display: "flex", flexDirection: "column" }}>
      {/* 页头 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: "#1e293b", display: "flex", alignItems: "center", gap: 8 }}>
          <IconFolder />
          文件库
        </h1>
        <button className="g-btn g-btn-primary" onClick={handleUploadClick} disabled={isUploading}>
          <IconPlus />
          {isUploading ? "上传中..." : "上传视频"}
        </button>
      </div>

      {/* 统计卡 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 16 }}>
        <StatCard cls="blue" num={videos.length} label="全部视频" icon={<IconFolder />} />
        <StatCard cls="green" num={completed} label="已完成" icon={<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 11-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>} />
        <StatCard cls="amber" num={processing} label="处理中" icon={<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3" /></svg>} />
        <StatCard cls="red" num={failed} label="失败" icon={<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg>} />
      </div>

      {/* 视频列表 */}
      <div className="g-card" style={{ flex: 1, minHeight: 0 }}>
        <div className="g-card-hd">
          <span className="g-card-tt">视频列表</span>
          {drillGroupId && (
            <button className="g-btn g-btn-sm" onClick={() => setDrillGroupId(null)}>← 返回全部</button>
          )}
        </div>
        <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <HistoryPanelContent
            videos={videos}
            currentVideoId={selectedVideoId}
            loading={false}
            videoGroups={videoGroups}
            drillGroupId={drillGroupId}
            onDrillChange={setDrillGroupId}
            onSelect={(id: string) => openWorkbench(id)}
            onDelete={removeVideoState}
          />
        </div>
      </div>
    </div>
  );
}
