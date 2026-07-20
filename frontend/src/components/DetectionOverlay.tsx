/* ════════════════════════════════════════════════════════════
   DetectionOverlay — Canvas overlay for bounding box rendering
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { api } from "../services/api";
import type { DetectionData, Detection, Track } from "../types";

/* ── Class-specific colors (COCO 80, visually distinct subset) ── */
const CLASS_COLORS: Record<string, string> = {
  person: "#FF6B6B",
  bicycle: "#45B7D1",
  car: "#4ECDC4",
  motorcycle: "#F7DC6F",
  airplane: "#A29BFE",
  bus: "#96CEB4",
  train: "#DDA0DD",
  truck: "#FF9F43",
  boat: "#54A0FF",
  "traffic light": "#FFD700",
  "fire hydrant": "#FF4757",
  "stop sign": "#FF6348",
  bench: "#7BED9F",
  bird: "#70A1FF",
  cat: "#FFA502",
  dog: "#FF6348",
  horse: "#E056A0",
  sheep: "#DFE6E9",
  cow: "#636E72",
  elephant: "#B2BEC3",
  bear: "#8B4513",
  zebra: "#2D3436",
  giraffe: "#FDCB6E",
  backpack: "#00B894",
  umbrella: "#6C5CE7",
  handbag: "#E17055",
  tie: "#0984E3",
  suitcase: "#00CEC9",
  frisbee: "#FAB1A0",
  skis: "#81ECEC",
  snowboard: "#74B9FF",
  "sports ball": "#A3CB38",
  kite: "#E056A0",
  skateboard: "#F8A5C2",
  "tennis racket": "#3AE374",
  bottle: "#17E8B5",
  "wine glass": "#D980FA",
  cup: "#FDA7DF",
  fork: "#B8E994",
  knife: "#B8E994",
  spoon: "#B8E994",
  bowl: "#F19066",
  banana: "#FFEAA7",
  apple: "#FF7675",
  sandwich: "#FDCB6E",
  orange: "#FFA502",
  broccoli: "#7BED9F",
  carrot: "#FF9F43",
  "hot dog": "#E17055",
  pizza: "#FDCB6E",
  donut: "#FAB1A0",
  cake: "#E056A0",
  chair: "#A29BFE",
  couch: "#DFE6E9",
  "potted plant": "#00B894",
  bed: "#636E72",
  "dining table": "#B2BEC3",
  toilet: "#DFE6E9",
  tv: "#0984E3",
  laptop: "#6C5CE7",
  mouse: "#00CEC9",
  remote: "#FDCB6E",
  keyboard: "#74B9FF",
  "cell phone": "#54A0FF",
  microwave: "#FFEAA7",
  oven: "#FF9F43",
  toaster: "#E17055",
  sink: "#B2BEC3",
  refrigerator: "#81ECEC",
  book: "#A3CB38",
  clock: "#F8A5C2",
  vase: "#D980FA",
  scissors: "#B8E994",
  "teddy bear": "#FDA7DF",
  "hair drier": "#FAB1A0",
  toothbrush: "#17E8B5",
  default: "#95A5A6",
};

const SELECTED_COLOR = "#FFD700"; // gold
const TRACK_INFO_HEIGHT = 32;

interface DetectionOverlayProps {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  videoId: string;
  enabled: boolean;
}

