/* ════════════════════════════════════════════════════════════
   TaskCenter — 任务中心（v0.34 接线 /tasks 后端）
   ① TaskHeader 顶部卡：任务中心标题 + 统计
   ② TaskBody   正文卡：筛选 Tab + 任务表格（checkbox/任务文件/所属/
     状态/提交时间/操作: 日志/重试/删除）+ 日志弹窗。4s 轮询 api.listTasks(scope)。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useApp } from "../AppContext";
import type { TaskItem, TaskLogLine } from "../types";
import { fmtDate, fmtDuration, fmtTime, versionName, copyText, parseUtcIso } from "../utils/helpers";
import { api, downloadFile, sanitizeFile } from "../services/api";
import { IconDownload, IconReport, IconLog, IconTask, IconRetry, IconCopy, IconTrash, IconCheck } from "./icons";

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "completed", label: "已完成" },
  { key: "processing", label: "处理中" },
  { key: "queued", label: "排队中" },
  { key: "failed", label: "失败" },
] as const;
type FilterKey = typeof FILTERS[number]["key"];

const STATUS_META: Record<string, { label: string; cls: string; pulse?: boolean }> = {
  pending: { label: "待处理", cls: "wait" },
  processing: { label: "处理中", cls: "run", pulse: true },
  completed: { label: "已完成", cls: "ok" },
  failed: { label: "失败", cls: "err" },
};
/* 排队中：已提交、在管道队列等 worker（status=pending + queued，黄徽章） */
const QUEUED_META: { label: string; cls: string; pulse?: boolean } = { label: "排队中", cls: "warn" };

/* 日志弹窗头部图标钮（导出/复制）：28×28 与 .modal-x 同尺寸 → 三钮等高对齐 */
const LOG_HDR_BTN =
  "w-7 h-7 rounded-md flex items-center justify-center text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors disabled:opacity-40 disabled:pointer-events-none";

/* 导出文件用完整时间戳（Asia/Shanghai，与界面 fmtTime 同时区策略） */
function fmtFull(iso: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    timeZone: "Asia/Shanghai",
  }).format(parseUtcIso(iso)).replace(/\//g, "-");
}

/* ═══════════════════════ ① 顶部卡 ═══════════════════════ */
function TaskHeader({
  filter, onFilter, onExportAll,
}: {
  filter: FilterKey;
  onFilter: (f: FilterKey) => void;
  onExportAll: () => void;
}) {
  return (
    <div className="case-card flex items-center justify-between flex-wrap gap-y-1.5 px-5 py-2 min-h-[56px] shrink-0">
      <div>
        <h1 className="text-[16px] font-semibold text-gray-900 leading-tight">任务中心</h1>
        <p className="text-[12px] text-gray-500 leading-tight">后台进程监控与历史记录追溯</p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <select className="g-input !h-[30px] !text-[12px]" value={filter}
          onChange={(e) => onFilter(e.target.value as FilterKey)} title="筛选状态">
          {FILTERS.map((f) => (
            <option key={f.key} value={f.key}>{f.label}</option>
          ))}
        </select>
        <button className="g-btn g-btn-primary" onClick={onExportAll}>
          <IconDownload />
          导出
        </button>
      </div>
    </div>
  );
}

/* ═══════════════════════ ② 正文卡 ═══════════════════════ */
function TaskBody({
  tasks, onOpenLog, onExportReport, onOpenTask, busyId, onRetry, onDelete, highlightIds,
}: {
  tasks: TaskItem[];
  onOpenLog: (t: TaskItem) => void;
  onExportReport: (t: TaskItem) => void;
  onOpenTask: (t: TaskItem) => void;
  busyId: string | null;
  onRetry: (t: TaskItem) => void;
  onDelete: (t: TaskItem) => void;
  highlightIds: string[];  // 本次进入任务中心待高亮的「新完成」行 id
}) {
  return (
    <div className="case-card flex-1 min-h-0 flex flex-col overflow-hidden">
      {/* 任务表格（筛选已上移至顶部卡下拉） */}
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
              const sm = t.status === "pending" && t.queued ? QUEUED_META : STATUS_META[t.status] || STATUS_META.pending;
              return (
                <tr
                  key={t.id}
                  className={"cursor-pointer " + (highlightIds.includes(t.id) ? "task-row-new" : "")}
                  onClick={() => onOpenTask(t)}
                  title="点击进入视频解析"
                >
                  <td className="!pr-0">
                    <div className="text-[13px] text-gray-800 truncate max-w-[280px]">{t.file_name ?? t.id.slice(0, 8)}</div>
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
                        <span className="text-[12px] text-gray-500 font-mono">{Math.round(t.progress * 100)}%</span>
                      )}
                    </div>
                  </td>
                  <td className="text-gray-500 !px-1">{fmtDate(t.created_at)}</td>
                  <td className="text-gray-500 font-mono !pl-1">{fmtDuration(t.duration_sec)}</td>
                  <td className="text-right pr-4 whitespace-nowrap">
                    {t.status === "failed" && (
                      <>
                        <button className="p-1.5 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors mr-1" title="删除任务"
                          onClick={(e) => { e.stopPropagation(); onDelete(t); }}>
                          <IconTrash />
                        </button>
                        <button className="p-1.5 rounded-md text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors mr-1" title="重试"
                          onClick={(e) => { e.stopPropagation(); onRetry(t); }} disabled={busyId === t.id}>
                          <IconRetry className={busyId === t.id ? "animate-spin" : ""} />
                        </button>
                      </>
                    )}
                    <button className="p-1.5 rounded-md text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors mr-1" title="导出报告"
                      onClick={(e) => { e.stopPropagation(); onExportReport(t); }}>
                      <IconReport />
                    </button>
                    <button className="p-1.5 rounded-md text-gray-400 hover:text-[#4f7cff] hover:bg-blue-50 transition-colors" title="任务日志"
                      onClick={(e) => { e.stopPropagation(); onOpenLog(t); }}>
                      <IconLog />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {tasks.length === 0 && <div className="g-empty"><IconTask /><span>当前筛选下暂无任务</span></div>}
      </div>
    </div>
  );
}

