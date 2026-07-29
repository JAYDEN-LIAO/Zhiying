/* ════════════════════════════════════════════════════════════
   DetectionTimeline — v2.0 dark theme (mockup-dark style)
   Uses CSS classes from index.css: timeline-wrap, tl-*, etc.
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useMemo, useState } from "react";
import type { DetectionData, Track, FaceData } from "../types";

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

const LANE_H = 9;
const LANE_GAP = 5;
const RULER_H = 20;
const PAD = 5;

interface Props {
  videoId: string;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  data: DetectionData | null;
  selectedTrackId: number | null;
  classFilter: string | null;
  onTrackSelect: (trackId: number, className: string, seekTo: number) => void;
  faceData?: FaceData | null;
}

interface TrackLane { track: Track; lane: number }

function computeLanes(tracks: Track[]): { lanes: TrackLane[]; maxLane: number } {
  const sorted = [...tracks].sort((a, b) => a.first_seen - b.first_seen);
  const assigned: TrackLane[] = sorted.map((track, i) => ({ track, lane: i }));
  const maxLane = assigned.length > 0 ? assigned.length - 1 : 0;
  return { lanes: assigned, maxLane };
}

export function DetectionTimeline({ videoRef, data, selectedTrackId, classFilter, onTrackSelect, faceData }: Props) {
  const lanesRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef(0);
  const playheadRef = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState<{ track: Track; x: number; y: number } | null>(null);

  const filteredTracks = useMemo(() => {
    if (!data?.tracks) return [];
    return classFilter ? data.tracks.filter((t) => t.class_name === classFilter) : data.tracks;
  }, [data?.tracks, classFilter]);

  const { lanes, maxLane } = useMemo(() => computeLanes(filteredTracks), [filteredTracks]);

  const videoDuration = videoRef.current?.duration;
  const duration = (videoDuration && videoDuration > 0 && !Number.isNaN(videoDuration))
    ? videoDuration
    : (filteredTracks.length ? filteredTracks[filteredTracks.length - 1].last_seen + 1 : 1);

  /* ── Scroll selected into view ── */
  useEffect(() => {
    if (selectedTrackId == null || !lanesRef.current) return;
    const el = lanesRef.current.querySelector(`[data-track-id="${selectedTrackId}"]`);
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selectedTrackId]);

  /* ── Playhead rAF ── */
  useEffect(() => {
    const tick = () => {
      if (playheadRef.current && videoRef.current?.duration) {
        playheadRef.current.style.left = `${(videoRef.current.currentTime / videoRef.current.duration) * 100}%`;
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [videoRef]);

  /* ── Empty / placeholder ── */
  if (!data?.has_detection || filteredTracks.length === 0) {
    return (
      <div className="timeline-wrap" style={{ flex: 1, minHeight: 80, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span className="text-xs text-white/20">时间轴</span>
      </div>
    );
  }

  /* ── Ruler ticks ── */
  const rulerTicks: number[] = [];
  const tickInterval = duration > 120 ? 30 : duration > 60 ? 15 : duration > 30 ? 10 : 5;
  for (let t = 0; t <= duration; t += tickInterval) rulerTicks.push(t);

  return (
    <div className="timeline-wrap" style={{ flex: 1, minHeight: 80 }}>
      {/* Time ruler */}
      <div className="tl-ruler">
        {rulerTicks.map((t) => (
          <div key={t} className="tl-tick" style={{ left: `${(t / duration) * 100}%` }}>
            <div className="tl-tick-l" />
            <span className="tl-tick-t">{fmtTick(t)}</span>
          </div>
        ))}
      </div>

      {/* Lanes (scrollable) */}
      <div ref={lanesRef} className="tl-lanes">
        <div style={{ height: Math.max((maxLane + 1) * (LANE_H + LANE_GAP) + PAD * 2, 0), position: "relative" }}>
          {lanes.map(({ track, lane }) => {
            const segs = track.segments?.length ? track.segments : [{ start: track.first_seen, end: track.last_seen }];
            const color = CLASS_COLORS[track.class_name] ?? CLASS_COLORS.default;
            const isSel = track.track_id === selectedTrackId;
            return segs.map((seg, si) => {
              const leftPct = (seg.start / duration) * 100;
              const wPct = Math.max(((seg.end - seg.start) / duration) * 100, 0.2);
              return (
                <div
                  key={`${track.track_id}-${si}`}
                  data-track-id={track.track_id}
                  className="tl-track"
                  style={{
                    left: `${leftPct}%`, width: `${wPct}%`,
                    top: PAD + lane * (LANE_H + LANE_GAP), height: LANE_H,
                    background: isSel ? SELECTED : color, opacity: isSel ? 1 : 0.65,
                    boxShadow: isSel ? `0 0 4px ${SELECTED}99` : undefined,
                  }}
                  onClick={(e) => {
                    if (track.track_id === selectedTrackId) {
                      const rect = e.currentTarget.getBoundingClientRect();
                      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                      onTrackSelect(track.track_id, track.class_name, seg.start + ratio * (seg.end - seg.start));
                    } else {
                      onTrackSelect(track.track_id, track.class_name, seg.start);
                    }
                  }}
                  onMouseEnter={(e) => {
                    const r = e.currentTarget.getBoundingClientRect();
                    setHovered({ track, x: r.left + r.width / 2, y: r.top });
                  }}
                  onMouseLeave={() => setHovered(null)}
                >
                  {wPct > 3 && si === 0 && (
                    <span className="tl-track-lbl">{track.class_name} #{track.track_id}</span>
                  )}
                </div>
              );
            });
          })}
        </div>
      </div>

      {/* Face markers */}
      {faceData?.has_face && faceData.identities.map((ident) => {
        const ts = ident.best_face_timestamp;
        if (ts == null) return null;
        return (
          <div
            key={`face-${ident.id}`}
            className="tl-face"
            style={{ left: `${(ts / duration) * 100}%` }}
            title={`${ident.label} · ${ts.toFixed(1)}s`}
          />
        );
      })}

      {/* Playhead */}
      <div ref={playheadRef} className="tl-playhead" style={{ left: "0%" }} />

      {/* Hover tooltip */}
      {hovered && (
        <div
          className="fixed z-50 pointer-events-none px-2 py-1 rounded-md text-[10px] leading-relaxed shadow-lg"
          style={{
            left: hovered.x, top: hovered.y - 34, transform: "translateX(-50%)",
            background: "rgba(0,0,0,0.85)", color: "#fff", whiteSpace: "nowrap",
          }}
        >
          <span style={{ color: CLASS_COLORS[hovered.track.class_name] ?? CLASS_COLORS.default, fontWeight: 600 }}>
            {hovered.track.class_name} #{hovered.track.track_id}
          </span>
          <span className="text-white/60 ml-1.5">
            {hovered.track.frame_count}f · {hovered.track.first_seen.toFixed(1)}s–{hovered.track.last_seen.toFixed(1)}s
          </span>
        </div>
      )}
    </div>
  );
}

function fmtTick(s: number): string {
  if (s === 0) return "0";
  if (s % 60 === 0) return `${s / 60}m`;
  return `${s}`;
}
