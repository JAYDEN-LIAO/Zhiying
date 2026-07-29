import { useState, useEffect } from "react";

/**
 * Detects browser HEVC (H.265) playback capability via canPlayType.
 */
export function useHEVCCapability(): boolean {
  const [hevcOk, setHevcOk] = useState(false);
  useEffect(() => {
    const v = document.createElement("video");
    setHevcOk(v.canPlayType('video/mp4; codecs="hvc1.1.6.L123.B0"') !== "");
  }, []);
  return hevcOk;
}
