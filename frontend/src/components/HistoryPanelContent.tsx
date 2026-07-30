/* ════════════════════════════════════════════════════════════
   HistoryPanelContent — v2.0 style (slide-out panel content)
   ════════════════════════════════════════════════════════════ */

import { useState } from "react";
import { api } from "../services/api";
import type { VideoListItem } from "../types";
import { fmtDate } from "../utils/helpers";

const ctLabel: Record<string, string> = {
  general: "通用", meeting: "会议", surveillance: "监控", text_recognition: "文字识别",
};

export function HistoryPanelContent({
  videos, currentVideoId, loading, onSelect, onDelete,
}: {
  videos: VideoListItem[];
  currentVideoId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");

  const handleDelete = async (id: string) => {
    setDeletingIds((prev) => new Set(prev).add(id));
    try { await api.deleteVideo(id); setTimeout(() => onDelete(id), 250); }
    catch { setDeletingIds((prev) => { const next = new Set(prev); next.delete(id); return next; }); }
  };

  const filteredVideos = searchQuery.trim()
    ? videos.filter((v) => v.file_name.toLowerCase().includes(searchQuery.toLowerCase()))
    : videos;

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Search */}
      <div className="px-4 pt-3 pb-2 shrink-0">
        <div className="relative">
          <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
          <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="搜索视频文件名..."
            className="w-full pl-8 pr-3 py-1.5 text-[11px] bg-white border border-gray-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-300 transition-all placeholder:text-gray-400" />
          {searchQuery && (
            <button onClick={() => setSearchQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500 cursor-pointer">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {searchQuery && <p className="text-[10px] text-gray-400">找到 {filteredVideos.length} 条</p>}
        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => <div key={i} className="animate-pulse bg-gray-50 rounded-xl p-3"><div className="aspect-video rounded-lg bg-gray-100" /><div className="h-3 bg-gray-100 rounded w-3/4 mt-2" /></div>)}
          </div>
        ) : filteredVideos.length === 0 ? (
          <div className="text-center py-12"><p className="text-sm text-gray-400">{searchQuery ? "无匹配视频" : "暂无视频"}</p></div>
        ) : (
          filteredVideos.map((item) => {
            const shortName = item.file_name.length > 10 ? item.file_name.slice(0, 10) + "…" : item.file_name;
            const fnParts: string[] = [];
            if (item.search_index_enabled) fnParts.push("搜索");
            if (item.summary_enabled) fnParts.push("摘要");
            const fnLabel = fnParts.length === 2 ? "搜索+摘要" : fnParts[0] || "—";
            const isDeleting = deletingIds.has(item.id);
            return (
              <div key={item.id}
                className={`overflow-hidden transition-all duration-500 ease-out ${
                  isDeleting
                    ? "max-h-0 opacity-0 -translate-x-full scale-y-0 mb-0"
                    : "max-h-[200px] opacity-100 translate-x-0 scale-y-100 mb-2"
                }`}>
                <div onClick={() => onSelect(item.id)}
                  className={`rounded-xl cursor-pointer border p-3 transition-all duration-300 ${
                    currentVideoId === item.id ? "bg-blue-50 border-blue-200" : "bg-white border-gray-100 hover:bg-gray-50 hover:border-gray-200"
                  }`}>
                  <div className="flex items-start gap-3">
                    <div className="w-[72px] aspect-video rounded-lg shrink-0 bg-gray-100 flex items-center justify-center overflow-hidden border border-gray-200/50">
                      {item.status === "completed" ? (
                        <img src={`/api/v1/videos/${item.id}/thumbnail/0`} alt="" className="w-full h-full object-cover" loading="lazy"
                          onError={(e) => { (e.target as HTMLImageElement).parentElement!.innerHTML = '<span class="text-[10px] text-gray-400">视频</span>'; }} />
                      ) : <span className="text-[10px] text-gray-400">视频</span>}
                    </div>
                    <div className="min-w-0 flex-1 self-stretch flex flex-col justify-between">
                      <div>
                        <h3 className="text-sm font-semibold text-gray-900 truncate" title={item.file_name}>{shortName}</h3>
                        <p className="text-[10px] text-gray-400 leading-tight mt-0.5">
                          {ctLabel[item.content_type] || item.content_type} <span className="text-gray-300">|</span> {fnLabel} <span className="text-gray-300">|</span> {item.sample_fps.toFixed(1)}fps
                        </p>
                      </div>
                      <div className="flex items-center justify-between mt-1">
                        <div className="flex items-center gap-2">
                          <span className={`text-[10px] font-medium ${
                            item.status === "completed" ? "text-green-500" : item.status === "processing" ? "text-blue-500"
                            : item.status === "failed" ? "text-red-400" : "text-gray-400"}`}>
                            {item.status === "completed" ? "已完成" : item.status === "processing" ? "处理中" : item.status === "failed" ? "失败" : "等待中"}
                          </span>
                          <span className="text-[9px] text-gray-400">{fmtDate(item.created_at)}</span>
                        </div>
                        <button onClick={(e) => { e.stopPropagation(); handleDelete(item.id); }} className="text-gray-300 hover:text-red-500 transition-colors cursor-pointer">
                          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" /></svg>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
      <div className="shrink-0 h-4" />
    </div>
  );
}
