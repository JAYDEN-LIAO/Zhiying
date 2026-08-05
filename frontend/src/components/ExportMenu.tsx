/* ════════════════════════════════════════════════════════════
   ExportMenu — 简化版导出菜单（单个表单）
   仅保留"导出视频片段或节点"功能。
   start == end → 导出单帧
   start < end  → 导出视频片段
   使用 GET + window.open 直接导航，避免浏览器屏蔽自动下载。
   ════════════════════════════════════════════════════════════ */

import { useState } from "react";
import { api } from "../services/api";
import { IconClose } from "./icons";

export function ExportMenu({
  videoId,
  onClose,
}: {
  videoId: string;
  onClose: () => void;
}) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const handleExport = () => {
    setErr(null);
    const s = parseFloat(start);
    const e = parseFloat(end);

    if (isNaN(s) || s < 0) { setErr("起始时间无效（必须 ≥ 0）"); return; }
    if (isNaN(e) || e < 0) { setErr("结束时间无效（必须 ≥ 0）"); return; }
    if (s > e) { setErr("结束时间必须 ≥ 起始时间"); return; }

    window.open(api.getClipExportUrl(videoId, s, e), "_blank");
    onClose();
  };

  return (
    <div className="absolute right-0 top-10 z-50 w-[360px] rounded-2xl bg-white shadow-2xl border border-gray-200"
         onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <h3 className="font-bold text-gray-900 text-sm">导出视频片段或节点</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
          <IconClose />
        </button>
      </div>

      <div className="py-4 space-y-4">
        <p className="px-5 text-xs text-gray-500">
          起始与结束时间相同时导出单帧，否则导出视频片段（mp4）。
        </p>

        <div className="px-5">
          <label className="block text-xs text-gray-500 mb-1">起始时间（秒）</label>
          <input
            type="number" min="0" step="any"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            placeholder="0.0"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400"
          />
        </div>

        <div className="px-5">
          <label className="block text-xs text-gray-500 mb-1">结束时间（秒）</label>
          <input
            type="number" min="0" step="any"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            placeholder="10.0"
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-teal-400"
          />
        </div>

        {err && <p className="px-5 text-xs text-red-500">{err}</p>}

        <div className="px-5 pt-1">
          <button
            onClick={handleExport}
            disabled={!start.trim() || !end.trim()}
            className="w-full rounded-lg bg-teal-600 text-white text-sm font-medium py-2.5 hover:bg-teal-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {start && end && parseFloat(start) === parseFloat(end) ? "导出帧" : "导出片段"}
          </button>
        </div>
      </div>
    </div>
  );
}
