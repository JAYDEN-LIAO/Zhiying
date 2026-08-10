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

const SELECTED = "#FFD700";  // 金色，与视频框(DetectionOverlay)/时间轴(DetectionTimeline)选中色统一

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
  identityLabel: string | null;  // v0.30: person track 归属的身份标签（替代 👤）
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
  track, isSel, video, color, hasFace, identityLabel, plate, tUrl, thumbTs, bbox,
  displayId, maxDuration, isDropdownOpen,
  onTrackSelect, onToggleDropdown, onCloseDropdown, onHoverThumb,
  onDownloadThumb, onDownloadTrack,
}: TrackRowProps) {
  return (
    <div
      role="button"
      tabIndex={0}
      data-track-id={track.track_id}
      className={`dtc-item${isSel ? " sel" : ""}`}
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
             style={{ border: "1px solid rgba(0,0,0,0.06)" }}  // 缩略图边框保持无色默认，选中标识由整行金色高亮承担
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
          {identityLabel && <span className="dtc-face" title="身份">{identityLabel}</span>}
          {hasFace && !identityLabel && <span className="dtc-face" title="检测到人脸">脸</span>}
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
  // hover 浮层：物体 = {videoId,ts,bbox} 现截视频；人脸 = {src} 直接显示已存缩略图
  const [hoverThumb, setHoverThumb] = useState<
    | { videoId: string; ts: number; bbox: { x1: number; y1: number; x2: number; y2: number }; x: number; y: number }
    | { src: string; x: number; y: number }
    | null
  >(null);
  const [expandedFaceId, setExpandedFaceId] = useState<number | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(400);
  const listRef = useRef<HTMLDivElement>(null);
  const scrollRaf = useRef(0);

  const showFaceBtn = !!(video?.face_enabled && faceData?.has_face);

  // v0.30: 切换视频时若新视频无脸（无"人脸"按钮），自动退回"物体检测"视图。
  // 否则组件复用保留 showFaces=true → 停在"人脸"视图显示"0人"（无该视频无人品类）。
  useEffect(() => {
    if (!showFaceBtn && showFaces) {
      setShowFaces(false);
    }
  }, [showFaceBtn, showFaces]);

  // v0.30: track_id → 身份标签（person track 条目显示"人物A"替代 👤，与车牌对称）
  const trackToLabel = useMemo(() => {
    const m = new Map<number, string>();
    if (faceData?.identities && faceData.track_to_identity) {
      const idToLabel = new Map(faceData.identities.map((i) => [i.id, i.label]));
      for (const [tid, { identity_id }] of Object.entries(faceData.track_to_identity)) {
        const label = idToLabel.get(identity_id);
        if (label) m.set(Number(tid), label);
      }
    }
    return m;
  }, [faceData]);

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

  /* ── 选中滚动（v0.30 增强）：页内不跳、页外丝滑居中、目标位置上移 1.5 行 ──
     实现要点：
     - 需求3：选中项已在可视区 → 完全不滚动（页内直接点击不再跳中段）
     - 需求4：目标比"纯居中"再上移 1.5 行（被选物体停在栏偏上，视觉更舒服）
     - 需求1：用 scrollTo({behavior:"smooth"}) 丝滑滚动；state 由 scroll 事件自然驱动
       （smooth 动画持续产生 scroll 事件，handleListScroll 的 rAF 会持续更新 scrollTop，
       虚拟窗口跟随 DOM，无抖动）。动画结束后用 timeout 兜底校正一次，防极端场景漏更新。 */
  useEffect(() => {
    if (showFaces || selectedTrackId == null || !listRef.current) return;
    const idx = filteredRef.current.findIndex((t) => t.track_id === selectedTrackId);
    if (idx < 0) return;
    const el = listRef.current;
    const itemTop = idx * ROW_STEP;
    const viewH = el.clientHeight;

    // 需求3：与可视区有交集（哪怕只露出一部分）→ 不滚动。
    // 原"完全在区内才不跳"会让一半在页内的记录也跳中段——用户不想要。
    if (itemTop + ROW_H > el.scrollTop && itemTop < el.scrollTop + viewH) {
      return;
    }

    // 需求4：目标位置 = 物品顶边停在视口顶部往下约 1 行处（偏上，不居中）。
    // 视觉位置 = itemTop - target = ROW_H ≈ 68px，即"顶部往下一条"。
    const target = Math.max(0, itemTop - ROW_H);

    // 需求1：丝滑滚动；取消 pending rAF 避免旧回调覆盖动画中的 scrollTop state
    if (scrollRaf.current) { cancelAnimationFrame(scrollRaf.current); scrollRaf.current = 0; }
    el.scrollTo({ top: target, behavior: "smooth" });
    // 动画结束后校正 state（防 smooth 未触发 scroll 事件的极端情况）
    const t = window.setTimeout(() => {
      if (listRef.current && Math.abs(listRef.current.scrollTop - target) > 2) {
        setScrollTop(listRef.current.scrollTop);
      }
    }, 500);
    return () => window.clearTimeout(t);
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
          物体检测
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
          <span className="major-card-badge">{showFaces ? `${faceData?.identities.length ?? 0} 人` : `${tracks.length} 条`}</span>
        </div>
      </div>

      <div className="major-card-bd" style={{ padding: "6px 10px 8px", display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {/* Class filter — dropdown（v0.30: 人脸作为一类并入下拉栏，移除顶部独立按钮；
           单类别也走下拉栏，消除"人 x465"降级文本标签） */}
        {(classEntries.length > 0 || showFaceBtn) && (
          <div className="relative mb-2 shrink-0">
            <button
              onClick={() => setDropdownOpen(!dropdownOpen)}
              className="dtc-filter-btn"
            >
              {showFaces ? (
                <span><span className="dot" style={{ background: "#8b5cf6" }} />人脸</span>
              ) : isAll ? (
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
                    className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-gray-50 ${!showFaces && isAll ? "font-semibold text-gray-900" : "text-gray-600"}`}
                    onClick={() => { onClassFilterChange(null); setShowFaces(false); setDropdownOpen(false); }}
                  >
                    全部 · {tracks.length}
                  </button>
                  {classEntries.map(([cls, count]) => (
                    <button
                      key={cls}
                      className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-gray-50 ${!showFaces && classFilter === cls ? "font-semibold text-gray-900" : "text-gray-600"}`}
                      onClick={() => { onClassFilterChange(cls); setShowFaces(false); setDropdownOpen(false); }}
                    >
                      <span className="dot" style={{ background: colorOf(cls) }} />{zh(cls)} · {count}
                    </button>
                  ))}
                  {showFaceBtn && (
                    <button
                      className={`w-full text-left px-3 py-2 text-xs flex items-center gap-2 hover:bg-gray-50 border-t border-gray-100 ${showFaces ? "font-semibold text-purple-600" : "text-gray-600"}`}
                      onClick={() => { onClassFilterChange(null); setShowFaces(true); setDropdownOpen(false); }}
                    >
                      <span className="dot" style={{ background: "#8b5cf6" }} />人脸 · {faceData?.identities.length ?? 0}
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
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
                const identityLabel = t.class_name === "person" ? (trackToLabel.get(t.track_id) ?? null) : null;
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
                      identityLabel={identityLabel}
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

        {/* Faces tab（v0.30: 行样式与物体 TrackRow 统一为 dtc-item 布局） */}
        {showFaces && faceData?.has_face && (
          <div className="dtc-list" ref={listRef} style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
            {faceData.identities.map((ident) => {
              const isSel = expandedFaceId === ident.id;
              return (
                <div key={ident.id}>
                  <div
                    role="button"
                    tabIndex={0}
                    className={`dtc-item${isSel ? " sel" : ""}`}
                    onClick={() => setExpandedFaceId(isSel ? null : ident.id)}
                    onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setExpandedFaceId(isSel ? null : ident.id); } }}
                  >
                    <div className="w-10 h-10 rounded-md shrink-0 overflow-hidden bg-gray-100 flex items-center justify-center cursor-pointer"
                         style={{ border: "1px solid rgba(0,0,0,0.06)" }}
                         onMouseEnter={(e) => {
                           if (ident.best_thumbnail_url) {
                             const r = e.currentTarget.getBoundingClientRect();
                             setHoverThumb({ src: ident.best_thumbnail_url, x: r.right + 8, y: r.top - 40 });
                           }
                         }}
                         onMouseLeave={() => setHoverThumb(null)}>
                      {ident.best_thumbnail_url ? (
                        <img src={ident.best_thumbnail_url} loading="lazy" className="w-full h-full object-contain" alt="" />
                      ) : (
                        <span className="text-base text-gray-300">👤</span>
                      )}
                    </div>
                    <div className="dtc-info">
                      <div className="dtc-name">
                        {ident.label}
                        <span className="dtc-id">×{ident.face_count}</span>
                      </div>
                      <div className="dtc-time">{ident.first_seen.toFixed(1)}s – {ident.last_seen.toFixed(1)}s</div>
                    </div>
                    <svg className={`w-3 h-3 shrink-0 text-gray-400 transition-transform ${isSel ? "rotate-180" : ""}`} viewBox="0 0 12 12" fill="currentColor"><path d="M3 5l3 3 3-3" /></svg>
                  </div>
                  {isSel && (
                    <div className="px-3 py-1.5 text-[10px] text-gray-400" style={{ paddingLeft: 60 }}>
                      出现 {ident.face_count} 次 · 平均质量 {ident.avg_quality.toFixed(2)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {showFaces && !faceData?.has_face && (
          <div className="flex-1 flex items-center justify-center"><span className="text-gray-400 text-sm">暂无人脸数据</span></div>
        )}
      </div>

      {/* Hover thumbnail preview（物体 = 现截视频；人脸 = 显示已存缩略图） */}
      {hoverThumb && (
        <div className="fixed z-[60] pointer-events-none rounded-xl overflow-hidden bg-transparent"
          style={{ left: hoverThumb.x, top: hoverThumb.y, width: 240, height: 240 }}>
          {"src" in hoverThumb ? (
            <img src={hoverThumb.src} className="w-full h-full object-contain" alt="" />
          ) : (
            <img src={thumbUrl(hoverThumb.videoId, hoverThumb.ts, hoverThumb.bbox)} className="w-full h-full object-contain" alt="" />
          )}
        </div>
      )}
    </div>
  );
}
