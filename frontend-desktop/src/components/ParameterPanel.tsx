/* ════════════════════════════════════════════════════════════
   ParameterPanel — v0.36 简化布局（扁平功能开关 + 可折叠子项）
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useMemo } from "react";
import { IconClose } from "./icons";
import { api } from "../services/api";
import type { ContentType, PipelineParams } from "../types";
import { zh } from "../labels";

/* ── 场景预设（一键配置所有开关）── */
const SCENE_PRESETS: Record<string, {
  label: string; desc: string;
  modules: { vision: boolean; audio: boolean; ocr: boolean; detection: boolean };
  functions: { searchIndex: boolean; summary: boolean };
  faceEnabled?: boolean; plateEnabled?: boolean;
}> = {
  general:       { label: "通用",     desc: "均衡模式", modules: { vision: true, audio: false, ocr: false, detection: false }, functions: { searchIndex: true, summary: false } },
  meeting:       { label: "会议",     desc: "语音对话核心", modules: { vision: true, audio: true, ocr: true, detection: false }, functions: { searchIndex: true, summary: true } },
  surveillance:  { label: "监控",     desc: "固定机位纯视觉", modules: { vision: true, audio: false, ocr: false, detection: true }, functions: { searchIndex: true, summary: false }, faceEnabled: true, plateEnabled: true },
  text_recognition: { label: "文字识别", desc: "文件/聊天/票据", modules: { vision: true, audio: false, ocr: true, detection: false }, functions: { searchIndex: false, summary: false } },
};

/* ── 功能开关列表（扁平 2-col grid，渲染顺序即视觉顺序）── */
const MODULES: Array<{
  key: "vision" | "audio" | "detection" | "ocr";
  label: string; hint: string;
  color: string; border: string;
}> = [
  { key: "vision",     label: "视觉分析", hint: "帧处理总开关", color: "bg-blue-50/60",  border: "border-blue-200" },
  { key: "audio",      label: "音频转录", hint: "语音转文字",   color: "bg-amber-50/60", border: "border-amber-200" },
  { key: "detection",  label: "物体检测", hint: "YOLO11 + 追踪", color: "bg-orange-50/60", border: "border-orange-200" },
  { key: "ocr",        label: "文字识别", hint: "提取画面文字",  color: "bg-emerald-50/60", border: "border-emerald-200" },
];

/* ── COCO 80 类 ── */
const COCO_ALL = [
  "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
  "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
  "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
  "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
  "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
  "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
  "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
  "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
  "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
  "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
  "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
  "toothbrush",
];
const COMMON_CLASSES = ["person", "car", "truck", "bus", "motorcycle", "dog", "cat"];

type ModuleKey = "vision" | "audio" | "ocr" | "detection";
const CUSTOM_PARAMS_KEY = "zhiying_custom_params";

function loadCustomParams(): Record<string, unknown> | null {
  try { const raw = localStorage.getItem(CUSTOM_PARAMS_KEY); return raw ? JSON.parse(raw) : null; } catch { return null; }
}
function saveCustomParams(params: Record<string, unknown>) { localStorage.setItem(CUSTOM_PARAMS_KEY, JSON.stringify(params)); }

