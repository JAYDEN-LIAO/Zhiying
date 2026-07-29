import { useState, useMemo, useCallback } from "react";
import type { ContentType } from "../types";

export type ModuleKey = "vision" | "audio" | "ocr" | "caption" | "detection";

interface AdvancedParams {
  language: string;
  sampleFps: number;
  segmentThreshold: number;
  captionWithContext: boolean;
  summaryDetail: string;
  encodeProfile: string | null;
}

const CUSTOM_PARAMS_KEY = "cerno_custom_params";

/** Which feature modules are available in the backend (hardware/model support). */
const MODULE_AVAILABLE: Record<ModuleKey, boolean> = {
  vision: true,
  audio: false,   // faster-whisper disabled by default
  ocr: false,     // PaddleOCR stub
  caption: true,
  detection: true,
};

/** Preset configurations for each scene type. */
export const PRESETS: Record<Exclude<ContentType, "custom">, {
  modules: Record<ModuleKey, boolean>;
  functions: { searchIndex: boolean; summary: boolean };
  advanced: AdvancedParams;
  summaryMode: string;
  detectionClasses: string[] | null;
  faceEnabled: boolean;
  plateEnabled: boolean;
}> = {
  general: {
    modules: { vision: true, audio: false, ocr: false, caption: true, detection: false },
    functions: { searchIndex: true, summary: true },
    advanced: { language: "auto", sampleFps: 1.0, segmentThreshold: 0.5, captionWithContext: true, summaryDetail: "standard", encodeProfile: null },
    summaryMode: "native_video",
    detectionClasses: null,
    faceEnabled: false,
    plateEnabled: false,
  },
  meeting: {
    modules: { vision: true, audio: true, ocr: true, caption: true, detection: false },
    functions: { searchIndex: true, summary: true },
    advanced: { language: "auto", sampleFps: 1.0, segmentThreshold: 0.3, captionWithContext: true, summaryDetail: "standard", encodeProfile: null },
    summaryMode: "native_video",
    detectionClasses: null,
    faceEnabled: false,
    plateEnabled: false,
  },
  surveillance: {
    modules: { vision: true, audio: false, ocr: false, caption: true, detection: true },
    functions: { searchIndex: true, summary: false },
    advanced: { language: "auto", sampleFps: 2.0, segmentThreshold: 0.5, captionWithContext: false, summaryDetail: "standard", encodeProfile: null },
    summaryMode: "native_video",
    detectionClasses: null,
    faceEnabled: true,
    plateEnabled: true,
  },
  text_recognition: {
    modules: { vision: true, audio: false, ocr: true, caption: false, detection: false },
    functions: { searchIndex: true, summary: false },
    advanced: { language: "auto", sampleFps: 1.0, segmentThreshold: 0.5, captionWithContext: true, summaryDetail: "standard", encodeProfile: null },
    summaryMode: "native_video",
    detectionClasses: null,
    faceEnabled: false,
    plateEnabled: false,
  },
};

const DEFAULT_ADVANCED: AdvancedParams = {
  language: "auto", sampleFps: 1.0, segmentThreshold: 0.5,
  captionWithContext: true, summaryDetail: "standard", encodeProfile: null,
};

/**
 * Gets whether a module is grayed out (unavailable in the UI).
 */
export function isModuleGrayed(
  key: ModuleKey,
  modules: Record<ModuleKey, boolean>,
  functions: { summary: boolean },
): boolean {
  if (key === "audio") return true;  // always unavailable in this build
  if (key === "ocr") return !modules.vision;
  if (key === "caption") return !modules.vision;
  if (key === "detection") return !modules.vision;
  return false;
}

/**
 * Gets whether an advanced param control should be grayed.
 */
export function isAdvancedGrayed(
  field: keyof AdvancedParams | "summary_mode",
  modules: Record<ModuleKey, boolean>,
  functions: { summary: boolean; searchIndex: boolean },
): boolean {
  if (field === "language") return !modules.audio;
  if (field === "sampleFps") return !modules.vision;
  if (field === "captionWithContext") return !modules.caption;
  if (field === "summaryDetail") return !(functions.summary && modules.caption);
  if (field === "summary_mode") return !functions.summary;
  return false;
}

/**
 * Cascading module invalidation:
 * vision OFF → ocr, caption, detection OFF
 * caption OFF → summary OFF
 */
