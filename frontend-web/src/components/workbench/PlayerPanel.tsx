import { useEffect, useRef, useState, type RefObject } from "react";
import { api } from "../../services/api";
import { useHEVCCapability } from "../../hooks/useHEVCCapability";
import { DetectionCanvas } from "./DetectionCanvas";
import { EventTimeline } from "./EventTimeline";
import type { DetectionData, VideoResponse } from "../../types";

/* ════════════════════════════════════════════════════════════
   PlayerPanel — 智能解析页左列
   视频播放器（HEVC 自适应 + 分析进度浮层）
   + DetectionCanvas AI 识别框覆盖层（可开关）
   + 底部事件标记进度条
   videoRef / currentTime 由 ParsePage 统一持有，Canvas 与时间轴共享
   （「更换视频」入口在 TopNav 右侧功能区）
   ════════════════════════════════════════════════════════════ */

function AnalysisOverlay({ video }: { video: VideoResponse | null }) {
  if (!video || (video.status !== "pending" && video.status !== "processing")) return null;
  const pct = Math.round(video.progress);
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/60 backdrop-blur-[2px]">
      <p className="text-sm text-white/90">
        {video.status === "processing" ? "正在解析" : "排队中"} · {pct}%
      </p>
      <div className="h-1 w-48 overflow-hidden rounded-full bg-white/20">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function PlayerPanel({
  video,
  detections,
  videoRef,
  currentTime,
  onTimeUpdate,
  seekTo,
  onSeek,
}: {
  video: VideoResponse | null;
  detections: DetectionData | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  currentTime: number;
  onTimeUpdate: (t: number) => void;
  seekTo: number | null;
  onSeek: (sec: number) => void;
}) {
  const hevcOk = useHEVCCapability();

  /* 跨页 seek（全局搜索命中片段 → 定位播放）。
     播放器元数据未就绪时挂起，onLoadedMetadata 再应用 */
  const pendingSeekRef = useRef<number | null>(null);
  useEffect(() => {
    if (seekTo == null) return;
    const el = videoRef.current;
    if (el && el.readyState >= 1) {
      el.currentTime = seekTo;
      void el.play().catch(() => {});
      pendingSeekRef.current = null;
    } else {
      pendingSeekRef.current = seekTo;
    }
  }, [seekTo, videoRef]);
  const applyPendingSeek = () => {
    const el = videoRef.current;
    const s = pendingSeekRef.current;
    if (el && s != null) {
      pendingSeekRef.current = null;
      el.currentTime = s;
      void el.play().catch(() => {});
    }
  };

  const duration = video?.duration ?? 0;
  const streamUrl = video ? api.getVideoStreamUrl(video.id, hevcOk) : "";
  const hasDetection = !!detections?.has_detection && (detections.tracks.length ?? 0) > 0;

  return (
    <div className="flex h-full min-w-0 flex-col gap-3">
      {/* 播放器 + Canvas 识别框覆盖层 */}
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-card bg-black shadow-card">
        {streamUrl ? (
          <video
            ref={videoRef}
            src={streamUrl}
            controls
            playsInline
            onLoadedMetadata={applyPendingSeek}
            onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime)}
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-sm text-white/60">加载中…</div>
        )}
        <DetectionCanvas
          videoId={video?.id ?? null}
          videoRef={videoRef}
          currentTime={currentTime}
          enabled={hasDetection}
        />
        <AnalysisOverlay video={video} />
      </div>

      {/* 事件标记进度条 */}
      <EventTimeline duration={duration} currentTime={currentTime} tracks={detections?.tracks ?? []} onSeek={onSeek} />
    </div>
  );
}
