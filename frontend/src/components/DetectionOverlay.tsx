/* ════════════════════════════════════════════════════════════
   DetectionOverlay — Canvas-only bbox + trail rendering
   State (selectedTrackId) lifted to Dashboard for cross-component sync.
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useCallback } from "react";
import type { DetectionData, Detection } from "../types";

/* ── Class-specific colors ── */
const CLASS_COLORS: Record<string, string> = {
  person: "#FF6B6B", bicycle: "#45B7D1", car: "#4ECDC4", motorcycle: "#F7DC6F",
  airplane: "#A29BFE", bus: "#96CEB4", train: "#DDA0DD", truck: "#FF9F43",
  boat: "#54A0FF", "traffic light": "#FFD700", "fire hydrant": "#FF4757",
  "stop sign": "#FF6348", bench: "#7BED9F", bird: "#70A1FF", cat: "#FFA502",
  dog: "#FF6348", horse: "#E056A0", backpack: "#00B894", umbrella: "#6C5CE7",
  handbag: "#E17055", tie: "#0984E3", suitcase: "#00CEC9",
  skis: "#81ECEC", snowboard: "#74B9FF", skateboard: "#F8A5C2",
  bottle: "#17E8B5", cup: "#FDA7DF", bowl: "#F19066",
  banana: "#FFEAA7", apple: "#FF7675", sandwich: "#FDCB6E",
  chair: "#A29BFE", couch: "#DFE6E9", bed: "#636E72",
  "dining table": "#B2BEC3", tv: "#0984E3", laptop: "#6C5CE7",
  "cell phone": "#54A0FF", remote: "#FDCB6E", keyboard: "#74B9FF",
  book: "#A3CB38", clock: "#F8A5C2", vase: "#D980FA",
  default: "#95A5A6",
};
const SELECTED_COLOR = "#FFD700";

interface Props {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  videoId: string;
  enabled: boolean;
  data: DetectionData | null;
  selectedTrackId: number | null;
  onTrackSelect: (trackId: number, className: string) => void;
}

