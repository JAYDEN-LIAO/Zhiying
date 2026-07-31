/* ════════════════════════════════════════════════════════════
   DetectionTimeline — v0.22 Canvas 化（终局）
   v2.0 dark theme. 时间视口 + zoom/pan + lane packing + 垂直虚拟化。

   设计:
     - buildRects: 每个 segment 摊平成一条 Rect，贪心 lane 装箱（复用被占用的泳道）
     - 时间视口 [viewStart, viewEnd]: wheel=zoom(锚定鼠标时间) / drag=pan
     - 画布恒定宽度; 高度=可见区域, 垂直滚动通过 spacer + 重绘 offset（防 canvas 尺寸上限）
     - playhead 用 DOM 覆盖线, left 按 timeToX(currentTime) px 定位（zoom 感知）
     - hover tooltip 为单个 fixed DOM 浮层
   ════════════════════════════════════════════════════════════ */

import { useEffect, useLayoutEffect, useRef, useMemo, useState, useCallback, memo } from "react";
import type { DetectionData, Track, FaceData } from "../types";
import { colorOf, zhLabel } from "../labels";

const LANE_H = 9;
const LANE_GAP = 5;
const PAD = 5;
const ROW = LANE_H + LANE_GAP;       // 14px / lane

interface Rect {
  trackId: number; className: string; color: string; label: string;
  start: number; end: number; lane: number;
  frameCount: number; firstSeen: number; lastSeen: number;
  showLabel: boolean;
}

interface Props {
  videoId: string;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  data: DetectionData | null;
  selectedTrackId: number | null;
  classFilter: string | null;
  onTrackSelect: (trackId: number, className: string, seekTo: number) => void;
  faceData?: FaceData | null;
  /* ── v0.22 修复: 视频元素在 streamReady 时才存在，playhead 监听以其为信号 ── */
  streamReady?: boolean;
}

/* ── lane packing: 按 first_seen 升序，把 segment 分到首个不重叠的 lane ── */
function buildRects(tracks: Track[]): { rects: Rect[]; laneCount: number } {
  const events: Array<{
    trackId: number; className: string; start: number; end: number;
    frameCount: number; firstSeen: number; lastSeen: number; showLabel: boolean;
  }> = [];
  for (const t of tracks) {
    const segs = t.segments?.length ? t.segments : [{ start: t.first_seen, end: t.last_seen }];
    segs.forEach((seg, si) => {
      events.push({
        trackId: t.track_id, className: t.class_name,
        start: seg.start, end: seg.end,
        frameCount: t.frame_count, firstSeen: t.first_seen, lastSeen: t.last_seen,
        showLabel: si === 0,
      });
    });
  }
  events.sort((a, b) => a.start - b.start);
  const laneEnd: number[] = [];
  const rects: Rect[] = [];
  for (const e of events) {
    let lane = laneEnd.findIndex((end) => e.start >= end);
    if (lane === -1) { lane = laneEnd.length; laneEnd.push(0); }
    laneEnd[lane] = e.end;
    rects.push({
      trackId: e.trackId, className: e.className,
      color: colorOf(e.className), label: zhLabel(e.className, e.trackId),
      start: e.start, end: e.end, lane,
      frameCount: e.frameCount, firstSeen: e.firstSeen, lastSeen: e.lastSeen,
      showLabel: e.showLabel,
    });
  }
  return { rects, laneCount: laneEnd.length };
}

function pickTickInterval(span: number, width: number): number {
  const targets = [1, 5, 10, 15, 30, 60, 120, 300, 600, 1800, 3600];
  for (const iv of targets) {
    if (width / (span / iv) >= 40) return iv;
  }
  return 3600;
}

function timeToX(t: number, view: { start: number; end: number }, width: number): number {
  return ((t - view.start) / Math.max(view.end - view.start, 1e-3)) * width;
}

function fmtTick(s: number): string {
  if (s === 0) return "0";
  if (s % 60 === 0) return `${s / 60}m`;
  return `${s}`;
}

