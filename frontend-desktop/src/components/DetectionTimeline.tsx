/* ════════════════════════════════════════════════════════════
   DetectionTimeline — v0.22 Canvas 化（终局）
   v2.0 dark theme. 时间视口 + zoom/pan + lane packing + 垂直虚拟化。

   设计:
     - buildRects: 严格「一行一个 track」——lane = 排序序号，不做 lane 复用；
       同 track 的所有 segment 在同一行，不同 track 绝不共享一行
     - 三滚动条: 左 zoom 条(拉长/缩短, thumb 高∝span) + 右原生纵向条(垂直滚动) + 底 pan 条(左右拖动, thumb=minimap)
     - 时间视口 [viewStart, viewEnd]: ctrl/cmd+滚轮=zoom(锚定鼠标时间) / 拖拽=pan(整体位移钳制, 保 span)
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

const MIN_SPAN = 2;                  // 最小时间跨度（与 ctrl+滚轮一致）
const ZOOM_MIN_THUMB = 8;            // 左侧 zoom 条最小 thumb 高度
const HSCROLL_MIN_THUMB = 14;        // 底部 pan 条最小 thumb 宽度
const MIN_BAR_PX = 5;                // 亚像素段最小可见条宽（略失真，保证短 track 可见可点）
const HIT_SLACK = 12;                // 命中容差 px：点到条中心 ±HIT_SLACK 内都算命中（短条可选中）

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

/* ── lane packing: 严格「一行一个 track」——lane = 排序序号，不做任何 lane 复用。
   同一 track 的所有 segment 在同一行；不同 track 绝不共享同一行。 ── */
