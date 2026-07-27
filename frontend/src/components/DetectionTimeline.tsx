/* ════════════════════════════════════════════════════════════
   DetectionTimeline — Track 时间轴，固定高度，不挤压管线
   Show labels inside bars + time ruler + hover tooltip + class filter
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

const LANE_H = 10;
const LANE_GAP = 2;
const RULER_H = 14;
const PAD = 6;
const TIMELINE_WRAPPER_H = 160; // fixed outer height — never changes

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
  // 每条 track 独占一行 (ReID 已保证每行 = 一个唯一物体)
  const sorted = [...tracks].sort((a, b) => a.first_seen - b.first_seen);
  const assigned: TrackLane[] = sorted.map((track, i) => ({ track, lane: i }));
  const maxLane = assigned.length > 0 ? assigned.length - 1 : 0;
  return { lanes: assigned, maxLane };
}

export function DetectionTimeline({ videoRef, data, selectedTrackId, classFilter, onTrackSelect, faceData }: Props) {
  const playheadRef = useRef<HTMLDivElement>(null);
  const lanesRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef(0);
  const [hovered, setHovered] = useState<{ track: Track; x: number; y: number } | null>(null);

  const filteredTracks = useMemo(() => {
    if (!data?.tracks) return [];
    return classFilter ? data.tracks.filter((t) => t.class_name === classFilter) : data.tracks;
  }, [data?.tracks, classFilter]);

  const { lanes, maxLane } = useMemo(() => computeLanes(filteredTracks), [filteredTracks]);
  const contentH = (maxLane + 1) * (LANE_H + LANE_GAP) + PAD * 2;

  const videoDuration = videoRef.current?.duration;
  const duration = (videoDuration && videoDuration > 0 && !Number.isNaN(videoDuration))
    ? videoDuration
    : (filteredTracks.length ? filteredTracks[filteredTracks.length - 1].last_seen + 1 : 1);

  /* ── Scroll selected track into view ── */
  useEffect(() => {
    if (selectedTrackId == null || !lanesRef.current) return;
    const el = lanesRef.current.querySelector(`[data-track-id="${selectedTrackId}"]`);
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selectedTrackId]);

  /* ── Playhead ── */
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

  // Empty placeholder — same fixed height as the real timeline
  if (!data?.has_detection || filteredTracks.length === 0) {
    return (
      <div className="w-full shrink-0 mt-2 rounded-lg flex items-center justify-center"
           style={{ height: TIMELINE_WRAPPER_H, background: "rgba(0,0,0,0.55)" }}>
        <span className="text-xs text-white/25">时间轴</span>
      </div>
    );
  }

  /* ── Ruler ticks ── */
  const rulerTicks: number[] = [];
  const tickInterval = duration > 120 ? 30 : duration > 60 ? 15 : duration > 30 ? 10 : 5;
  for (let t = 0; t <= duration; t += tickInterval) rulerTicks.push(t);

  return (
    <div className="w-full shrink-0 mt-2 rounded-lg overflow-hidden" style={{ height: TIMELINE_WRAPPER_H }}>
      <div
        className="relative w-full h-full flex flex-col"
        style={{ background: "rgba(0,0,0,0.55)", backdropFilter: "blur(3px)" }}
      >
        {/* ── Time ruler ── */}
        <div className="relative shrink-0" style={{ height: RULER_H, background: "rgba(0,0,0,0.15)" }}>
          {rulerTicks.map((t) => (
            <div key={t} className="absolute top-0 flex flex-col items-center" style={{ left: `${(t / duration) * 100}%`, transform: "translateX(-50%)" }}>
              <div className="w-px bg-white/25" style={{ height: RULER_H * 0.45 }} />
              <span className="text-[8px] text-white/45 font-mono leading-none">{fmtTick(t)}</span>
            </div>
          ))}
        </div>

        {/* ── Lanes (scrollable) ── */}
        <div
          ref={lanesRef}
          className="flex-1 overflow-y-auto timeline-scroll"
          style={{ minHeight: 0 }}
        >
          <div style={{ height: Math.max(contentH, TIMELINE_WRAPPER_H - RULER_H), position: "relative" }}>
            {lanes.map(({ track, lane }) => {
              const segs = track.segments?.length
                ? track.segments
                : [{ start: track.first_seen, end: track.last_seen }];
              const color = CLASS_COLORS[track.class_name] ?? CLASS_COLORS.default;
              const isSel = track.track_id === selectedTrackId;
              return segs.map((seg, si) => {
                const leftPct = (seg.start / duration) * 100;
                const wPct = Math.max(((seg.end - seg.start) / duration) * 100, 0.2);
                return (
                  <div
                    key={`${track.track_id}-${si}`}
                    data-track-id={track.track_id}
                    onClick={(e) => {
                      const isSame = track.track_id === selectedTrackId;
                      if (isSame) {
                        const rect = e.currentTarget.getBoundingClientRect();
                        const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                        const seekTo = seg.start + ratio * (seg.end - seg.start);
                        onTrackSelect(track.track_id, track.class_name, seekTo);
                      } else {
                        onTrackSelect(track.track_id, track.class_name, seg.start);
                      }
                    }}
                    onMouseEnter={(e) => {
                      const r = e.currentTarget.getBoundingClientRect();
                      setHovered({ track, x: r.left + r.width / 2, y: r.top });
                    }}
                    onMouseLeave={() => setHovered(null)}
                    className="absolute rounded-sm cursor-pointer flex items-center overflow-hidden"
                    style={{
                      left: `${leftPct}%`, width: `${wPct}%`,
                      top: PAD + lane * (LANE_H + LANE_GAP), height: LANE_H,
                      background: isSel ? SELECTED : color, opacity: isSel ? 1 : 0.7,
                      boxShadow: isSel ? `0 0 4px ${SELECTED}99` : undefined,
                      minWidth: 3, paddingLeft: 3, paddingRight: 3,
                    }}
                  >
                    {wPct > 3 && si === 0 && (
                      <span className="text-[8px] font-medium leading-none truncate select-none"
                            style={{ color: "#fff", textShadow: "0 1px 2px rgba(0,0,0,0.6)" }}>
                        {track.class_name} #{track.track_id}
                      </span>
                    )}
                  </div>
                );
              });
            })}
          </div>
        </div>

        {/* ── Face markers (white dots on person tracks) ── */}
        {faceData?.has_face && faceData.identities.map((ident) => {
          const ts = ident.best_face_timestamp;
          if (ts == null) return null;
          const leftPct = (ts / duration) * 100;
          return (
            <div
              key={`face-${ident.id}`}
              className="absolute pointer-events-none"
              style={{ top: "50%", left: `${leftPct}%`, transform: "translate(-50%, -50%)", zIndex: 5 }}
              title={`${ident.label} · ${ts.toFixed(1)}s`}
            >
              <span className="block w-2 h-2 rounded-full bg-white border border-purple-400 shadow-sm" />
            </div>
          );
        })}

        {/* ── Playhead (full height) ── */}
        <div
          ref={playheadRef}
          className="absolute top-0 bottom-0 pointer-events-none z-10"
          style={{ left: "0%", width: 2, background: "#fff", boxShadow: "0 0 6px rgba(255,255,255,0.5)" }}
        />
      </div>

      {/* ── Hover tooltip ── */}
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
