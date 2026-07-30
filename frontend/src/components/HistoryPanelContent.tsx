/* ════════════════════════════════════════════════════════════
   HistoryPanelContent — v2.0 style + v0.19 group support
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect } from "react";
import { api } from "../services/api";
import type { VideoListItem, VideoGroup } from "../types";
import { fmtDate } from "../utils/helpers";

const ctLabel: Record<string, string> = {
  general: "通用", meeting: "会议", surveillance: "监控", text_recognition: "文字识别",
};

interface Props {
  videos: VideoListItem[];
  currentVideoId: string | null;
  loading: boolean;
  onSelect: (id: string, groupId?: string) => void;
  onDelete: (id: string) => void;
  videoGroups: VideoGroup[];
  drillGroupId?: string | null;
  onDrillChange?: (id: string | null) => void;
}

export function HistoryPanelContent({
  videos, currentVideoId, loading, onSelect, onDelete, videoGroups,
  drillGroupId = null, onDrillChange,
}: Props) {
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");

  const handleDelete = async (id: string) => {
    setDeletingIds((prev) => new Set(prev).add(id));
    try { await api.deleteVideo(id); setTimeout(() => onDelete(id), 250); }
    catch { setDeletingIds((prev) => { const next = new Set(prev); next.delete(id); return next; }); }
  };

  const handleGroupDelete = async (groupVideos: VideoListItem[]) => {
    if (!confirm("确定整组删除？")) return;
    const ids = groupVideos.map(v => v.id);
    setDeletingIds((prev) => { const n = new Set(prev); ids.forEach(id => n.add(id)); return n; });
    try {
      await Promise.all(ids.map(id => api.deleteVideo(id)));
      setTimeout(() => { ids.forEach(id => onDelete(id)); }, 250);
    } catch {
      setDeletingIds((prev) => { const n = new Set(prev); ids.forEach(id => n.delete(id)); return n; });
    }
  };

  const filteredVideos = searchQuery.trim()
    ? videos.filter((v) => v.file_name.toLowerCase().includes(searchQuery.toLowerCase()))
    : videos;

  // When drilling into a group, only show that group's videos
  const displayVideos = drillGroupId
    ? filteredVideos.filter(v => v.group_id === drillGroupId)
    : filteredVideos;

  // 组内最后一条视频被删 → 自动返回总表
  useEffect(() => {
    if (drillGroupId && displayVideos.length === 0) {
      onDrillChange?.(null);
      setSearchQuery("");
    }
  }, [drillGroupId, displayVideos.length, onDrillChange]);

  // Build group/single list (only when not drilling)
  const groupIds = new Map<string, VideoListItem[]>();
  const ungrouped: VideoListItem[] = [];
  if (!drillGroupId) {
    for (const v of filteredVideos) {
      if (v.group_id) {
        const existing = groupIds.get(v.group_id) ?? [];
        existing.push(v);
        groupIds.set(v.group_id, existing);
      } else {
        ungrouped.push(v);
      }
    }
  }

  interface HistoryGroup {
    type: "group" | "single";
    groupId?: string;
    videos: VideoListItem[];
  }
  const historyGroups: HistoryGroup[] = [];
  for (const [gid, gvideos] of groupIds) {
    historyGroups.push({ type: "group", groupId: gid, videos: gvideos });
  }
  for (const v of ungrouped) {
    historyGroups.push({ type: "single", videos: [v] });
  }

  const renderVideoCard = (v: VideoListItem, isInGroup: boolean) => {
    const shortName = v.file_name.length > 10 ? v.file_name.slice(0, 10) + "…" : v.file_name;
    const fnParts: string[] = [];
    if (v.search_index_enabled) fnParts.push("搜索");
    if (v.summary_enabled) fnParts.push("摘要");
    const fnLabel = fnParts.length === 2 ? "搜索+摘要" : fnParts[0] || "—";
    const isDeleting = deletingIds.has(v.id);
    return (
      <div key={v.id}
        className={`overflow-hidden transition-all duration-500 ease-out ${
          isDeleting
            ? "max-h-0 opacity-0 -translate-x-full scale-y-0 mb-0"
            : isInGroup ? "max-h-[200px] opacity-100 translate-x-0 scale-y-100 mb-0.5" : "max-h-[200px] opacity-100 translate-x-0 scale-y-100 mb-2"
        }`}>
        <div onClick={() => onSelect(v.id, v.group_id ?? undefined)}
          className={`rounded-xl cursor-pointer border p-3 transition-all duration-300 ${
            currentVideoId === v.id ? "bg-blue-50 border-blue-200" : "bg-white border-gray-100 hover:bg-gray-50 hover:border-gray-200"
          }`}>
          <div className="flex items-start gap-3">
            <div className="w-[72px] aspect-video rounded-lg shrink-0 bg-gray-100 flex items-center justify-center overflow-hidden border border-gray-200/50">
              {v.status === "completed" ? (
                <img src={`/api/v1/videos/${v.id}/thumbnail/0`} alt="" className="w-full h-full object-cover" loading="lazy"
                  onError={(e) => { (e.target as HTMLImageElement).parentElement!.innerHTML = '<span class="text-[10px] text-gray-400">视频</span>'; }} />
              ) : <span className="text-[10px] text-gray-400">视频</span>}
            </div>
            <div className="min-w-0 flex-1 self-stretch flex flex-col justify-between">
              <div>
                <h3 className="text-sm font-semibold text-gray-900 truncate" title={v.file_name}>{shortName}</h3>
                <p className="text-[10px] text-gray-400 leading-tight mt-0.5">
                  {ctLabel[v.content_type] || v.content_type} <span className="text-gray-300">|</span> {fnLabel} <span className="text-gray-300">|</span> {v.sample_fps.toFixed(1)}fps
                </p>
              </div>
              <div className="flex items-center justify-between mt-1">
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-medium ${
                    v.status === "completed" ? "text-green-500" : v.status === "processing" ? "text-blue-500"
                    : v.status === "failed" ? "text-red-400" : "text-gray-400"}`}>
                    {v.status === "completed" ? "已完成" : v.status === "processing" ? "处理中" : v.status === "failed" ? "失败" : "等待中"}
                  </span>
                  <span className="text-[9px] text-gray-400">{fmtDate(v.created_at)}</span>
                </div>
                <button onClick={(e) => { e.stopPropagation(); handleDelete(v.id); }} className="text-gray-300 hover:text-red-500 transition-colors cursor-pointer">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" /></svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Top bar: search always visible */}
      <div className="px-4 pt-3 pb-2 shrink-0">
        <div className="relative">
          <input type="text" value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={drillGroupId ? `在 ${displayVideos.length} 个视频中搜索...` : "搜索视频文件名..."}
            className="w-full pl-3 pr-7 py-1.5 text-[11px] bg-white border border-gray-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-300 transition-all placeholder:text-gray-400" />
          {searchQuery && (
            <button onClick={() => setSearchQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500 cursor-pointer">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {searchQuery && !drillGroupId && <p className="text-[10px] text-gray-400">找到 {filteredVideos.length} 条</p>}
        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => <div key={i} className="animate-pulse bg-gray-50 rounded-xl p-3"><div className="aspect-video rounded-lg bg-gray-100" /><div className="h-3 bg-gray-100 rounded w-3/4 mt-2" /></div>)}
          </div>
        ) : displayVideos.length === 0 ? (
          <div className="text-center py-12"><p className="text-sm text-gray-400">{searchQuery ? "无匹配视频" : "暂无视频"}</p></div>
        ) : drillGroupId ? (
          /* ══ Drilled into a group: show individual video cards ══ */
          displayVideos.map(v => renderVideoCard(v, false))
        ) : (
          /* ══ Normal mode: group cards + single video cards ══ */
          historyGroups.map((group) => {
            if (group.type === "group") {
              return (
                <div key={group.groupId} className="mb-2">
                  {/* Group card — click to drill in + auto-select first video */}
                  <div className="cursor-pointer" onClick={() => {
                    onSelect(group.videos[0].id, group.groupId ?? undefined);
                    onDrillChange?.(group.groupId!);
                  }}>
                    <div className="rounded-xl border border-gray-200 bg-white p-3 transition-all hover:border-gray-300 hover:bg-gray-50 shadow-md">
                      <div className="flex items-start gap-3">
                        <div className="w-[72px] aspect-video rounded-lg shrink-0 bg-gray-100 overflow-hidden">
                          {group.videos[0].status === "completed" ? (
                            <img src={`/api/v1/videos/${group.videos[0].id}/thumbnail/0`} alt="" className="w-full h-full object-cover" loading="lazy"
                              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
                          ) : <div className="w-full h-full flex items-center justify-center text-[10px] text-gray-400">视频</div>}
                        </div>
                        <div className="min-w-0 flex-1 self-stretch flex flex-col justify-between">
                          <div>
                            <h3 className="text-sm font-semibold text-gray-900 truncate" title={group.videos.map(v => v.file_name).join(" / ")}>
                              {group.videos.map(v => v.file_name).join(" / ")}
                            </h3>
                            <p className="text-[10px] text-gray-400 leading-tight mt-0.5 flex items-center gap-1.5 flex-wrap">
                              <span>{ctLabel[group.videos[0].content_type] || group.videos[0].content_type}</span>
                              <span className="text-gray-300">|</span>
                              <span>{(() => {
                                const v0 = group.videos[0];
                                const parts: string[] = [];
                                if (v0.search_index_enabled) parts.push("搜索");
                                if (v0.summary_enabled) parts.push("摘要");
                                return parts.length === 2 ? "搜索+摘要" : parts[0] || "—";
                              })()}</span>
                              <span className="text-gray-300">|</span>
                              <span>{group.videos[0].sample_fps.toFixed(1)}fps</span>
                              <span className="text-[9px] font-medium text-blue-500 bg-blue-50 px-1.5 py-0.5 rounded ml-auto">{group.videos.length} 个视频</span>
                            </p>
                          </div>
                          <div className="flex items-center justify-between mt-1">
                            <span className="text-[9px] text-gray-400">{fmtDate(group.videos[0].created_at)}</span>
                            <button onClick={(e) => { e.stopPropagation(); handleGroupDelete(group.videos); }} className="text-gray-300 hover:text-red-500 transition-colors cursor-pointer" title="删除整组">
                              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" /></svg>
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              );
            }
            // Single video
            return renderVideoCard(group.videos[0], false);
          })
        )}
      </div>
      <div className="shrink-0 h-4" />
    </div>
  );
}
