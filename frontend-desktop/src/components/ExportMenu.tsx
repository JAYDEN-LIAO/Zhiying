/* ════════════════════════════════════════════════════════════
   ExportMenu — 紧凑下拉导出菜单
   5 个选项：视频片段（展开时间输入）/ 分析报告 / 视频摘要 / 文字识别 / 车牌识别
   除视频片段外，点击即导出。
   ════════════════════════════════════════════════════════════ */

import { useState } from "react";
import { api } from "../services/api";

export function ExportMenu({
  videoId,
  hasSummary = false,
  hasOcr = false,
  hasPlate = false,
  onClose,
}: {
  videoId: string;
  hasSummary?: boolean;
  hasOcr?: boolean;
  hasPlate?: boolean;
  onClose: () => void;
}) {
  const [clipOpen, setClipOpen] = useState(false);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const handleClipExport = () => {
    setErr(null);
    const s = parseFloat(start);
    const e = parseFloat(end);
    if (isNaN(s) || s < 0) { setErr("起始时间无效"); return; }
    if (isNaN(e) || e < 0) { setErr("结束时间无效"); return; }
    if (s > e) { setErr("结束时间须 ≥ 起始时间"); return; }
    window.open(api.getClipExportUrl(videoId, s, e), "_blank");
    onClose();
  };

  const itemCls = (enabled: boolean) =>
    "w-full text-left px-3 py-[7px] text-[13px] rounded-md transition-all duration-150 border-l-2 " +
    (enabled
      ? "text-gray-700 border-transparent hover:border-teal-500 hover:bg-teal-50 hover:text-teal-700 cursor-pointer"
      : "text-gray-400 border-transparent cursor-not-allowed");

  return (
    <div className="py-1.5" onClick={(e) => e.stopPropagation()}>
      {/* 视频片段 */}
      <button
        className="w-full text-left px-3 py-[7px] text-[13px] rounded-md border-l-2 border-transparent hover:border-teal-500 hover:bg-teal-50 hover:text-teal-700 transition-all duration-150 flex items-center justify-between text-gray-700"
        onClick={() => setClipOpen((v) => !v)}
      >
        <span>视频片段</span>
        <svg className={"w-3 h-3 text-gray-400 transition-transform " + (clipOpen ? "rotate-180" : "")} fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
      </button>
      {clipOpen && (
        <div className="px-3 pb-2 space-y-1.5">
          <div className="flex gap-1.5">
            <input
              type="number" min="0" step="any"
              value={start} onChange={(e) => setStart(e.target.value)}
              placeholder="起始(秒)"
              className="flex-1 min-w-0 rounded border border-gray-200 px-2 py-1 text-[12px] focus:outline-none focus:ring-1 focus:ring-teal-400"
            />
            <input
              type="number" min="0" step="any"
              value={end} onChange={(e) => setEnd(e.target.value)}
              placeholder="结束(秒)"
              className="flex-1 min-w-0 rounded border border-gray-200 px-2 py-1 text-[12px] focus:outline-none focus:ring-1 focus:ring-teal-400"
            />
          </div>
          {err && <p className="text-[11px] text-red-500">{err}</p>}
          <button
            onClick={handleClipExport}
            disabled={!start.trim() || !end.trim()}
            className="w-full rounded bg-teal-600 text-white text-[12px] font-medium py-1.5 hover:bg-teal-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            导出
          </button>
        </div>
      )}

      {/* 分析报告 */}
      <button
        className={itemCls(true)}
        onClick={() => { window.open(api.getTaskReportExportUrl(videoId), "_blank"); onClose(); }}
      >
        分析报告
      </button>

      {/* 视频摘要 */}
      <button
        className={itemCls(hasSummary)}
        disabled={!hasSummary}
        onClick={() => { if (hasSummary) { window.open(api.getSummaryExportUrl(videoId), "_blank"); onClose(); } }}
        title={!hasSummary ? "解析时未开启摘要" : undefined}
      >
        视频摘要{!hasSummary && <span className="text-[11px] ml-1">（未开启）</span>}
      </button>

      {/* 文字识别 */}
      <button
        className={itemCls(hasOcr)}
        disabled={!hasOcr}
        onClick={() => { if (hasOcr) { window.open(api.getOcrExportUrl(videoId), "_blank"); onClose(); } }}
        title={!hasOcr ? "解析时未开启 OCR" : undefined}
      >
        文字识别{!hasOcr && <span className="text-[11px] ml-1">（未开启）</span>}
      </button>

      {/* 车牌识别 */}
      <button
        className={itemCls(hasPlate)}
        disabled={!hasPlate}
        onClick={() => { if (hasPlate) { window.open(api.getPlatesExportUrl(videoId), "_blank"); onClose(); } }}
        title={!hasPlate ? "解析时未开启车牌识别" : undefined}
      >
        车牌识别{!hasPlate && <span className="text-[11px] ml-1">（未开启）</span>}
      </button>
    </div>
  );
}