export function TaskCenter() {
  const { openWorkbench, taskHighlightIds } = useApp();
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [filter, setFilter] = useState<FilterKey>("all");
  const [logTask, setLogTask] = useState<TaskItem | null>(null);
  const [logs, setLogs] = useState<TaskLogLine[]>([]);
  const [loadingLog, setLoadingLog] = useState(false);
  const [copiedLog, setCopiedLog] = useState(false);

  /* 日志弹窗尾部跟随：sticky=用户滚到底部附近时自动吸底，往上翻则不打扰 */
  const logBoxRef = useRef<HTMLDivElement | null>(null);
  const stickBottomRef = useRef(true);
  const lastLogSeqRef = useRef(0);

  const handleCopyLog = async () => {
    const text = logs
      .map((l) => `${l.created_at ?? ""} #${String(l.seq).padStart(2, "0")} ${l.message}`)
      .join("\n");
    if (!text) return;
    if (await copyText(text)) {
      setCopiedLog(true);
      setTimeout(() => setCopiedLog(false), 2000);
    }
  };

  /* 日志导出：.log 纯文本（机器日志行业扩展名，编辑器高亮 + grep/tail 可用）。
     结构 = 头部元信息块（# 注释行，兼容 grep 过滤）+ 正文「时间 [级别] #序号 消息」。
     UTF-8 加 BOM：客户机 Windows 记事本旧默认 ANSI，无 BOM 会中文乱码。 */
  const handleDownloadLog = () => {
    if (!logTask || loadingLog || logs.length === 0) return;
    const sm = logTask.status === "pending" && logTask.queued ? QUEUED_META : STATUS_META[logTask.status] || STATUS_META.pending;
    const first = logs[0], last = logs[logs.length - 1];
    const header = [
      "# ══════════════════════════════════════════",
      "# 智影任务日志",
      `# 任务 ID   : ${logTask.id}`,
      `# 文件      : ${logTask.file_name ?? "-"}`,
      `# 状态      : ${sm.label}`,
      `# 记录条数  : ${logs.length}`,
      `# 开始时间  : ${first?.created_at ? fmtFull(first.created_at) : "-"}`,
      `# 结束时间  : ${last?.created_at ? fmtFull(last.created_at) : "-"}`,
      `# 导出时间  : ${fmtFull(new Date().toISOString())}`,
      "# ══════════════════════════════════════════",
      "",
    ].join("\r\n");
    const body = logs.map((l) => {
      const lv = (l.level || "info").toUpperCase().padEnd(5);
      return `${l.created_at ? fmtFull(l.created_at) : "-".repeat(19)} [${lv}] #${String(l.seq).padStart(3, "0")} ${l.message}`;
    }).join("\r\n");
    const blob = new Blob(["\ufeff", header + "\r\n" + body + "\r\n"], { type: "text/plain;charset=utf-8" });
    downloadFile(blob, `tasklog_${sanitizeFile(logTask.file_name ?? "")}_${logTask.id.slice(0, 8)}.log`);
  };

  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () => {
    // 一次拉全量，客户端按筛选状态过滤（后端 scope 只支持 all/active/history）
    api.listTasks("all").then((data) => {
      // 任务中心只显示已提交任务：剔除纯待处理（仅上传未提交，status=pending 且未排队）
      const raw = (data ?? []).filter((t) => !(t.status === "pending" && !t.queued));
      let list = raw;
      if (filter === "completed") list = raw.filter((t) => t.status === "completed");
      else if (filter === "processing") list = raw.filter((t) => t.status === "processing");
      else if (filter === "queued") list = raw.filter((t) => !!t.queued);
      else if (filter === "failed") list = raw.filter((t) => t.status === "failed");
      setTasks(list);
    }).catch(() => {});
  };
  useEffect(() => { load(); }, [filter]);
  useEffect(() => {
    const iv = setInterval(load, 1000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const openLog = async (t: TaskItem) => {
    setLogTask(t);
    setLogs([]);
    setLoadingLog(true);
    lastLogSeqRef.current = 0;
    // 存活任务初始直接跳到底部看最新日志；已完成任务从头看
    const statusNow = tasks.find((x) => x.id === t.id)?.status ?? t.status;
    stickBottomRef.current = statusNow === "processing" || statusNow === "pending";
    try {
      const d = await api.getTaskLog(t.id);
      const list = d?.log ?? [];
      if (list.length > 0) lastLogSeqRef.current = list[list.length - 1].seq;
      setLogs(list);
    } catch { setLogs([]); }
    setLoadingLog(false);
  };

  /* 处理中/排队中任务的日志弹窗自动增量刷新（2.5s 按 seq 追加），结束后停止。
     依赖用状态值而非 tasks 数组（列表每秒轮询刷新，数组恒变化会不断重建 interval） */
  const logTaskStatus = logTask
    ? (tasks.find((x) => x.id === logTask.id)?.status ?? logTask.status)
    : null;
  useEffect(() => {
    if (!logTask || !(logTaskStatus === "processing" || logTaskStatus === "pending")) return;
    const tid = logTask.id;
    const iv = setInterval(async () => {
      try {
        const d = await api.getTaskLog(tid);
        const fresh = (d?.log ?? []).filter((l) => l.seq > lastLogSeqRef.current);
        if (fresh.length > 0) {
          lastLogSeqRef.current = fresh[fresh.length - 1].seq;
          setLogs((prev) => [...prev, ...fresh]);
        }
      } catch { /* 后端瞬时不可达：忽略，下一轮重试 */ }
    }, 2500);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logTask?.id, logTaskStatus]);

  /* 日志内容变化 → 吸底跟随（用户主动上翻后不再强制拉回） */
  useEffect(() => {
    const el = logBoxRef.current;
    if (!el || logs.length === 0 || !stickBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [logs]);

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

  const deleteTask = async (t: TaskItem) => {
    if (!window.confirm(`确认删除该任务？视频文件不会被删除。`)) return;
    setBusyId(t.id);
    try {
      await api.deleteTask(t.id);
      load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
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
      {/* ① 顶部卡（含状态筛选下拉 + 导出） */}
      <TaskHeader filter={filter} onFilter={setFilter} onExportAll={exportAll} />

      {/* ② 正文卡 */}
      <TaskBody
        tasks={tasks}
        onOpenLog={openLog}
        onExportReport={exportReport}
        onOpenTask={(t) => openWorkbench(t.id, { openParams: false, versionId: t.id })}
        busyId={busyId}
        onRetry={retry}
        onDelete={deleteTask}
        highlightIds={taskHighlightIds}
      />

      {/* 日志弹窗 */}
      {logTask && createPortal(
        <div className="g-modal-overlay">
          <div className="g-modal" style={{ width: 600 }}>
            <div className="g-card-hd">
              <span className="g-card-tt">任务日志 · {logTask.file_name ?? ""}</span>
              {/* 导出(.log) / 复制 / 关闭 —— 三钮统一 28×28 图标（与 .modal-x 同尺寸等高对齐） */}
              <div className="flex items-center gap-1">
                <button className={LOG_HDR_BTN} disabled={loadingLog || logs.length === 0}
                  onClick={handleDownloadLog} title="导出日志文件" aria-label="导出日志文件">
                  <IconDownload />
                </button>
                <button className={copiedLog ? LOG_HDR_BTN + " !text-green-500" : LOG_HDR_BTN}
                  onClick={() => void handleCopyLog()} disabled={loadingLog || logs.length === 0}
                  title={copiedLog ? "已复制" : "复制日志"} aria-label="复制日志">
                  {copiedLog ? <IconCheck /> : <IconCopy />}
                </button>
                <button className="modal-x ml-1" onClick={() => setLogTask(null)} title="关闭" aria-label="关闭">×</button>
              </div>
            </div>
            <div ref={logBoxRef} onScroll={() => {
              // 用户上翻（距底 > 40px）→ 暂停吸底；翻回底部 → 恢复跟随
              const el = logBoxRef.current;
              if (!el) return;
              stickBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
            }}
              className="p-4" style={{ maxHeight: "60vh", overflowY: "auto", fontFamily: "var(--font-mono)", fontSize: 12, background: "#0d1117", color: "#d1d5db" }}>
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
        </div>,
        document.body,
      )}
    </div>
  );
}
