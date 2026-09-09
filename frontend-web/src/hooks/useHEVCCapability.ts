import { useState, useEffect } from "react";

/**
 * Detects browser HEVC (H.265) playback capability via canPlayType.
 * Web 端 H.265 支持因浏览器而异，流地址需带 hevc_ok 参数。
 */
export function useHEVCCapability(): boolean {
  const [hevcOk, setHevcOk] = useState(false);
  useEffect(() => {
    const v = document.createElement("video");
    setHevcOk(v.canPlayType('video/mp4; codecs="hvc1.1.6.L123.B0"') !== "");
  }, []);
  return hevcOk;
}
