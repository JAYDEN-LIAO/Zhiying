/* ════════════════════════════════════════════════════════════
   TaskCenter — 任务中心（v0.34 接线 /tasks 后端）
   ① TaskHeader 顶部卡：任务中心标题 + 统计
   ② TaskBody   正文卡：筛选 Tab + 任务表格（checkbox/任务文件/所属/
     状态/提交时间/操作: 日志/重试/删除）+ 日志弹窗。4s 轮询 api.listTasks(scope)。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useState } from "react";
import { api } from "../services/api";
import { useApp } from "../AppContext";
import type { TaskItem, TaskLogLine } from "../types";
import { fmtDate, fmtDuration, fmtTime, versionName } from "../utils/helpers";
import { IconDownload } from "./icons";

const FILTERS = [
  { key: "all", label: "全部任务" },
  { key: "active", label: "处理中" },
  { key: "history", label: "已完成/失败" },
] as const;
type FilterKey = typeof FILTERS[number]["key"];

const STATUS_META: Record<string, { label: string; cls: string; pulse?: boolean }> = {
  pending: { label: "待处理", cls: "wait" },
  processing: { label: "处理中", cls: "run", pulse: true },
  completed: { label: "已完成", cls: "ok" },
  failed: { label: "失败", cls: "err" },
};

/* ═══════════════════════ ① 顶部卡 ═══════════════════════ */
function TaskHeader({ onExportAll }: { onExportAll: () => void }) {
  return (
    <div className="case-card flex items-center justify-between flex-wrap gap-y-1.5 px-5 py-2 min-h-[56px] shrink-0">
      <div>
        <h1 className="text-[16px] font-semibold text-gray-900 leading-tight">任务中心</h1>
        <p className="text-[12px] text-gray-500 leading-tight">后台进程监控与历史记录追溯</p>
      </div>
      <button className="g-btn g-btn-primary" onClick={onExportAll}>
        <IconDownload />
        批量导出
      </button>
    </div>
  );
}

