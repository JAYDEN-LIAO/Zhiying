/* ════════════════════════════════════════════════════════════
   TaskCenter — 任务中心（v0.34 接线 /tasks 后端）
   顶栏 + 筛选 Tab + 任务表格（checkbox/任务文件/所属/状态/提交时间/操作:
   日志/重试/删除）。4s 轮询 api.listTasks(scope)。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import type { TaskItem, TaskLogLine } from "../types";
import { fmtDate } from "../utils/helpers";
import { IconTask } from "./icons";

const FILTERS = [
  { key: "all", label: "全部任务" },
  { key: "active", label: "处理中" },
  { key: "history", label: "已完成/失败" },
] as const;
type FilterKey = typeof FILTERS[number]["key"];

const STATUS_META: Record<string, { label: string; cls: string; pulse?: boolean }> = {
  pending: { label: "待参数", cls: "wait" },
  processing: { label: "处理中", cls: "run", pulse: true },
  completed: { label: "已完成", cls: "ok" },
  failed: { label: "失败", cls: "err" },
};

export function TaskCenter() {
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

  const counts = useMemo(() => {
    const done = tasks.filter((t) => t.status === "completed").length;
    const failed = tasks.filter((t) => t.status === "failed").length;
    return { done, failed };
  }, [tasks]);

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

  const del = async (t: TaskItem) => {
    if (!window.confirm(`确定删除「${t.file_name ?? t.id}」？将释放磁盘空间。`)) return;
    try {
      await api.deleteVideo(t.id);
      load();
    } catch (err) { alert(err instanceof Error ? err.message : "删除失败"); }
  };

  return (
    <div className="h-full flex flex-col">
      {/* ══ 顶栏 ══ */}
      <div className="h-[52px] px-5 bg-white border-b border-gray-200 flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-[15px] font-semibold text-gray-900 leading-tight flex items-center gap-2">
            <IconTask /> 任务中心
          </h1>
          <p className="text-[11.5px] text-gray-500 leading-tight">后台进程监控与历史记录追溯</p>
        </div>
      </div>

      {/* ══ 筛选栏 ══ */}
      <div className="px-5 py-2 bg-white border-b border-gray-100 flex items-center gap-1 shrink-0">
        {FILTERS.map((f) => (
          <button key={f.key} className={"g-tab " + (filter === f.key ? "active" : "")} onClick={() => setFilter(f.key)}>
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-[11.5px] text-gray-500">完成 {counts.done} · 失败 {counts.failed} · 每 4 秒自动刷新</span>
      </div>

      {/* ══ 任务表格 ══ */}
      <div className="flex-1 min-h-0 bg-white overflow-auto">
        <table className="g-table">
          <thead>
            <tr>
              <th>版本</th>
              <th>任务 / 文件</th>
              <th className="w-36">所属</th>
              <th className="w-52">状态</th>
              <th className="w-36">提交时间</th>
              <th className="w-[200px] text-right pr-4">操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => {
              const sm = STATUS_META[t.status] || STATUS_META.pending;
              return (
                <tr key={t.id}>
                  <td className="text-[12px] font-mono text-gray-500">
                    {t.version_no != null ? `V${t.version_no}` : "—"}
                  </td>
                  <td>
                    <div className="text-[13px] text-gray-800 truncate max-w-[280px]" title={t.file_name ?? ""}>{t.file_name ?? t.id.slice(0, 8)}</div>
                    <div className="text-[11px] text-gray-500 font-mono">{t.id.slice(0, 8)}</div>
                  </td>
                  <td className="text-gray-600">{t.group_name ?? <span className="text-gray-300">未分组</span>}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      <span className={"g-badge " + sm.cls}>{sm.pulse && <span className="pulse" />}{sm.label}</span>
                      {(t.status === "processing" || t.status === "pending") && (
                        <div className="g-progress w-16"><div style={{ width: `${t.progress}%` }} /></div>
                      )}
                    </div>
                  </td>
                  <td className="text-gray-500">{fmtDate(t.created_at)}</td>
                  <td className="text-right pr-4 whitespace-nowrap">
                    <button className="g-btn !px-2 !py-1 mr-1" onClick={() => openLog(t)}>日志</button>
                    {t.status === "failed" && (
                      <button className="g-btn !px-2 !py-1 mr-1" onClick={() => retry(t)} disabled={busyId === t.id}>
                        {busyId === t.id ? "重试中…" : "重试"}
                      </button>
                    )}
                    <button className="g-btn g-btn-danger !px-2 !py-1" onClick={() => del(t)}>删除</button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {tasks.length === 0 && <div className="g-empty"><span>当前筛选下暂无任务</span></div>}
      </div>

      {/* ══ 日志 Modal ══ */}
      {logTask && (
        <div className="g-modal-overlay">
          <div className="g-modal" style={{ width: 600 }}>
            <div className="g-card-hd">
              <span className="g-card-tt">任务日志 · {logTask.file_name ?? ""}</span>
              <button className="g-btn g-btn-sm" onClick={() => setLogTask(null)}>关闭</button>
            </div>
            <div className="p-4" style={{ maxHeight: "60vh", overflowY: "auto", fontFamily: "var(--font-mono)", fontSize: 12 }}>
              {loadingLog && <div className="text-gray-500">加载中…</div>}
              {!loadingLog && logs.length === 0 && <div className="text-gray-500">暂无日志</div>}
              {logs.map((l) => (
                <div key={l.seq} style={{ color: l.level === "error" ? "#ef4444" : "#334155", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>
                  <span className="text-gray-500">{String(l.seq).padStart(2, "0")}</span>  {l.message}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
