/* ════════════════════════════════════════════════════════════
   DetectionPanel — 物体列表（视频右侧），多状态 + 缩略图 + 下拉筛选
   状态同 VideoSummaryCard：空/未开启/处理中/有数据/无数据
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useState } from "react";
import type { DetectionData, Track, VideoResponse } from "../types";
import { api, downloadFile } from "../services/api";

/* ── Class colors ── */
const CLASS_COLORS: Record<string, string> = {
  person: "#FF6B6B", car: "#4ECDC4", truck: "#FF9F43", bus: "#96CEB4",
  motorcycle: "#F7DC6F", bicycle: "#45B7D1", dog: "#FF6348", cat: "#FFA502",
  bird: "#70A1FF", horse: "#E056A0", chair: "#A29BFE", couch: "#DFE6E9",
  bed: "#636E72", "dining table": "#B2BEC3", laptop: "#6C5CE7",
  "cell phone": "#54A0FF", tv: "#0984E3", book: "#A3CB38",
  backpack: "#00B894", umbrella: "#6C5CE7", bottle: "#17E8B5", cup: "#FDA7DF",
  default: "#95A5A6",
};
const SELECTED = "#FFD700";

interface Props {
  video: VideoResponse | null;
  data: DetectionData | null;
  selectedTrackId: number | null;
  classFilter: string | null;
  onClassFilterChange: (cls: string | null) => void;
  onTrackSelect: (trackId: number, className: string, seekTo: number) => void;
}

function getThumbBbox(data: DetectionData, track: Track): { bbox: NonNullable<DetectionData["detections"][string][number]["bbox"]>; ts: number } | null {
  // 遍历 track 所有检测帧，选 bbox 面积最大的（物体离镜头最近、最清晰）
  let bestBbox: { x1: number; y1: number; x2: number; y2: number } | null = null;
  let bestArea = 0;
  let bestTs = track.first_seen;

  for (const tsKey of Object.keys(data.detections)) {
    const dets = data.detections[tsKey];
    for (const det of dets) {
      if (det.track_id === track.track_id) {
        const area = (det.bbox.x2 - det.bbox.x1) * (det.bbox.y2 - det.bbox.y1);
        if (area > bestArea) {
          bestArea = area;
          bestBbox = det.bbox;
          bestTs = parseFloat(tsKey);
        }
      }
    }
  }

  return bestBbox ? { bbox: bestBbox, ts: bestTs } : null;
}

function thumbUrl(videoId: string, ts: number, bbox: { x1: number; y1: number; x2: number; y2: number }) {
  return `/api/v1/videos/${videoId}/detection/thumbnail?timestamp=${ts}&x1=${bbox.x1}&y1=${bbox.y1}&x2=${bbox.x2}&y2=${bbox.y2}`;
}

const CONTAINER = "w-[220px] card-surface rounded-2xl p-3 border border-gray-200/60 flex flex-col h-full";