/* ═══════════════════════ ② 正文卡 ═══════════════════════ */
function TaskBody({
  tasks, filter, onFilter, onOpenLog, onExportReport, onOpenTask, busyId, onRetry,
}: {
  tasks: TaskItem[];
  filter: FilterKey;
  onFilter: (f: FilterKey) => void;
  onOpenLog: (t: TaskItem) => void;
  onExportReport: (t: TaskItem) => void;
  onOpenTask: (t: TaskItem) => void;
  busyId: string | null;
  onRetry: (t: TaskItem) => void;
}) {
  return (
    <div className="case-card flex-1 min-h-0 flex flex-col overflow-hidden">
      {/* 筛选 Tab */}
      <div className="px-4 border-b border-gray-100 flex items-center gap-2 flex-wrap shrink-0">
        {FILTERS.map((f) => (
          <button key={f.key} className={"g-tab " + (filter === f.key ? "active" : "")} onClick={() => onFilter(f.key)}>
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-[11.5px] text-gray-500">每 4 秒自动刷新</span>
      </div>

      {/* 任务表格 */}
      <div className="flex-1 min-h-0 overflow-auto">
        <table className="g-table">
          <thead>
            <tr>
              <th className="!pr-0">任务 / 文件</th>
              <th className="w-56 !px-0">版本</th>
              <th className="w-36 !pl-0 !pr-12">所属</th>
              <th className="w-52 !pl-2 !pr-1">状态</th>
              <th className="w-36 !px-1">提交时间</th>
              <th className="w-24 !pl-1">耗时</th>
              <th className="w-[200px] text-right pr-4">操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => {
              const sm = STATUS_META[t.status] || STATUS_META.pending;
              return (
                <tr key={t.id}>
                  <td className="!pr-0">
                    <div
                      className="text-[13px] text-gray-800 truncate max-w-[280px] cursor-pointer hover:text-[#4f7cff] transition-colors"
                      title="点击进入视频解析" onClick={() => onOpenTask(t)}
                    >{t.file_name ?? t.id.slice(0, 8)}</div>
                    <div className="text-[11px] text-gray-500 font-mono">{t.id.slice(0, 8)}</div>
                  </td>
                  <td className="text-[12px] text-gray-600 !px-0">
                    <span className="truncate block max-w-[200px]" title={t.version_no != null ? versionName(t) : ""}>
                      {t.version_no != null ? versionName(t) : "—"}
                    </span>
                  </td>
                  <td className="text-gray-600 !pl-0 !pr-12">{t.group_name ?? <span className="text-gray-300">未分组</span>}</td>
                  <td className="!pl-2 !pr-1">
                    <div className="flex items-center gap-2">
                      <span className={"g-badge " + sm.cls}>{sm.pulse && <span className="pulse" />}{sm.label}</span>
                      {(t.status === "processing" || t.status === "pending") && (
                        <div className="g-progress w-16"><div style={{ width: `${t.progress}%` }} /></div>
                      )}
                    </div>
                  </td>
                  <td className="text-gray-500 !px-1">{fmtDate(t.created_at)}</td>
                  <td className="text-gray-500 font-mono !pl-1">{fmtDuration(t.duration_sec)}</td>
                  <td className="text-right pr-4 whitespace-nowrap">
                    {t.status === "failed" && (
                      <button className="g-btn !px-2 !py-1 mr-1" onClick={() => onRetry(t)} disabled={busyId === t.id}>
                        {busyId === t.id ? "重试中…" : "重试"}
                      </button>
                    )}
                    <button className="g-btn !px-2 !py-1 mr-1" onClick={() => onExportReport(t)}>导出报告</button>
                    <button className="g-btn !px-2 !py-1" onClick={() => onOpenLog(t)}>日志</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {tasks.length === 0 && <div className="g-empty"><span>当前筛选下暂无任务</span></div>}
      </div>
    </div>
  );
}

export function TaskCenter() {
  const { openWorkbench } = useApp();
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [logTask, setLogTask] = useState<TaskItem | null>(null);
  const [logs, setLogs] = useState<TaskLogLine[]>([]);
  const [loadingLog, setLoadingLog] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    api.listTasks(filter).then((data) => setTasks(data ?? [])).catch(() => {});
  };
  useEffect(() => { load(); }, [filter]);
  useEffect(() => {
    const iv = setInterval(load, 4000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const openLog = async (t: TaskItem) => {
    setLogTask(t);
    setLogs([]);
    setLoadingLog(true);
    try {
      const d = await api.getTaskLog(t.id);
      setLogs(d?.log ?? []);
    } catch { setLogs([]); }
    setLoadingLog(false);
  };

  const retry = async (t: TaskItem) => {
    setBusyId(t.id);
    try {
      await api.retryTask(t.id);
      load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "重试失败");
    }
    setBusyId(null);
  };

  const exportReport = async (t: TaskItem) => {
    try {
      await api.exportTaskReport(t.id, t.file_name ?? t.id);
    } catch (err) {
      alert(err instanceof Error ? err.message : "导出报告失败");
    }
  };

  const exportAll = async () => {
    if (tasks.length === 0) { alert("当前筛选下暂无任务"); return; }
    const ids = tasks.map((t) => t.id);
    const zipName = `reports_${ids.length}.zip`;
    try {
      await api.exportTasksBatch(ids, zipName);
    } catch (err) {
      alert(err instanceof Error ? err.message : "批量导出失败");
    }
  };

  return (
    <div className="h-full flex flex-col gap-2 p-2">
      {/* ① 顶部卡 */}
      <TaskHeader onExportAll={exportAll} />

      {/* ② 正文卡 */}
      <TaskBody
        tasks={tasks}
        filter={filter}
        onFilter={setFilter}
        onOpenLog={openLog}
        onExportReport={exportReport}
        onOpenTask={(t) => openWorkbench(t.id, { openParams: false, versionId: t.id })}
        busyId={busyId}
        onRetry={retry}
      />

      {/* 日志弹窗 */}
      {logTask && (
        <div className="g-modal-overlay">
          <div className="g-modal" style={{ width: 600 }}>
            <div className="g-card-hd">
              <span className="g-card-tt">任务日志 · {logTask.file_name ?? ""}</span>
              <button className="g-btn g-btn-sm" onClick={() => setLogTask(null)}>关闭</button>
            </div>
            <div className="p-4" style={{ maxHeight: "60vh", overflowY: "auto", fontFamily: "var(--font-mono)", fontSize: 12, background: "#0d1117", color: "#d1d5db" }}>
              {loadingLog && <div className="text-gray-400">加载中…</div>}
              {!loadingLog && logs.length === 0 && <div className="text-gray-400">暂无日志</div>}
              {logs.map((l) => (
                <div key={l.seq} style={{ color: l.level === "error" ? "#f87171" : "#d1d5db", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                  <span className="text-gray-600 font-mono">{l.created_at ? fmtTime(l.created_at) : ""}</span>{" "}
                  <span className="text-gray-600">{String(l.seq).padStart(2, "0")}</span>  {l.message}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
