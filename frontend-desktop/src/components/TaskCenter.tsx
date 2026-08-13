/* ════════════════════════════════════════════════════════════
   TaskCenter — 任务中心（v0.34 桌面重构）
   处理任务状态表格：统计卡 + 状态筛选 Tab + 任务表格（状态徽章/进度条/
   操作）。数据 = 共享视频列表（4s 轮询），按 status 过滤。
   ════════════════════════════════════════════════════════════ */

import { useState } from "react";
import { useApp } from "../AppContext";
import type { VideoListItem } from "../types";
import { fmtDate, fmtDuration } from "../utils/helpers";
import { IconTask, IconVideo } from "./icons";

const FILTERS = [
  { key: "all", label: "全部任务" },
  { key: "active", label: "处理中" },
  { key: "done", label: "已完成" },
  { key: "failed", label: "失败" },
] as const;

type FilterKey = typeof FILTERS[number]["key"];

function statusBadge(v: VideoListItem): { cls: string; label: string; pulse?: boolean } {
  switch (v.status) {
    case "completed": return { cls: "ok", label: "已完成" };
    case "processing": return { cls: "run", label: "处理中", pulse: true };
    case "pending": return { cls: "wait", label: "等待参数" };
    case "failed": return { cls: "err", label: "失败" };
    default: return { cls: "wait", label: v.status };
  }
}

export function TaskCenter() {
  const { videos, openWorkbench, deleteVideo } = useApp();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());

  const active = videos.filter((v) => v.status === "processing" || v.status === "pending").length;
  const done = videos.filter((v) => v.status === "completed").length;
  const failed = videos.filter((v) => v.status === "failed").length;

  const filtered = videos.filter((v) => {
    switch (filter) {
      case "active": return v.status === "processing" || v.status === "pending";
      case "done": return v.status === "completed";
      case "failed": return v.status === "failed";
      default: return true;
    }
  });

  const handleDelete = async (id: string) => {
    if (!window.confirm("确定删除该任务？将同时释放磁盘空间。")) return;
    setDeletingIds((prev) => new Set(prev).add(id));
    try {
      await deleteVideo(id);
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
    }
    setDeletingIds((prev) => { const n = new Set(prev); n.delete(id); return n; });
  };

  return (
    <div className="page-pad" style={{ display: "flex", flexDirection: "column" }}>
      {/* 页头 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: "#1e293b", display: "flex", alignItems: "center", gap: 8 }}>
          <IconTask />
          任务中心
        </h1>
      </div>

      {/* 统计卡 */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 16 }}>
        <div className="stat-card"><div className="stat-ic blue"><IconTask /></div><div><div className="stat-num">{videos.length}</div><div className="stat-lbl">全部任务</div></div></div>
        <div className="stat-card"><div className="stat-ic amber"><IconVideo /></div><div><div className="stat-num">{active}</div><div className="stat-lbl">处理中</div></div></div>
        <div className="stat-card"><div className="stat-ic green"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 11-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg></div><div><div className="stat-num">{done}</div><div className="stat-lbl">已完成</div></div></div>
        <div className="stat-card"><div className="stat-ic red"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg></div><div><div className="stat-num">{failed}</div><div className="stat-lbl">失败</div></div></div>
      </div>

      {/* 任务表格卡片 */}
      <div className="g-card" style={{ flex: 1, minHeight: 0 }}>
        <div className="g-card-hd">
          <div style={{ display: "flex", gap: 4 }}>
            {FILTERS.map((f) => (
              <button key={f.key} className={"g-tab" + (filter === f.key ? " active" : "")} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
        </div>
        <div className="g-table-wrap" style={{ flex: 1, overflow: "auto" }}>
          <table className="g-table">
            <thead>
              <tr>
                <th>视频文件</th>
                <th>状态</th>
                <th>进度</th>
                <th>时长</th>
                <th>提交时间</th>
                <th style={{ textAlign: "right" }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr><td colSpan={6}><div className="g-empty" style={{ padding: 40 }}>暂无任务</div></td></tr>
              )}
              {filtered.map((v) => {
                const sb = statusBadge(v);
                const pct = v.progress ?? 0;
                return (
                  <tr key={v.id} style={{ opacity: deletingIds.has(v.id) ? 0.5 : 1 }}>
                    <td>
                      <div style={{ fontWeight: 500, color: "#1e293b", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v.file_name}</div>
                      {v.group_id && <div style={{ fontSize: 10, color: "#94a3b8" }}>分组任务</div>}
                    </td>
                    <td><span className={"g-badge " + sb.cls}>{sb.pulse && <span className="pulse" />}{sb.label}</span></td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, width: 180 }}>
                        <div className="g-progress" style={{ flex: 1 }}>
                          <div className={"g-progress-fill" + (v.status === "completed" ? " ok" : v.status === "failed" ? " err" : "")} style={{ width: `${pct}%` }} />
                        </div>
                        <span style={{ fontSize: 11, color: "#64748b", fontFamily: "var(--font-mono)" }}>{pct.toFixed(0)}%</span>
                      </div>
                    </td>
                    <td style={{ fontSize: 12, color: "#64748b" }}>{v.duration != null ? fmtDuration(v.duration) : "—"}</td>
                    <td style={{ fontSize: 12, color: "#94a3b8" }}>{fmtDate(v.created_at)}</td>
                    <td>
                      <div style={{ display: "flex", justifyContent: "flex-end", gap: 6 }}>
                        <button className="g-btn g-btn-sm" onClick={() => openWorkbench(v.id)}>查看结果</button>
                        <button className="g-btn g-btn-sm g-btn-danger" onClick={() => handleDelete(v.id)} disabled={deletingIds.has(v.id)}>删除</button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