export function DetectionOverlay({ videoRef, videoId, enabled, data, selectedTrackId, onTrackSelect }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  /* ── Draw callback: interpolation + trails + bboxes ── */
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video || !enabled || !data?.has_detection) {
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const rect = video.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
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

    // object-fit: contain calculation
    const vw = video.videoWidth || cw;
    const vh = video.videoHeight || ch;
    const va = vw / vh;
    const ca = cw / ch;
    let displayW: number, displayH: number, offsetX: number, offsetY: number;
    if (va > ca) { displayW = cw; displayH = cw / va; offsetX = 0; offsetY = (ch - displayH) / 2; }
    else         { displayH = ch; displayW = ch * va; offsetX = (cw - displayW) / 2; offsetY = 0; }

    const currentTime = video.currentTime;
    const step = 0.1;
    const floor = Math.floor(currentTime / step) * step;
    const ceil = Math.ceil(currentTime / step) * step;
    const t = (currentTime - floor) / (ceil - floor || step);

    const floorDets = data.detections[floor.toFixed(1)] ?? [];
    const ceilDets = data.detections[ceil.toFixed(1)] ?? [];

    // Build lookup maps
    const floorMap = new Map<number, Detection>();
    for (const d of floorDets) floorMap.set(d.track_id, d);
    const ceilMap = new Map<number, Detection>();
    for (const d of ceilDets) ceilMap.set(d.track_id, d);

    // Interpolate
    const interpolated: (Detection & { opacity?: number })[] = [];
    for (const [tid, fDet] of floorMap) {
      const cDet = ceilMap.get(tid);
      if (cDet) {
        interpolated.push({
          track_id: tid, class_name: fDet.class_name,
          bbox: {
            x1: fDet.bbox.x1 + (cDet.bbox.x1 - fDet.bbox.x1) * t,
            y1: fDet.bbox.y1 + (cDet.bbox.y1 - fDet.bbox.y1) * t,
            x2: fDet.bbox.x2 + (cDet.bbox.x2 - fDet.bbox.x2) * t,
            y2: fDet.bbox.y2 + (cDet.bbox.y2 - fDet.bbox.y2) * t,
          },
        });
      } else {
        interpolated.push({ ...fDet, opacity: 0.35 });
      }
    }

    // ── Trails ──
    const TRAIL_DURATION = 2.0, TRAIL_STEP = 0.1, MAX_GAP = 3;
    for (const det of interpolated) {
      const color = CLASS_COLORS[det.class_name] ?? CLASS_COLORS.default;
      const isSel = det.track_id === selectedTrackId;
      const curCx = offsetX + ((det.bbox.x1 + det.bbox.x2) / 2) * displayW;
      const curCy = offsetY + ((det.bbox.y1 + det.bbox.y2) / 2) * displayH;
      const points: { x: number; y: number }[] = [{ x: curCx, y: curCy }];
      let gapCount = 0;
      for (let s = 1; s <= TRAIL_DURATION / TRAIL_STEP; s++) {
        const tKey = (currentTime - s * TRAIL_STEP).toFixed(1);
        const pastDets = data.detections[tKey];
        if (!pastDets) { gapCount++; if (gapCount > MAX_GAP) break; continue; }
        const past = pastDets.find((d) => d.track_id === det.track_id);
        if (!past) { gapCount++; if (gapCount > MAX_GAP) break; continue; }
        gapCount = 0;
        points.push({ x: offsetX + ((past.bbox.x1 + past.bbox.x2) / 2) * displayW, y: offsetY + ((past.bbox.y1 + past.bbox.y2) / 2) * displayH });
      }
      if (points.length >= 2) {
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);
        for (let i = 1; i < points.length; i++) ctx.lineTo(points[i].x, points[i].y);
        ctx.strokeStyle = isSel ? SELECTED_COLOR : color;
        ctx.lineWidth = isSel ? 3.5 : 3.0;
        ctx.globalAlpha = isSel ? 0.75 : 0.6;
        ctx.lineCap = "round"; ctx.lineJoin = "round";
        ctx.stroke();
      }
    }
    ctx.globalAlpha = 1.0;

    // ── Bboxes ──
    for (const det of interpolated) {
      const isSel = det.track_id === selectedTrackId;
      const color = CLASS_COLORS[det.class_name] ?? CLASS_COLORS.default;
      const x = offsetX + det.bbox.x1 * displayW;
      const y = offsetY + det.bbox.y1 * displayH;
      const w = (det.bbox.x2 - det.bbox.x1) * displayW;
      const h = (det.bbox.y2 - det.bbox.y1) * displayH;
      if (w < 2 || h < 2) continue;
      const alpha = isSel ? 1.0 : (det.opacity ?? 0.65);
      ctx.globalAlpha = isSel ? 0.25 : 0.12;
      ctx.fillStyle = isSel ? SELECTED_COLOR : color;
      ctx.fillRect(x, y, w, h);
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = isSel ? SELECTED_COLOR : color;
      ctx.lineWidth = isSel ? 3.0 : 2.0;
      ctx.strokeRect(x, y, w, h);
      if (w > 24) {
        ctx.globalAlpha = alpha;
        const label = `${det.class_name} #${det.track_id}`;
        const fs = Math.max(10, Math.min(13, h * 0.35));
        ctx.font = `${fs}px system-ui, sans-serif`;
        const tw = ctx.measureText(label).width + 6;
        const lh = fs + 4;
        const ly = y - lh > 0 ? y - lh : y;
        ctx.fillStyle = isSel ? SELECTED_COLOR : color;
        ctx.fillRect(x, ly, tw, lh);
        ctx.fillStyle = isSel ? "#1a1a1a" : "#fff";
        ctx.fillText(label, x + 3, ly + fs - 1);
      }
    }
    ctx.globalAlpha = 1.0;
    rafRef.current = requestAnimationFrame(draw);
  }, [data, selectedTrackId, videoRef]);

  useEffect(() => {
    if (!data?.has_detection) return;
    rafRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafRef.current);
  }, [data, draw]);

  /* ── Coord transform ── */
  const toFrameCoord = useCallback(
    (clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
      const video = videoRef.current;
      if (!canvas || !video) return null;
      const rect = canvas.getBoundingClientRect();
      const mx = (clientX - rect.left) / rect.width;
      const my = (clientY - rect.top) / rect.height;
      const cw = rect.width, ch = rect.height;
      const vw = video.videoWidth || cw, vh = video.videoHeight || ch;
      const va = vw / vh, ca = cw / ch;
      let dw: number, dh: number, ox: number, oy: number;
      if (va > ca) { dw = cw; dh = cw / va; ox = 0; oy = (ch - dh) / 2; }
      else         { dh = ch; dw = ch * va; ox = (cw - dw) / 2; oy = 0; }
      const fx = (mx * cw - ox) / dw;
      const fy = (my * ch - oy) / dh;
      return { fx, fy };
    },
    [videoRef],
  );

  /* ── Click → select track ── */
  const handleClick = useCallback(
    (e: MouseEvent) => {
      if (!data?.has_detection) return;
      const fc = toFrameCoord(e.clientX, e.clientY);
      if (!fc || fc.fx < 0 || fc.fx > 1 || fc.fy < 0 || fc.fy > 1) {
        onTrackSelect(-1, "");
        return;
      }
      const video = videoRef.current;
      const currentTime = video?.currentTime ?? 0;
      const tsKey = (Math.round(currentTime * 10) / 10).toFixed(1);
      const dets = data.detections[tsKey] ?? [];
      let best: Detection | null = null;
      let bestArea = Infinity;
      for (const d of dets) {
        if (fc.fx >= d.bbox.x1 && fc.fx <= d.bbox.x2 && fc.fy >= d.bbox.y1 && fc.fy <= d.bbox.y2) {
          const area = (d.bbox.x2 - d.bbox.x1) * (d.bbox.y2 - d.bbox.y1);
          if (area < bestArea) { bestArea = area; best = d; }
        }
      }
      if (best) onTrackSelect(best.track_id, best.class_name);
      else onTrackSelect(-1, "");
    },
    [data, videoRef, toFrameCoord, onTrackSelect],
  );

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      const parent = canvasRef.current?.parentElement;
      if (!data?.has_detection) { if (parent) parent.style.cursor = "default"; return; }
      const fc = toFrameCoord(e.clientX, e.clientY);
      if (!fc || fc.fx < 0 || fc.fx > 1 || fc.fy < 0 || fc.fy > 1) {
        if (parent) parent.style.cursor = "default"; return;
      }
      const video = videoRef.current;
      const tsKey = (Math.round((video?.currentTime ?? 0) * 10) / 10).toFixed(1);
      const dets = data.detections[tsKey] ?? [];
      const hit = dets.some((d) => fc.fx >= d.bbox.x1 && fc.fx <= d.bbox.x2 && fc.fy >= d.bbox.y1 && fc.fy <= d.bbox.y2);
      if (parent) parent.style.cursor = hit ? "crosshair" : "default";
    },
    [data, videoRef, toFrameCoord],
  );

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

  if (!enabled || !data?.has_detection) return null;

  return (
    <canvas
      ref={canvasRef}
      style={{ position: "absolute", top: 0, left: 0, pointerEvents: "none", zIndex: 0 }}
    />
  );
}