export function DetectionOverlay({ videoRef, videoId, enabled }: DetectionOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [data, setData] = useState<DetectionData | null>(null);
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [tracked, setTracked] = useState<{ class_name: string; track_id: number } | null>(null);
  const rafRef = useRef<number>(0);
  const playheadRef = useRef<HTMLDivElement>(null);

  /* ── Compute track lanes (greedy, avoid overlap) ── */
  const trackLanes = useMemo(() => {
    if (!data?.tracks?.length) return { lanes: [] as { track: Track; lane: number }[], maxLane: 0 };
    const sorted = [...data.tracks].sort((a, b) => a.first_seen - b.first_seen);
    const assigned: { track: Track; lane: number }[] = [];
    for (const track of sorted) {
      let lane = 0;
      for (const { track: existing, lane: existingLane } of assigned) {
        if (track.first_seen < existing.last_seen && track.last_seen > existing.first_seen) {
          lane = Math.max(lane, existingLane + 1);
        }
      }
      assigned.push({ track, lane });
    }
    const maxLane = assigned.length > 0 ? Math.max(...assigned.map((l) => l.lane), 0) : 0;
    return { lanes: assigned, maxLane };
  }, [data?.tracks]);

  /* ── Fetch detection data on mount ── */
  useEffect(() => {
    if (!enabled || !videoId) {
      setData(null);
      return;
    }
    api.fetchDetectionData(videoId)
      .then((d) => setData(d))
      .catch(() => setData(null));
  }, [videoId, enabled]);

  /* ── Animate callback ── */
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video || !data?.has_detection) {
      rafRef.current = requestAnimationFrame(draw);
      return;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // 每帧自同步 canvas 尺寸：从 video 的 DOM 测量值直接拷贝，无异步偏差
    const rect = video.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
      rafRef.current = requestAnimationFrame(draw);
      return;
    }
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const cw = rect.width;
    const ch = rect.height;

    ctx.clearRect(0, 0, cw, ch);

    // object-fit: contain — 计算视频实际显示区域（含黑边偏移）
    const videoW = video.videoWidth || cw;
    const videoH = video.videoHeight || ch;
    const videoAspect = videoW / videoH;
    const containerAspect = cw / ch;

    let displayW: number, displayH: number, offsetX: number, offsetY: number;
    if (videoAspect > containerAspect) {
      displayW = cw;
      displayH = cw / videoAspect;
      offsetX = 0;
      offsetY = (ch - displayH) / 2;
    } else {
      displayH = ch;
      displayW = ch * videoAspect;
      offsetX = (cw - displayW) / 2;
      offsetY = 0;
    }

    const currentTime = video.currentTime;
    const step = 0.1; // 0.1s granularity to match API key (10fps detection)
    const floor = Math.floor(currentTime / step) * step;
    const ceil = Math.ceil(currentTime / step) * step;
    const t = (currentTime - floor) / (ceil - floor || step); // interpolation factor 0..1

    const floorKey = floor.toFixed(1);
    const ceilKey = ceil.toFixed(1);

    const floorDets = data.detections[floorKey] ?? [];
    const ceilDets = data.detections[ceilKey] ?? [];

    // Match by track_id across adjacent frames, interpolate
    const floorMap = new Map<number, Detection>();
    for (const d of floorDets) floorMap.set(d.track_id, d);
    const ceilMap = new Map<number, Detection>();
    for (const d of ceilDets) ceilMap.set(d.track_id, d);

    const interpolated: (Detection & { opacity?: number })[] = [];

    for (const [tid, fDet] of floorMap) {
      const cDet = ceilMap.get(tid);
      if (cDet) {
        interpolated.push({
          track_id: tid,
          class_name: fDet.class_name,
          bbox: {
            x1: fDet.bbox.x1 + (cDet.bbox.x1 - fDet.bbox.x1) * t,
            y1: fDet.bbox.y1 + (cDet.bbox.y1 - fDet.bbox.y1) * t,
            x2: fDet.bbox.x2 + (cDet.bbox.x2 - fDet.bbox.x2) * t,
            y2: fDet.bbox.y2 + (cDet.bbox.y2 - fDet.bbox.y2) * t,
          },
        });
      } else {
        // Track only in floor frame → show at reduced opacity
        interpolated.push({ ...fDet, opacity: 0.35 });
      }
    }

    // ── Draw motion trails (behind bboxes) ──
    const TRAIL_DURATION = 2.0; // seconds of trail history
    const TRAIL_STEP = 0.1;     // match detection interval
    const MAX_GAP = 3;           // consecutive missed frames = track disappeared

    for (const det of interpolated) {
      const color = CLASS_COLORS[det.class_name] ?? CLASS_COLORS.default;
      const isSelected = det.track_id === selectedTrackId;

      // Current bbox center (connection point)
      const curCx = offsetX + ((det.bbox.x1 + det.bbox.x2) / 2) * displayW;
      const curCy = offsetY + ((det.bbox.y1 + det.bbox.y2) / 2) * displayH;

      // Collect trail points walking backwards in time
      const points: { x: number; y: number }[] = [{ x: curCx, y: curCy }];
      let gapCount = 0;
      for (let step = 1; step <= TRAIL_DURATION / TRAIL_STEP; step++) {
        const tKey = (currentTime - step * TRAIL_STEP).toFixed(1);
        const pastDets = data.detections[tKey];
        if (!pastDets) { gapCount++; if (gapCount > MAX_GAP) break; continue; }
        const past = pastDets.find((d) => d.track_id === det.track_id);
        if (!past) { gapCount++; if (gapCount > MAX_GAP) break; continue; }
        gapCount = 0;
        points.push({
          x: offsetX + ((past.bbox.x1 + past.bbox.x2) / 2) * displayW,
          y: offsetY + ((past.bbox.y1 + past.bbox.y2) / 2) * displayH,
        });
      }

      if (points.length < 2) continue;

      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        ctx.lineTo(points[i].x, points[i].y);
      }
      ctx.strokeStyle = isSelected ? SELECTED_COLOR : color;
      ctx.lineWidth = isSelected ? 1.8 : 1.2;
      ctx.globalAlpha = isSelected ? 0.45 : 0.3;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.stroke();
    }
    ctx.globalAlpha = 1.0;

    // Draw each bbox (on top of trails)
    for (const det of interpolated) {
      const isSelected = det.track_id === selectedTrackId;
      const color = CLASS_COLORS[det.class_name] ?? CLASS_COLORS.default;

      const x = offsetX + det.bbox.x1 * displayW;
      const y = offsetY + det.bbox.y1 * displayH;
      const w = (det.bbox.x2 - det.bbox.x1) * displayW;
      const h = (det.bbox.y2 - det.bbox.y1) * displayH;

      if (w < 2 || h < 2) continue; // skip tiny bboxes

      const alpha = isSelected ? 1.0 : (det.opacity ?? 0.65);

      // Fill
      ctx.globalAlpha = isSelected ? 0.25 : 0.12;
      ctx.fillStyle = isSelected ? SELECTED_COLOR : color;
      ctx.fillRect(x, y, w, h);

      // Border
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = isSelected ? SELECTED_COLOR : color;
      ctx.lineWidth = isSelected ? 2.5 : 1.5;
      ctx.strokeRect(x, y, w, h);

      // Label
      if (isSelected || w > 40) {
        ctx.globalAlpha = alpha;
        const label = det.class_name;
        const fontSize = Math.max(10, Math.min(13, h * 0.35));
        ctx.font = `${fontSize}px system-ui, sans-serif`;
        const textW = ctx.measureText(label).width + 6;
        const labelH = fontSize + 4;
        const labelY = y - labelH > 0 ? y - labelH : y;

        ctx.fillStyle = isSelected ? SELECTED_COLOR : color;
        ctx.fillRect(x, labelY, textW, labelH);
        ctx.fillStyle = isSelected ? "#1a1a1a" : "#fff";
        ctx.fillText(label, x + 3, labelY + fontSize - 1);
      }
    }

    ctx.globalAlpha = 1.0;

    // Update playhead position (direct DOM, no React re-render)
    if (playheadRef.current && video.duration > 0) {
      playheadRef.current.style.left = `${(currentTime / video.duration) * 100}%`;
    }

    rafRef.current = requestAnimationFrame(draw);
  }, [data, selectedTrackId, videoRef]);

  /* ── Start / stop render loop ── */
  useEffect(() => {
    if (!data?.has_detection) return;
    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [data, draw]);

  /* ── object-fit 坐标反算：canvas 坐标 → 视频帧归一化坐标 ── */
  const toFrameCoord = useCallback(
    (clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
      const video = videoRef.current;
      if (!canvas || !video) return null;

      const rect = canvas.getBoundingClientRect();
      // canvas 内坐标（0~1）
      const mx = (clientX - rect.left) / rect.width;
      const my = (clientY - rect.top) / rect.height;

      // object-fit: contain → 反算视频帧坐标
      const cw = rect.width;
      const ch = rect.height;
      const vw = video.videoWidth || cw;
      const vh = video.videoHeight || ch;
      const va = vw / vh;
      const ca = cw / ch;
      let dw: number, dh: number, ox: number, oy: number;
      if (va > ca) { dw = cw; dh = cw / va; ox = 0; oy = (ch - dh) / 2; }
      else         { dh = ch; dw = ch * va; ox = (cw - dw) / 2; oy = 0; }

      const fx = (mx * cw - ox) / dw;
      const fy = (my * ch - oy) / dh;
      return { fx, fy, ox, oy, dw, dh };
    },
    [videoRef],
  );

  /* ── Click hit-testing ── */
  const handleClick = useCallback(
    (e: MouseEvent) => {
      if (!data?.has_detection) return;
      const fc = toFrameCoord(e.clientX, e.clientY);
      if (!fc || fc.fx < 0 || fc.fx > 1 || fc.fy < 0 || fc.fy > 1) {
        setSelectedTrackId(null);
        setTracked(null);
        return;
      }

      const video = videoRef.current;
      const currentTime = video?.currentTime ?? 0;
      const tsKey = (Math.round(currentTime * 10) / 10).toFixed(1);
      const dets = data.detections[tsKey] ?? [];

      let best: Detection | null = null;
      let bestArea = Infinity;
      for (const d of dets) {
        const { x1, y1, x2, y2 } = d.bbox;
        if (fc.fx >= x1 && fc.fx <= x2 && fc.fy >= y1 && fc.fy <= y2) {
          const area = (x2 - x1) * (y2 - y1);
          if (area < bestArea) { bestArea = area; best = d; }
        }
      }

      if (best) {
        setSelectedTrackId(best.track_id);
        setTracked({ class_name: best.class_name, track_id: best.track_id });
      } else {
        setSelectedTrackId(null);
        setTracked(null);
      }
    },
    [data, videoRef, toFrameCoord],
  );

  /* ── Mouse-move: 悬停 bbox 时十字光标 ── */
  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      const parent = canvasRef.current?.parentElement;
      if (!data?.has_detection) { if (parent) parent.style.cursor = "default"; return; }

      const fc = toFrameCoord(e.clientX, e.clientY);
      if (!fc || fc.fx < 0 || fc.fx > 1 || fc.fy < 0 || fc.fy > 1) {
        if (parent) parent.style.cursor = "default";
        return;
      }

      const video = videoRef.current;
      const currentTime = video?.currentTime ?? 0;
      const tsKey = (Math.round(currentTime * 10) / 10).toFixed(1);
      const dets = data.detections[tsKey] ?? [];

      const hit = dets.some(
        (d) => fc.fx >= d.bbox.x1 && fc.fx <= d.bbox.x2 && fc.fy >= d.bbox.y1 && fc.fy <= d.bbox.y2,
      );
      if (parent) parent.style.cursor = hit ? "crosshair" : "default";
    },
    [data, videoRef, toFrameCoord],
  );

  /* ── 事件绑定到父容器（冒泡穿透 canvas + video）── */
  useEffect(() => {
    const parent = canvasRef.current?.parentElement;
    if (!parent || !data?.has_detection) return;

    parent.addEventListener("click", handleClick);
    parent.addEventListener("mousemove", handleMouseMove);
    return () => {
      parent.removeEventListener("click", handleClick);
      parent.removeEventListener("mousemove", handleMouseMove);
      parent.style.cursor = "";
    };
  }, [data, handleClick, handleMouseMove]);

  /* ── Render ── */
  if (!enabled || !data?.has_detection) return null;

  return (
    <>
      <canvas
        ref={canvasRef}
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          pointerEvents: "none",
          zIndex: 0,
        }}
      />
      {/* Track timeline */}
      {data.tracks.length > 0 && (() => {
        const LANE_H = 6;
        const LANE_GAP = 1;
        const PAD = 4;
        const TIMELINE_H = Math.min((trackLanes.maxLane + 1) * (LANE_H + LANE_GAP) + PAD * 2, 48);
        const duration = videoRef.current?.duration ?? (data.tracks[data.tracks.length - 1]?.last_seen + 1 || 1);

        return (
          <div
            style={{
              position: "absolute",
              bottom: tracked ? TRACK_INFO_HEIGHT + 4 : 4,
              left: 8,
              right: 8,
              height: TIMELINE_H,
              background: "rgba(0,0,0,0.55)",
              borderRadius: 6,
              overflow: "hidden",
              zIndex: 2,
              backdropFilter: "blur(3px)",
            }}
          >
            {/* Track bars */}
            {trackLanes.lanes.map(({ track, lane }) => {
              const leftPct = (track.first_seen / duration) * 100;
              const widthPct = Math.max(((track.last_seen - track.first_seen) / duration) * 100, 0.3);
              const color = CLASS_COLORS[track.class_name] ?? CLASS_COLORS.default;
              const isSel = track.track_id === selectedTrackId;
              return (
                <div
                  key={track.track_id}
                  onClick={() => {
                    if (videoRef.current) {
                      videoRef.current.currentTime = track.first_seen;
                    }
                    setSelectedTrackId(track.track_id);
                    setTracked({ class_name: track.class_name, track_id: track.track_id });
                  }}
                  title={`${track.class_name} #${track.track_id} · ${track.frame_count} 帧 · ${track.first_seen.toFixed(1)}s–${track.last_seen.toFixed(1)}s`}
                  style={{
                    position: "absolute",
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    top: PAD + lane * (LANE_H + LANE_GAP),
                    height: LANE_H,
                    background: isSel ? SELECTED_COLOR : color,
                    opacity: isSel ? 1 : 0.65,
                    borderRadius: 1.5,
                    cursor: "pointer",
                    transition: "opacity 0.15s",
                    boxShadow: isSel ? `0 0 4px ${SELECTED_COLOR}80` : undefined,
                  }}
                />
              );
            })}
            {/* Playhead */}
            <div
              ref={playheadRef}
              style={{
                position: "absolute",
                left: "0%",
                top: 0,
                bottom: 0,
                width: 2,
                background: "#fff",
                zIndex: 3,
                boxShadow: "0 0 3px rgba(255,255,255,0.5)",
                pointerEvents: "none",
              }}
            />
          </div>
        );
      })()}
      {/* Track info bar */}
      {tracked && (
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: TRACK_INFO_HEIGHT,
            background: "rgba(0,0,0,0.75)",
            color: "#FFD700",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            fontSize: 12,
            fontFamily: "system-ui, sans-serif",
            zIndex: 3,
            backdropFilter: "blur(4px)",
          }}
        >
          <span style={{ color: "#fff", opacity: 0.7 }}>选中:</span>
          <span style={{ fontWeight: 600 }}>{tracked.class_name}</span>
          <span style={{ color: "#fff", opacity: 0.5 }}>·</span>
          <span style={{ opacity: 0.8 }}>track #{tracked.track_id}</span>
          <button
            onClick={() => { setSelectedTrackId(null); setTracked(null); }}
            style={{
              marginLeft: 8,
              background: "rgba(255,255,255,0.15)",
              border: "none",
              color: "#fff",
              padding: "2px 10px",
              borderRadius: 4,
              cursor: "pointer",
              fontSize: 11,
            }}
          >
            取消
          </button>
        </div>
      )}
    </>
  );
}
