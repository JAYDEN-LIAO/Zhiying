import { useMemo } from "react";
import type { VideoResponse } from "../types";

/**
 * Computes whether the video stream URL is safe to load in the browser.
 * Handles 4 cases:
 * - H.264 → always ready
 * - HEVC + hevcOk (Safari/Electron) → MP4 container OK, else needs remux
 * - Other codecs → needs proxy to be ready
 */
export function useStreamReady(
  video: VideoResponse | null,
  hevcOk: boolean,
): boolean {
  return useMemo(() => {
    if (!video) return false;
    const vc = video.video_codec;
    const cf = video.container_format;
    if (!vc) return false;
    // H.264: always browser-safe
    if (vc === "h264") return true;
    // HEVC on capable browser: MP4 direct, otherwise needs remux
    if (vc === "hevc" && hevcOk) {
      if (cf === "mp4") return true;
      return !!video.remuxed_path;
    }
    // Other codecs or non-HEVC browser: wait for proxy
    return video.proxy_status === "ready";
  }, [video?.video_codec, video?.container_format, video?.remuxed_path, video?.proxy_status, hevcOk]);
}
