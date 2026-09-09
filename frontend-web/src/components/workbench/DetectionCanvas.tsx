import { useEffect, useRef, type RefObject } from "react";
import { api } from "../../services/api";
import { colorOf, zh } from "../../labels";
import type { Detection } from "../../types";

/* ════════════════════════════════════════════════════════════
   DetectionCanvas — AI 识别框 Canvas 层
   覆盖在视频画面上：按播放时间从 /detection/detections 时间窗
   按需加载检测框（0.1s 精度），实时绘制 bbox + 类别标签
   坐标兼容：bbox 全 ≤1 视为归一化，否则按视频分辨率像素值
   ════════════════════════════════════════════════════════════ */

const WINDOW_SEC = 6; // 时间窗半径
const MAX_KEY_DIFF = 0.4; // 最近检测帧匹配容差（秒）

export function DetectionCanvas({
  videoId,
  videoRef,
  currentTime,
  enabled,
}: {
  videoId: string | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  currentTime: number;
  enabled: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rangeRef = useRef<{ start: number; end: number; detections: Record<string, Detection[]> } | null>(null);
  const loadingRef = useRef(false);

  /* 切换视频 → 清空缓存 */
  useEffect(() => {
    rangeRef.current = null;
  }, [videoId]);

  /* 播放位置接近缓存窗口边界 → 加载新窗口 */
  useEffect(() => {
    if (!videoId || !enabled) return;
    const cached = rangeRef.current;
    const need = !cached || currentTime < cached.start + 1.5 || currentTime > cached.end - 1.5;
    if (!need || loadingRef.current) return;
    loadingRef.current = true;
    const start = Math.max(0, currentTime - WINDOW_SEC);
    const end = currentTime + WINDOW_SEC;
    api
      .fetchDetectionRange(videoId, start, end)
      .then((r) => {
        rangeRef.current = { start, end, detections: r.detections ?? {} };
      })
      .catch(() => {})
      .finally(() => {
        loadingRef.current = false;
      });
  }, [videoId, currentTime, enabled]);

  /* 绘制：currentTime / 窗口数据变化时重绘 */
  useEffect(() => {
    const canvas = canvasRef.current;
    const v = videoRef.current;
    if (!canvas || !v || !enabled) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const w = v.clientWidth;
    const h = v.clientHeight;
    if (w === 0 || h === 0) return;
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    ctx.clearRect(0, 0, w, h);

    const range = rangeRef.current;
    if (!range) return;

    /* 匹配最近的检测帧 key（0.1s 精度字符串） */
    let bestKey: string | null = null;
    let bestDiff = MAX_KEY_DIFF;
    for (const k of Object.keys(range.detections)) {
      const diff = Math.abs(parseFloat(k) - currentTime);
      if (diff <= bestDiff) {
        bestDiff = diff;
        bestKey = k;
      }
    }
    if (!bestKey) return;

    /* object-contain letterbox 补偿：视频实际显示区域 */
    const vW = v.videoWidth || 1;
    const vH = v.videoHeight || 1;
    const scale = Math.min(w / vW, h / vH);
    const dw = vW * scale;
    const dh = vH * scale;
    const ox = (w - dw) / 2;
    const oy = (h - dh) / 2;

    for (const d of range.detections[bestKey]) {
      const norm = d.bbox.x1 <= 1 && d.bbox.y1 <= 1 && d.bbox.x2 <= 1 && d.bbox.y2 <= 1;
      const nx1 = norm ? d.bbox.x1 : d.bbox.x1 / vW;
      const ny1 = norm ? d.bbox.y1 : d.bbox.y1 / vH;
      const nx2 = norm ? d.bbox.x2 : d.bbox.x2 / vW;
      const ny2 = norm ? d.bbox.y2 : d.bbox.y2 / vH;
      const x1 = ox + nx1 * dw;
      const y1 = oy + ny1 * dh;
      const x2 = ox + nx2 * dw;
      const y2 = oy + ny2 * dh;
      const color = colorOf(d.class_name);

      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);

      /* 类别标签 */
      const label = `${zh(d.class_name)} #${d.display_seq ?? d.track_id}`;
      ctx.font = "12px sans-serif";
      const tw = ctx.measureText(label).width + 8;
      const ly = y1 - 16 < 0 ? y1 + 2 : y1 - 16;
      ctx.fillStyle = color;
      ctx.fillRect(x1, ly, tw, 16);
      ctx.fillStyle = "#fff";
      ctx.fillText(label, x1 + 4, ly + 12);
    }
  }, [currentTime, enabled, videoId, videoRef]);

  if (!enabled) return null;
  return <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" />;
}
