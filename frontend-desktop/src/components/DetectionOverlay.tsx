/* ════════════════════════════════════════════════════════════
   DetectionOverlay — Canvas-only bbox + trail rendering
   Renders: YOLO detection bboxes, plate bboxes, face bboxes.
   State (selectedTrackId) lifted to Dashboard for cross-component sync.

   v0.22 (S2): 改按需区间加载（useDetectionRanges），不再持有全量 detections。
   ════════════════════════════════════════════════════════════ */

import { useEffect, useRef, useCallback } from "react";
import type { Detection } from "../types";
import { useDetectionRanges } from "../hooks/useDetectionRanges";
import { colorOf, zhLabel } from "../labels";
const SELECTED_COLOR = "#FFD700";
const HIT_PAD = 0.01;   // 点击命中 padding（归一化，约 10px@1080p / 4px@480p）—— 小目标 / 插值偏移也能点中

interface Props {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  videoId: string;
  enabled: boolean;
  hasDetection: boolean;
  selectedTrackId: number | null;
  selectedFaceTrackIds: number[];
  onTrackSelect: (trackId: number, className: string) => void;
}

export function DetectionOverlay({ videoRef, videoId, enabled, hasDetection, selectedTrackId, selectedFaceTrackIds, onTrackSelect }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);
  const pendingClickRef = useRef<{ x: number; y: number; t: number } | null>(null);
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onTrackSelectRef = useRef(onTrackSelect); onTrackSelectRef.current = onTrackSelect;
  // v0.30: 选中人脸身份的归属 person track 集合（金色高亮，draw 热路径读 ref）
  const selectedFaceRef = useRef(selectedFaceTrackIds); selectedFaceRef.current = selectedFaceTrackIds;
  const { get, version, ensure, hasLoadedRange } = useDetectionRanges(videoId, videoRef, enabled, hasDetection);

  /* ── 插值 bbox（与绘制一致）：floor/ceil 之间的线性插值。
     供 draw 绘制与 handleClick 命中共用 —— 命中目标 = 画出来的目标（所见即所点）。── */
  const interpolatedAt = useCallback((currentTime: number): (Detection & { opacity?: number })[] => {
    const step = 0.1;
    const floor = Math.floor(currentTime / step) * step;
    const ceil = Math.ceil(currentTime / step) * step;
    const t = (currentTime - floor) / (ceil - floor || step);
    const floorMap = new Map<number, Detection>();
    for (const d of get(floor)) floorMap.set(d.track_id, d);
    const ceilMap = new Map<number, Detection>();
    for (const d of get(ceil)) ceilMap.set(d.track_id, d);
    const out: (Detection & { opacity?: number })[] = [];
    for (const [tid, fDet] of floorMap) {
      const cDet = ceilMap.get(tid);
      if (cDet) {
        out.push({
          track_id: tid, class_name: fDet.class_name,
          display_seq: fDet.display_seq ?? fDet.track_id,
          bbox: {
            x1: fDet.bbox.x1 + (cDet.bbox.x1 - fDet.bbox.x1) * t,
            y1: fDet.bbox.y1 + (cDet.bbox.y1 - fDet.bbox.y1) * t,
            x2: fDet.bbox.x2 + (cDet.bbox.x2 - fDet.bbox.x2) * t,
            y2: fDet.bbox.y2 + (cDet.bbox.y2 - fDet.bbox.y2) * t,
          },
        });
      } else {
        out.push({ ...fDet, opacity: 0.35 });
      }
    }
    return out;
  }, [get]);

  /* ── Draw callback: interpolation + trails + bboxes ── */
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video || !enabled || !hasDetection) {
      return;
    }
    // ★ Draw current frame then only schedule next frame when playing
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
    // 插值统一走 interpolatedAt —— draw 与 handleClick 共用同一套 bbox
    const interpolated = interpolatedAt(currentTime);

    // ── Trails ──
    const TRAIL_DURATION = 2.0, TRAIL_STEP = 0.1, MAX_GAP = 3;
    for (const det of interpolated) {
      const color = colorOf(det.class_name);
      const isSel = det.track_id === selectedTrackId || selectedFaceRef.current.includes(det.track_id);
      const curCx = offsetX + ((det.bbox.x1 + det.bbox.x2) / 2) * displayW;
      const curCy = offsetY + ((det.bbox.y1 + det.bbox.y2) / 2) * displayH;
      const points: { x: number; y: number }[] = [{ x: curCx, y: curCy }];
      let gapCount = 0;
      for (let s = 1; s <= TRAIL_DURATION / TRAIL_STEP; s++) {
        const pastDets = get(currentTime - s * TRAIL_STEP);
        if (!pastDets.length) { gapCount++; if (gapCount > MAX_GAP) break; continue; }
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
      const isSel = det.track_id === selectedTrackId || selectedFaceRef.current.includes(det.track_id);
      const color = colorOf(det.class_name);
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
        const label = zhLabel(det.class_name, det.display_seq ?? det.track_id);
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

    // Only schedule next frame when playing (avoids waste during pause)
    if (!video.paused) {
      rafRef.current = requestAnimationFrame(draw);
    }
  }, [enabled, hasDetection, interpolatedAt, selectedTrackId, videoRef]);

  useEffect(() => {
    if (!hasDetection) return;

    // Initial draw
    rafRef.current = requestAnimationFrame(draw);

    // Restart rAF loop when video starts playing (paused → playing)
    const video = videoRef.current;
    const onPlay = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(draw);
    };
    // 暂停态 seek 后立即重绘（区间数据可能已在 get 里，先画已有；数据到达后 version++ 再触发）
    const onSeeked = () => {
      requestAnimationFrame(draw);
    };
    video?.addEventListener("play", onPlay);
    video?.addEventListener("seeked", onSeeked);

    return () => {
      cancelAnimationFrame(rafRef.current);
      video?.removeEventListener("play", onPlay);
      video?.removeEventListener("seeked", onSeeked);
    };
  }, [hasDetection, draw, version]);

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

  /* ── 命中检测：返回点击位置命中的最小面积检测框（与绘制插值一致 + HIT_PAD）。
     atTime 可选：数据补拉后的重试需要按点击时刻命中（播放中 currentTime 已前移）。── */
  const pickTrack = useCallback(
    (clientX: number, clientY: number, atTime?: number): Detection | null => {
      const fc = toFrameCoord(clientX, clientY);
      if (!fc || fc.fx < 0 || fc.fx > 1 || fc.fy < 0 || fc.fy > 1) return null;
      const video = videoRef.current;
      const dets = interpolatedAt(atTime ?? video?.currentTime ?? 0);
      let best: Detection | null = null;
      let bestArea = Infinity;
      for (const d of dets) {
        if (fc.fx >= d.bbox.x1 - HIT_PAD && fc.fx <= d.bbox.x2 + HIT_PAD
            && fc.fy >= d.bbox.y1 - HIT_PAD && fc.fy <= d.bbox.y2 + HIT_PAD) {
          const area = (d.bbox.x2 - d.bbox.x1) * (d.bbox.y2 - d.bbox.y1);
          if (area < bestArea) { bestArea = area; best = d; }
        }
      }
      return best;
    },
    [toFrameCoord, videoRef, interpolatedAt],
  );

  /* ── click（document capture）：bbox 点击选中。
     click 是唯一能穿透 <video controls> 原生控件到达 DOM 的事件（pointerdown/mousedown
     会被视频原生控件在更底层吃掉）；配合 render 里的透明捕获层，点击正常到达这里。
     命中 bbox → 选中 + preventDefault/stopPropagation（阻止原生播放/暂停切换）；
     未命中且数据未就绪 → 挂 pending 等 version 重试；空点击 → 模拟原生播放/暂停切换。── */
  const handleClick = useCallback(
    (e: MouseEvent) => {
      if (!hasDetection) return;
      const container = canvasRef.current?.parentElement;
      if (!container) return;
      const rect = container.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) return;
      // 只在视频容器内的点击处理（document capture 会收到全页面 click，需坐标过滤）
      if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) return;
      const video = videoRef.current;
      const currentTime = video?.currentTime ?? 0;
      ensure(currentTime); // 数据空档兜底：确保点击时刻窗口已加载（已加载则 no-op）
      const best = pickTrack(e.clientX, e.clientY, currentTime);
      if (best) {
        e.preventDefault();   // 阻止视频原生点击暂停/播放
        e.stopPropagation();
        const wasPaused = video?.paused ?? null;
        // v0.30: 点击已选中的 bbox → 取消选中（显式取消入口）；
        // 否则选中该框。播放/暂停状态不因选中而改变。
        if (best.track_id === selectedTrackId) {
          onTrackSelect(-1, "");
        } else {
          onTrackSelect(best.track_id, best.class_name);
        }
        // 保险：若 preventDefault 未阻止原生 toggle，下一帧恢复播放状态
        if (video && wasPaused !== null) {
          requestAnimationFrame(() => {
            if (video.paused !== wasPaused) {
              if (wasPaused) video.pause();
              else video.play().catch(() => {});
            }
          });
        }
      } else if (!hasLoadedRange(currentTime)) {
        // 数据未就绪（刚 seek/快进，窗口还在路上）：记 pending，version 到达后重试；超时兜底反选。
        pendingClickRef.current = { x: e.clientX, y: e.clientY, t: currentTime };
        pendingTimerRef.current = setTimeout(() => {
          pendingTimerRef.current = null;
          if (pendingClickRef.current) {
            pendingClickRef.current = null;
            onTrackSelectRef.current(-1, "");
          }
        }, 500);
      } else {
        // v0.30 空点击：只模拟原生播放/暂停切换，不再反选选中框。
        // （原实现 play/pause + onTrackSelect(-1) 耦合导致：暂停态选中物体后
        //   点空白播放 → 高亮被取消。现在播放/暂停与选中/取消完全解耦。）
        if (video) {
          if (video.paused) video.play().catch(() => {});
          else video.pause();
        }
      }
    },
    [hasDetection, ensure, hasLoadedRange, pickTrack, onTrackSelect, selectedTrackId],
  );

  const handleMove = useCallback(
    (e: MouseEvent) => {
      const parent = canvasRef.current?.parentElement;
      if (!hasDetection) { if (parent) parent.style.cursor = "default"; return; }
      const fc = toFrameCoord(e.clientX, e.clientY);
      if (!fc || fc.fx < 0 || fc.fx > 1 || fc.fy < 0 || fc.fy > 1) {
        if (parent) parent.style.cursor = "default"; return;
      }
      const video = videoRef.current;
      const dets = interpolatedAt(video?.currentTime ?? 0);
      const hit = dets.some((d) => fc.fx >= d.bbox.x1 - HIT_PAD && fc.fx <= d.bbox.x2 + HIT_PAD && fc.fy >= d.bbox.y1 - HIT_PAD && fc.fy <= d.bbox.y2 + HIT_PAD);
      if (parent) parent.style.cursor = hit ? "crosshair" : "default";
    },
    [hasDetection, videoRef, toFrameCoord, interpolatedAt],
  );

  /* ── 数据到达（version++）→ 重试 pending 的点击命中（刚 seek/快进后点击瞬间数据未就绪的兜底）── */
  useEffect(() => {
    const pending = pendingClickRef.current;
    if (!pending) return;
    pendingClickRef.current = null;
    const best = pickTrack(pending.x, pending.y, pending.t);
    onTrackSelectRef.current(best ? best.track_id : -1, best ? best.class_name : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, pickTrack]);

  useEffect(() => {
    if (!hasDetection) return;
    // click 挂 document（capture）—— click 是唯一能穿透 <video controls> 原生控件到达 DOM 的事件
    // （pointerdown/mousedown 会被视频原生控件在更底层吃掉，document capture 都收不到）。
    // move 挂父容器（bubble，crosshair）。
    document.addEventListener("click", handleClick, true);
    const parent = canvasRef.current?.parentElement;
    parent?.addEventListener("pointermove", handleMove);
    parent?.addEventListener("mousemove", handleMove);
    return () => {
      document.removeEventListener("click", handleClick, true);
      parent?.removeEventListener("pointermove", handleMove);
      parent?.removeEventListener("mousemove", handleMove);
      if (parent) parent.style.cursor = "";
    };
    // enabled 也进依赖：enabled 翻转（canvas 挂载/卸载）时重挂监听，避免幽灵失效
  }, [hasDetection, enabled, handleClick, handleMove]);

  /* ── 卸载清理 pending-click 超时（防卸载后悬空回调） ── */
  useEffect(() => {
    return () => {
      if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);
    };
  }, []);

  if (!enabled || !hasDetection) return null;

  return (
    <>
      <canvas
        ref={canvasRef}
        style={{ position: "absolute", top: 0, left: 0, pointerEvents: "none", zIndex: 0 }}
      />
      {/* 点击捕获层：普通 DOM 元素，覆盖视频内容区（底部留 44px 给原生控制条）。
         <video controls> 的原生手势把视频区域的点击拦截在 UA shadow DOM 内、不派发到 document，
         所以必须用这个透明层接住点击，让它正常到达 document 的 click 监听。 */}
      <div
        style={{
          position: "absolute", top: 0, left: 0, right: 0, bottom: 44,
          zIndex: 1, pointerEvents: "auto", cursor: "inherit", background: "transparent",
        }}
      />
    </>
  );
}
