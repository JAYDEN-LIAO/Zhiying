/* ════════════════════════════════════════════════════════════
   DetectionPanel — v2.0 major-card style + v0.22 虚拟滚动
   Preserves: class filter, face tab, hover preview, export, plates
   v0.22 (S3/C1): 手写固定行高虚拟列表（零依赖）—— 只渲染视口 ~30 行，
   TrackRow memo 让选中/筛选只重渲受影响行；缩略图天然按需加载。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useState, useMemo, memo, useCallback } from "react";
import type { DetectionData, VideoResponse, VideoListItem, Track, PlateDetectionItem } from "../types";
import { api } from "../services/api";
import { colorOf, zh } from "../labels";

const SELECTED = "#FFD700";

// ── 虚拟滚动常量（dtc-item 固定行高 ~68px + dtc-list gap 4px）──
const ROW_H = 68;
const ROW_GAP = 4;
const ROW_STEP = ROW_H + ROW_GAP;
const OVERSCAN = 5;

interface Props {
  video: VideoResponse | null;
  data: DetectionData | null;
  selectedTrackId: number | null;
  classFilter: string | null;
  onClassFilterChange: (cls: string | null) => void;
  onTrackSelect: (trackId: number, className: string, seekTo: number) => void;
  faceData: import("../types").FaceData | null;
  plateData: import("../types").PlateData | null;
  /* ── v0.19 组感知 ── */
  groupVideos?: string[];
  videos?: VideoListItem[];
  detectionVideoId?: string | null;
  onDetectionVideoChange?: (videoId: string | null) => void;
}

function thumbUrl(videoId: string, ts: number, bbox: { x1: number; y1: number; x2: number; y2: number }) {
  return `/api/v1/videos/${videoId}/detection/thumbnail?timestamp=${ts}&x1=${bbox.x1}&y1=${bbox.y1}&x2=${bbox.x2}&y2=${bbox.y2}`;
}

/* ── TrackRow: memoized 单行（props 除 isSel/isDropdownOpen 外全部引用稳定）── */

interface TrackRowProps {
  track: Track;
  isSel: boolean;
  video: VideoResponse;
  color: string;
  hasFace: boolean;
  plate: PlateDetectionItem | undefined;
  tUrl: string | null;
  thumbTs: number;
  bbox: { x1: number; y1: number; x2: number; y2: number } | null;
  displayId: number;
  maxDuration: number;
  isDropdownOpen: boolean;
  onTrackSelect: (trackId: number, className: string, seekTo: number) => void;
  onToggleDropdown: (trackId: number) => void;
  onCloseDropdown: () => void;
  onHoverThumb: (th: { videoId: string; ts: number; bbox: { x1: number; y1: number; x2: number; y2: number }; x: number; y: number } | null) => void;
  onDownloadThumb: (trackId: number, displayId: number) => void;
  onDownloadTrack: (trackId: number, displayId: number) => void;
}

