/* ════════════════════════════════════════════════════════════
   VideoSearchCard — v2.0 major-card style + face search
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "../services/api";
import type { SearchResultItem, VideoResponse, FaceSearchResult } from "../types";
import { formatSec } from "../utils/helpers";
import { zhLabel } from "../labels";
import { SubjectPhotoPicker } from "./SubjectPhotoPicker";

export function VideoSearchCard({
  video,
  videoId,
  onSeekTo,
  onTrackResult,
  onFaceResult,
  initialQuery,
  initialFaceFile,
  initialImageFile,
  selectedTrackId,
}: {
  video: VideoResponse | null;
  videoId: string | null;
  onSeekTo?: (start: number, end: number | null) => void;
  onTrackResult?: (videoId: string, trackId: number, className: string, start: number, end?: number | null) => void;
  /* v0.30: 人脸结果点击 → 定位检测栏"人脸"视图（identityId + 时间戳 + 出现片段） */
  onFaceResult?: (videoId: string, identityId: number, timestamp: number, segments?: { start: number; end: number }[]) => void;
  /* ── 跨页搜索关键词同步：全局搜索→本卡片自动填充并搜索（一次性） ── */
  initialQuery?: string | null;
  initialFaceFile?: File | null;
  initialImageFile?: File | null;
  /* ── 检测栏当前选中的 track：物体/车牌结果命中时同步金色选中框 ── */
  selectedTrackId?: number | null;
}) {
  // 用 Dashboard 的 currentVideoId（跨视频切换时 video 对象会先置 null，若从 video?.id 派生
  // currentVideoId 会经历 旧→null→新 两次变化 → 重置 effect 跑两次，suppress flag 被第一次消费掉）
  const currentVideoId = videoId ?? null;

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plateMode, setPlateMode] = useState(false);
  const [ocrMode, setOcrMode] = useState(false);
  const [resultFilter, setResultFilter] = useState<"all" | "frame" | "track">("all");
  const [filterOpen, setFilterOpen] = useState(false);
  // 智能推荐筛选（画面定位/物体定位）：用户手动切换后置 false 尊重其选择；auto 兜底展示
  const [autoFilterActive, setAutoFilterActive] = useState(true);
  // 自动推荐触发的 resultFilter 变更 → 抑制下方 effect 的重复搜索（已在本轮搜索中带上新筛选）
  const skipFilterReseachRef = useRef(false);
  // 搜索结果自己发起的视频切换 → 抑制重置（本帧 effect 读到 true 跳过；setTimeout 清理，StrictMode 安全）
  const suppressResetRef = useRef(false);
  const [faceSearching, setFaceSearching] = useState(false);
  const [faceResults, setFaceResults] = useState<FaceSearchResult[]>([]);
  const [faceExportOpen, setFaceExportOpen] = useState<number | null>(null); // 人脸"导出"展开的 identity_id
  const [trackExportOpen, setTrackExportOpen] = useState<number | null>(null); // 物体"导出"展开的 track_id
  // 最近点击的结果（非 track 类无检测栏选中态可用，用本地记录标记金色选中框）；新搜索结果到达即清除
  const [clickedKey, setClickedKey] = useState<string | null>(null);
  useEffect(() => { setClickedKey(null); }, [results]);
  const [imageSearching, setImageSearching] = useState(false);
  // v0.30: 当前结果来自哪种搜索（决定 sr-type 标签；语义=frame/text/chunk/track/plate 混合）
  const [searchMode, setSearchMode] = useState<"semantic" | "image" | "face">("semantic");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  // 严格限定当前视频
  const searchVideoIds: string[] | null = currentVideoId ? [currentVideoId] : null;

  // 图搜/人脸搜选图来源菜单（本地 / 从素材库）
  const [assetPicker, setAssetPicker] = useState<{ kind: "image" | "face" } | null>(null);
  const [assetMenu, setAssetMenu] = useState<{ kind: "image" | "face"; x: number; y: number } | null>(null);

  const openAssetMenu = (e: React.MouseEvent, kind: "image" | "face") => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setAssetMenu({ kind, x: r.right, y: r.bottom + 4 });
  };

  // 功能门控：仅看当前视频
  const detEnabled = !!video?.detection_enabled;
  const faceDisabled = !detEnabled || !video?.face_enabled;
  const plateDisabled = !detEnabled || !video?.plate_enabled;
  const ocrDisabled = !detEnabled || !video?.ocr_enabled;
  const semanticReady = !!video?.search_index_enabled;
  const initialQueryRef = useRef<string | null>(null);

  // 切换过滤器时重新搜索（已有查询才触发）
  useEffect(() => {
    if (!query.trim() || !hasSearched) return;
    // 自动推荐触发的结果筛选变更 → 本次搜索已带新筛选，跳过重复搜索
    if (skipFilterReseachRef.current) { skipFilterReseachRef.current = false; return; }
    void handleSearch();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resultFilter]);

  // 视频切换：手动切换（header/历史）→ 重置搜索上下文；搜索结果自己发起的切换 → 抑制（保留结果）
  // 若有 initialQuery/initialFaceFile/initialImageFile（全局搜索同步），跳过重置并自动搜索
  useEffect(() => {
    if (suppressResetRef.current) {
      suppressResetRef.current = false;
      return;
    }
    // 全局搜索关键词同步：跳过重置，直接填充并搜索（含智能结果筛选推荐）
    if (initialQuery && currentVideoId && initialQuery !== initialQueryRef.current) {
      initialQueryRef.current = initialQuery;
      setQuery(initialQuery);
      void runSemanticSearch(initialQuery);
      return;
    }
    // 全局搜索人脸/图搜同步
    if (initialFaceFile && currentVideoId) {
      setResults([]); setFaceResults([]); setError(null);
      void runFaceSearch(initialFaceFile);
      return;
    }
    if (initialImageFile && currentVideoId) {
      setResults([]); setFaceResults([]); setError(null);
      void runImageSearch(initialImageFile);
      return;
    }
    setQuery(""); setResults([]); setSearching(false); setHasSearched(false); setError(null); setFaceResults([]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentVideoId, initialQuery, initialFaceFile, initialImageFile]);

  const runFaceSearch = useCallback(async (file: File) => {
    if (!file) return;
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

  const handleFaceFile = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    void runFaceSearch(file);
  }, [runFaceSearch]);

  /* ── 通用图搜 ── */
  const runImageSearch = useCallback(async (file: File) => {
    if (!file) return;
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

  const handleImageSearch = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    void runImageSearch(file);
  }, [runImageSearch]);

  // 语义搜索 + 智能推荐结果筛选（画面/物体定位），供搜索框 Enter 与全局搜索关键词同步共用
  const runSemanticSearch = useCallback(async (text: string) => {
    const q = text.trim();
    setResults([]); setSearching(true); setError(null); setFaceResults([]);
    setSearchMode("semantic"); // 语义搜索（含帧/物体/车牌）
    // 智能推荐结果筛选：仅当用户未手动覆盖时才自动判断；
    // 车牌/文字模式不参与（它们有各自的精确检索路径）
    let effectiveFilter: "all" | "frame" | "track" = resultFilter;
    if (autoFilterActive && !plateMode && !ocrMode) {
      try {
        const sug = await api.suggestSearchFilter(q);
        if (sug.filter === "frame" || sug.filter === "track") {
          effectiveFilter = sug.filter;
          if (effectiveFilter !== resultFilter) {
            skipFilterReseachRef.current = true; // 本次已带新筛选，抑制 effect 重复搜索
            setResultFilter(effectiveFilter);
          }
        }
      } catch { /* 推荐失败保持原筛选，不阻断搜索 */ }
    }
    try {
      const data = await api.searchSemantic(q, {
        video_ids: searchVideoIds ?? undefined,
        ...(plateMode ? { search_types: ["plate"], top_k: 100 } : {}),
        ...(ocrMode ? { search_types: ["ocr"], top_k: 100 } : {}),
        ...(effectiveFilter === "frame" && !plateMode && !ocrMode ? { search_types: ["frame"] } : {}),
        ...(effectiveFilter === "track" && !plateMode && !ocrMode ? { search_types: ["track"] } : {}),
      });
      setResults(data.results ?? []); setHasSearched(true);
    } catch (err) { setError(err instanceof Error ? err.message : "搜索失败"); }
    finally { setSearching(false); }
  }, [resultFilter, autoFilterActive, plateMode, ocrMode, searchVideoIds]);

  const handleSearch = useCallback(() => {
    if (!query.trim()) return;
    void runSemanticSearch(query);
  }, [query, runSemanticSearch]);

  const resultCount = results.length;

  /* ── Processing（统一空态：居中灰字，与摘要/检测卡一致） ── */
  if (video && (video.status === "pending" || video.status === "processing")) {
    return (
      <div className="major-card">
        <div className="major-card-hd">
          <div className="major-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
            视频搜索
          </div>
        </div>
        <div className="major-card-bd flex items-center justify-center">
          <span className="text-gray-400 text-sm">视频处理完成后自动建立搜索索引</span>
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
          <span className={`text-[9px] px-1.5 py-0.5 rounded whitespace-nowrap shrink-0 transition-colors ${!plateDisabled ? "bg-amber-50 text-amber-600 font-semibold" : "bg-gray-100 text-gray-400"}`} title={plateDisabled ? "范围内无已开启车牌识别的视频，车牌搜索不可用" : "车牌识别"}>车牌</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded whitespace-nowrap shrink-0 transition-colors ${!ocrDisabled ? "bg-cyan-50 text-cyan-600 font-semibold" : "bg-gray-100 text-gray-400"}`} title={ocrDisabled ? "范围内无已开启文字识别的视频，文字搜索不可用" : "画面文字"}>文字</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded whitespace-nowrap shrink-0 transition-colors ${!faceDisabled ? "bg-purple-50 text-purple-600 font-semibold" : "bg-gray-100 text-gray-400"}`} title={faceDisabled ? "范围内无已开启人脸识别的视频，人脸搜索不可用" : "人脸识别"}>人脸</span>
        </div>
      </div>

      <div className="major-card-bd flex flex-col p-0">
        {/* 搜索框固定不滚动 */}
        <div className="flex items-stretch w-full min-w-0 h-[34px] gap-1 shrink-0 px-3.5 pb-1">
          {/* 结果类型筛选下拉 */}
          <div className="relative shrink-0">
            <button
              onClick={() => setFilterOpen((o) => !o)}
              className={`flex h-full items-center gap-0.5 px-1.5 text-[11px] font-medium rounded-lg border transition-all min-w-[58px] ${
                filterOpen
                  ? "border-teal-400 bg-teal-50 text-teal-700"
                  : "border-gray-300 bg-gray-50 text-gray-600 hover:border-teal-300 hover:text-teal-700"
              }`}
            >
              <span className="truncate">{resultFilter === "all" ? "全部" : resultFilter === "frame" ? "事件" : "目标"}</span>
              <svg className={`w-3 h-3 shrink-0 transition-transform ${filterOpen ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M6 9l6 6 6-6" /></svg>
            </button>
            {filterOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setFilterOpen(false)} />
                <div className="absolute top-full left-0 mt-1 bg-white rounded-lg shadow-xl border border-gray-200 z-50 overflow-hidden min-w-[80px] py-0.5">
                  {([["all", "全部"], ["frame", "事件检索"], ["track", "目标检索"]] as const).map(([key, label]) => (
                    <button
                      key={key}
                      className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${resultFilter === key ? "bg-teal-50 text-teal-700 font-medium" : "text-gray-600 hover:bg-gray-50"}`}
                      onClick={() => { setAutoFilterActive(false); setResultFilter(key); setFilterOpen(false); }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          {/* Search input + 右侧图标 */}
          <div className="relative flex-1 min-w-0 h-full">
            <input
              className="block w-full h-full box-border rounded-lg border border-gray-300 bg-gray-50 text-gray-900 outline-none transition-colors
                focus:border-teal-400 focus:bg-white focus:ring-2 focus:ring-teal-100 placeholder:text-gray-400
                text-[12px] py-0 pr-[132px]"
              type="text" value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder={plateMode ? "输入车牌任意字符模糊搜索…" : ocrMode ? "输入聊天/字幕原话精确搜索…" : "场景 物体 车牌 动作 人物..."}
            />

          {/* Plate fuzzy-search mode toggle（未开车牌处理则置灰；联合搜索时范围内有任一视频开车牌即可） */}
          <button
            onClick={() => { if (!plateDisabled || plateMode) { setPlateMode(v => !v); setOcrMode(false); } }}
            title={plateDisabled ? "未开启车牌处理" : (plateMode ? "退出车牌模糊搜索模式" : "车牌模糊搜索：输入任意字符/数字，列出所有相关车牌")}
            className={`absolute right-7 top-1/2 -translate-y-1/2 h-6 min-w-6 px-1 rounded flex items-center justify-center text-[11px] font-bold transition-colors ${
              plateDisabled ? "bg-gray-200 text-gray-600"
                : plateMode ? "bg-amber-400 text-white"
                : "bg-amber-50 text-amber-600 hover:bg-amber-100"
            }`}
          >
            牌
          </button>

          {/* OCR 文字搜索 toggle（v0.34：与车牌互斥，只跑 ocr 路精确串匹配） */}
          <button
            onClick={() => { if (!ocrDisabled || ocrMode) { setOcrMode(v => !v); setPlateMode(false); } }}
            title={ocrDisabled ? "未开启文字识别" : (ocrMode ? "退出文字搜索模式" : "文字搜索：输入聊天/字幕原话，精确定位到帧")}
            className={`absolute right-[52px] top-1/2 -translate-y-1/2 h-6 min-w-6 px-1 rounded flex items-center justify-center text-[11px] font-bold transition-colors ${
              ocrDisabled ? "bg-gray-200 text-gray-600"
                : ocrMode ? "bg-cyan-400 text-white"
                : "bg-cyan-50 text-cyan-600 hover:bg-cyan-100"
            }`}
          >
            文
          </button>

          {/* Image search (inside input right) — 顺序最左 */}
          <input ref={imageInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={handleImageSearch} className="hidden" />
          <button onClick={(e) => openAssetMenu(e, "image")} disabled={imageSearching}
            className="absolute right-[76px] top-1/2 -translate-y-1/2 w-6 h-6 rounded bg-teal-50 hover:bg-teal-100 text-teal-600 flex items-center justify-center transition-colors disabled:opacity-50" title="以图搜图（本地选图 / 从素材库选图）">
            {imageSearching ? <span className="inline-block w-3 h-3 border-2 border-teal-300 border-t-teal-500 rounded-full animate-spin" /> : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" />
              </svg>
            )}
          </button>

          {/* Face search (inside input right)（未开人脸处理则置灰；联合搜索时范围内有任一视频开人脸即可） */}
          <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={handleFaceFile} className="hidden" />
          <button onClick={(e) => { if (!faceDisabled) openAssetMenu(e, "face"); }} disabled={faceSearching}
            className={`absolute right-1 top-1/2 -translate-y-1/2 w-6 h-6 rounded flex items-center justify-center transition-colors disabled:opacity-50 ${
              faceDisabled ? "bg-gray-200 text-gray-600" : "bg-purple-50 hover:bg-purple-100 text-purple-600"
            }`}
            title={faceDisabled ? "未开启人脸处理" : "人脸搜索（本地选图 / 从素材库选图）"}>
            {faceSearching ? <span className="inline-block w-3 h-3 border-2 border-purple-300 border-t-purple-500 rounded-full animate-spin" /> : (
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="7" r="4" /><path d="M20 21v-1a8 8 0 00-16 0v1" /></svg>
            )}
          </button>

            {/* Text search spinner（在最右侧按钮左侧，避免盖住右侧按钮） */}
            {searching && (
              <span className="absolute right-[108px] top-1/2 -translate-y-1/2 inline-block w-3.5 h-3.5 border-2 border-teal-300 border-t-teal-500 rounded-full animate-spin" />
            )}
          </div>
        </div>

        {/* 结果区域独立滚动 */}
        <div className="flex-1 min-h-0 overflow-auto px-3.5" style={{ scrollbarGutter: "stable" }}>
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
                      // 每个出现段 = 一个匹配上的 person track 的 [track_start, track_end]（真实标黄时长）。
                      // 按 track_id 聚合取该 track 起止；无 track 的人脸按检测点独立成段。不跨 track 合并。
                      const segMap = new Map<number | string, { start: number; end: number }>();
                      for (const ap of appearances) {
                        const tid = ap.track_id;
                        const key = tid != null ? tid : `t${ap.timestamp_sec}`;
                        const s = ap.track_start ?? ap.timestamp_sec;
                        const e = ap.track_end ?? ap.timestamp_sec;
                        const seg = segMap.get(key);
                        if (seg) {
                          if (s < seg.start) seg.start = s;
                          if (e > seg.end) seg.end = e;
                        } else {
                          segMap.set(key, { start: s, end: e });
                        }
                      }
                      const segments = Array.from(segMap.values()).sort((a, b) => a.start - b.start);
                      onFaceResult?.(fr.video_id, fr.identity_id, ts, segments.length > 1 ? segments : undefined);
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
                        {/* 停止冒泡只放在单个按钮上：容器整行宽，之前整层吞点击导致
                            按钮右侧空白区「点了没反应」（点缩略图/标签却正常） */}
                        <div className="sr-acts relative z-20">
                          {faceExportOpen !== fr.identity_id ? (
                            <button className="sr-act" onClick={(e) => { e.stopPropagation(); setFaceExportOpen(fr.identity_id); }}>
                              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>导出
                            </button>
                          ) : (
                            <>
                              {fr.thumbnail_url && (
                                <button className="sr-act" onClick={(e) => { e.stopPropagation(); setFaceExportOpen(null); window.open(fr.thumbnail_url!, "_blank"); }}>
                                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>导出缩略图
                                </button>
                              )}
                              {(() => {
                                const firstTid = appearances.find((ap) => ap.track_id != null)?.track_id;
                                return firstTid != null ? (
                                  <button className="sr-act" onClick={(e) => { e.stopPropagation(); setFaceExportOpen(null); window.open(api.getTrackExportUrl(fr.video_id, firstTid, true, firstTid), "_blank"); }}>
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
            const isOcr = item.precision_level === "ocr";
            const itemKey = isTrack ? `t-${item.video_id}-${item.track_id}-${idx}`
              : isPlate ? `p-${item.video_id}-${item.track_id}-${idx}`
              : isOcr ? `o-${item.video_id}-${item.precise_start}-${idx}`
              : `${item.video_id}-f-${idx}`;
            /* 注意：键必须唯一到「单条结果」——不能只用 scene_id（_enrich_merged 会把
               同一场景的多个帧簇填上相同 scene_id，曾导致点一条→同场景全部亮）。 */
            // 选中标识：物体/车牌结果跟检测栏 track 选中联动；其余结果记录最近点击项
            const isSel = (isTrack || (isPlate && item.track_id != null)) && item.track_id != null
              ? selectedTrackId === item.track_id
              : clickedKey === itemKey;
            // v0.30: 统一标签——图搜=图片搜索(teal)；语义按精度分=画面定位(蓝)/物体定位(玫红)/车牌搜索(琥珀)；OCR=文字搜索(青)
            const typeLabel = searchMode === "image" ? "图片搜索"
              : isTrack ? "物体定位"
              : isPlate ? "车牌搜索"
              : isOcr ? "文字搜索"
              : "画面定位";
            const typeClass = searchMode === "image" ? "image"
              : isTrack ? "track"
              : isPlate ? "plate"
              : isOcr ? "ocr"
              : "semantic";
            return (
              <div key={itemKey}
                className={"sr-item" + (isSel ? " sel" : "")}
                onClick={() => {
                  setClickedKey(itemKey);
                  if (isTrack && item.track_id != null && item.precise_start != null) {
                    onTrackResult?.(item.video_id, item.track_id, item.class_name ?? "", item.precise_start, item.precise_end);
                  } else if (isPlate && item.precise_start != null) {
                    if (item.track_id != null) onTrackResult?.(item.video_id, item.track_id, item.class_name ?? "", item.precise_start, item.precise_end);
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
                      ) : isOcr && item.ocr_text ? (
                        <span className="sr-tag" style={{ color: "#0891b2" }}>{item.ocr_text}</span>
                      ) : null}
                      {item.similarity != null && <span className="sr-score">{Math.round((item.confidence ?? item.similarity) * 100)}%</span>}
                      <span className={`sr-type ${typeClass}`}>{typeLabel}</span>
                    </div>
                    {isOcr && item.ocr_text && (
                      <div className="sr-text" style={{ color: "#155e75", WebkitLineClamp: "unset" }}>{item.ocr_text}</div>
                    )}
                    {/* 停止冒泡只放在单个按钮上（理由同人脸区）：容器整行宽会吞掉右侧空白区的点击 */}
                    <div className="sr-acts relative z-20">
                      {isTrack && item.track_id != null ? (
                        trackExportOpen !== item.track_id ? (
                          <button className="sr-act" onClick={(e) => { e.stopPropagation(); setTrackExportOpen(item.track_id!); }}>
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>导出
                          </button>
                        ) : (
                          <>
                            <button className="sr-act" onClick={(e) => { e.stopPropagation(); setTrackExportOpen(null); window.open(api.getTrackThumbnailUrl(item.video_id, item.track_id!, item.track_id!), "_blank"); }}>
                              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>导出缩略图
                            </button>
                            <button className="sr-act" onClick={(e) => { e.stopPropagation(); setTrackExportOpen(null); window.open(api.getTrackExportUrl(item.video_id, item.track_id!, true, item.track_id!), "_blank"); }}>
                              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>导出轨迹视频
                            </button>
                          </>
                        )
                      ) : null}
                      {!isTrack && !isPlate && item.precise_start != null && item.precise_end != null && (
                        <button className="sr-act" onClick={(e) => { e.stopPropagation(); window.open(api.getClipExportUrl(item.video_id, item.precise_start!, item.precise_end!), "_blank"); }}>
                          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>下载
                        </button>
                      )}
                      {isPlate && item.thumbnail_url && (
                        <button className="sr-act" onClick={(e) => { e.stopPropagation(); window.open(item.thumbnail_url!, "_blank"); }}>
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
            <p className="text-xs">{plateMode ? "输入车牌任意字符，列出所有相关车牌" : ocrMode ? "输入聊天/字幕原话，精确匹配画面文字" : "输入关键词搜索视频画面"}</p>
          </div>
        )}
        </div>
      </div>

      {/* 图搜/人脸搜 选图来源菜单（本地 / 从素材库） */}
      {assetMenu && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setAssetMenu(null)} />
          <div className="fixed z-40 w-40 rounded-lg border border-gray-200 bg-white shadow-xl py-1 text-xs" style={{ left: Math.max(8, assetMenu.x - 160), top: assetMenu.y }}>
            <button className="w-full px-3 py-1.5 text-left text-gray-700 hover:bg-gray-50"
              onClick={() => { const k = assetMenu.kind; setAssetMenu(null); (k === "image" ? imageInputRef : fileInputRef).current?.click(); }}>
              本地选择图片
            </button>
            <button className="w-full px-3 py-1.5 text-left text-gray-700 hover:bg-gray-50"
              onClick={() => { setAssetMenu(null); setAssetPicker({ kind: assetMenu.kind }); }}>
              从素材库选图
            </button>
          </div>
        </>
      )}

      {/* 从素材库选图弹窗 */}
      {assetPicker && (
        <SubjectPhotoPicker
          onClose={() => setAssetPicker(null)}
          onSelect={(file) => {
            setAssetPicker(null);
            if (assetPicker.kind === "image") void runImageSearch(file);
            else void runFaceSearch(file);
          }}
        />
      )}
    </div>
  );
}