export function ParameterPanel({
  videoId, onClose, onParamsSet, onUploadDone,
  reparse = false, batchCount, onBatchSubmit,
}: {
  videoId?: string | null;
  onClose: () => void;
  onParamsSet: () => void;
  onUploadDone?: (newVideoId: string) => void;
  reparse?: boolean;
  batchCount?: number;
  onBatchSubmit?: (params: PipelineParams) => Promise<void>;
}) {
  const [sceneType, setSceneType] = useState<ContentType>(() => {
    const saved = loadCustomParams(); return (saved?.sceneType as ContentType) ?? "general";
  });
  const [modules, setModules] = useState<Record<ModuleKey, boolean>>(() => {
    const saved = loadCustomParams();
    if (saved?.modules) { const { caption: _, ...m } = saved.modules as Record<string, boolean>; return { vision: false, audio: false, ocr: false, detection: false, ...m }; }
    return { ...SCENE_PRESETS.general.modules };
  });
  const [functions, setFunctions] = useState<Record<string, boolean>>(() => {
    const saved = loadCustomParams();
    if (saved?.functions) { const f = saved.functions as Record<string, boolean>; return { searchIndex: f.searchIndex ?? true, summary: f.summary ?? true }; }
    return { ...SCENE_PRESETS.general.functions };
  });
  const [summaryMode, setSummaryMode] = useState<string>(() => {
    const saved = loadCustomParams();
    const m = saved?.summaryMode as string; return m === "native_video" ? "vlm_llm" : (m ?? "vlm_llm");
  });
  const [detectionClasses, setDetectionClasses] = useState<string[] | null>(() => {
    const saved = loadCustomParams(); return (saved?.detectionClasses as string[] | null) ?? null;
  });
  const [faceEnabled, setFaceEnabled] = useState<boolean>(() => (loadCustomParams()?.faceEnabled as boolean) ?? false);
  const [plateEnabled, setPlateEnabled] = useState<boolean>(() => (loadCustomParams()?.plateEnabled as boolean) ?? false);
  const [classSearch, setClassSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [expandedClasses, setExpandedClasses] = useState(false);
  const [expandedSummary, setExpandedSummary] = useState(false);

  /* ── 插件可用性 ── */
  const [moduleAvailable, setModuleAvailable] = useState<Record<string, boolean>>({ audio: false, ocr: false, detection: true, face: true, plate: true });
  useEffect(() => {
    fetch("/api/v1/settings/pipeline").then(r => r.json()).then(d => {
      const p = d?.data?.plugins;
      if (p) setModuleAvailable({ audio: !!p.transcriber, ocr: !!p.ocr, detection: !!p.detector, face: !!p.face, plate: !!p.plate });
      if (d?.data?.default_summary_mode) setSummaryMode(c => c === "native_video" ? d.data.default_summary_mode : c);
    }).catch(() => {});
  }, []);

  /* ── 置灰逻辑（扁平化：每个开关直接判断）── */
  const grayed = useMemo(() => ({
    vision:     false, // 主开关永不禁用
    audio:      !moduleAvailable.audio,
    ocr:        !moduleAvailable.ocr || !modules.vision,
    detection:  !moduleAvailable.detection || !modules.vision,
    face:       !moduleAvailable.face || !modules.detection,
    plate:      !moduleAvailable.plate || !modules.detection,
  }), [modules, moduleAvailable]);

  /* ── 自定义参数持久化 ── */
  useEffect(() => {
    if (sceneType === "custom") saveCustomParams({ sceneType, modules, functions, summaryMode, detectionClasses, faceEnabled, plateEnabled });
  }, [sceneType, modules, functions, detectionClasses, summaryMode, faceEnabled, plateEnabled]);

  /* ── 场景切换 ── */
  const handlePreset = (key: string) => {
    const p = SCENE_PRESETS[key]; if (!p) return;
    setSceneType(key as ContentType);
    setModules({ ...p.modules });
    setFunctions({ ...p.functions });
    setFaceEnabled(p.faceEnabled ?? false);
    setPlateEnabled(p.plateEnabled ?? false);
    setError(null);
  };

  /* ── 自定义模式（从预设恢复上次保存）── */
  const enterCustom = () => {
    setSceneType("custom");
    const saved = loadCustomParams();
    if (saved?.modules) { const { caption: _, ...m } = saved.modules as Record<string, boolean>; setModules({ vision: false, audio: false, ocr: false, detection: false, ...m }); }
    if (saved?.functions) setFunctions(saved.functions as Record<string, boolean>);
    if (saved?.summaryMode) setSummaryMode(saved.summaryMode as string);
    if (saved?.faceEnabled !== undefined) setFaceEnabled(saved.faceEnabled as boolean);
    if (saved?.plateEnabled !== undefined) setPlateEnabled(saved.plateEnabled as boolean);
    setError(null);
  };

  /* ── L2 模块切换 ── */
  const toggleModule = (key: ModuleKey) => {
    if (grayed[key]) return;
    setModules(prev => {
      const next = { ...prev, [key]: !prev[key] };
      if (!next.vision) { next.ocr = false; next.detection = false; setFunctions(f => ({ ...f, summary: false })); }
      return next;
    });
    setSceneType("custom");
    setError(null);
  };

  const toggleFunction = (key: string) => {
    setFunctions(prev => ({ ...prev, [key]: !prev[key] }));
    setSceneType("custom");
    setError(null);
  };

  /* ── 校验 ── */
  const validate = (): string | null => {
    if (!modules.vision && !modules.audio) return "视觉分析和音频转录至少开启一个";
    if (!modules.vision && modules.detection) return "视觉分析已关闭，物体检测应同时关闭";
    if (!modules.vision && functions.summary) return "视觉分析已关闭，智能摘要应同时关闭";
    return null;
  };

  /* ── 提交（与原版完全一致）── */
  const handleSubmit = async () => {
    const err = validate(); if (err) { setError(err); return; }
    const buildParams = (): PipelineParams => ({
      content_type: sceneType, vision_enabled: modules.vision, audio_enabled: modules.audio,
      ocr_enabled: modules.ocr, caption_enabled: functions.summary, detection_enabled: modules.detection,
      detection_classes: modules.detection ? (detectionClasses?.length ? detectionClasses : null) : null,
      face_enabled: modules.detection ? faceEnabled : false, plate_enabled: modules.detection ? plateEnabled : false,
      search_index_enabled: functions.searchIndex, summary_enabled: functions.summary,
      summary_mode: summaryMode === "native_video" ? "vlm_llm" : summaryMode,
      language: "auto", sample_fps: 1.0, segment_threshold: 0.5,
      caption_with_context: true, summary_detail: "standard", encode_profile: null,
    });
    setSubmitting(true); setError(null);
    try {
      if (onBatchSubmit) {
        await onBatchSubmit(buildParams()); onParamsSet(); onClose();
      } else if (!videoId) {
        const input = document.createElement("input"); input.type = "file"; input.accept = ".mp4,.mov,.avi,.mkv,.webm";
        input.onchange = async () => {
          const file = input.files?.[0]; ac.abort();
          if (!file) { setSubmitting(false); return; }
          try { const r = await api.upload(file, buildParams()); await api.updateParams(r.id, buildParams()); onUploadDone?.(r.id); onParamsSet(); onClose(); }
          catch (e2) { setError(e2 instanceof Error ? e2.message : "上传失败"); }
          finally { setSubmitting(false); }
        };
        const ac = new AbortController();
        window.addEventListener("focus", () => setTimeout(() => setSubmitting(false), 500), { signal: ac.signal, once: true });
        input.click();
      } else if (reparse) {
        await api.reanalyze(videoId, buildParams()); onParamsSet(); onClose();
      } else {
        await api.updateParams(videoId, { ...buildParams(), apply_to_group: false }); onParamsSet(); onClose();
      }
      if (sceneType === "custom") saveCustomParams({ sceneType, modules, functions, summaryMode, detectionClasses, faceEnabled, plateEnabled });
      else localStorage.removeItem(CUSTOM_PARAMS_KEY);
    } catch (e) { setError(e instanceof Error ? e.message : "启动失败"); }
    finally { if (videoId || onBatchSubmit) setSubmitting(false); }
  };

  /* ── Toggle 子组件 ── */
  const Toggle = ({ checked, onChange, disabled }: { checked: boolean; onChange: () => void; disabled: boolean }) => (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-all duration-300 ease-out
        focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-600/60 focus-visible:ring-offset-2 focus-visible:ring-offset-white
        ${disabled ? "bg-gray-200 cursor-not-allowed" : checked ? "bg-teal-600 cursor-pointer shadow-[0_0_10px_rgba(79,124,255,0.35)]" : "bg-gray-200 cursor-pointer hover:bg-gray-300"}`}
      onClick={() => !disabled && onChange()}>
      <span style={{ backgroundColor: disabled ? "rgba(255,255,255,0.4)" : "#fff" }}
        className={`inline-block h-5 w-5 rounded-full shadow-md transition-all duration-300 ease-out ${checked ? "translate-x-[22px]" : "translate-x-0.5"}`} />
    </button>
  );

  const activePreset = sceneType !== "custom" ? sceneType : null;

  return (
    <div className="w-[min(840px,92vw)] h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 shrink-0">
        <h2 className="font-bold text-slate-800 text-base">
          {batchCount ? `批量解析（${batchCount} 个文件）` : "参数设置"}
        </h2>
        <button onClick={onClose} className="modal-x" title="关闭" aria-label="关闭"><IconClose /></button>
      </div>

      {/* Scrollable */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="space-y-5">

          {/* ── L1 场景类型 ── */}
          <section>
            <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">场景类型</h3>
            <div className="flex gap-1.5 flex-wrap">
              {Object.entries(SCENE_PRESETS).map(([key, { label }]) => (
                <button key={key} onClick={() => handlePreset(key)}
                  title={SCENE_PRESETS[key].desc}
                  className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
                    activePreset === key ? "bg-[#4f7cff] text-white shadow-sm" : "bg-gray-100/60 text-gray-600 hover:bg-gray-100"}`}>
                  {label}
                </button>
              ))}
              <button onClick={enterCustom}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
                  sceneType === "custom" ? "bg-teal-600 text-teal-950 shadow-sm" : "bg-gray-100/60 text-gray-600 hover:bg-gray-100"}`}>
                自定义
              </button>
            </div>
          </section>

          {/* ── 功能开关（扁平 2-col grid）── */}
          <section>
            <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">功能开关</h3>
            <div className="grid grid-cols-2 gap-2">
              {/* 四大感知模块 */}
              {MODULES.map(mod => {
                const isOn = modules[mod.key];
                const disabled = grayed[mod.key];
                return (
                  <div key={mod.key}
                    className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all select-none
                      ${disabled ? "bg-gray-50/60 border border-gray-100/60" : isOn ? `${mod.color} border ${mod.border}` : "bg-gray-100/40 border border-gray-200/60"}`}>
                    <div className="flex-1 min-w-0">
                      <span className={`text-xs font-medium block ${disabled ? "text-gray-400" : isOn ? "text-gray-900" : "text-gray-600"}`}>{mod.label}</span>
                      <span className="text-[10px] text-gray-500 truncate block">
                        {disabled
                          ? (moduleAvailable[mod.key] === false ? "插件未启用" : "依赖视觉分析")
                          : mod.hint}
                      </span>
                    </div>
                    <Toggle checked={isOn} onChange={() => toggleModule(mod.key)} disabled={disabled} />
                  </div>
                );
              })}

              {/* 人脸 — 独立卡片 */}
              <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all select-none
                ${grayed.face ? "bg-gray-50/60 border border-gray-100/60" : faceEnabled ? "bg-purple-50/60 border border-purple-200" : "bg-gray-100/40 border border-gray-200/60"}`}>
                <div className="flex-1 min-w-0">
                  <span className={`text-xs font-medium block ${grayed.face ? "text-gray-400" : faceEnabled ? "text-gray-900" : "text-gray-600"}`}>人脸识别</span>
                  <span className="text-[10px] text-gray-500 truncate block">{grayed.face ? "依赖物体检测" : "人脸聚类与检索"}</span>
                </div>
                <Toggle checked={faceEnabled} onChange={() => { setFaceEnabled(!faceEnabled); setSceneType("custom"); }} disabled={grayed.face} />
              </div>

              {/* 车牌 — 独立卡片 */}
              <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all select-none
                ${grayed.plate ? "bg-gray-50/60 border border-gray-100/60" : plateEnabled ? "bg-green-50/60 border border-green-200" : "bg-gray-100/40 border border-gray-200/60"}`}>
                <div className="flex-1 min-w-0">
                  <span className={`text-xs font-medium block ${grayed.plate ? "text-gray-400" : plateEnabled ? "text-gray-900" : "text-gray-600"}`}>车牌识别</span>
                  <span className="text-[10px] text-gray-500 truncate block">{grayed.plate ? "依赖物体检测" : "车牌文字提取"}</span>
                </div>
                <Toggle checked={plateEnabled} onChange={() => { setPlateEnabled(!plateEnabled); setSceneType("custom"); }} disabled={grayed.plate} />
              </div>

              {/* 智能摘要 */}
              <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all select-none
                ${!modules.vision ? "bg-gray-50/60 border border-gray-100/60" : functions.summary ? "bg-teal-50/60 border border-teal-200" : "bg-gray-100/40 border border-gray-200/60"}`}>
                <div className="flex-1 min-w-0">
                  <span className={`text-xs font-medium block ${!modules.vision ? "text-gray-400" : functions.summary ? "text-gray-900" : "text-gray-600"}`}>智能摘要</span>
                  <span className="text-[10px] text-gray-500 truncate block">{!modules.vision ? "依赖视觉分析" : "全局结构化摘要"}</span>
                </div>
                <Toggle checked={functions.summary} onChange={() => toggleFunction("summary")} disabled={!modules.vision} />
              </div>

              {/* 搜索索引 */}
              <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all select-none
                ${functions.searchIndex ? "bg-sky-50/60 border border-sky-200" : "bg-gray-100/40 border border-gray-200/60"}`}>
                <div className="flex-1 min-w-0">
                  <span className={`text-xs font-medium block ${functions.searchIndex ? "text-gray-900" : "text-gray-600"}`}>搜索索引</span>
                  <span className="text-[10px] text-gray-500 truncate block">建立向量索引支持语义搜索</span>
                </div>
                <Toggle checked={functions.searchIndex} onChange={() => toggleFunction("searchIndex")} disabled={false} />
              </div>
            </div>

            {/* ── 目标类别（可折叠，仅检测开时可展开）── */}
            {modules.detection && (
              <div className="mt-2 ml-2 pl-3 border-l-2 border-orange-300 bg-orange-50/30 rounded-r-lg py-2 pr-2">
                <button onClick={() => setExpandedClasses(!expandedClasses)}
                  className="flex items-center justify-between w-full text-left">
                  <span className="text-[11px] font-medium text-gray-600">
                    目标类别
                    {detectionClasses !== null && detectionClasses.length > 0
                      && <span className="ml-1 text-gray-400">({detectionClasses.length} 项)</span>}
                  </span>
                  <svg className={`w-3.5 h-3.5 text-gray-400 transition-transform ${expandedClasses ? "rotate-90" : ""}`}
                    viewBox="0 0 16 16" fill="currentColor"><path d="M6 4l4 4-4 4" /></svg>
                </button>
                {expandedClasses && (
                  <div className="mt-2 space-y-2">
                    <div className="flex gap-1">
                      <button onClick={() => setDetectionClasses(null)}
                        className={`px-2 py-0.5 text-[10px] font-medium rounded-md transition-all ${detectionClasses === null ? "bg-[#4f7cff] text-white" : "bg-gray-100/80 text-gray-600 hover:bg-gray-200/80"}`}>
                        全部
                      </button>
                      <button onClick={() => setDetectionClasses([])}
                        className={`px-2 py-0.5 text-[10px] font-medium rounded-md transition-all ${detectionClasses !== null ? "bg-teal-600 text-teal-950" : "bg-gray-100/80 text-gray-600 hover:bg-gray-200/80"}`}>
                        自定义
                      </button>
                    </div>
                    {detectionClasses !== null && (
                      <>
                        {detectionClasses.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {detectionClasses.map(cls => (
                              <span key={cls} onClick={() => setDetectionClasses(p => (p ?? []).filter(c => c !== cls))}
                                className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-medium bg-[#4f7cff] text-white rounded-md cursor-pointer hover:bg-[#4369f5] transition-colors">
                                {zh(cls)}
                                <svg className="w-2.5 h-2.5 opacity-70" viewBox="0 0 12 12" fill="currentColor">
                                  <path d="M3 3l6 6M9 3l-6 6" stroke="white" strokeWidth="1.5" fill="none" />
                                </svg>
                              </span>
                            ))}
                          </div>
                        )}
                        <div className="relative">
                          <input type="text" value={classSearch} onChange={e => setClassSearch(e.target.value)}
                            placeholder="搜索 80 类…"
                            className="w-full px-2.5 py-1 text-[11px] border border-gray-200 rounded-md focus:outline-none focus:border-teal-600 bg-white/80 placeholder:text-gray-400" />
                          {classSearch && (() => {
                            const q = classSearch.toLowerCase();
                            const matches = COCO_ALL.filter(c => (c.toLowerCase().includes(q) || zh(c).toLowerCase().includes(q)) && !(detectionClasses ?? []).includes(c)).slice(0, 6);
                            if (!matches.length) return null;
                            return (
                              <div className="absolute top-full left-0 right-0 mt-0.5 bg-gray-50 border border-gray-300 rounded-md shadow-xl z-10 max-h-[140px] overflow-y-auto custom-scrollbar">
                                {matches.map(c => (
                                  <button key={c} onClick={() => { setDetectionClasses(p => [...(p ?? []), c]); setClassSearch(""); }}
                                    className="w-full text-left px-2.5 py-1 text-[11px] hover:bg-teal-600/20 text-gray-600 transition-colors">
                                    {zh(c)}
                                  </button>
                                ))}
                              </div>
                            );
                          })()}
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {COMMON_CLASSES.filter(c => !(detectionClasses ?? []).includes(c)).map(cls => (
                            <button key={cls} onClick={() => setDetectionClasses(p => [...(p ?? []), cls])}
                              className="px-1.5 py-0.5 text-[10px] font-medium bg-gray-100/60 text-gray-500 rounded-md hover:bg-teal-600/30 hover:text-teal-500 transition-colors">
                              + {zh(cls)}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* ── 摘要模式（可折叠，仅摘要开时可展开）── */}
            {functions.summary && (
              <div className="mt-2 ml-2 pl-3 border-l-2 border-teal-300 bg-teal-50/30 rounded-r-lg py-2 pr-2">
                <button onClick={() => setExpandedSummary(!expandedSummary)}
                  className="flex items-center justify-between w-full text-left">
                  <span className="text-[11px] font-medium text-gray-600">
                    摘要模式
                    <span className="ml-1 text-gray-400">{summaryMode === "vlm_llm" ? "VLM + LLM" : "原生视频"}</span>
                  </span>
                  <svg className={`w-3.5 h-3.5 text-gray-400 transition-transform ${expandedSummary ? "rotate-90" : ""}`}
                    viewBox="0 0 16 16" fill="currentColor"><path d="M6 4l4 4-4 4" /></svg>
                </button>
                {expandedSummary && (
                  <div className="mt-2 space-y-1.5">
                    {[{ key: "native_video", label: "原生视频理解", disabled: true },
                      { key: "vlm_llm", label: "VLM + LLM", disabled: false }].map(opt => (
                      <label key={opt.key}
                        className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-all ${
                          opt.disabled ? "opacity-50 cursor-not-allowed bg-gray-50 border-gray-200/60"
                            : summaryMode === opt.key ? "bg-teal-600/15 border-teal-500/70 cursor-pointer"
                              : "bg-gray-50 border-gray-200/60 cursor-pointer hover:border-gray-300"}`}>
                        <input type="radio" name="summaryMode" value={opt.key} checked={summaryMode === opt.key}
                          onChange={() => setSummaryMode(opt.key)} disabled={opt.disabled} className="accent-teal-600" />
                        <span className="text-xs font-medium text-gray-800 flex items-center gap-1.5">
                          {opt.label}
                          {opt.disabled && <span className="text-[10px] font-normal text-gray-400 border border-gray-300/60 rounded px-1 py-px">已停用</span>}
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </div>

      {/* Error */}
      {error && <div className="px-5 py-2 shrink-0"><p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">{error}</p></div>}

      {/* Footer */}
      <div className="px-5 py-3 border-t border-gray-200 shrink-0 flex justify-end items-center">
        <button onClick={handleSubmit} disabled={submitting} className="g-btn g-btn-primary">
          {submitting ? "提交中..." : onBatchSubmit ? "批量解析" : reparse ? "重新解析" : "参数启动"}
        </button>
      </div>
    </div>
  );
}