const TrackRow = memo(function TrackRow({
  track, isSel, video, color, hasFace, plate, tUrl, thumbTs, bbox,
  displayId, maxDuration, isDropdownOpen,
  onTrackSelect, onToggleDropdown, onCloseDropdown, onHoverThumb,
  onDownloadThumb, onDownloadTrack,
}: TrackRowProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      data-track-id={track.track_id}
      className={`dtc-item `}
      style={{ width: "100%" }}
      onClick={() => onTrackSelect(track.track_id, track.class_name, track.first_seen)}
      onKeyDown={(e) => {
        if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onTrackSelect(track.track_id, track.class_name, track.first_seen);
        }
      }}
    >
      {bbox && tUrl ? (
        <div className="w-10 h-10 rounded-md shrink-0 overflow-hidden bg-gray-100 flex items-center justify-center cursor-pointer"
             style={{ border: isSel ? `1.5px solid ${SELECTED}` : "1px solid rgba(0,0,0,0.06)" }}
             onMouseEnter={(e) => { const r = e.currentTarget.getBoundingClientRect(); onHoverThumb({ videoId: video.id, ts: thumbTs, bbox, x: r.right + 8, y: r.top - 40 }); }}
             onMouseLeave={() => onHoverThumb(null)}
        >
          <img src={tUrl} loading="lazy" className="w-full h-full object-contain" alt="" />
        </div>
      ) : (
        <div className="dtc-dot" style={{ background: isSel ? SELECTED : color }} />
      )}
      <div className="dtc-info">
        <div className="dtc-name">
          {zh(track.class_name)}
          <span className="dtc-id">#{displayId}</span>
          {hasFace && <span className="dtc-face">👤</span>}
          {plate && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3, marginLeft: 2 }}>
              <span className="dtc-plate">{plate.plate_text}</span>
              <span className={`dtc-plt ${plate.plate_type}`}>
                {plate.plate_type === "blue" ? "蓝" : plate.plate_type === "yellow" ? "黄" : plate.plate_type === "green" ? "绿" : plate.plate_type}
              </span>
            </span>
          )}
        </div>
        <div className="dtc-time">{track.first_seen.toFixed(1)}s - {track.last_seen.toFixed(1)}s</div>
      </div>
      <div className="dtc-bar">
        <div className="dtc-bar-fill" style={{ width: `${Math.min(100, ((track.last_seen - track.first_seen) / (maxDuration || 1)) * 100)}%`, background: isSel ? SELECTED : color }} />
      </div>
      {/* Export dropdown */}
      <div className="relative shrink-0">
        <button
          onClick={(e) => { e.stopPropagation(); onToggleDropdown(track.track_id); }}
          className="w-6 h-6 rounded-md flex items-center justify-center text-gray-300 hover:text-teal-500 hover:bg-teal-50 transition-all cursor-pointer"
          title="导出"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
        </button>
        {isDropdownOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={onCloseDropdown} />
            <div className="absolute right-0 top-full mt-1 bg-white rounded-lg shadow-lg border border-gray-200 z-20 overflow-hidden min-w-[140px]">
              <button onClick={(e) => { e.stopPropagation(); onCloseDropdown(); onDownloadThumb(track.track_id, displayId); }}
                className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2">
                <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>
                导出缩略图
              </button>
              <button onClick={(e) => { e.stopPropagation(); onCloseDropdown(); onDownloadTrack(track.track_id, displayId); }}
                className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2">
                <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" /></svg>
                导出track视频
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
});

