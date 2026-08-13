/* ════════════════════════════════════════════════════════════
   VideoSearchCard — v2.0 major-card style + face search
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { api } from "../services/api";
import type { SearchResultItem, VideoResponse, VideoListItem, FaceSearchResult } from "../types";
import { formatSec } from "../utils/helpers";
import { zhLabel } from "../labels";

type SearchScope = "current" | "group" | "all" | "custom";

export function VideoSearchCard({
  video,
  videoId,
  onSeekTo,
  onTrackResult,
  onFaceResult,
  groupVideos,
  allVideos,
  onGroupVideoSwitch,
}: {
  video: VideoResponse | null;
  videoId: string | null;
  onSeekTo?: (start: number, end: number | null) => void;
  onTrackResult?: (videoId: string, trackId: number, className: string, start: number) => void;
  /* v0.30: 人脸结果点击 → 定位检测栏"人脸"视图（identityId + 时间戳） */
  onFaceResult?: (videoId: string, identityId: number, timestamp: number) => void;
  /* ── v0.19 组感知 ── */
  groupVideos?: string[];
  allVideos?: VideoListItem[];
  onGroupVideoSwitch?: (videoId: string) => void;
}) {
  // 用 Dashboard 的 currentVideoId（跨视频切换时 video 对象会先置 null，若从 video?.id 派生
  // currentVideoId 会经历 旧→null→新 两次变化 → 重置 effect 跑两次，suppress flag 被第一次消费掉）
  const currentVideoId = videoId ?? null;
  const searchIndexEnabled = video?.search_index_enabled ?? false;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [plateMode, setPlateMode] = useState(false);
  // 搜索范围（v0.30）: current=当前视频 / group=全组 / all=全部视频 / custom=自定义多选
  const [searchScope, setSearchScope] = useState<SearchScope>(currentVideoId ? "current" : "all");
  const [customIds, setCustomIds] = useState<Set<string>>(new Set());
  // 搜索结果自己发起的视频切换 → 抑制重置（本帧 effect 读到 true 跳过；setTimeout 清理，StrictMode 安全）
  const suppressResetRef = useRef(false);
  const [faceSearching, setFaceSearching] = useState(false);
  const [faceResults, setFaceResults] = useState<FaceSearchResult[]>([]);
  const [faceExportOpen, setFaceExportOpen] = useState<number | null>(null); // 人脸"导出"展开的 identity_id
  const [trackExportOpen, setTrackExportOpen] = useState<number | null>(null); // 物体"导出"展开的 track_id
  const [imageSearching, setImageSearching] = useState(false);
  // v0.30: 当前结果来自哪种搜索（决定 sr-type 标签；语义=frame/text/chunk/track/plate 混合）
  const [searchMode, setSearchMode] = useState<"semantic" | "image" | "face">("semantic");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  // 搜索 video_ids：all → null（后端 None = 全库）；custom → 勾选集合；其余为具体范围
  const searchVideoIds: string[] | null = useMemo(() => {
    if (searchScope === "all") return null;
    if (searchScope === "group") return groupVideos ?? [];
    if (searchScope === "custom") return Array.from(customIds);
    return currentVideoId ? [currentVideoId] : null;
  }, [searchScope, groupVideos, customIds, currentVideoId]);

  // 范围按钮文案（简短）
  const scopeLabel = useMemo(() => {
    if (searchScope === "all") return "全部";
    if (searchScope === "group") return "全组";
    if (searchScope === "custom") return customIds.size > 0 ? `已选${customIds.size}` : "当前";
    return "当前";
  }, [searchScope, customIds.size]);

  // 搜索范围涉及的视频（用于人脸/车牌门控 —— 联合搜索时范围内有任一视频具备即可用，不必当前视频具备）
  const scopeVideos = useMemo(() => {
    if (searchVideoIds == null) return allVideos ?? [];
    const ids = new Set(searchVideoIds);
    return (allVideos ?? []).filter(v => ids.has(v.id));
  }, [searchVideoIds, allVideos]);
  const detInScope = scopeVideos.some(v => v.detection_enabled);
  const faceDisabled = !detInScope || !scopeVideos.some(v => v.face_enabled);
  const plateDisabled = !detInScope || !scopeVideos.some(v => v.plate_enabled);
  // 语义/图搜可用性：无视频=全库搜索恒可用；有视频=范围需开搜索索引
  const semanticReady = !video || scopeVideos.some(v => v.search_index_enabled) || searchVideoIds == null;

  // 视频切换：手动切换（header/历史）→ 重置搜索上下文；搜索结果自己发起的切换 → 抑制（保留结果与范围）
  useEffect(() => {
    if (suppressResetRef.current) {
      suppressResetRef.current = false;  // 消费 flag：搜索结果自己发起的切换 → 跳过本次重置（无 setTimeout 竞态）
      return;
    }
    setQuery(""); setResults([]); setSearching(false); setHasSearched(false); setError(null); setFaceResults([]);
    setSearchScope(currentVideoId ? "current" : "all");
    setCustomIds(new Set());
  }, [currentVideoId]);

  const toggleCustomVideo = useCallback((id: string) => {
    const next = new Set(customIds);
    if (next.has(id)) next.delete(id); else next.add(id);
    setCustomIds(next);
    if (next.size > 0) setSearchScope("custom");
    else setSearchScope(currentVideoId ? "current" : "all");
  }, [customIds, currentVideoId]);

  const clearCustom = useCallback(() => {
    setCustomIds(new Set());
    setSearchScope(currentVideoId ? "current" : "all");
  }, [currentVideoId]);

  // 下拉"跨视频选择"按 group_id 分组渲染（同组视频清晰可见；未分组放最后）
  const currentVideoGroupId = allVideos?.find(v => v.id === currentVideoId)?.group_id ?? null;
  const groupedForPicker = useMemo(() => {
    const groups = new Map<string, { groupId: string | null; videos: VideoListItem[] }>();
    for (const v of allVideos ?? []) {
      const key = v.group_id ?? "__none__";
      if (!groups.has(key)) groups.set(key, { groupId: v.group_id, videos: [] });
      groups.get(key)!.videos.push(v);
    }
    return Array.from(groups.values()).sort((a, b) => (a.groupId ? 0 : 1) - (b.groupId ? 0 : 1));
  }, [allVideos]);

  const handleFaceFile = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    // 人脸搜索：清空语义/图搜旧结果，避免新结果从旧结果上方插入
    setResults([]); setFaceResults([]); setSearching(false);
    setFaceSearching(true); setError(null); setSearchMode("face");
    try {
      const data = await api.searchFace(file, searchVideoIds ?? undefined);
      setFaceResults(data); setHasSearched(true);
    }
    catch (err) { setError(err instanceof Error ? err.message : "人脸搜索失败"); }
    finally { setFaceSearching(false); if (fileInputRef.current) fileInputRef.current.value = ""; }
  }, [searchVideoIds]);

  /* ── 通用图搜 ── */
  const handleImageSearch = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    // 图搜：与语义/人脸搜索统一，先清空旧结果
    setResults([]); setImageSearching(true); setError(null); setFaceResults([]); setSearchMode("image");
    try {
      const data = await api.searchImage(file, {
        video_ids: searchVideoIds ?? undefined,
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
    setResults([]); setSearching(true); setError(null); setFaceResults([]);
    setSearchMode("semantic"); // 语义搜索（含帧/物体/车牌）
    try {
      const data = await api.searchSemantic(query.trim(), {
        video_ids: searchVideoIds ?? undefined,
        // 车牌模式：只跑车牌路 + 提高上限（「一个字列出所有相关」）
        ...(plateMode ? { search_types: ["plate"], top_k: 100 } : {}),
      });
      setResults(data.results ?? []); setHasSearched(true);
    } catch (err) { setError(err instanceof Error ? err.message : "搜索失败"); }
    finally { setSearching(false); }
  }, [query, searchVideoIds, plateMode]);

  const resultCount = results.length;

  /* ── Processing（无视频时直接可用，跳过索引门控 → 支持"默认工作台直接全库搜索"）── */
  if (video && (video.status === "pending" || video.status === "processing")) {
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

  /* ── Search index disabled（仅选中视频时判断；无视频=全库搜索不受单视频索引门控）── */
  if (video && !searchIndexEnabled) {
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
        <div className="major-card-tt min-w-0">
          <svg className="shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
          <span className="truncate">视频搜索</span>
        </div>
        <div className="flex items-center gap-1 shrink-0 min-w-0 overflow-hidden">
          {/* 搜索能力可用性 label：点亮=当前范围可搜，未开=置灰（nowrap 防窄面板换行挤压） */}
          {resultCount > 0 && <span className="major-card-badge mr-1 whitespace-nowrap shrink-0">{resultCount} 条</span>}
          <span className={`text-[9px] px-1.5 py-0.5 rounded whitespace-nowrap shrink-0 transition-colors ${semanticReady ? "bg-blue-50 text-blue-600 font-semibold" : "bg-gray-100 text-gray-400"}`} title="语义搜索（文本/场景/物体）">语义</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded whitespace-nowrap shrink-0 transition-colors ${semanticReady ? "bg-teal-50 text-teal-600 font-semibold" : "bg-gray-100 text-gray-400"}`} title="通用图搜（以图搜图）">图搜</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded whitespace-nowrap shrink-0 transition-colors ${!plateDisabled ? "bg-amber-50 text-amber-600 font-semibold" : "bg-gray-100 text-gray-400"}`} title="车牌识别">车牌</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded whitespace-nowrap shrink-0 transition-colors ${!faceDisabled ? "bg-purple-50 text-purple-600 font-semibold" : "bg-gray-100 text-gray-400"}`} title="人脸识别">人脸</span>
        </div>
      </div>

      <div className="major-card-bd" style={{ scrollbarGutter: "stable", paddingRight: 8 }}>
        {/* Search: scope dropdown + input + icons in one row */}
        {/* Search: scope button（同高左侧）+ input + icons in one row */}
        <div className="flex items-stretch w-full min-w-0 h-[34px] gap-1">
          {/* Scope button（同高左侧，替代搜索框左段；搜索框左沿与其右沿接壤） */}
          <div className="relative shrink-0">
            <button
              onClick={() => setScopeOpen(v => !v)}
              className={`flex h-full w-[50px] items-center justify-between gap-0.5 px-1 text-[11px] font-medium rounded-lg border transition-all ${
                scopeOpen
                  ? "border-teal-400 bg-teal-50 text-teal-700 shadow-sm"
                  : "border-gray-300 bg-gray-50 text-gray-600 hover:border-teal-300 hover:bg-teal-50/60 hover:text-teal-700"
              }`}
            >
              <span className="truncate">{scopeLabel}</span>
              <svg className={`w-3 h-3 shrink-0 transition-transform ${scopeOpen ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M6 9l6 6 6-6" /></svg>
            </button>
            {scopeOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setScopeOpen(false)} />
                <div className="absolute left-0 top-full mt-1 bg-gray-50 rounded-xl shadow-xl border border-gray-300 z-50 overflow-hidden w-44 py-1.5">
                  {/* 快捷范围 */}
                  <div className="px-3 pt-1 pb-1 text-[10px] font-semibold text-gray-400 tracking-widest">搜索范围</div>
                  <button
                    className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${!currentVideoId ? "text-gray-300 cursor-not-allowed" : (searchScope === "current" ? "bg-teal-50 text-teal-700 font-medium" : "text-gray-600 hover:bg-gray-50")}`}
                    disabled={!currentVideoId}
                    onClick={() => { setSearchScope("current"); setCustomIds(new Set()); setScopeOpen(false); }}
                  >
                    <svg className={`w-3 h-3 shrink-0 ${searchScope === "current" ? "text-teal-500" : "text-gray-300"}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="3"><path d="M20 6L9 17l-5-5" /></svg>
                    当前视频
                  </button>
                  <button
                    className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${!(groupVideos && groupVideos.length > 1) ? "text-gray-300 cursor-not-allowed" : (searchScope === "group" ? "bg-teal-50 text-teal-700 font-medium" : "text-gray-600 hover:bg-gray-50")}`}
                    disabled={!(groupVideos && groupVideos.length > 1)}
                    onClick={() => { setSearchScope("group"); setCustomIds(new Set()); setScopeOpen(false); }}
                  >
                    <svg className={`w-3 h-3 shrink-0 ${searchScope === "group" ? "text-teal-500" : "text-gray-300"}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="3"><path d="M20 6L9 17l-5-5" /></svg>
                    全组视频
                  </button>
                  <button
                    className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${searchScope === "all" ? "bg-teal-50 text-teal-700 font-medium" : "text-gray-600 hover:bg-gray-50"}`}
                    onClick={() => { setSearchScope("all"); setCustomIds(new Set()); setScopeOpen(false); }}
                  >
                    <svg className={`w-3 h-3 shrink-0 ${searchScope === "all" ? "text-teal-500" : "text-gray-300"}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="3"><path d="M20 6L9 17l-5-5" /></svg>
                    全部视频
                  </button>
                  <div className="h-px bg-gray-100 mx-2 my-1" />
                  {/* 跨视频多选（按组渲染，同组清晰可见） */}
                  <div className="flex items-center justify-between px-3 pt-1 pb-0.5">
                    <span className="text-[10px] font-semibold text-gray-400 tracking-widest">跨视频选择</span>
                    {customIds.size > 0 && (
                      <button onClick={clearCustom} className="text-[10px] text-teal-600 hover:text-teal-800">清空</button>
                    )}
                  </div>
                  <div className="max-h-[180px] overflow-y-auto px-1.5 pb-1.5">
                    {groupedForPicker.length === 0 ? (
                      <div className="px-2 py-4 text-center text-[10px] text-gray-400">暂无视频</div>
                    ) : groupedForPicker.map(g => (
                      <div key={g.groupId ?? "__none__"} className="mb-0.5">
                        <div className="flex items-center gap-1 px-2 pt-1 pb-0.5">
                          {g.groupId ? (
                            <>
                              <span className={`inline-block px-1 py-px rounded text-[9px] font-semibold leading-none ${g.groupId === currentVideoGroupId ? "bg-teal-100 text-teal-700" : "bg-gray-100 text-gray-500"}`}>
                                {g.groupId === currentVideoGroupId ? "当前组" : "同组"}
                              </span>
                              <span className="text-[10px] text-gray-400">{g.videos.length} 个视频</span>
                            </>
                          ) : (
                            <span className="text-[10px] text-gray-400">未分组</span>
                          )}
                        </div>
                        {g.videos.map(v => (
                          <label key={v.id} className="flex items-center gap-2 px-2 py-1.5 text-xs text-gray-600 hover:bg-gray-50 rounded cursor-pointer">
                            <input type="checkbox" checked={customIds.has(v.id)}
                              onChange={() => toggleCustomVideo(v.id)}
                              className="w-3 h-3 accent-teal-500" />
                            <span className="truncate">{v.file_name}</span>
                          </label>
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Search input + 右侧图标 */}
          <div className="relative flex-1 min-w-0 h-full">
            <input
              className="block w-full h-full box-border rounded-lg border border-gray-300 bg-gray-50 text-gray-900 outline-none transition-colors
                focus:border-teal-400 focus:bg-white focus:ring-2 focus:ring-teal-100 placeholder:text-gray-400
                text-[12px] py-0 pr-[104px]"
              type="text" value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder={plateMode ? "输入车牌任意字符模糊搜索…" : "场景 物体 车牌 动作 人物..."}
            />

          {/* Plate fuzzy-search mode toggle（未开车牌处理则置灰；联合搜索时范围内有任一视频开车牌即可） */}
          <button
            onClick={() => { if (!plateDisabled || plateMode) setPlateMode(v => !v); }}
            title={plateDisabled ? "未开启车牌处理" : (plateMode ? "退出车牌模糊搜索模式" : "车牌模糊搜索：输入任意字符/数字，列出所有相关车牌")}
            className={`absolute right-7 top-1/2 -translate-y-1/2 h-6 min-w-6 px-1 rounded flex items-center justify-center text-[11px] font-bold transition-colors ${
              plateDisabled ? "bg-gray-200 text-gray-600"
                : plateMode ? "bg-amber-400 text-white"
                : "bg-amber-50 text-amber-600 hover:bg-amber-100"
            }`}
          >
            牌
          </button>

          {/* Image search (inside input right) — 顺序最左 */}
          <input ref={imageInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={handleImageSearch} className="hidden" />
          <button onClick={() => imageInputRef.current?.click()} disabled={imageSearching}
            className="absolute right-[52px] top-1/2 -translate-y-1/2 w-6 h-6 rounded bg-teal-50 hover:bg-teal-100 text-teal-600 flex items-center justify-center transition-colors disabled:opacity-50" title="以图搜图">
            {imageSearching ? <span className="inline-block w-3 h-3 border-2 border-teal-300 border-t-teal-500 rounded-full animate-spin" /> : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" />
              </svg>
            )}
          </button>

          {/* Face search (inside input right)（未开人脸处理则置灰；联合搜索时范围内有任一视频开人脸即可） */}
          <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={handleFaceFile} className="hidden" />
          <button onClick={() => { if (!faceDisabled) fileInputRef.current?.click(); }} disabled={faceSearching}
            className={`absolute right-1 top-1/2 -translate-y-1/2 w-6 h-6 rounded flex items-center justify-center transition-colors disabled:opacity-50 ${
              faceDisabled ? "bg-gray-200 text-gray-600" : "bg-purple-50 hover:bg-purple-100 text-purple-600"
            }`}
            title={faceDisabled ? "未开启人脸处理" : "人脸搜索"}>
            {faceSearching ? <span className="inline-block w-3 h-3 border-2 border-purple-300 border-t-purple-500 rounded-full animate-spin" /> : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round"><circle cx="9" cy="9" r="3" /><path d="M1 20v-1a6 6 0 0112 0v1" /></svg>
            )}
          </button>

            {/* Text search spinner（在车牌按钮左侧，避免盖住右侧按钮） */}
            {searching && (
              <span className="absolute right-[80px] top-1/2 -translate-y-1/2 inline-block w-3.5 h-3.5 border-2 border-teal-300 border-t-teal-500 rounded-full animate-spin" />
            )}
          </div>
        </div>

        {/* Error */}
        {error && <div className="mb-2 p-2 rounded-lg bg-red-50 border border-red-100 text-[10px] text-red-600">{error}</div>}

        {/* Q5: 导出展开后点空白收起（fixed 遮罩，与搜索范围下拉同一模式；sr-acts 提升 z-20 保证子按钮可点） */}
        {(faceExportOpen != null || trackExportOpen != null) && (
          <div className="fixed inset-0 z-10" onClick={() => { setFaceExportOpen(null); setTrackExportOpen(null); }} />
        )}

        {/* Face search results（v0.30: 与语义/车牌搜索统一 sr-item 骨架；方案A=点卡片主体展开出现列表） */}
        {faceResults.length > 0 && (
          <div className="sr">
              {faceResults.map((fr) => {
                const appearances = fr.appearances ?? [];
                return (
                  <div key={`${fr.video_id}-${fr.identity_id}`} className="sr-item"
                    onClick={() => {
                      // v0.30: 定位"人脸"种类 → 检测栏人脸视图 + 展开身份 + 视频定位
                      //（跳转到该身份「第一条」出现时间点，非最典型脸时间戳；下钻在检测栏人脸视图）
                      if (fr.video_id !== currentVideoId) {
                        suppressResetRef.current = true;  // 由重置 effect 消费
                      }
                      const ts = fr.appearances?.[0]?.timestamp_sec ?? fr.first_seen;
                      onFaceResult?.(fr.video_id, fr.identity_id, ts);
                    }}
                  >
                    <div className="sr-top">
                      <div className="sr-thumb">
                        {fr.thumbnail_url ? <img src={fr.thumbnail_url} alt="" loading="lazy" onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} /> : (
                          <div className="w-full h-full flex items-center justify-center text-gray-300"><span className="text-base">👤</span></div>
                        )}
                      </div>
                      <div className="sr-c">
                        <div className="sr-meta">
                          <span className="sr-time">
                            {formatSec(fr.first_seen)}
                            {fr.last_seen != null && fr.last_seen !== fr.first_seen ? ` – ${formatSec(fr.last_seen)}` : ""}
                          </span>
                          <span className="sr-tag" style={{ color: "#8b5cf6" }}>{fr.identity_label}</span>
                          <span className="sr-score">{fr.similarity != null ? Math.round(fr.similarity * 100) + "%" : ""}</span>
                          <span className="sr-type face">人脸搜索</span>
                        </div>
                        <div className="sr-acts relative z-20" onClick={(e) => e.stopPropagation()}>
                          {faceExportOpen !== fr.identity_id ? (
                            <button className="sr-act" onClick={() => setFaceExportOpen(fr.identity_id)}>
                              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>导出
                            </button>
                          ) : (
                            <>
                              {fr.thumbnail_url && (
                                <button className="sr-act" onClick={() => { setFaceExportOpen(null); window.open(fr.thumbnail_url!, "_blank"); }}>
                                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>导出缩略图
                                </button>
                              )}
                              {(() => {
                                const firstTid = appearances.find((ap) => ap.track_id != null)?.track_id;
                                return firstTid != null ? (
                                  <button className="sr-act" onClick={() => { setFaceExportOpen(null); window.open(api.getTrackExportUrl(fr.video_id, firstTid, true, firstTid), "_blank"); }}>
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>导出轨迹视频
                                  </button>
                                ) : null;
                              })()}
                            </>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
        )}

        {/* Empty results */}
        {hasSearched && !searching && !imageSearching && !faceSearching && !error && results.length === 0 && faceResults.length === 0 && (
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
            // v0.30: 统一标签——图搜=图片搜索(teal)；语义按精度分=画面定位(蓝)/物体定位(玫红)/车牌搜索(琥珀)
            const typeLabel = searchMode === "image" ? "图片搜索"
              : isTrack ? "物体定位"
              : isPlate ? "车牌搜索"
              : "画面定位";
            const typeClass = searchMode === "image" ? "image"
              : isTrack ? "track"
              : isPlate ? "plate"
              : "semantic";
            return (
              <div key={isTrack ? `track-${item.video_id}-${item.track_id}` : isPlate ? `plate-${item.video_id}-${item.track_id}-${idx}` : (item.scene_id || idx)}
                className="sr-item"
                onClick={() => {
                  // v0.19: 跨视频跳转（搜索结果自己发起的切换 → 抑制搜索卡重置，保留结果与范围）
                  if (item.video_id !== currentVideoId && onGroupVideoSwitch) {
                    suppressResetRef.current = true;  // 由重置 effect 消费
                    onGroupVideoSwitch(item.video_id);
                  }
                  if (isTrack && item.track_id != null && item.precise_start != null) {
                    onTrackResult?.(item.video_id, item.track_id, item.class_name ?? "", item.precise_start);
                  } else if (isPlate && item.precise_start != null) {
                    if (item.track_id != null) onTrackResult?.(item.video_id, item.track_id, item.class_name ?? "", item.precise_start);
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
                      {isTrack && item.class_name ? (
                        <span className="sr-tag">{zhLabel(item.class_name, item.display_seq ?? item.track_id!)}</span>
                      ) : isPlate && item.plate_text ? (
                        <span className="sr-tag" style={{ color: "#d97706" }}>{item.plate_text}</span>
                      ) : null}
                      {item.similarity != null && <span className="sr-score">{Math.round((item.confidence ?? item.similarity) * 100)}%</span>}
                      <span className={`sr-type ${typeClass}`}>{typeLabel}</span>
                    </div>
                    <div className="sr-acts relative z-20" onClick={(e) => e.stopPropagation()}>
                      {isTrack && item.track_id != null ? (
                        trackExportOpen !== item.track_id ? (
                          <button className="sr-act" onClick={() => setTrackExportOpen(item.track_id!)}>
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>导出
                          </button>
                        ) : (
                          <>
                            <button className="sr-act" onClick={() => { setTrackExportOpen(null); window.open(api.getTrackThumbnailUrl(item.video_id, item.track_id!, item.track_id!), "_blank"); }}>
                              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>导出缩略图
                            </button>
                            <button className="sr-act" onClick={() => { setTrackExportOpen(null); window.open(api.getTrackExportUrl(item.video_id, item.track_id!, true, item.track_id!), "_blank"); }}>
                              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>导出轨迹视频
                            </button>
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
        {!hasSearched && !searching && !imageSearching && !faceSearching && !error && (
          <div className="flex flex-col items-center justify-center py-8 text-gray-400">
            <svg className="w-8 h-8 mb-2 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
            <p className="text-xs">{plateMode ? "输入车牌任意字符，列出所有相关车牌" : "输入关键词搜索视频画面"}</p>
          </div>
        )}
      </div>
    </div>
  );
}
