import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import type { Detection, DetectionRange } from "../types";

// v0.22 (S4 打磨):
//   窗口按 30s 网格对齐 —— t 在同一格内窗口 key 稳定，播放中约每 30s 才发一次请求
//   （原先按 t 实时计算窗口，key 每秒变化 → 播放中 ~1 请求/秒的冗余轰炸）。
//   窗口 = [grid-31, grid+61]：覆盖 t±31（floor/ceil 插值 + trail 过去 2s）+ 30s 预取。
const GRID_SEC = 30;
const MAX_RANGES = 12;       // 上限 ≈ 12 段（12×~92s ≈ 18 分钟播放窗口），超出淘汰最旧

/**
 * DetectionOverlay 的按需区间加载 hook（v0.22, S2/B2）。
 *
 * 不再一次性持有全量 detections（长视频 = 15MB+ JSON），而是跟随 video.currentTime
 * 加载当前 ±30s 窗口 + 预取下一段；LRU 上限淘汰，重叠去重，组切换/禁用时清空。
 *
 * 对外暴露：
 *   - get(ts): 稳定查找函数（读 ref，不随渲染变化）→ 命中窗口返回该帧 detections，否则 []
 *   - version: 每加载一段 +1，供 Overlay 监听以在数据到达时重绘（含暂停态 seek 场景）
 */
export function useDetectionRanges(
  videoId: string | null,
  videoRef: React.RefObject<HTMLVideoElement | null>,
  enabled: boolean,
  hasDetection: boolean,
): { get: (ts: number) => Detection[]; version: number } {
  const rangesRef = useRef<DetectionRange[]>([]);
  const loadedKeys = useRef<Set<string>>(new Set());
  const inflight = useRef<Set<string>>(new Set());
  const [version, setVersion] = useState(0);

  const rangeKey = useCallback((start: number, end: number) => {
    return `${Math.floor(start)}:${Math.ceil(end)}`;
  }, []);

  const loadRange = useCallback(
    async (start: number, end: number) => {
      if (!videoId || !enabled || !hasDetection) return;
      const key = rangeKey(start, end);
      if (loadedKeys.current.has(key) || inflight.current.has(key)) return;
      inflight.current.add(key);
      try {
        const data = await api.fetchDetectionRange(videoId, start, end);
        if (!data) return;
        const dkey = rangeKey(data.start_sec, data.end_sec);
        // 重叠去重（预取与补拉可能重叠）：同 key 替换，新段追加
        const merged = [
          ...rangesRef.current.filter((r) => rangeKey(r.start_sec, r.end_sec) !== dkey),
          data,
        ];
        // LRU 淘汰：被丢掉的窗口必须同步清除 loaded 标记，
        // 否则 revisit 该时间窗时 loadedKeys 命中 → 不重新拉取 → bbox 消失（S4 修复）
        if (merged.length > MAX_RANGES) {
          for (const dropped of merged.slice(0, merged.length - MAX_RANGES)) {
            loadedKeys.current.delete(rangeKey(dropped.start_sec, dropped.end_sec));
          }
        }
        rangesRef.current = merged.slice(-MAX_RANGES);
        loadedKeys.current.add(dkey);
        setVersion((v) => v + 1);
      } finally {
        inflight.current.delete(key);
      }
    },
    [videoId, enabled, hasDetection, rangeKey],
  );

  const ensureWindow = useCallback(
    (t: number) => {
      if (!(t >= 0)) return;
      // 30s 网格对齐：t 在同一格内 key 稳定；跨格才触发新请求（播放中约 30s 一次）
      const grid = Math.floor(t / GRID_SEC) * GRID_SEC;
      const start = Math.max(0, grid - 31);   // 覆盖 t-31（插值 floor/ceil + trail 过去 2s）
      const end = grid + 31 + 30;             // 当前 ±31 + 30s 预取，段间无缝
      loadRange(start, end);
    },
    [loadRange],
  );

  // 跟随视频：seeked / timeupdate → 加载对应窗口
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !enabled || !hasDetection) return;
    const onTime = () => ensureWindow(video.currentTime);
    video.addEventListener("seeked", onTime);
    video.addEventListener("timeupdate", onTime);
    ensureWindow(video.currentTime || 0);
    return () => {
      video.removeEventListener("seeked", onTime);
      video.removeEventListener("timeupdate", onTime);
    };
  }, [videoRef, enabled, hasDetection, ensureWindow]);

  // 组切换 / 禁用 → 清空缓存
  useEffect(() => {
    if (!videoId || !enabled || !hasDetection) {
      rangesRef.current = [];
      loadedKeys.current.clear();
      inflight.current.clear();
      setVersion((v) => v + 1);
    }
  }, [videoId, enabled, hasDetection]);

  // 稳定查找（读 ref，不随渲染变化 —— Overlay 的 draw useCallback 可依赖它保持稳定）
  const get = useCallback((ts: number): Detection[] => {
    const ranges = rangesRef.current;
    if (!ranges.length) return [];
    const key = ts.toFixed(1);
    for (const r of ranges) {
      if (ts >= r.start_sec - 0.05 && ts <= r.end_sec + 0.05) {
        return r.detections[key] ?? [];
      }
    }
    return [];
  }, []);

  return { get, version };
}
