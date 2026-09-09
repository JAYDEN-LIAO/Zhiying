import { useRef } from "react";
import { formatSec } from "../../utils/helpers";
import { colorOf, zh } from "../../labels";
import type { Track } from "../../types";

/* ════════════════════════════════════════════════════════════
   EventTimeline — 事件标记进度条（播放器底部）
   检测轨迹出现区间按类别着色标记 + 播放位置指示 + 点击/拖拽 seek
   ════════════════════════════════════════════════════════════ */

export function EventTimeline({
  duration,
  currentTime,
  tracks,
  onSeek,
}: {
  duration: number;
  currentTime: number;
  tracks: Track[];
  onSeek: (sec: number) => void;
}) {
  const barRef = useRef<HTMLDivElement>(null);

  const seekAt = (clientX: number) => {
    const rect = barRef.current?.getBoundingClientRect();
    if (!rect || duration <= 0) return;
    const pct = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    onSeek(pct * duration);
  };

  const pct = duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0;

  return (
    <div className="shrink-0 rounded-card bg-card-bg px-4 py-3 shadow-card">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-semibold text-gray-500">事件标记</p>
        <span className="text-xs tabular-nums text-gray-400">
          {formatSec(currentTime)} / {formatSec(duration)}
        </span>
      </div>

      <div
        ref={barRef}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          seekAt(e.clientX);
        }}
        onPointerMove={(e) => {
          if (e.buttons === 1) seekAt(e.clientX);
        }}
        className="relative h-3 cursor-pointer touch-none rounded-full bg-gray-100"
      >
        {/* 轨迹区段标记（segments 优先，缺省用 first_seen → last_seen） */}
        {duration > 0 &&
          tracks.flatMap((t) =>
            (t.segments ?? [{ start: t.first_seen, end: t.last_seen }]).map((seg, i) => (
              <div
                key={`${t.track_id}-${i}`}
                className="absolute top-0 h-full rounded-full opacity-70 transition-opacity hover:opacity-100"
                style={{
                  left: `${(seg.start / duration) * 100}%`,
                  width: `${Math.max(0.4, ((seg.end - seg.start) / duration) * 100)}%`,
                  backgroundColor: colorOf(t.class_name),
                }}
                title={`${zh(t.class_name)} ${formatSec(seg.start)} → ${formatSec(seg.end)}`}
              />
            )),
          )}
        {/* 播放位置指示 */}
        <div
          className="pointer-events-none absolute top-[-3px] h-[calc(100%+6px)] w-[3px] rounded-full bg-primary shadow"
          style={{ left: `calc(${pct}% - 1.5px)` }}
        />
      </div>

      {tracks.length === 0 && (
        <p className="mt-1.5 text-center text-[11px] text-gray-300">
          暂无事件标记（解析时启用目标检测后显示）
        </p>
      )}
    </div>
  );
}