export function DetectionPanel({ video, data, selectedTrackId, classFilter, onClassFilterChange, onTrackSelect, faceData, plateData, groupVideos, videos, detectionVideoId, onDetectionVideoChange }: Props) {
  const [showFaces, setShowFaces] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [trackDropdown, setTrackDropdown] = useState<number | null>(null);
  const [hoverThumb, setHoverThumb] = useState<{ videoId: string; ts: number; bbox: { x1: number; y1: number; x2: number; y2: number }; x: number; y: number } | null>(null);
  const [expandedFaceId, setExpandedFaceId] = useState<number | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(400);
  const listRef = useRef<HTMLDivElement>(null);
  const scrollRaf = useRef(0);

  const showFaceBtn = !!(video?.face_enabled && faceData?.has_face);

  const plateByTrack = useMemo(() => {
    const map = new Map<number, PlateDetectionItem>();
    if (plateData?.detections) {
      for (const p of plateData.detections) {
        const existing = map.get(p.track_id);
        if (!existing || p.confidence > existing.confidence) map.set(p.track_id, p);
      }
    }
    return map;
  }, [plateData]);

  const tracks = data?.tracks ?? [];
  const filtered = useMemo(
    () => (classFilter ? tracks.filter((t) => t.class_name === classFilter) : tracks),
    [tracks, classFilter],
  );
  // 供 scrollToIndex effect 读取（避免把 filtered 放 deps 导致每次渲染重触发）
  const filteredRef = useRef(filtered);
  filteredRef.current = filtered;

  const classCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const t of tracks) c[t.class_name] = (c[t.class_name] || 0) + 1;
    return c;
  }, [tracks]);
  const classEntries = Object.entries(classCounts).sort((a, b) => b[1] - a[1]);
  const isAll = classFilter === null;
  const activeColor = !isAll ? (colorOf(classFilter!)) : "#6B7280";

  /* ── 虚拟滚动：容器滚动 → rAF 节流更新 scrollTop ── */
  const handleListScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const top = e.currentTarget.scrollTop;   // 同步捕获（合成事件在异步回调中 currentTarget 不可靠）
    if (scrollRaf.current) return;
    scrollRaf.current = requestAnimationFrame(() => {
      scrollRaf.current = 0;
      setScrollTop(top);
    });
  }, []);

  /* ── objects 列表可见性（与 JSX 门禁共用同一变量，杜绝"渲染门禁 vs effect 依赖"漂移）── */
  const listVisible = !showFaces && !!data?.has_detection && !!data.tracks?.length;

  /* ── 视口高度测量：keyed on listVisible，每轮 effect 新建 observer（新闭包捕获当前元素，
     消灭"复用 observer 闭包捕获已卸载元素 → clientHeight=0"的陈旧引用 bug）── */
  useEffect(() => {
    const el = listRef.current;
    if (!listVisible || !el) return;
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight));
    ro.observe(el);
    setViewportH(el.clientHeight);
    return () => ro.disconnect();
  }, [listVisible]);

  /* ── 选中居中（scrollTop 计算替代 scrollIntoView；仅 objects tab）── */
  useEffect(() => {
    if (showFaces || selectedTrackId == null || !listRef.current) return;
    const idx = filteredRef.current.findIndex((t) => t.track_id === selectedTrackId);
    if (idx < 0) return;
    const el = listRef.current;
    const target = Math.max(0, idx * ROW_STEP - (el.clientHeight - ROW_H) / 2);
    // 同步 DOM + state：仅设 el.scrollTop 时滚动事件会被 handleListScroll 的 rAF 节流丢弃
    // （pending 中该事件直接 return）→ scrollTop state 不更新 → 虚拟窗口不含选中行 → 面板「跳不到位」。
    if (scrollRaf.current) { cancelAnimationFrame(scrollRaf.current); scrollRaf.current = 0; }
    el.scrollTop = target;
    setScrollTop(target);
  }, [selectedTrackId, showFaces]);

  /* ── 筛选/切 tab/切视频 → 回顶（同时复位 state 与 DOM，消除陈旧滚动位置）── */
  useEffect(() => {
    setScrollTop(0);
    if (!showFaces && listRef.current) listRef.current.scrollTop = 0;
  }, [classFilter, showFaces, data?.tracks]);

  /* ── 稳定 handlers（memo 生效前提：除 isSel/isDropdownOpen 外全部引用稳定）── */
  const toggleDropdown = useCallback((tid: number) => {
    setTrackDropdown((prev) => (prev === tid ? null : tid));
  }, []);
  const closeDropdown = useCallback(() => setTrackDropdown(null), []);
  const onHoverThumb = useCallback(setHoverThumb, []);
  const downloadThumb = useCallback((trackId: number, displayId: number) => {
    if (video) window.open(api.getTrackThumbnailUrl(video.id, trackId, displayId), "_blank");
  }, [video]);
  const downloadTrack = useCallback((trackId: number, displayId: number) => {
    if (video) window.open(api.getTrackExportUrl(video.id, trackId, true, displayId), "_blank");
  }, [video]);

  /* ── 可见行窗口 ── */
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_STEP) - OVERSCAN);
  const endIdx = Math.min(filtered.length, Math.ceil((scrollTop + viewportH) / ROW_STEP) + OVERSCAN);

  /* ── No video ── */
  if (!video) {
    return (
      <div className="major-card">
        <div className="major-card-hd">
          <div className="major-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
            </svg>
            物体检测
          </div>
        </div>
        <div className="major-card-bd flex items-center justify-center">
          <span className="text-gray-400 text-sm">选择视频后查看</span>
        </div>
      </div>
    );
  }

  /* ── Detection not enabled ── */
  if (!video.detection_enabled && video.status === "completed") {
    return (
      <div className="major-card">
        <div className="major-card-hd">
          <div className="major-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
            </svg>
            物体检测
          </div>
        </div>
        <div className="major-card-bd flex flex-col items-center justify-center gap-1 opacity-50">
          <span className="text-gray-400 text-sm">检测功能未开启</span>
          <span className="text-xs text-gray-300">请在参数设置中启用「物体检测」</span>
        </div>
      </div>
    );
  }

  /* ── Processing ── */
  if (video.status === "processing" || video.status === "pending") {
    return (
      <div className="major-card">
        <div className="major-card-hd">
          <div className="major-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
            </svg>
            物体检测
          </div>
        </div>
        <div className="major-card-bd">
          <div className="animate-pulse space-y-2.5 w-full">
            <div className="h-3 bg-gray-200 rounded w-2/3" />
            <div className="flex gap-2"><div className="h-10 w-10 bg-gray-200 rounded-md" /><div className="flex-1 space-y-1.5"><div className="h-3 bg-gray-200 rounded w-3/4" /><div className="h-2.5 bg-gray-200 rounded w-1/2" /></div></div>
            <div className="flex gap-2"><div className="h-10 w-10 bg-gray-200 rounded-md" /><div className="flex-1 space-y-1.5"><div className="h-3 bg-gray-200 rounded w-3/4" /><div className="h-2.5 bg-gray-200 rounded w-1/2" /></div></div>
          </div>
        </div>
      </div>
    );
  }

  /* ── No data ── */
  if (!data?.has_detection || !data.tracks?.length) {
    return (
      <div className="major-card">
        <div className="major-card-hd">
          <div className="major-card-tt">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
            </svg>
            物体检测
          </div>
        </div>
        <div className="major-card-bd flex items-center justify-center">
          <span className="text-gray-400 text-sm">暂无检测数据</span>
        </div>
      </div>
    );
  }

  const maxDuration = tracks[tracks.length - 1]?.last_seen || 1;

  return (
    <div className="major-card">
      {/* Header */}
      <div className="major-card-hd">
        <div className="major-card-tt">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
          </svg>
          {showFaces ? "人脸" : "物体检测"}
        </div>
        <div className="flex items-center gap-2">
          {/* v0.19: 组内视频选择器 */}
          {(groupVideos && groupVideos.length > 1 && onDetectionVideoChange) && (
            <select
              value={detectionVideoId ?? video?.id ?? ""}
              onChange={(e) => onDetectionVideoChange(e.target.value || null)}
              className="text-[10px] border border-gray-200 rounded-md px-1.5 py-0.5 bg-white text-gray-700 max-w-[100px]"
              title="选择检测视频"
            >
              {groupVideos.map((vId) => {
                const vName = videos?.find(v => v.id === vId)?.file_name ?? vId.slice(0, 8);
                return (
                  <option key={vId} value={vId}>{vName.length > 8 ? vName.slice(0, 8) + "…" : vName}</option>
                );
              })}
            </select>
          )}
          {showFaceBtn && (
            <button
              onClick={() => setShowFaces(!showFaces)}
              className={`text-[10px] font-medium px-2 py-0.5 rounded-md transition-all ${showFaces ? "bg-purple-500/20 text-purple-200" : "text-slate-400 hover:text-purple-300 hover:bg-purple-500/10"}`}
            >
              👤 人脸
            </button>
          )}
          <span className="major-card-badge">{showFaces ? `${faceData?.identities.length ?? 0} 人` : `${tracks.length} 条`}</span>
        </div>
      </div>

      <div className="major-card-bd" style={{ padding: "6px 10px 8px", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Class filter — dropdown */}
        {!showFaces && classEntries.length > 1 && (
          <div className="relative mb-2 shrink-0">
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="dtc-filter-btn"
            >
              {isAll ? (
                <span>全部 · {tracks.length}</span>
              ) : (
                <><span className="dot" style={{ background: activeColor }} />{zh(classFilter)} · {classCounts[classFilter]}</>
              )}
              <svg className={`w-3 h-3 transition-transform ${dropdownOpen ? "rotate-180" : ""}`} viewBox="0 0 12 12" fill="currentColor"><path d="M3 5l3 3 3-3" /></svg>
            </button>
            {dropdownOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setDropdownOpen(false)} />
                <div className="absolute top-full left-0 mt-1 bg-white rounded-lg shadow-lg border border-gray-200 z-20 overflow-hidden min-w-[160px]">
                  <button
                    className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-gray-50 ${isAll ? "font-semibold text-gray-900" : "text-gray-600"}`}
                    onClick={() => { onClassFilterChange(null); setDropdownOpen(false); }}
                  >
                    全部 · {tracks.length}
                  </button>
                  {classEntries.map(([cls, count]) => (
                    <button
                      key={cls}
                      className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-gray-50 ${classFilter === cls ? "font-semibold text-gray-900" : "text-gray-600"}`}
                      onClick={() => { onClassFilterChange(cls); setDropdownOpen(false); }}
                    >
                      <span className="dot" style={{ background: colorOf(cls) }} />{zh(cls)} · {count}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
        {!showFaces && classEntries.length <= 1 && classEntries.length > 0 && (
          <span className="text-[11px] font-medium shrink-0" style={{ color: colorOf(classEntries[0][0]) }}>
            {zh(classEntries[0][0])} × {classEntries[0][1]}
          </span>
        )}

        {/* Objects tab — 虚拟滚动 (v0.22)；空筛选提示（切视频后陈旧 filter 命中空类） */}
        {!showFaces && (filtered.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-xs text-gray-400">该类别暂无轨迹</div>
        ) : (
          <div className="dtc-list" ref={listRef}
            style={{ position: "relative", overflowY: "auto", flex: 1, minHeight: 0 }}
            onScroll={handleListScroll}
          >
            <div style={{ height: filtered.length * ROW_STEP, position: "relative", flexShrink: 0 }}>
              {filtered.slice(startIdx, endIdx).map((t, i) => {
                const idx = startIdx + i;
                const color = colorOf(t.class_name);
                const isSel = t.track_id === selectedTrackId;
                // v0.22: 后端预计算缩略图信息（SQL 最大面积，与旧 getThumbBbox 准则一致）
                const bbox = t.best_bbox ?? null;
                const thumbTs = t.best_thumb_ts ?? Math.min(t.first_seen + 0.5, t.last_seen);
                const tUrl = t.thumbnail_url || (bbox ? thumbUrl(video.id, thumbTs, bbox) : null);
                const hasFace = !!(video?.face_enabled && t.class_name === "person" && faceData?.has_face);
                const isVehicle = ["car", "truck", "bus", "motorcycle"].includes(t.class_name);
                const plate = isVehicle ? plateByTrack.get(t.track_id) : undefined;
                return (
                  <div key={t.track_id}
                    style={{ position: "absolute", top: idx * ROW_STEP, left: 0, right: 0, height: ROW_H }}>
                    <TrackRow
                      track={t}
                      isSel={isSel}
                      video={video}
                      color={color}
                      hasFace={hasFace}
                      plate={plate}
                      tUrl={tUrl}
                      thumbTs={thumbTs}
                      bbox={bbox}
                      displayId={t.display_seq ?? t.track_id}
                      maxDuration={maxDuration}
                      isDropdownOpen={trackDropdown === t.track_id}
                      onTrackSelect={onTrackSelect}
                      onToggleDropdown={toggleDropdown}
                      onCloseDropdown={closeDropdown}
                      onHoverThumb={onHoverThumb}
                      onDownloadThumb={downloadThumb}
                      onDownloadTrack={downloadTrack}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        ))}

        {/* Faces tab */}
        {showFaces && faceData?.has_face && (
          <div className="flex-1 overflow-y-auto" ref={listRef}>
            {faceData.identities.map((ident) => (
              <div key={ident.id} className="border-b border-gray-100 last:border-b-0">
                <button
                  onClick={() => setExpandedFaceId(expandedFaceId === ident.id ? null : ident.id)}
                  className="w-full flex items-center gap-2 px-2 py-2 text-left hover:bg-gray-50 transition-colors cursor-pointer"
                >
                  <div className="face-thumb" style={{ width: 36, height: 36 }}>
                    {ident.best_thumbnail_url ? <img src={ident.best_thumbnail_url} loading="lazy" alt="" /> : <span>👤</span>}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="face-name">{ident.label} <span className="face-sim">×{ident.face_count}</span></div>
                    <div className="face-detail">{ident.first_seen.toFixed(1)}s – {ident.last_seen.toFixed(1)}s</div>
                  </div>
                  <svg className={`w-3 h-3 shrink-0 text-gray-400 transition-transform ${expandedFaceId === ident.id ? "rotate-180" : ""}`} viewBox="0 0 12 12" fill="currentColor"><path d="M3 5l3 3 3-3" /></svg>
                </button>
                {expandedFaceId === ident.id && (
                  <div className="bg-gray-50 border-t border-gray-100 px-2 py-1 text-[10px] text-gray-400">
                    出现 {ident.face_count} 次 · 平均质量 {ident.avg_quality.toFixed(2)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {showFaces && !faceData?.has_face && (
          <div className="flex-1 flex items-center justify-center"><span className="text-gray-400 text-sm">暂无人脸数据</span></div>
        )}
      </div>

      {/* Hover thumbnail preview */}
      {hoverThumb && (
        <div className="fixed z-[60] pointer-events-none rounded-xl overflow-hidden bg-transparent"
          style={{ left: hoverThumb.x, top: hoverThumb.y, width: 240, height: 240 }}>
          <img src={thumbUrl(hoverThumb.videoId, hoverThumb.ts, hoverThumb.bbox)} className="w-full h-full object-contain" alt="" />
        </div>
      )}
    </div>
  );
}