export function applyCascade(
  modules: Record<ModuleKey, boolean>,
  functions: { searchIndex: boolean; summary: boolean },
): { modules: Record<ModuleKey, boolean>; functions: { searchIndex: boolean; summary: boolean } } {
  const m = { ...modules };
  const f = { ...functions };
  if (!m.vision) {
    m.ocr = false;
    m.caption = false;
    m.detection = false;
  }
  if (!m.caption) {
    f.summary = false;
  }
  return { modules: m, functions: f };
}

/**
 * Custom form state hook for the parameter panel.
 * Preserves "custom" settings in localStorage.
 */
export function useParameterForm(initialVideo?: { content_type: ContentType } | null) {
  const savedCustom = useMemo(() => {
    try {
      const raw = localStorage.getItem(CUSTOM_PARAMS_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }, []);

  const [sceneType, setSceneType] = useState<ContentType>(
    initialVideo?.content_type ?? savedCustom?.sceneType ?? "general",
  );
  const [modules, setModules] = useState<Record<ModuleKey, boolean>>(
    savedCustom?.modules ?? PRESETS.general.modules,
  );
  const [functions, setFunctions] = useState<{ searchIndex: boolean; summary: boolean }>(
    savedCustom?.functions ?? PRESETS.general.functions,
  );
  const [advanced, setAdvanced] = useState<AdvancedParams>(
    savedCustom?.advanced ?? DEFAULT_ADVANCED,
  );
  const [summaryMode, setSummaryMode] = useState<string>(
    savedCustom?.summaryMode ?? "native_video",
  );
  const [detectionClasses, setDetectionClasses] = useState<string[] | null>(
    savedCustom?.detectionClasses ?? null,
  );
  const [faceEnabled, setFaceEnabled] = useState<boolean>(
    savedCustom?.faceEnabled ?? false,
  );
  const [plateEnabled, setPlateEnabled] = useState<boolean>(
    savedCustom?.plateEnabled ?? false,
  );

  // Apply preset when scene type changes (unless custom)
  const applyPreset = useCallback((ct: ContentType) => {
    setSceneType(ct);
    if (ct === "custom") return;
    const p = PRESETS[ct as Exclude<ContentType, "custom">];
    if (!p) return;
    setModules(p.modules);
    setFunctions(p.functions);
    setAdvanced(p.advanced);
    setSummaryMode(p.summaryMode);
    setDetectionClasses(p.detectionClasses);
    setFaceEnabled(p.faceEnabled);
    setPlateEnabled(p.plateEnabled);
    localStorage.removeItem(CUSTOM_PARAMS_KEY);
  }, []);

  // Persist custom params
  const saveCustom = useCallback(() => {
    if (sceneType === "custom") {
      localStorage.setItem(CUSTOM_PARAMS_KEY, JSON.stringify({
        sceneType, modules, functions, advanced, summaryMode, detectionClasses, faceEnabled, plateEnabled,
      }));
    }
  }, [sceneType, modules, functions, advanced, summaryMode, detectionClasses, faceEnabled, plateEnabled]);

  const cascaded = useMemo(() => applyCascade(modules, functions), [modules, functions]);

  const allGrayed = useMemo(() => ({
    audio: isModuleGrayed("audio", modules, functions),
    ocr: isModuleGrayed("ocr", modules, functions),
    caption: isModuleGrayed("caption", modules, functions),
    detection: isModuleGrayed("detection", modules, functions),
    language: isAdvancedGrayed("language", modules, functions),
    sampleFps: isAdvancedGrayed("sampleFps", modules, functions),
    captionWithContext: isAdvancedGrayed("captionWithContext", modules, functions),
    summaryDetail: isAdvancedGrayed("summaryDetail", modules, functions),
    summary_mode: isAdvancedGrayed("summary_mode", modules, functions),
  }), [modules, functions]);

  return {
    sceneType, setSceneType: applyPreset,
    modules, setModules,
    functions, setFunctions,
    advanced, setAdvanced,
    summaryMode, setSummaryMode,
    detectionClasses, setDetectionClasses,
    faceEnabled, setFaceEnabled,
    plateEnabled, setPlateEnabled,
    cascaded,
    grayed: allGrayed,
    saveCustom,
    moduleAvailable: MODULE_AVAILABLE,
  };
}
