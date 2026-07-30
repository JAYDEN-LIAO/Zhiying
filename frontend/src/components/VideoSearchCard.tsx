/* ════════════════════════════════════════════════════════════
   VideoSearchCard — v2.0 major-card style + face search
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { api } from "../services/api";
import type { SearchResultItem, VideoResponse, VideoListItem, FaceSearchResult } from "../types";
import { formatSec } from "../utils/helpers";
import { zhLabel } from "../labels";

export function VideoSearchCard({
  video,
  onSeekTo,
  onTrackResult,
  groupVideos,
  allVideos,
  onGroupVideoSwitch,
}: {
  video: VideoResponse | null;
  onSeekTo?: (start: number, end: number | null) => void;
  onTrackResult?: (trackId: number, className: string, start: number) => void;
  /* ── v0.19 组感知 ── */
  groupVideos?: string[];
  allVideos?: VideoListItem[];
  onGroupVideoSwitch?: (videoId: string) => void;
}) {
  const currentVideoId = video?.id ?? null;
  const searchIndexEnabled = video?.search_index_enabled ?? false;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [selectedVideoIds, setSelectedVideoIds] = useState<Set<string>>(
    () => new Set(groupVideos ?? (currentVideoId ? [currentVideoId] : [])),
  );
  const [dlTrackId, setDlTrackId] = useState<number | null>(null);
  const [faceSearching, setFaceSearching] = useState(false);
  const [faceResults, setFaceResults] = useState<FaceSearchResult[]>([]);
  const [imageSearching, setImageSearching] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  // Show scope selector only when there are multiple videos
  const searchScopeVisible = (groupVideos?.length ?? 0) > 1;

  // Compute search video IDs: always concrete, never undefined (was: undefined = all DB videos — bug)
  const searchVideoIds: string[] = useMemo(() => {
    if (selectedVideoIds.size === 0 && currentVideoId) return [currentVideoId];
    return Array.from(selectedVideoIds);
  }, [selectedVideoIds, currentVideoId]);

  // Is "all group videos" checkbox checked?
  const allGroupSelected = useMemo(() => {
    if (!groupVideos || groupVideos.length === 0) return false;
    return groupVideos.every((id) => selectedVideoIds.has(id));
  }, [groupVideos, selectedVideoIds]);

  // Scope button label
  const scopeLabel = useMemo(() => {
    if (allGroupSelected) return "全组视频";
    const count = selectedVideoIds.size;
    if (count <= 1) return "当前视频";
    if (count <= 2) {
      return Array.from(selectedVideoIds).map(id => allVideos?.find(v => v.id === id)?.file_name?.slice(0, 6) ?? id.slice(0, 6)).join(",");
    }
    return `${count} 个视频`;
  }, [allGroupSelected, selectedVideoIds, allVideos]);

  const toggleAllGroup = useCallback(() => {
    if (allGroupSelected) {
      // Uncheck all → only keep current video
      setSelectedVideoIds(new Set(currentVideoId ? [currentVideoId] : []));
    } else {
      // Check all → all group videos
      setSelectedVideoIds(new Set(groupVideos ?? []));
    }
  }, [allGroupSelected, groupVideos, currentVideoId]);

  const toggleVideoId = useCallback((id: string) => {
    setSelectedVideoIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        // Never allow empty set — keep at least current video
        if (next.size === 0 && currentVideoId) next.add(currentVideoId);
      } else {
        next.add(id);
      }
      return next;
    });
  }, [currentVideoId]);

  useEffect(() => {
    setQuery(""); setResults([]); setSearching(false); setHasSearched(false); setError(null); setFaceResults([]);
  }, [currentVideoId]);

  // Reset scope when group or current video changes
  useEffect(() => {
    setSelectedVideoIds(new Set(groupVideos ?? (currentVideoId ? [currentVideoId] : [])));
  }, [groupVideos, currentVideoId]);

  const classLocalMap = useMemo(() => {
    const trackItems = results.filter((r) => r.precision_level === "track" && r.track_id != null);
    const groups = new Map<string, number[]>();
    for (const r of trackItems) { if (!groups.has(r.class_name!)) groups.set(r.class_name!, []); groups.get(r.class_name!)!.push(r.track_id!); }
    const map = new Map<number, number>();
    for (const [, ids] of groups) { ids.sort((a, b) => a - b); ids.forEach((id, idx) => map.set(id, idx + 1)); }
    return map;
  }, [results]);

  const handleFaceFile = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    setFaceSearching(true); setError(null);
    try { setFaceResults(await api.searchFace(file, searchVideoIds)); }
    catch (err) { setError(err instanceof Error ? err.message : "人脸搜索失败"); }
    finally { setFaceSearching(false); if (fileInputRef.current) fileInputRef.current.value = ""; }
  }, [searchVideoIds]);

  /* ── 通用图搜 ── */
  const handleImageSearch = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    setImageSearching(true); setError(null); setFaceResults([]);
    try {
      const data = await api.searchImage(file, {
        video_ids: searchVideoIds,
      });
      setResults(data.results ?? []);
      setHasSearched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "图搜失败");
    } finally {
      setImageSearching(false);
      if (imageInputRef.current) imageInputRef.current.value = "";
    }
  }, [searchVideoIds]);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setResults([]); setSearching(true); setError(null);
    try {
      const data = await api.searchSemantic(query.trim(), { video_ids: searchVideoIds });
      setResults(data.results ?? []); setHasSearched(true);
    } catch (err) { setError(err instanceof Error ? err.message : "搜索失败"); }
    finally { setSearching(false); }
  }, [query, searchVideoIds]);

  const resultCount = results.length;

  /* ── No video ── */
  if (!video) {
    return (
      <div className="major-card">
        <div className="major-card-hd">
          <div className="major-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
            视频搜索
          </div>
        </div>
        <div className="major-card-bd flex items-center justify-center">
          <span className="text-gray-400 text-sm">选择视频后使用搜索</span>
        </div>
      </div>
    );
  }

  /* ── Processing ── */
  if (video.status === "pending" || video.status === "processing") {
    return (
      <div className="major-card">
        <div className="major-card-hd">
          <div className="major-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
            视频搜索
          </div>
        </div>
        <div className="major-card-bd flex flex-col items-center justify-center">
          <div className="animate-pulse space-y-3 w-full">
            <div className="h-4 bg-gray-100 rounded w-1/2 mx-auto" />
            <div className="h-3 bg-gray-100 rounded w-3/4 mx-auto" />
            <div className="h-9 bg-gray-100 rounded-xl w-full" />
          </div>
          <p className="text-xs text-gray-400 mt-4">视频处理完成后自动建立搜索索引</p>
        </div>
      </div>
    );
  }

  /* ── Search index disabled ── */
  if (!searchIndexEnabled) {
    return (
      <div className="major-card">
        <div className="major-card-hd">
          <div className="major-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
            视频搜索
          </div>
        </div>
        <div className="major-card-bd flex flex-col items-center justify-center gap-2 opacity-50">
          <svg className="w-10 h-10 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
          <span className="text-sm text-gray-400">搜索索引未开启</span>
          <span className="text-xs text-gray-300">请在参数设置中启用「搜索索引」</span>
        </div>
      </div>
    );
  }

  /* ── Normal search UI ── */
  return (
    <div className="major-card">
      <div className="major-card-hd">
        <div className="major-card-tt">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
          视频搜索
        </div>
        {resultCount > 0 && <span className="major-card-badge">{resultCount} 条</span>}
      </div>

      <div className="major-card-bd">
        {/* Search: scope dropdown + input + icons in one row */}
        <div className="relative">
          {/* Scope dropdown (inside input left) */}
          {searchScopeVisible && (
            <>
              <div className="absolute left-1 top-1/2 -translate-y-1/2 z-10">
                <button className="flex items-center justify-between gap-0.5 text-[11px] font-medium text-blue-600 hover:text-blue-800 transition-colors px-1.5 py-0.5 rounded bg-blue-50 border border-blue-100 w-[78px] overflow-hidden"
                  onClick={() => setScopeOpen(v => !v)}>
                  <span className="truncate">{scopeLabel}</span>
                  <svg className={`w-3 h-3 shrink-0 transition-transform ${scopeOpen ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M6 9l6 6 6-6" /></svg>
                </button>
              </div>
              {scopeOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setScopeOpen(false)} />
                  <div className="absolute left-0 top-full mt-1 bg-white rounded-lg shadow-lg border border-gray-200 z-20 overflow-hidden w-44 py-1">
                    <label className="flex items-center gap-2 px-3 py-2 text-xs text-gray-600 hover:bg-gray-50 cursor-pointer">
                      <input type="checkbox" checked={allGroupSelected}
                        onChange={toggleAllGroup}
                        className="w-3 h-3 accent-blue-500" />
                      全组视频
                    </label>
                    <div className="h-px bg-gray-100 mx-2" />
                    {(groupVideos && groupVideos.length > 0 ? groupVideos : (currentVideoId ? [currentVideoId] : [])).map(vId => {
                      const v = allVideos?.find(vv => vv.id === vId);
                      return (
                        <label key={vId} className="flex items-center gap-2 px-3 py-2 text-xs text-gray-600 hover:bg-gray-50 cursor-pointer">
                          <input type="checkbox" checked={selectedVideoIds.has(vId)}
                            onChange={() => toggleVideoId(vId)}
                            className="w-3 h-3 accent-blue-500" />
                          <span className="truncate">{v?.file_name ?? vId.slice(0, 8)}</span>
                        </label>
                      );
                    })}
                  </div>
                </>
              )}
            </>
          )}

          {/* Search input */}
          <input
            className={`w-full rounded-lg border border-gray-300 bg-gray-50 text-gray-900 outline-none transition-all
              focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100 placeholder:text-gray-400
              text-[12px] py-2 ${searchScopeVisible ? 'pl-[100px] pr-16' : 'px-3'}`}
            type="text" value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="场景 物体 车牌 动作 人物..."
          />

          {/* Image search (inside input right) */}
          <input ref={imageInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={handleImageSearch} className="hidden" />
          <button onClick={() => imageInputRef.current?.click()} disabled={imageSearching}
            className={`absolute ${searching ? 'right-1' : 'right-7'} top-1/2 -translate-y-1/2 w-6 h-6 rounded bg-emerald-50 hover:bg-emerald-100 text-emerald-600 flex items-center justify-center transition-colors disabled:opacity-50`} title="以图搜图">
            {imageSearching ? <span className="inline-block w-3 h-3 border-2 border-emerald-300 border-t-emerald-500 rounded-full animate-spin" /> : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" />
              </svg>
            )}
          </button>

          {/* Face search (inside input right) */}
          <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={handleFaceFile} className="hidden" />
          <button onClick={() => fileInputRef.current?.click()} disabled={faceSearching}
            className="absolute right-1 top-1/2 -translate-y-1/2 w-6 h-6 rounded bg-purple-50 hover:bg-purple-100 text-purple-600 flex items-center justify-center transition-colors disabled:opacity-50" title="人脸搜索">
            {faceSearching ? <span className="inline-block w-3 h-3 border-2 border-purple-300 border-t-purple-500 rounded-full animate-spin" /> : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round"><circle cx="9" cy="9" r="3" /><path d="M1 20v-1a6 6 0 0112 0v1" /></svg>
            )}
          </button>

          {/* Text search spinner (replaces face button position) */}
          {searching && (
            <span className="absolute right-1 top-1/2 -translate-y-1/2 inline-block w-3.5 h-3.5 border-2 border-blue-300 border-t-blue-500 rounded-full animate-spin" />
          )}
        </div>

        {/* Error */}
        {error && <div className="mb-2 p-2 rounded-lg bg-red-50 border border-red-100 text-[10px] text-red-600">{error}</div>}

        {/* Face search results */}
        {faceResults.length > 0 && (
          <div className="mb-2">
            <div className="face-hd">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><circle cx="9" cy="9" r="3" /><path d="M1 20v-1a6 6 0 0112 0v1" /></svg>
              <span>人脸匹配 · {faceResults.length} 人</span>
            </div>
            {faceResults.map((fr) => (
              <button key={`${fr.video_id}-${fr.identity_id}`}
                onClick={() => { if (fr.best_face_timestamp != null) onSeekTo?.(fr.best_face_timestamp, null); }}
                className="face-item w-full text-left cursor-pointer"
              >
                <div className="face-thumb">{fr.thumbnail_url ? <img src={fr.thumbnail_url} alt="" /> : <span>👤</span>}</div>
                <div className="face-info">
                  <div className="face-name">{fr.identity_label} <span className="face-sim">{fr.similarity.toFixed(2)}</span></div>
                  <div className="face-detail">{fr.face_count} 次 · {fr.first_seen.toFixed(1)}s – {fr.last_seen.toFixed(1)}s</div>
                </div>
              </button>
            ))}
            <div className="h-px bg-gray-100 my-2" />
          </div>
        )}

        {faceSearching && (
          <div className="flex items-center justify-center py-4 text-purple-400 text-xs gap-2">
            <span className="inline-block w-3 h-3 border-2 border-purple-300 border-t-purple-500 rounded-full animate-spin" />人脸搜索中...
          </div>
        )}

        {/* Empty results */}
        {hasSearched && !searching && !error && results.length === 0 && faceResults.length === 0 && (
          <div className="flex flex-col items-center justify-center py-10 text-gray-400">
            <svg className="w-10 h-10 mb-2 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
            <p className="text-sm">未找到匹配结果</p>
            <p className="text-xs mt-0.5">试试其他关键词</p>
          </div>
        )}

        {/* Results list */}
        <div className="sr">
          {results.map((item, idx) => {
            const isTrack = item.precision_level === "track";
            const isPlate = item.precision_level === "plate";
            return (
              <div key={isTrack ? `track-${item.track_id}` : isPlate ? `plate-${item.video_id}-${item.track_id}-${idx}` : (item.scene_id || idx)}
                className="sr-item"
                onClick={() => {
                  // v0.19: 跨视频跳转
                  if (item.video_id !== currentVideoId && onGroupVideoSwitch) {
                    onGroupVideoSwitch(item.video_id);
                  }
                  if (isTrack && item.track_id != null && item.precise_start != null) {
                    onTrackResult?.(item.track_id, item.class_name ?? "", item.precise_start);
                  } else if (isPlate && item.precise_start != null) {
                    if (item.track_id != null) onTrackResult?.(item.track_id, item.class_name ?? "", item.precise_start);
                    else onSeekTo?.(item.precise_start, null);
                  } else {
                    const ts = item.precise_start ?? item.scene_range_start;
                    if (onSeekTo && ts != null) onSeekTo(ts, item.precise_end);
                  }
                }}
              >
                <div className="sr-top">
                  <div className="sr-thumb">
                    {item.thumbnail_url ? <img src={item.thumbnail_url} alt="" loading="lazy" onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} /> : (
                      <div className="w-full h-full flex items-center justify-center text-gray-300"><svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg></div>
                    )}
                  </div>
                  <div className="sr-c">
                    <div className="sr-meta">
                      <span className="sr-time">
                        {formatSec(item.precise_start ?? item.scene_range_start)}
                        {(() => {
                          const end = item.precise_end;
                          const start = item.precise_start ?? item.scene_range_start;
                          return (end != null && end !== start)
                            ? ` – ${formatSec(end)}`
                            : "";
                        })()}
                      </span>
                      {item.similarity != null && <span className="sr-score">{Math.round(item.similarity * 100)}%</span>}
                      <span className={`sr-type ${isTrack ? "track" : isPlate ? "plate" : "frame"}`}>
                        {isTrack ? "物体定位" : isPlate ? "车牌" : "帧定位"}
                      </span>
                    </div>
                    {isTrack && item.class_name ? (
                      <div className="sr-track">{zhLabel(item.class_name, classLocalMap.get(item.track_id!) ?? item.track_id!)}</div>
                    ) : isPlate && item.plate_text ? (
                      <div className="sr-plate">{item.plate_text}</div>
                    ) : item.caption ? (
                      <div className="sr-text">{item.caption}</div>
                    ) : null}
                    <div className="sr-acts" onClick={(e) => e.stopPropagation()}>
                      {isTrack && item.track_id != null ? (
                        !dlTrackId || dlTrackId !== item.track_id ? (
                          <button className="sr-act" onClick={() => setDlTrackId(item.track_id!)}>
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>导出
                          </button>
                        ) : (
                          <>
                            <button className="sr-act" onClick={() => { setDlTrackId(null); window.open(api.getTrackThumbnailUrl(item.video_id, item.track_id!, classLocalMap.get(item.track_id!)), "_blank"); }}>缩略图</button>
                            <button className="sr-act" onClick={() => { setDlTrackId(null); window.open(api.getTrackExportUrl(item.video_id, item.track_id!, true, classLocalMap.get(item.track_id!)), "_blank"); }}>轨迹</button>
                          </>
                        )
                      ) : null}
                      {!isTrack && !isPlate && item.precise_start != null && item.precise_end != null && (
                        <button className="sr-act" onClick={() => window.open(api.getClipExportUrl(item.video_id, item.precise_start!, item.precise_end!), "_blank")}>
                          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>下载
                        </button>
                      )}
                      {isPlate && item.thumbnail_url && (
                        <button className="sr-act" onClick={() => window.open(item.thumbnail_url!, "_blank")}>
                          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>截图
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Initial prompt */}
        {!hasSearched && !searching && !error && (
          <div className="flex flex-col items-center justify-center py-8 text-gray-400">
            <svg className="w-8 h-8 mb-2 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
            <p className="text-xs">输入关键词搜索视频画面</p>
          </div>
        )}
      </div>
    </div>
  );
}
