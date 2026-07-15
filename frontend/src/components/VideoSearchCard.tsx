/* ════════════════════════════════════════════════════════════
   VideoSearchCard — extracted from Dashboard.tsx
   ════════════════════════════════════════════════════════════ */

import { IconSearch } from "./icons";
import { useState, useEffect, useCallback } from "react";
import { api } from "../services/api";
import type { SearchResultItem } from "../types";
import { formatSec } from "../utils/helpers";


export function VideoSearchCard({
  currentVideoId,
  searchIndexEnabled,
  onSeekTo,
}: {
  currentVideoId: string | null;
  searchIndexEnabled: boolean;
  onSeekTo?: (start: number, end: number | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* ── 切换视频时清除搜索结果 ── */
  useEffect(() => {
    setQuery("");
    setResults([]);
    setSearching(false);
    setHasSearched(false);
    setError(null);
  }, [currentVideoId]);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setResults([]);
    setSearching(true);
    setError(null);
    try {
      const data = await api.searchSemantic(query.trim(), {
        video_ids: currentVideoId ? [currentVideoId] : undefined,
      });
      setResults(data.results ?? []);
      setHasSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "搜索失败");
    } finally {
      setSearching(false);
    }
  }, [query, currentVideoId]);

  const resultCount = results.length;

  /* ── 搜索未开启时显示置灰状态 ── */
  if (!searchIndexEnabled) {
    return (
      <div className="card-surface rounded-2xl p-4 border border-gray-200/60 flex flex-col h-full min-h-0">
        <div className="flex items-center justify-between mb-3 shrink-0">
          <h3 className="font-bold text-gray-900 text-base">视频搜索</h3>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center gap-2 opacity-50">
          <svg className="w-10 h-10 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <p className="text-sm text-gray-400">搜索索引未开启</p>
          <p className="text-xs text-gray-300 mt-0.5">如需搜索，请在参数设置中启用「搜索索引」</p>
        </div>
      </div>
    );
  }

  return (
    <div className="card-surface rounded-2xl p-4 border border-gray-200/60 flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between mb-3 shrink-0">
        <div>
          <h3 className="font-bold text-gray-900 text-base">视频搜索</h3>
        </div>
        {resultCount > 0 && (
          <span className="text-[11px] text-gray-400 font-mono bg-gray-50 px-2 py-0.5 rounded-full">
            {resultCount} 条
          </span>
        )}
      </div>

      {/* Search Input */}
      <div className="relative mb-3 shrink-0">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
          <IconSearch />
        </span>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="搜索场景内容..."
          className="w-full pl-9 pr-20 py-2.5 bg-gray-50 border border-gray-200 rounded-xl text-sm
                     focus:bg-white focus:ring-2 focus:ring-blue-100 focus:border-blue-300
                     outline-none transition-all placeholder:text-gray-400"
        />
        <button
          onClick={handleSearch}
          disabled={searching || !query.trim()}
          className="absolute right-1.5 top-1/2 -translate-y-1/2 px-3.5 py-1.5 bg-blue-500 text-white text-xs font-medium rounded-lg
                     hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-sm"
        >
          {searching ? (
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              搜索中
            </span>
          ) : "搜索"}
        </button>
      </div>

      {/* Results Area */}
      <div className="flex-1 overflow-y-auto custom-scrollbar space-y-2 min-h-0">
        {/* Error */}
        {error && (
          <div className="p-3 rounded-xl bg-red-50 border border-red-100 text-xs text-red-600">{error}</div>
        )}

        {/* Empty results after search */}
        {hasSearched && !error && results.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 text-gray-400">
            <svg className="w-10 h-10 mb-2 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p className="text-sm">未找到匹配结果</p>
            <p className="text-xs mt-0.5">试试其他关键词</p>
          </div>
        )}

        {/* Results list */}
        {results.map((item, idx) => (
          <div
            key={item.scene_id || idx}
            className="p-3 bg-white rounded-xl border border-gray-100 shadow-sm hover:shadow-md hover:border-blue-200 transition-all cursor-pointer"
            onClick={() => {
              const ts = item.precise_start ?? item.scene_range_start;
              if (onSeekTo && ts != null) onSeekTo(ts, item.precise_end ?? item.scene_range_end);
            }}
          >
            <div className="flex items-start gap-3">
              {/* Thumbnail */}
              <div className="shrink-0 w-[68px] h-[51px] rounded-lg overflow-hidden bg-gray-50 border border-gray-200">
                {item.thumbnail_url ? (
                  <img
                    src={item.thumbnail_url}
                    alt=""
                    className="w-full h-full object-cover"
                    loading="lazy"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <svg className="w-5 h-5 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
                      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                      <circle cx="8.5" cy="8.5" r="1.5" />
                      <polyline points="21 15 16 10 5 21" />
                    </svg>
                  </div>
                )}
              </div>

              {/* Content */}
              <div className="min-w-0 flex-1">
                {/* Time + Score row */}
                <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                  {/* Precision time */}
                  {item.precise_start != null ? (
                    <span className="text-[11px] font-mono text-blue-500 font-medium">
                      @ {formatSec(item.precise_start)}
                      {item.precise_end != null && item.precise_end !== item.precise_start
                        ? ` — ${formatSec(item.precise_end)}`
                        : ""}
                    </span>
                  ) : (
                    <span className="text-[11px] font-mono text-gray-400">
                      {formatSec(item.scene_range_start)} — {formatSec(item.scene_range_end)}
                    </span>
                  )}

                  {/* Similarity */}
                  {item.similarity != null && (
                    <span className="text-[11px] font-mono text-blue-600 font-semibold">
                      {Math.round(item.similarity * 100)}%
                    </span>
                  )}

                  {/* Precision badge */}
                  {item.precision_level && item.precision_level !== "scene" && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-purple-50 text-purple-400 font-medium">
                      {item.precision_level === "frame" ? "帧定位"
                        : item.precision_level === "chunk" ? "段落"
                        : item.precision_level}
                    </span>
                  )}
                </div>

                {/* Caption */}
                {item.caption && (
                  <p className="text-xs text-gray-600 leading-relaxed line-clamp-2 mt-1">{item.caption}</p>
                )}
              </div>
            </div>
          </div>
        ))}

        {/* Initial state */}
        {!hasSearched && !searching && !error && (
          <div className="flex flex-col items-center justify-center py-10 text-gray-400">
            <svg className="w-10 h-10 mb-2 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <p className="text-sm text-gray-400">输入关键词搜索视频画面</p>
            <p className="text-xs text-gray-300 mt-0.5">支持场景描述、物体名称、动作等</p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════
   HistoryPanelContent — 历史记录列表（面板内嵌内容）
   ════════════════════════════════════════════════════════════ */

