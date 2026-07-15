/* ════════════════════════════════════════════════════════════
   HistoryPanelContent — 历史记录列表（面板内嵌内容）
   ════════════════════════════════════════════════════════════ */

import { useState } from "react";
import { api } from "../services/api";
import type { VideoListItem } from "../types";
import { fmtDate } from "../utils/helpers";

const ctLabel: Record<string, string> = {
  general: "通用", meeting: "会议", surveillance: "监控", text_recognition: "文字识别",
};

export function HistoryPanelContent({
  videos,
  currentVideoId,
  loading,
  onSelect,
  onDelete,
}: {
  videos: VideoListItem[];
  currentVideoId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());

  const handleDelete = async (id: string) => {
    setDeletingIds((prev) => new Set(prev).add(id));
    try {
      await api.deleteVideo(id);
      setTimeout(() => onDelete(id), 250);
    } catch {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  };

  return (
    <div className="flex-1 overflow-y-auto custom-scrollbar p-4 space-y-2">
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse bg-gray-100 rounded-xl p-3">
              <div className="aspect-video rounded-lg bg-gray-200" />
              <div className="h-3 bg-gray-200 rounded w-3/4 mt-2" />
            </div>
          ))}
        </div>
      ) : videos.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-sm text-gray-400 mt-2">暂无视频</p>
        </div>
      ) : (
        videos.map((item) => {
          const shortName = item.file_name.length > 10 ? item.file_name.slice(0, 10) + "…" : item.file_name;
          const fnParts: string[] = [];
          if (item.search_index_enabled) fnParts.push("搜索");
          if (item.summary_enabled) fnParts.push("摘要");
          const fnLabel = fnParts.length === 2 ? "搜索+摘要" : fnParts[0] || "—";
          const fpsLabel = `${item.sample_fps.toFixed(1)}fps`;
          const typeLabel = ctLabel[item.content_type] || item.content_type;
          return (
            <div
              key={item.id}
              onClick={() => onSelect(item.id)}
              className={`rounded-xl cursor-pointer transition-all duration-300 ${
                deletingIds.has(item.id)
                  ? "!p-0 !m-0 max-h-0 opacity-0 -translate-x-full scale-95 border-transparent overflow-hidden"
                  : `${currentVideoId === item.id ? "bg-blue-50 border-blue-200" : "hover:bg-gray-50 border-transparent"} p-3`
              }`}
            >
              <div className="flex items-start gap-3">
                <div className="w-[72px] aspect-video rounded-lg shrink-0 bg-gray-100 flex items-center justify-center overflow-hidden">
                  {item.status === "completed" ? (
                    <img
                      src={`/api/v1/videos/${item.id}/thumbnail/0`}
                      alt=""
                      className="w-full h-full object-cover"
                      loading="lazy"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; (e.target as HTMLImageElement).parentElement!.innerHTML = '<span class=\'text-[10px] text-gray-400\'>视频</span>'; }}
                    />
                  ) : (
                    <span className="text-[10px] text-gray-400">视频</span>
                  )}
                </div>
                <div className="min-w-0 flex-1 self-stretch flex flex-col justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-900 truncate" title={item.file_name}>{shortName}</h3>
                    <p className="text-[10px] text-gray-400 leading-tight mt-0.5">
                      {typeLabel} <span className="text-gray-300">|</span> {fnLabel} <span className="text-gray-300">|</span> {fpsLabel}
                    </p>
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <div className="flex items-center gap-2">
                      <span className={`text-[10px] font-medium ${
                        item.status === "completed" ? "text-green-500" :
                        item.status === "processing" ? "text-blue-500" :
                        item.status === "failed" ? "text-red-400" : "text-gray-400"
                      }`}>
                        {item.status === "completed" ? "已完成" :
                         item.status === "processing" ? "处理中" :
                         item.status === "failed" ? "失败" : "等待中"}
                      </span>
                      <span className="text-[9px] text-gray-350">{fmtDate(item.created_at)}</span>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(item.id); }}
                      className="text-gray-300 hover:text-red-500 transition-colors"
                    >
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round">
                        <polyline points="3 6 5 6 21 6" />
                        <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
