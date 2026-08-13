/* ════════════════════════════════════════════════════════════
   TaskCenter — 任务中心（v0.34 桌面重构 · 照 demo TaskCenter 表格）
   顶栏（标题+已选N+批量操作） + 筛选 Tab（全部/处理中/已完成失败） +
   任务表格（checkbox/任务文件/所属/状态/提交时间/操作）。
   数据 = 共享视频列表（4s 轮询），按 status 过滤。
   ════════════════════════════════════════════════════════════ */

import { useMemo, useState } from "react";
import { useApp } from "../AppContext";
import type { VideoListItem } from "../types";
import { fmtDate, fmtDuration } from "../utils/helpers";
import { IconTask } from "./icons";

const FILTERS = [
  { key: "all", label: "全部任务" },
  { key: "active", label: "处理中" },
  { key: "history", label: "已完成/失败" },
] as const;
type FilterKey = typeof FILTERS[number]["key"];

function StatusBadge({ v }: { v: VideoListItem }) {
  if (v.status === "processing") {
    return (
      <div className="flex items-center gap-2">
        <span className="g-badge run">处理中 {Math.round(v.progress)}%</span>
        <div className="g-progress w-16"><div style={{ width: `${v.progress}%` }} /></div>
      </div>
    );
  }
  const map: Record<string, [string, string]> = {
    pending: ["待参数", "wait"],
    completed: ["已完成", "ok"],
    failed: ["失败", "err"],
  };
  const [label, cls] = map[v.status] || [v.status, "wait"];
  return <span className={"g-badge " + cls}>{label}</span>;
}

export function TaskCenter() {
  const { videos, videoGroups, openWorkbench, deleteVideo } = useApp();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [checked, setChecked] = useState<Set<string>>(new Set());

  const filtered = useMemo(() => {
    switch (filter) {
      case "active": return videos.filter((v) => v.status === "processing" || v.status === "pending");
      case "history": return videos.filter((v) => v.status === "completed" || v.status === "failed");
      default: return videos;
    }
  }, [videos, filter]);

  const doneCount = videos.filter((v) => v.status === "completed").length;
  const failedCount = videos.filter((v) => v.status === "failed").length;

  const toggleCheck = (id: string) => {
    setChecked((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  };
  const allChecked = filtered.length > 0 && checked.size === filtered.length;
  const toggleAll = () => setChecked(allChecked ? new Set() : new Set(filtered.map((v) => v.id)));

  const handleDelete = async (id: string) => {
    if (!window.confirm("确定删除该任务？将同时释放磁盘空间。")) return;
    try { await deleteVideo(id); }
    catch (err) { alert(err instanceof Error ? err.message : "删除失败"); }
  };

  const batchDelete = async () => {
    if (checked.size === 0) return;
    if (!window.confirm(`确定删除所选 ${checked.size} 个任务？`)) return;
    for (const id of checked) { try { await deleteVideo(id); } catch { /* 单个失败继续 */ } }
    setChecked(new Set());
  };

  return (
    <div className="h-full flex flex-col">
      {/* ══ 顶栏 ══ */}
      <div className="h-[52px] px-5 bg-white border-b border-gray-200 flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-[15px] font-semibold text-gray-900 leading-tight flex items-center gap-2">
            <IconTask /> 任务中心
          </h1>
          <p className="text-[11.5px] text-gray-400 leading-tight">后台进程监控与历史记录追溯</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11.5px] text-gray-400 mr-1">已选 {checked.size} 项</span>
          <button className="g-btn" onClick={batchDelete} disabled={!checked.size}>批量删除</button>
        </div>
      </div>

      {/* ══ 筛选栏 ══ */}
      <div className="px-5 py-2 bg-white border-b border-gray-100 flex items-center gap-1 shrink-0">
        {FILTERS.map((f) => (
          <button key={f.key} className={"g-tab " + (filter === f.key ? "active" : "")} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-[11.5px] text-gray-400">完成 {doneCount} · 失败 {failedCount} · 每 4 秒自动刷新</span>
      </div>

      {/* ══ 任务表格 ══ */}
      <div className="flex-1 min-h-0 bg-white overflow-auto">
        <table className="g-table">
          <thead>
            <tr>
              <th className="w-9">
                <input type="checkbox" className="accent-[#4f7cff] cursor-pointer" checked={allChecked} onChange={toggleAll} />
              </th>
              <th>任务 / 文件</th>
              <th className="w-40">所属</th>
              <th className="w-52">状态</th>
              <th className="w-36">提交时间</th>
              <th className="w-24">时长</th>
              <th className="w-[180px] text-right pr-4">操作</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((v) => {
              const gid = v.group_id;
              const groupCount = gid ? videoGroups.find((g) => g.groupId === gid)?.videoIds.length ?? 1 : 0;
              return (
                <tr key={v.id} className={checked.has(v.id) ? "bg-brand/5" : ""}>
                  <td>
                    <input type="checkbox" className="accent-[#4f7cff] cursor-pointer" checked={checked.has(v.id)} onChange={() => toggleCheck(v.id)} />
                  </td>
                  <td>
                    <div className="text-[13px] text-gray-800 truncate max-w-[280px]" title={v.file_name}>{v.file_name}</div>
                    <div className="text-[11px] text-gray-400 font-mono">{v.id.slice(0, 8)}</div>
                  </td>
                  <td className="text-gray-600">{gid ? `分组 ${groupCount} 个视频` : <span className="text-gray-300">未分组</span>}</td>
                  <td><StatusBadge v={v} /></td>
                  <td className="text-gray-500">{fmtDate(v.created_at)}</td>
                  <td className="text-gray-500">{v.duration != null ? fmtDuration(v.duration) : "-"}</td>
                  <td className="text-right pr-4 whitespace-nowrap">
                    <button className="g-btn !px-2 !py-1 mr-1" onClick={() => openWorkbench(v.id)}>查看结果</button>
                    <button className="g-btn g-btn-danger !px-2 !py-1" onClick={() => handleDelete(v.id)}>删除</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 && <div className="g-empty"><span>当前筛选下暂无任务</span></div>}
      </div>
    </div>
  );
}