export const DetectionTimeline = memo(function DetectionTimeline({ videoId, videoRef, data, selectedTrackId, classFilter, onTrackSelect, faceData, streamReady }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const playheadRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef(0);
  const dragRef = useRef<{ x: number; startView: { start: number; end: number } | null } | null>(null);

  const [view, setView] = useState<{ start: number; end: number } | null>(null);
  const [hover, setHover] = useState<{ rect: Rect; x: number; y: number } | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  // 热路径 refs（render / 事件处理器读取，不随渲染重建闭包）
  const viewRef = useRef(view); viewRef.current = view;
  const sizeRef = useRef(size); sizeRef.current = size;
  const scrollTopRef = useRef(0);
  const selectedRef = useRef(selectedTrackId); selectedRef.current = selectedTrackId;
  const hoverRef = useRef(hover); hoverRef.current = hover;
  const faceRef = useRef(faceData); faceRef.current = faceData;
  const onTrackSelectRef = useRef(onTrackSelect); onTrackSelectRef.current = onTrackSelect;

  const filtered = useMemo(
    () => (classFilter ? (data?.tracks ?? []).filter((t) => t.class_name === classFilter) : data?.tracks ?? []),
    [data?.tracks, classFilter],
  );
  const { rects, laneCount } = useMemo(() => buildRects(filtered), [filtered]);
  const rectsRef = useRef(rects); rectsRef.current = rects;
  const laneCountRef = useRef(laneCount); laneCountRef.current = laneCount;

  const videoDur = videoRef.current?.duration;
  const duration = (videoDur && videoDur > 0 && !Number.isNaN(videoDur))
    ? videoDur
    : ((data?.tracks?.length ? Math.max(...data.tracks.map((t) => t.last_seen)) : 0) + 1);
  const durationRef = useRef(duration); durationRef.current = duration;

  const totalH = laneCount * ROW + PAD * 2;
  // 元素存在性门禁 —— 与 JSX 空态判断共用同一变量，杜绝"渲染门禁 vs effect 依赖"漂移
  const hasTracks = !!data?.has_detection && filtered.length > 0;

  /* ── 视口重置（全片视图）：tracks/时长/筛选变化时 ── */
  useEffect(() => {
    setView({ start: 0, end: Math.max(duration, 1) });
  }, [duration, data?.tracks]);

  /* ── 选中 track 居中（不在视口内才 pan）── */
  useEffect(() => {
    if (selectedTrackId == null) return;
    const rect = rectsRef.current.find((r) => r.trackId === selectedTrackId);
    const v = viewRef.current;
    if (!rect || !v) return;
    if (rect.start >= v.start && rect.start <= v.end) return;
    const span = v.end - v.start;
    let s = rect.start - span / 2, en = rect.start + span / 2;
    s = Math.max(0, s); en = Math.min(duration, en);
    if (en - s < 1) en = s + 1;
    setView({ start: s, end: en });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTrackId]);

  /* ── Canvas 绘制（读取 refs，稳定函数；每次渲染后重绘）── */
  const render = useCallback(() => {
    const canvas = canvasRef.current;
    const v = viewRef.current;
    const { w, h } = sizeRef.current;
    if (!canvas || !v || w === 0 || h === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const scrollTop = scrollTopRef.current;
    const startLane = Math.max(0, Math.floor(scrollTop / ROW));
    const endLane = Math.min(laneCountRef.current, Math.ceil((scrollTop + h) / ROW));

    // face markers（best_face_timestamp 在视口内画竖短线）
    const identities = faceRef.current?.identities ?? [];
    if (identities.length) {
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      for (const id of identities) {
        const ts = id.best_face_timestamp;
        if (ts == null || ts < v.start || ts > v.end) continue;
        const x = timeToX(ts, v, w);
        ctx.fillRect(x - 1, 0, 2, 8);
      }
    }

    // lanes
    for (const r of rectsRef.current) {
      if (r.lane < startLane || r.lane > endLane) continue;
      if (r.end < v.start || r.start > v.end) continue;
      const x1 = timeToX(Math.max(r.start, v.start), v, w);
      const x2 = timeToX(Math.min(r.end, v.end), v, w);
      if (x2 - x1 < 1) continue;
      const y = PAD + r.lane * ROW - scrollTop;
      const isSel = r.trackId === selectedRef.current;
      const isHover = hoverRef.current?.rect === r;
      ctx.fillStyle = isSel ? "#FFD700" : r.color;
      ctx.globalAlpha = isSel ? 1 : (isHover ? 0.95 : 0.65);
      ctx.fillRect(x1, y, x2 - x1, LANE_H);
      ctx.globalAlpha = 1;
      // label（每 track 首段，宽度足够才画）
      if (r.showLabel && x2 - x1 > 16) {
        ctx.fillStyle = "rgba(255,255,255,0.75)";
        ctx.font = "8px system-ui, sans-serif";
        ctx.fillText(r.label, x1 + 3, y + LANE_H - 2);
      }
    }
  }, []);

  /* 每次渲染后重绘（view/hover/size/selected/rects 变化都会触发渲染；useLayoutEffect 避免闪白） */
  useLayoutEffect(() => { render(); });

  /* ── wrap 元素生命周期（keyed on hasTracks）：
     ResizeObserver 测尺寸 + Ctrl/Cmd+滚轮 zoom。
     hasTracks 变化 → effect 重跑，新闭包捕获当前元素；卸载 → cleanup。── */
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!hasTracks || !wrap) return;
    const updateSize = () => setSize({ w: wrap.clientWidth, h: wrap.clientHeight });
    const ro = new ResizeObserver(updateSize);
    ro.observe(wrap);
    updateSize();
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;   // 普通滚轮 → .tl-lanes 垂直滚动
      e.preventDefault();
      const v = viewRef.current;
      if (!v) return;
      const rect = wrap.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const span = v.end - v.start;
      const tAtMouse = v.start + (mx / rect.width) * span;
      const factor = e.deltaY > 0 ? 1.1 : 0.9;
      const newSpan = Math.max(2, Math.min(durationRef.current, span * factor));
      let s = tAtMouse - (mx / rect.width) * newSpan;
      let en = s + newSpan;
      if (s < 0) { s = 0; en = newSpan; }
      if (en > durationRef.current) { en = durationRef.current; s = Math.max(0, en - newSpan); }
      setView({ start: s, end: en });
    };
    wrap.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      ro.disconnect();
      wrap.removeEventListener("wheel", onWheel);
    };
  }, [hasTracks]);

  /* ── playhead（DOM 覆盖线，left 按 timeToX px；paused 停 rAF）。
     keyed on [hasTracks, streamReady, videoId] —— 视频元素在 streamReady 时才存在，
     切视频时元素被 key={videoId} 重建，videoId 必须进依赖才能重挂监听。── */
  useEffect(() => {
    const ph = playheadRef.current;
    const video = videoRef.current;
    if (!hasTracks || !streamReady || !ph || !video) return;
    const updatePlayhead = () => {
      const v = viewRef.current;
      const wrap = wrapRef.current;
      if (v && wrap) {
        const x = timeToX(videoRef.current?.currentTime ?? 0, v, wrap.clientWidth);
        ph.style.left = `${x}px`;
      }
    };
    const tick = () => {
      updatePlayhead();
      if (video.paused) return;
      rafRef.current = requestAnimationFrame(tick);
    };
    const onPlay = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    video.addEventListener("play", onPlay);
    video.addEventListener("seeked", updatePlayhead);
    video.addEventListener("pause", updatePlayhead);
    return () => {
      cancelAnimationFrame(rafRef.current);
      video.removeEventListener("play", onPlay);
      video.removeEventListener("seeked", updatePlayhead);
      video.removeEventListener("pause", updatePlayhead);
    };
  }, [hasTracks, streamReady, videoId]);

  /* ── 交互：拖拽 pan + 点击命中 + hover 命中 ── */

  const hitTest = useCallback((clientX: number, clientY: number): { rect: Rect; t: number } | null => {
    const wrap = wrapRef.current;
    const v = viewRef.current;
    if (!wrap || !v) return null;
    const rect = wrap.getBoundingClientRect();
    const mx = clientX - rect.left;
    const my = clientY - rect.top;
    const span = v.end - v.start;
    const t = v.start + (mx / rect.width) * span;
    const lane = Math.floor((scrollTopRef.current + my - PAD) / ROW);
    for (const r of rectsRef.current) {
      if (r.lane === lane && t >= r.start && t <= r.end) return { rect: r, t };
    }
    return null;
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    dragRef.current = { x: e.clientX, startView: viewRef.current };
  }, []);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    const drag = dragRef.current;
    if (drag) {
      // 拖拽 pan
      const wrap = wrapRef.current;
      const v = drag.startView;
      if (!wrap || !v) return;
      const rect = wrap.getBoundingClientRect();
      const span = v.end - v.start;
      const dsec = -(e.clientX - drag.x) * (span / rect.width);
      let s = v.start + dsec, en = v.end + dsec;
      s = Math.max(0, s); en = Math.min(durationRef.current, en);
      if (en - s < 1) en = s + 1;
      setView({ start: s, end: en });
      return;
    }
    // hover 命中
    const hit = hitTest(e.clientX, e.clientY);
    setHover(hit ? { rect: hit.rect, x: e.clientX, y: e.clientY } : null);
  }, [hitTest]);

  const onMouseUp = useCallback((e: React.MouseEvent) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag) return;
    if (Math.abs(e.clientX - drag.x) > 5) return;   // 拖拽过 → 非点击
    const hit = hitTest(e.clientX, e.clientY);
    if (!hit) return;
    const { rect, t } = hit;
    if (rect.trackId === selectedRef.current) {
      // 已选中：条内比例 seek（复刻原 DOM 版 onClick 行为）
      const ratio = Math.max(0, Math.min(1, (t - rect.start) / (rect.end - rect.start)));
      onTrackSelectRef.current(rect.trackId, rect.className, rect.start + ratio * (rect.end - rect.start));
    } else {
      onTrackSelectRef.current(rect.trackId, rect.className, rect.start);
    }
  }, [hitTest]);

  const onMouseLeave = useCallback(() => {
    dragRef.current = null;
    setHover(null);
  }, []);

  const onLanesScroll = useCallback(() => {
    scrollTopRef.current = wrapRef.current?.scrollTop ?? 0;
    render();
  }, [render]);

  /* ── 空态（与 hasTracks 门禁同源）── */
  if (!hasTracks) {
    return (
      <div className="timeline-wrap" style={{ flex: 1, minHeight: 80, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span className="text-xs text-white/20">时间轴</span>
      </div>
    );
  }

  /* ── Ruler ticks（DOM，zoom 感知）── */
  const rulerTicks: number[] = [];
  if (view) {
    const span = view.end - view.start;
    const iv = pickTickInterval(span, size.w || 400);
    for (let t = Math.ceil(view.start / iv) * iv; t <= view.end + 1e-6; t += iv) rulerTicks.push(t);
  }

  return (
    <div className="timeline-wrap">
      {/* Time ruler */}
      <div className="tl-ruler">
        {rulerTicks.map((t) => (
          <div key={t} className="tl-tick" style={{ left: `${timeToX(t, view!, size.w || 400)}px` }}>
            <div className="tl-tick-l" />
            <span className="tl-tick-t">{fmtTick(t)}</span>
          </div>
        ))}
      </div>

      {/* Lanes: spacer 撑滚动 + Canvas 固定覆盖（垂直虚拟化，重绘 offset） */}
      <div
        ref={wrapRef}
        className="tl-lanes"
        onScroll={onLanesScroll}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseLeave}
      >
        <div style={{ height: totalH, minHeight: "100%" }} />
        <canvas ref={canvasRef} style={{ position: "absolute", top: 0, left: 0, width: size.w, height: size.h }} />
      </div>

      {/* Playhead (zoom 感知 left) */}
      <div ref={playheadRef} className="tl-playhead" style={{ left: "0px" }} />

      {/* Hover tooltip（单个 fixed DOM 浮层） */}
      {hover && (
        <div
          className="fixed z-50 pointer-events-none px-2 py-1 rounded-md text-[10px] leading-relaxed shadow-lg"
          style={{
            left: hover.x, top: hover.y - 34, transform: "translateX(-50%)",
            background: "rgba(0,0,0,0.85)", color: "#fff", whiteSpace: "nowrap",
          }}
        >
          <span style={{ color: hover.rect.color, fontWeight: 600 }}>
            {hover.rect.label}
          </span>
          <span className="text-white/60 ml-1.5">
            {hover.rect.frameCount}f · {hover.rect.firstSeen.toFixed(1)}s–{hover.rect.lastSeen.toFixed(1)}s
          </span>
        </div>
      )}
    </div>
  );
});
