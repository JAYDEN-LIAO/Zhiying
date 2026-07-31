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

    api.fetchDetectionTracks(videoId)
      .then((d) => setDetectionData(d))
      .catch(() => setDetectionData(null));

    if (faceEnabled) {
      api.fetchFaceData(videoId)
        .then((d) => setFaceData(d))
        .catch(() => setFaceData(null));
    } else {
      setFaceData(null);
    }

    if (plateEnabled) {
      api.fetchPlateData(videoId)
        .then((d) => setPlateData(d))
        .catch(() => setPlateData(null));
    } else {
      setPlateData(null);
    }
  }, [videoId, enabled, faceEnabled, plateEnabled]);

  return { detectionData, faceData, plateData };
}
