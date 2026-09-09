/* ════════════════════════════════════════════════════════════
   DownloadManager — 下载管理弹窗（TitleBar 下载图标入口）
   列表：文件名 / 大小 / 进度条 / 状态 / 错误信息；
   操作：已完成 → 打开文件夹；失败/已取消 → 重试；终态 → 清除。
   数据来自壳（downloads.py job 队列）+ 前端合成任务（文本导出），
   由 services/downloads.tsx 轮询汇聚。
   ════════════════════════════════════════════════════════════ */

import { createPortal } from "react-dom";
import { useDownloader } from "../services/downloads";
import { fmtBytes } from "../utils/helpers";

const STATUS_CLS: Record<string, string> = {
  "下载中": "text-[#4f7cff]",
  "已完成": "text-emerald-600",
  "失败": "text-red-500",
  "已取消": "text-gray-400",
};

export function DownloadManager() {
  const { jobs, open, setOpen, retry, clear, openDir } = useDownloader();
  if (!open) return null;

  return createPortal(
    <div className="g-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setOpen(false); }}>
      <div className="g-modal" style={{ width: 560 }}>
        <div className="g-card-hd">
          <span className="g-card-tt">下载管理</span>
          <button className="modal-x" onClick={() => setOpen(false)} aria-label="关闭">×</button>
        </div>
        <div className="p-4 space-y-2 overflow-auto" style={{ maxHeight: "60vh" }}>
          {jobs.length === 0 && (
            <div className="text-center text-[13px] text-gray-400 py-8">暂无下载任务</div>
          )}
          {jobs.map((j) => {
            const pct = j.total > 0 ? Math.min(100, Math.round((j.done / j.total) * 100)) : null;
            const finished = j.status === "已完成";
            const dead = j.status === "失败" || j.status === "已取消";
            return (
              <div key={j.id} className="rounded-lg border border-gray-200 px-3 py-2.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] text-gray-800" title={j.path || j.name}>{j.name}</span>
                  <span className={"shrink-0 text-[12px] font-medium " + (STATUS_CLS[j.status] ?? "text-gray-500")}>
                    {j.status}{j.status === "下载中" && pct != null ? ` ${pct}%` : ""}
                  </span>
                </div>
                {j.status === "下载中" && (
                  <div className="g-progress mt-2">
                    <div className="g-progress-fill" style={{ width: `${pct ?? 5}%` }} />
                  </div>
                )}
                {j.error && <div className="mt-1 text-[11px] text-red-500 truncate" title={j.error}>{j.error}</div>}
                <div className="mt-1.5 flex items-center justify-between text-[11px] text-gray-400">
                  <span>
                    {j.status === "下载中" || finished || dead ? fmtBytes(j.done) : ""}
                    {(j.status === "下载中" || finished) && j.total > 0 ? ` / ${fmtBytes(j.total)}` : ""}
                  </span>
                  <div className="flex items-center gap-3">
                    {finished && j.path && (
                      <button className="hover:text-[#4f7cff]" onClick={() => openDir(j.path)}>打开文件夹</button>
                    )}
                    {dead && (
                      <button className="hover:text-[#4f7cff]" onClick={() => retry(j.id)}>重试</button>
                    )}
                    {(finished || dead) && (
                      <button className="hover:text-gray-600" onClick={() => clear(j.id)}>清除</button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>,
    document.body,
  );
}