function buildRects(tracks: Track[]): { rects: Rect[]; laneCount: number } {
  const sorted = [...tracks].sort((a, b) => a.first_seen - b.first_seen);
  const rects: Rect[] = [];
  sorted.forEach((t, lane) => {
    const segs = t.segments?.length ? t.segments : [{ start: t.first_seen, end: t.last_seen }];
    segs.forEach((seg, si) => {
      rects.push({
        trackId: t.track_id, className: t.class_name,
        color: colorOf(t.class_name), label: zhLabel(t.class_name, t.track_id),
        start: seg.start, end: seg.end, lane,
        frameCount: t.frame_count, firstSeen: t.first_seen, lastSeen: t.last_seen,
        showLabel: si === 0,
      });
    });
  });
  return { rects, laneCount: sorted.length };
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

/* ── 左 zoom 条几何：thumb 高 ∝ span（scrollbar 隐喻），thumb 顶 = (1-r)²·H 平滑映射。
   逆向 spanFromZoomTop 与其自洽（拖动无跳变）。── */
function zoomThumbMetrics(span: number, duration: number, trackH: number): { top: number; height: number } {
  const r = duration > 0 ? Math.min(1, Math.max(0, span / duration)) : 1;
  const height = Math.max(ZOOM_MIN_THUMB, Math.min(trackH, r * trackH));
  const top = Math.min(trackH - height, (1 - r) * (1 - r) * trackH);
  return { top, height };
}
function spanFromZoomTop(topPx: number, trackH: number, duration: number): number {
  const r = trackH > 0
    ? Math.min(1, Math.max(0, 1 - Math.sqrt(Math.min(trackH, Math.max(0, topPx)) / trackH)))
    : 1;
  return Math.max(MIN_SPAN, Math.min(duration, r * duration));
}

/* ── 底 pan 条几何：thumb 左缘 = view.start/duration，thumb 宽 = span/duration（minimap 滚动条）── */
function hthumbMetrics(v: { start: number; end: number }, duration: number, trackW: number): { left: number; width: number } {
  const span = v.end - v.start;
  const width = Math.max(HSCROLL_MIN_THUMB, Math.min(trackW, (span / Math.max(duration, 1e-6)) * trackW));
  const left = duration > 0 ? Math.min(trackW - width, (v.start / duration) * trackW) : 0;
  return { left: Math.max(0, left), width };
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
  const zoomBarRef = useRef<HTMLDivElement>(null);
  const hscrollRef = useRef<HTMLDivElement>(null);
  const zoomDragRef = useRef<{ grabOffset: number; center: number } | null>(null);
  const hDragRef = useRef<{ startX: number; startView: { start: number; end: number }; tw: number } | null>(null);

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

  /* ── 选中 track 联动：垂直滚动到其 lane（面板点击→时间轴跳页）+ 水平 pan 到其时间段 ── */
  useLayoutEffect(() => {
    if (selectedTrackId == null) return;
    const rect = rectsRef.current.find((r) => r.trackId === selectedTrackId);
    const v = viewRef.current;
    if (!rect || !v) return;
    // 垂直：把选中 track 的 lane 滚到可视区中央（useLayoutEffect 在 paint 前执行，无闪烁）
    const wrap = wrapRef.current;
    if (wrap) {
      const laneTop = PAD + rect.lane * ROW;
      wrap.scrollTop = Math.max(0, laneTop - (wrap.clientHeight - ROW) / 2);
    }
    // 水平：时间不在视口内才 pan
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
      // 亚像素段补最小可见宽度（对齐旧 DOM 的 min-width:3px）——任何缩放下所有 track 都可见
      const drawW = Math.max(x2 - x1, MIN_BAR_PX);
      const y = PAD + r.lane * ROW - scrollTop;
      const isSel = r.trackId === selectedRef.current;
      const isHover = hoverRef.current?.rect === r;
      ctx.fillStyle = isSel ? "#FFD700" : r.color;
      ctx.globalAlpha = isSel ? 1 : (isHover ? 0.95 : 0.65);
      ctx.fillRect(x1, y, drawW, LANE_H);
      ctx.globalAlpha = 1;
      // label（每 track 首段；条宽足够才画，避免细条上糊文字）
      if (r.showLabel && drawW > 16) {
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
    const t = v.start + (mx / wrap.clientWidth) * span;
    const lane = Math.floor((scrollTopRef.current + my - PAD) / ROW);
    // 命中 = 点到「绘制条 [x1, x1+drawW]」的最短距离 ≤ HIT_SLACK。
    // 长条任何位置都在条内（dist=0）都可点/可 hover；短条靠最小条宽 + 容差获得足够大的命中区。
    // 严格一行一个 track 下同 lane 只属一个 track，无歧义。
    let best: { rect: Rect; dist: number } | null = null;
    for (const r of rectsRef.current) {
      if (r.lane !== lane) continue;
      if (r.end < v.start || r.start > v.end) continue;
      const x1 = timeToX(Math.max(r.start, v.start), v, wrap.clientWidth);
      const x2 = timeToX(Math.min(r.end, v.end), v, wrap.clientWidth);
      const drawW = Math.max(x2 - x1, MIN_BAR_PX);
      const dist = mx < x1 ? x1 - mx : (mx > x1 + drawW ? mx - (x1 + drawW) : 0);
      if (best === null || dist < best.dist) best = { rect: r, dist };
    }
    if (best && best.dist <= HIT_SLACK) return { rect: best.rect, t };
    return null;
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    dragRef.current = { x: e.clientX, startView: viewRef.current };
  }, []);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    const drag = dragRef.current;
    if (drag) {
      // 拖拽 pan —— 按窗口整体位移钳制，保 span 不变（不再出现"拖拽拉长"假 zoom）
      const wrap = wrapRef.current;
      const v = drag.startView;
      if (!wrap || !v) return;
      const rect = wrap.getBoundingClientRect();
      const span = v.end - v.start;
      const dsec = -(e.clientX - drag.x) * (span / rect.width);
      const clamped = Math.max(-v.start, Math.min(dsec, durationRef.current - v.end));
      setView({ start: v.start + clamped, end: v.end + clamped });
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
    // 一律 seek 到精确点击时间 t ——「点哪跳哪」。
    // 旧逻辑新 track 跳到 rect.start（segment 起点）：长 segment（如 35.5→73.4）上点末端
    // 会跳回段头，差几十秒，表现为「跳转不到位」。已选中的比例 seek 结果本就等于 t，两者统一。
    onTrackSelectRef.current(rect.trackId, rect.className, t);
  }, [hitTest]);

  const onMouseLeave = useCallback(() => {
    dragRef.current = null;
    setHover(null);
  }, []);

  const onLanesScroll = useCallback(() => {
    scrollTopRef.current = wrapRef.current?.scrollTop ?? 0;
    render();
  }, [render]);

  /* ── 底部 pan 条：拖 thumb = 平移视口（窗口跟随 thumb，右拖→看更晚）；点击轨道拖动亦可 ── */
  const onHScrollDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const bar = hscrollRef.current;
    const v = viewRef.current;
    if (!bar || !v) return;
    hDragRef.current = { startX: e.clientX, startView: v, tw: bar.getBoundingClientRect().width };
    bar.setPointerCapture(e.pointerId);
  }, []);

  const onHScrollMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const d = hDragRef.current;
    if (!d) return;
    const dur = durationRef.current;
    const span = d.startView.end - d.startView.start;
    const dsec = (e.clientX - d.startX) * (span / d.tw);
    const clamped = Math.max(-d.startView.start, Math.min(dsec, dur - d.startView.end));
    setView({ start: d.startView.start + clamped, end: d.startView.end + clamped });
  }, []);

  const onHScrollUp = useCallback(() => { hDragRef.current = null; }, []);

  /* ── 左 zoom 条：拖 thumb = 拉长/缩短（等价 ctrl+滚轮，锚定拖动起始的视口中心）── */
  const onZoomDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const bar = zoomBarRef.current;
    const v = viewRef.current;
    if (!bar || !v) return;
    const rect = bar.getBoundingClientRect();
    const trackH = rect.height;
    const dur = durationRef.current;
    const { top, height } = zoomThumbMetrics(v.end - v.start, dur, trackH);
    const py = e.clientY - rect.top;
    // 点在 thumb 上 → 保留抓取偏移（delta 拖）；点轨道空白 → 跳到该位置（grabOffset=0）
    const grabOffset = py >= top && py <= top + height ? py - top : 0;
    zoomDragRef.current = { grabOffset, center: (v.start + v.end) / 2 };
    bar.setPointerCapture(e.pointerId);
  }, []);

  const onZoomMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const d = zoomDragRef.current;
    if (!d) return;
    const bar = zoomBarRef.current;
    if (!bar) return;
    const rect = bar.getBoundingClientRect();
    const trackH = rect.height;
    const dur = durationRef.current;
    const newTop = Math.max(0, Math.min(trackH - ZOOM_MIN_THUMB, e.clientY - rect.top - d.grabOffset));
    const span = spanFromZoomTop(newTop, trackH, dur);
    const s = Math.max(0, Math.min(d.center - span / 2, dur - span));
    setView({ start: s, end: s + span });
  }, []);

  const onZoomUp = useCallback(() => { zoomDragRef.current = null; }, []);

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

  /* ── 三滚动条 thumb 几何（view 驱动，受控）── */
  const tw = hscrollRef.current?.clientWidth || size.w || 400;
  const th = zoomBarRef.current?.clientHeight || size.h || 100;
  const hthumb = view ? hthumbMetrics(view, duration, tw) : null;
  const zthumb = view ? zoomThumbMetrics(view.end - view.start, duration, th) : null;

  return (
    <div className="timeline-wrap">
      <div className="tl-main-row">
        {/* 左：zoom 条（拉长/缩短 = ctrl+滚轮效果） */}
        <div
          className="tl-zoom"
          ref={zoomBarRef}
          onPointerDown={onZoomDown}
          onPointerMove={onZoomMove}
          onPointerUp={onZoomUp}
          onPointerCancel={onZoomUp}
        >
          {zthumb && <div className="tl-zoom-thumb" style={{ top: zthumb.top, height: zthumb.height }} />}
        </div>

        {/* 中：ruler + lanes + pan 条 + playhead */}
        <div className="tl-body">
          <div className="tl-ruler">
            {rulerTicks.map((t) => (
              <div key={t} className="tl-tick" style={{ left: `${timeToX(t, view!, size.w || 400)}px` }}>
                <div className="tl-tick-l" />
                <span className="tl-tick-t">{fmtTick(t)}</span>
              </div>
            ))}
          </div>

          {/* Lanes-wrap: 非滚动定位容器 —— canvas 钉在这里（绝对定位子元素会随滚动容器滚走，
              必须放在不滚动的包装层，见 Overlay 同款做法）；.tl-lanes 只负责滚动 spacer。 */}
          <div className="tl-lanes-wrap">
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
            </div>
            <canvas
              ref={canvasRef}
              style={{ position: "absolute", top: 0, left: 0, width: size.w, height: size.h, pointerEvents: "none" }}
            />
          </div>

          {/* 底：pan 条（左右拖动，与鼠标直接拖时间轴同效） */}
          <div
            className="tl-hscroll"
            ref={hscrollRef}
            onPointerDown={onHScrollDown}
            onPointerMove={onHScrollMove}
            onPointerUp={onHScrollUp}
            onPointerCancel={onHScrollUp}
          >
            {hthumb && <div className="tl-hscroll-thumb" style={{ left: hthumb.left, width: hthumb.width }} />}
          </div>

          {/* Playhead (zoom 感知 left，锚定 .tl-body = 与 lanes 左缘对齐) */}
          <div ref={playheadRef} className="tl-playhead" style={{ left: "0px" }} />
        </div>
      </div>

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
