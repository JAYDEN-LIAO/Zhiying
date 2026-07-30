/* ════════════════════════════════════════════════════════════
   DetectionPanel — v2.0 major-card style
   Preserves: class filter, face tab, hover preview, export, plates
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useState, useMemo } from "react";
import type { DetectionData, Track, VideoResponse } from "../types";
import { api } from "../services/api";
import { colorOf, zh } from "../labels";

const SELECTED = "#FFD700";

interface Props {
  video: VideoResponse | null;
  data: DetectionData | null;
  selectedTrackId: number | null;
  classFilter: string | null;
  onClassFilterChange: (cls: string | null) => void;
  onTrackSelect: (trackId: number, className: string, seekTo: number) => void;
  faceData: import("../types").FaceData | null;
  plateData: import("../types").PlateData | null;
}

function getThumbBbox(data: DetectionData, track: Track) {
  let bestBbox: { x1: number; y1: number; x2: number; y2: number } | null = null;
  let bestArea = 0;
  let bestTs = track.first_seen;
  for (const tsKey of Object.keys(data.detections)) {
    for (const det of data.detections[tsKey]) {
      if (det.track_id === track.track_id) {
        const area = (det.bbox.x2 - det.bbox.x1) * (det.bbox.y2 - det.bbox.y1);
        if (area > bestArea) { bestArea = area; bestBbox = det.bbox; bestTs = parseFloat(tsKey); }
      }
    }
  }
  return bestBbox ? { bbox: bestBbox, ts: bestTs } : null;
}

function thumbUrl(videoId: string, ts: number, bbox: { x1: number; y1: number; x2: number; y2: number }) {
  return `/api/v1/videos/${videoId}/detection/thumbnail?timestamp=${ts}&x1=${bbox.x1}&y1=${bbox.y1}&x2=${bbox.x2}&y2=${bbox.y2}`;
}

export function DetectionPanel({ video, data, selectedTrackId, classFilter, onClassFilterChange, onTrackSelect, faceData, plateData }: Props) {
  const [showFaces, setShowFaces] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [trackDropdown, setTrackDropdown] = useState<number | null>(null);
  const [downloadingTid, setDownloadingTid] = useState<number | null>(null);
  const [hoverThumb, setHoverThumb] = useState<{ videoId: string; ts: number; bbox: { x1: number; y1: number; x2: number; y2: number }; x: number; y: number } | null>(null);
  const [expandedFaceId, setExpandedFaceId] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const showFaceBtn = !!(video?.face_enabled && faceData?.has_face);

  useEffect(() => {
    if (selectedTrackId == null || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-track-id="${selectedTrackId}"]`);
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selectedTrackId]);

  const classLocalIds = useMemo(() => {
    const map = new Map<number, number>();
    const allTracks = data?.tracks ?? [];
    const groups = new Map<string, Array<{ track_id: number; first_seen: number }>>();
    for (const t of allTracks) {
      if (!groups.has(t.class_name)) groups.set(t.class_name, []);
      groups.get(t.class_name)!.push({ track_id: t.track_id, first_seen: t.first_seen });
    }
    for (const [, items] of groups) {
      items.sort((a, b) => a.first_seen - b.first_seen);
      items.forEach((item, idx) => map.set(item.track_id, idx + 1));
    }
    return map;
  }, [data?.tracks]);

  const plateByTrack = useMemo(() => {
    const map = new Map<number, import("../types").PlateDetectionItem>();
    if (plateData?.detections) {
      for (const p of plateData.detections) {
        const existing = map.get(p.track_id);
        if (!existing || p.confidence > existing.confidence) map.set(p.track_id, p);
      }
    }
    return map;
  }, [plateData]);

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

  /* ── Has data ── */
  const tracks = data.tracks;
  const classCounts: Record<string, number> = {};
  for (const t of tracks) classCounts[t.class_name] = (classCounts[t.class_name] || 0) + 1;
  const classEntries = Object.entries(classCounts).sort((a, b) => b[1] - a[1]);
  const filtered = classFilter ? tracks.filter((t) => t.class_name === classFilter) : tracks;
  const isAll = classFilter === null;
  const activeColor = !isAll ? (colorOf(classFilter!)) : "#6B7280";

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

      <div className="major-card-bd" style={{ padding: "6px 10px 8px" }}>
        {/* Class filter — dropdown */}
        {!showFaces && classEntries.length > 1 && (
          <div className="relative mb-2">
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
          <span className="text-[11px] font-medium" style={{ color: colorOf(classEntries[0][0]) }}>
            {zh(classEntries[0][0])} × {classEntries[0][1]}
          </span>
        )}

        {/* Objects tab */}
        {!showFaces && (
          <div className="dtc-list" ref={listRef}>
            {filtered.map((t) => {
              const color = colorOf(t.class_name);
              const isSel = t.track_id === selectedTrackId;
              const thumbResult = getThumbBbox(data, t);
              const bbox = thumbResult?.bbox ?? null;
              const thumbTs = thumbResult?.ts ?? Math.min(t.first_seen + 0.5, t.last_seen);
              const hasFace = !!(video?.face_enabled && t.class_name === "person" && faceData?.has_face);
              const isVehicle = ["car", "truck", "bus", "motorcycle"].includes(t.class_name);
              const plate = isVehicle ? plateByTrack.get(t.track_id) : undefined;
              return (
                <button
                  key={t.track_id}
                  data-track-id={t.track_id}
                  className={`dtc-item ${isSel ? "sel" : ""}`}
                  onClick={() => onTrackSelect(t.track_id, t.class_name, t.first_seen)}
                >
                  {bbox ? (
                    <div className="w-10 h-10 rounded-md shrink-0 overflow-hidden bg-gray-100 flex items-center justify-center cursor-pointer"
                         style={{ border: isSel ? `1.5px solid ${SELECTED}` : "1px solid rgba(0,0,0,0.06)" }}
                         onMouseEnter={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHoverThumb({ videoId: video.id, ts: thumbTs, bbox, x: r.right + 8, y: r.top - 40 }); }}
                         onMouseLeave={() => setHoverThumb(null)}
                    >
                      <img src={thumbUrl(video.id, thumbTs, bbox)} loading="lazy" className="w-full h-full object-contain" alt="" />
                    </div>
                  ) : (
                    <div className="dtc-dot" style={{ background: isSel ? SELECTED : color }} />
                  )}
                  <div className="dtc-info">
                    <div className="dtc-name">
                      {zh(t.class_name)}
                      <span className="dtc-id">#{classLocalIds.get(t.track_id) ?? t.track_id}</span>
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
                    <div className="dtc-time">{t.first_seen.toFixed(1)}s - {t.last_seen.toFixed(1)}s</div>
                  </div>
                  <div className="dtc-bar">
                    <div className="dtc-bar-fill" style={{ width: `${Math.min(100, ((t.last_seen - t.first_seen) / (tracks[tracks.length - 1]?.last_seen || 1)) * 100)}%`, background: isSel ? SELECTED : color }} />
                  </div>
                  {/* Export dropdown */}
                  <div className="relative shrink-0">
                    <button
                      onClick={(e) => { e.stopPropagation(); setTrackDropdown(trackDropdown === t.track_id ? null : t.track_id); }}
                      className="w-6 h-6 rounded-md flex items-center justify-center text-gray-300 hover:text-blue-500 hover:bg-blue-50 transition-all cursor-pointer"
                      title="导出"
                    >
                      {downloadingTid === t.track_id ? (
                        <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" /></svg>
                      ) : (
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                      )}
                    </button>
                    {trackDropdown === t.track_id && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setTrackDropdown(null)} />
                        <div className="absolute right-0 top-full mt-1 bg-white rounded-lg shadow-lg border border-gray-200 z-20 overflow-hidden min-w-[140px]">
                          <button onClick={(e) => { e.stopPropagation(); setTrackDropdown(null); const displayId = classLocalIds.get(t.track_id); window.open(api.getTrackThumbnailUrl(video.id, t.track_id, displayId), "_blank"); }}
                            className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2">
                            <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" /></svg>
                            导出缩略图
                          </button>
                          <button onClick={(e) => { e.stopPropagation(); setTrackDropdown(null); const displayId = classLocalIds.get(t.track_id); window.open(api.getTrackExportUrl(video.id, t.track_id, true, displayId), "_blank"); }}
                            className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 flex items-center gap-2">
                            <svg className="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" /></svg>
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
        )}

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
