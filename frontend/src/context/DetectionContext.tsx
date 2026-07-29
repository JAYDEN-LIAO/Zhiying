import { createContext, useContext, useCallback, useState } from "react";
import type { DetectionData, FaceData, PlateData } from "../types";

export interface DetectionContextValue {
  detectionData: DetectionData | null;
  faceData: FaceData | null;
  plateData: PlateData | null;
  selectedTrackId: number | null;
  tracked: { class_name: string; track_id: number } | null;
  classFilter: string | null;
  setDetectionData: (d: DetectionData | null) => void;
  setFaceData: (d: FaceData | null) => void;
  setPlateData: (d: PlateData | null) => void;
  onTrackSelect: (trackId: number, className: string, seekTo?: number) => void;
  onClassFilterChange: (cls: string | null) => void;
}

const DetectionContext = createContext<DetectionContextValue | null>(null);

export function DetectionProvider({ children }: { children: React.ReactNode }) {
  const [detectionData, setDetectionData] = useState<DetectionData | null>(null);
  const [faceData, setFaceData] = useState<FaceData | null>(null);
  const [plateData, setPlateData] = useState<PlateData | null>(null);
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [tracked, setTracked] = useState<{ class_name: string; track_id: number } | null>(null);
  const [classFilter, setClassFilter] = useState<string | null>(null);

  const onTrackSelect = useCallback((trackId: number, className: string, seekTo?: number) => {
    if (trackId < 0) {
      setSelectedTrackId(null);
      setTracked(null);
      return;
    }
    setSelectedTrackId(trackId);
    setTracked({ class_name: className, track_id: trackId });
  }, []);

  const onClassFilterChange = useCallback((cls: string | null) => {
    setClassFilter(cls);
  }, []);

  return (
    <DetectionContext.Provider
      value={{
        detectionData, setDetectionData,
        faceData, setFaceData,
        plateData, setPlateData,
        selectedTrackId, tracked,
        classFilter,
        onTrackSelect,
        onClassFilterChange,
      }}
    >
      {children}
    </DetectionContext.Provider>
  );
}

export function useDetection(): DetectionContextValue {
  const ctx = useContext(DetectionContext);
  if (!ctx) throw new Error("useDetection must be used within DetectionProvider");
  return ctx;
}
