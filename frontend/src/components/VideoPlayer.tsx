/* ════════════════════════════════════════════════════════════
   VideoPlayer — 视频播放器封装 + 格式覆盖层 + DetectionOverlay
   ════════════════════════════════════════════════════════════ */

import { RefObject, useEffect } from "react";
import { api } from "../services/api";
import { DetectionOverlay } from "./DetectionOverlay";
import type { VideoResponse, DetectionData, ProxyStatus } from "../types";

interface Props {
  videoId: string | null;
  video: VideoResponse | null;
  streamReady: boolean;
  hevcOk: boolean;
  isUploading: boolean;
  detectionEnabled: boolean;
  hasDetection: boolean;
  detectionData: DetectionData | null;
  selectedTrackId: number | null;
  proxyStatus: ProxyStatus | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  onTrackSelect: (trackId: number, className: string) => void;
}

export function VideoPlayer({
  videoId,
  video,
  streamReady,
  hevcOk,
  isUploading,
  detectionEnabled,
  hasDetection,
  detectionData,
  selectedTrackId,
  proxyStatus,
  videoRef,
  onTrackSelect,
}: Props) {

  // Force reload when stream becomes ready
  useEffect(() => {
    if (streamReady && videoRef.current) {
      videoRef.current.load();
    }
  }, [streamReady]);

  // Pass videoRef up to parent via callback ref
  // (The parent accesses it for seek/currentTime control)

  return (
    <div className="video-player-wrap">
      {videoId && video ? (
        <div className="relative w-full h-full">

          {/* Format not ready — show preparing overlay */}
          {!streamReady ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/80 z-20">
              <div className="w-10 h-10 rounded-full border-2 border-white/30 border-t-white animate-spin" />
              <p className="text-sm text-white/70 font-medium">
                {!video.video_codec ? "正在分析视频格式…" : "正在准备视频流…"}
              </p>
              {proxyStatus && proxyStatus.status === "processing" && (
                <>
                  <div className="w-48 h-1.5 bg-white/20 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-400 rounded-full transition-all duration-500"
                      style={{ width: `${Math.round((proxyStatus.progress || 0) * 100)}%` }}
                    />
                  </div>
                  <p className="text-xs text-white/50 font-mono">
                    {Math.round((proxyStatus.progress || 0) * 100)}%
                  </p>
                </>
              )}
            </div>
          ) : (
            <video
              ref={videoRef}
              key={videoId}
              className="w-full h-full object-contain bg-black"
              src={api.getVideoStreamUrl(videoId, hevcOk)}
              controls
              autoPlay={false}
              preload="auto"
              playsInline
            >
              您的浏览器不支持视频播放
            </video>
          )}

          {/* Detection overlay */}
          {streamReady && hasDetection && (
            <DetectionOverlay
              videoRef={videoRef}
              videoId={videoId}
              enabled={detectionEnabled}
              data={detectionData}
              selectedTrackId={selectedTrackId}
              onTrackSelect={onTrackSelect}
            />
          )}

          {/* Proxy failed overlay */}
          {proxyStatus && proxyStatus.status === "failed" && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/70 backdrop-blur-sm z-30">
              <p className="text-sm text-red-400">
                浏览器兼容代理生成失败 — 请使用 Safari 或 Electron 打开
              </p>
            </div>
          )}
        </div>
      ) : isUploading ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
          <div className="w-12 h-12 rounded-full bg-black/30 flex items-center justify-center shadow-lg">
            <svg className="w-6 h-6 text-white animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
          <p className="text-sm text-gray-400">视频上传中...</p>
        </div>
      ) : (
        <div className="video-placeholder">
          <div className="vp-icon">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.5">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
          </div>
          <span className="vp-text">上传或选择视频开始分析</span>
        </div>
      )}
    </div>
  );
}
