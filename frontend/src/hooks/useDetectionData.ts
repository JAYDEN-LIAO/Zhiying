import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { DetectionData, FaceData, PlateData } from "../types";

interface DetectionDataResult {
  detectionData: DetectionData | null;
  faceData: FaceData | null;
  plateData: PlateData | null;
}

/**
 * Lazy-loads detection, face, and plate data when a video is completed
 * and the respective feature toggles are enabled.
 */
export function useDetectionData(
  videoId: string | null,
  enabled: boolean,
  faceEnabled: boolean,
  plateEnabled: boolean,
): DetectionDataResult {
  const [detectionData, setDetectionData] = useState<DetectionData | null>(null);
  const [faceData, setFaceData] = useState<FaceData | null>(null);
  const [plateData, setPlateData] = useState<PlateData | null>(null);

  useEffect(() => {
    if (!videoId || !enabled) {
      setDetectionData(null);
      setFaceData(null);
      setPlateData(null);
      return;
    }

    // 竞态守卫：快速切换视频时旧请求晚到不得覆盖新视频数据（对齐 useVideoPolling 的 cancelled 模式）
    let cancelled = false;

    api.fetchDetectionTracks(videoId)
      .then((d) => { if (!cancelled) setDetectionData(d); })
      .catch(() => { if (!cancelled) setDetectionData(null); });

    if (faceEnabled) {
      api.fetchFaceData(videoId)
        .then((d) => { if (!cancelled) setFaceData(d); })
        .catch(() => { if (!cancelled) setFaceData(null); });
    } else {
      setFaceData(null);
    }

    if (plateEnabled) {
      api.fetchPlateData(videoId)
        .then((d) => { if (!cancelled) setPlateData(d); })
        .catch(() => { if (!cancelled) setPlateData(null); });
    } else {
      setPlateData(null);
    }

    return () => { cancelled = true; };
  }, [videoId, enabled, faceEnabled, plateEnabled]);

  return { detectionData, faceData, plateData };
}