export function DetectionPanel({ video, data, selectedTrackId, classFilter, onClassFilterChange, onTrackSelect }: Props) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [trackDropdown, setTrackDropdown] = useState<number | null>(null);
  const [downloadingTid, setDownloadingTid] = useState<number | null>(null);
  const [hoverThumb, setHoverThumb] = useState<{ videoId: string; ts: number; bbox: { x1: number; y1: number; x2: number; y2: number }; x: number; y: number } | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Scroll selected track into view
  useEffect(() => {
    if (selectedTrackId == null || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-track-id="${selectedTrackId}"]`);
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selectedTrackId]);

  // ── No video ──
  if (!video) {
    return (
      <div className={CONTAINER}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">物体检测</h3>
        <div className="flex-1 flex flex-col items-center justify-center gap-2">
          <svg className="w-8 h-8 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
            <rect x="3" y="3" width="18" height="18" rx="3" />
            <circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
          </svg>
          <span className="text-gray-400 text-sm">选择视频后查看</span>
        </div>
      </div>
    );
  }

  // ── Detection not enabled ──
  if (!video.detection_enabled && video.status === "completed") {
    return (
      <div className={CONTAINER}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">物体检测</h3>
        <div className="flex-1 flex flex-col items-center justify-center gap-1 opacity-50">
          <span className="text-gray-400 text-sm">检测功能未开启</span>
          <span className="text-xs text-gray-300">请在参数设置中启用「物体检测」</span>
        </div>
      </div>
    );
  }

  // ── Processing / pending ──
  if (video.status === "processing" || video.status === "pending") {
    return (
      <div className={CONTAINER}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">物体检测</h3>
        <div className="flex-1 flex items-center">
          <div className="animate-pulse space-y-2.5 w-full">
            <div className="h-3 bg-gray-200 rounded w-2/3" />
            <div className="flex gap-2">
              <div className="h-10 w-10 bg-gray-200 rounded-md" />
              <div className="flex-1 space-y-1.5">
                <div className="h-3 bg-gray-200 rounded w-3/4" />
                <div className="h-2.5 bg-gray-200 rounded w-1/2" />
              </div>
            </div>
            <div className="flex gap-2">
              <div className="h-10 w-10 bg-gray-200 rounded-md" />
              <div className="flex-1 space-y-1.5">
                <div className="h-3 bg-gray-200 rounded w-3/4" />
                <div className="h-2.5 bg-gray-200 rounded w-1/2" />
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Completed but no data ──
  if (!data?.has_detection || !data.tracks?.length) {
    return (
      <div className={CONTAINER}>
        <h3 className="font-bold text-gray-900 text-lg mb-2">物体检测</h3>
        <div className="flex-1 flex items-center justify-center">
          <span className="text-gray-400 text-sm">暂无检测数据</span>
        </div>
      </div>
    );
  }

  // ── Has data: full panel ──
  const tracks = data.tracks;
  const classCounts: Record<string, number> = {};
  for (const t of tracks) classCounts[t.class_name] = (classCounts[t.class_name] || 0) + 1;
  const classEntries = Object.entries(classCounts).sort((a, b) => b[1] - a[1]);

  const filtered = classFilter ? tracks.filter((t) => t.class_name === classFilter) : tracks;
  const isAll = classFilter === null;
  const activeClass = isAll ? null : classFilter;
  const activeColor = activeClass ? (CLASS_COLORS[activeClass] ?? CLASS_COLORS.default) : "#6B7280";

  return (
    <div className={CONTAINER} style={{ padding: 0 }}>
      {/* Header */}
      <div className="px-3 pt-3 pb-2 border-b border-gray-100/60 shrink-0">
        <h3 className="font-bold text-gray-900 text-lg mb-2">物体检测</h3>
        {/* Dropdown — skip when only 1 class */}
        {classEntries.length > 1 ? (
        <div className="relative">
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="w-full flex items-center gap-1.5 px-2 py-1.5 text-[11px] font-medium rounded-md transition-colors hover:bg-white/40"
            style={isAll
              ? { background: "rgba(107,114,128,0.08)", color: "#6B7280", border: "1px solid rgba(107,114,128,0.2)" }
              : { background: `${activeColor}15`, color: "#1F2937", border: `1px solid ${activeColor}30` }}
          >
            {isAll ? null : <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: activeColor! }} />}
            <span className="flex-1 text-left truncate">{isAll ? `全部 · ${tracks.length}` : `${activeClass} × ${classCounts[activeClass!] || 0}`}</span>
            <svg className={`w-3 h-3 shrink-0 transition-transform ${dropdownOpen ? "rotate-180" : ""}`} viewBox="0 0 12 12" fill="currentColor">
              <path d="M3 5l3 3 3-3" />
            </svg>
          </button>
          {dropdownOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setDropdownOpen(false)} />
              <div className="absolute top-full left-0 right-0 mt-1 bg-white rounded-lg shadow-lg border border-gray-200 z-20 overflow-hidden">
                <button onClick={() => { onClassFilterChange(null); setDropdownOpen(false); }}
                  className={`w-full text-left px-2.5 py-1.5 text-[11px] hover:bg-gray-50 ${isAll ? "font-semibold text-gray-800 bg-gray-50" : "text-gray-600"}`}>
                  全部 ({tracks.length})
                </button>
                {classEntries.map(([cls, count]) => {
                  const c = CLASS_COLORS[cls] ?? CLASS_COLORS.default;
                  return (
                    <button key={cls} onClick={() => { onClassFilterChange(cls); setDropdownOpen(false); }}
                      className={`w-full flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] hover:bg-gray-50 ${classFilter === cls ? "font-semibold bg-gray-50" : "text-gray-600"}`}>
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: c }} />{cls} × {count}
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>
        ) : (
          <span className="text-[11px] font-medium"
                style={{ color: CLASS_COLORS[classEntries[0][0]] ?? CLASS_COLORS.default }}>
            {classEntries[0][0]} × {classEntries[0][1]}
          </span>
        )}
      </div>

      {/* Track list */}
      <div className="flex-1 overflow-y-auto custom-scrollbar" ref={listRef}>
        {filtered.map((t) => {
          const color = CLASS_COLORS[t.class_name] ?? CLASS_COLORS.default;
          const isSel = t.track_id === selectedTrackId;
          const thumbResult = getThumbBbox(data, t);
          const bbox = thumbResult?.bbox ?? null;
          const thumbTs = thumbResult?.ts ?? Math.min(t.first_seen + 0.5, t.last_seen);
          return (
            <button
              key={t.track_id}
              data-track-id={t.track_id}
              onClick={() => onTrackSelect(t.track_id, t.class_name, t.first_seen)}
              className={`w-full flex items-center gap-2 px-3 py-3 text-left transition-colors hover:bg-gray-50/60 border-b border-gray-100/40 last:border-b-0 relative ${isSel ? "bg-amber-50" : ""}`}
              style={isSel ? { boxShadow: "inset 3px 0 0 #FFD700" } : undefined}
            >
              {bbox ? (
                <div className="w-16 h-16 rounded-md shrink-0 overflow-hidden bg-gray-100 flex items-center justify-center cursor-pointer"
                     style={{ border: isSel ? `1.5px solid ${SELECTED}` : "1px solid rgba(0,0,0,0.06)" }}
                     onMouseEnter={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHoverThumb({ videoId: video.id, ts: thumbTs, bbox, x: r.right + 8, y: r.top - 40 }); }}
                     onMouseLeave={() => setHoverThumb(null)}>
                  <img src={thumbUrl(video.id, thumbTs, bbox)} loading="lazy" className="w-full h-full object-contain" alt="" />
                </div>
              ) : (
                <span className="w-16 h-16 rounded-md shrink-0 flex items-center justify-center" style={{ background: `${color}15` }}>
                  <span className="w-4 h-4 rounded-full" style={{ background: isSel ? SELECTED : color }} />
                </span>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1">
                  <span className={`text-[11px] truncate ${isSel ? "font-bold text-amber-800" : "font-semibold text-gray-800"}`}>{t.class_name}</span>
                  <span className={`text-[10px] shrink-0 ${isSel ? "text-amber-600 font-medium" : "text-gray-400"}`}>#{t.track_id}</span>
                </div>
                <div className="mt-0.5">
                  <span className={`text-[10px] font-mono ${isSel ? "text-amber-600" : "text-gray-400"}`}>{t.first_seen.toFixed(1)}s–{t.last_seen.toFixed(1)}s</span>
                </div>
              </div>
              {isSel && <svg className="w-3 h-3 shrink-0" viewBox="0 0 12 12" fill={SELECTED}><path d="M4 3l4 3-4 3V3z" /></svg>}
              {/* Download button */}
              <div className="relative shrink-0">
                <button
                  onClick={(e) => { e.stopPropagation(); setTrackDropdown(trackDropdown === t.track_id ? null : t.track_id); }}
                  className="w-6 h-6 rounded-md flex items-center justify-center text-gray-300 hover:text-blue-500 hover:bg-blue-50 transition-all"
                  title="导出"
                >
                  {downloadingTid === t.track_id ? (
                    <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  ) : (
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                      <polyline points="7 10 12 15 17 10" />
                      <line x1="12" y1="15" x2="12" y2="3" />
                    </svg>
                  )}
                </button>
                {trackDropdown === t.track_id && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setTrackDropdown(null)} />
                    <div className="absolute right-0 top-full mt-1 bg-white rounded-lg shadow-lg border border-gray-200 z-20 overflow-hidden min-w-[140px]">
                      <button
                        onClick={(e) => { e.stopPropagation(); setTrackDropdown(null);
                          window.open(api.getTrackThumbnailUrl(video.id, t.track_id), "_blank"); }}
                        className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                      >
                        <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                        导出缩略图
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setTrackDropdown(null);
                          window.open(api.getTrackExportUrl(video.id, t.track_id, true), "_blank"); }}
                        className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                      >
                        <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>
                        导出track视频
                      </button>
                    </div>
                  </>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Hover thumbnail preview */}
      {hoverThumb && (
        <div
          className="fixed z-[60] pointer-events-none rounded-xl overflow-hidden bg-transparent"
          style={{ left: hoverThumb.x, top: hoverThumb.y, width: 240, height: 240 }}
        >
          <img
            src={thumbUrl(hoverThumb.videoId, hoverThumb.ts, hoverThumb.bbox)}
            className="w-full h-full object-contain"
            alt=""
          />
        </div>
      )}
    </div>
  );
}

/* ── Timestamp formatting for filenames (mirrors backend format_ts) ── */
function formatTs(sec: number): string {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return `${String(h).padStart(2, "0")}h${String(m).padStart(2, "0")}m${String(s).padStart(2, "0")}s`;
}
