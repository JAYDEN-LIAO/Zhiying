/* ════════════════════════════════════════════════════════════
   ParameterPanel — extracted from Dashboard.tsx
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useMemo } from "react";
import { IconClose } from "./icons";
import { api } from "../services/api";
import type { ContentType, PipelineParams } from "../types";

const SCENE_PRESETS: Record<string, {
  label: string;
  desc: string;
  modules: { vision: boolean; audio: boolean; ocr: boolean; caption: boolean; detection: boolean };
  functions: { searchIndex: boolean; summary: boolean };
  faceEnabled?: boolean;
  plateEnabled?: boolean;
}> = {
  general: {
    label: "通用",
    desc: "均衡模式，适合未知内容类型",
    modules: { vision: true, audio: false, ocr: false, caption: true, detection: false },
    functions: { searchIndex: true, summary: true },
  },
  meeting: {
    label: "会议",
    desc: "以语音和对话为核心（含课堂、访谈、教程）",
    modules: { vision: true, audio: true, ocr: true, caption: true, detection: false },
    functions: { searchIndex: true, summary: true },
  },
  surveillance: {
    label: "监控",
    desc: "固定机位，无音频轨道，纯视觉分析",
    modules: { vision: true, audio: false, ocr: false, caption: true, detection: true },
    functions: { searchIndex: true, summary: false },
    faceEnabled: true,
    plateEnabled: true,
  },
  text_recognition: {
    label: "文字识别",
    desc: "扫描视频中的文件、聊天截图、票据、PPT 等文字",
    modules: { vision: true, audio: false, ocr: true, caption: false, detection: false },
    functions: { searchIndex: true, summary: false },
  },
};

const CONTENT_TYPES = Object.entries(SCENE_PRESETS).map(([value, { label }]) => ({ value, label }));

const LANGUAGES = [
  { value: "auto", label: "自动" },
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "ja", label: "日本語" },
  { value: "ko", label: "한국어" },
] as const;

const SUMMARY_DETAILS = [
  { value: "brief", label: "简要" },
  { value: "standard", label: "标准" },
  { value: "detailed", label: "详细" },
] as const;

const MODULE_AVAILABLE: Record<string, boolean> = {
  audio: false,
  ocr: false,
  detection: true,
  face: true,
  plate: true,
};

/* ── COCO 80 类（YOLO11 完整列表）── */
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

const COMMON_CLASSES = [
  "person", "car", "truck", "bus", "motorcycle", "bicycle",
  "dog", "cat", "bird", "horse",
  "chair", "couch", "bed", "dining table",
  "laptop", "cell phone", "tv", "book",
  "backpack", "umbrella", "bottle", "cup",
];

type ModuleKey = "vision" | "audio" | "ocr" | "caption" | "detection";

interface AdvancedParams {
  language: string;
  sampleFps: number;
  segmentThreshold: number;
  captionWithContext: boolean;
  summaryDetail: string;
  encodeProfile: string | null;
}

const DEFAULT_ADVANCED: AdvancedParams = {
  language: "auto",
  sampleFps: 1.0,
  segmentThreshold: 0.5,
  captionWithContext: true,
  summaryDetail: "standard",
  encodeProfile: null,
};

const CUSTOM_PARAMS_KEY = "cerno_custom_params";

function loadCustomParams(): Record<string, unknown> | null {
  try {
    const raw = localStorage.getItem(CUSTOM_PARAMS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveCustomParams(params: Record<string, unknown>) {
  localStorage.setItem(CUSTOM_PARAMS_KEY, JSON.stringify(params));
}

export function ParameterPanel({
  videoId,
  onClose,
  onParamsSet,
  onUploadDone,
}: {
  videoId?: string | null;
  onClose: () => void;
  onParamsSet: () => void;
  onUploadDone?: (newVideoId: string) => void;
}) {
  const [sceneType, setSceneType] = useState<ContentType>(() => {
    const saved = loadCustomParams();
    return (saved?.sceneType as ContentType) ?? "general";
  });
  const [modules, setModules] = useState<Record<ModuleKey, boolean>>(() => {
    const saved = loadCustomParams();
    if (saved?.modules) {
      const m = saved.modules as Record<string, boolean>;
      return { vision: false, audio: false, ocr: false, caption: false, detection: false, ...m };
    }
    const preset = SCENE_PRESETS["general"];
    return { ...preset.modules };
  });
  const [functions, setFunctions] = useState<Record<string, boolean>>(() => {
    const saved = loadCustomParams();
    if (saved?.functions) return saved.functions as Record<string, boolean>;
    const preset = SCENE_PRESETS["general"];
    return { ...preset.functions };
  });
  const [advanced, setAdvanced] = useState<AdvancedParams>(() => {
    const saved = loadCustomParams();
    if (saved?.advanced) return { ...DEFAULT_ADVANCED, ...saved.advanced as Partial<AdvancedParams> };
    return { ...DEFAULT_ADVANCED };
  });
  const [summaryMode, setSummaryMode] = useState<string>(() => {
    const saved = loadCustomParams();
    return (saved?.summaryMode as string) ?? "native_video";
  });
  const [detectionClasses, setDetectionClasses] = useState<string[] | null>(() => {
    const saved = loadCustomParams();
    return (saved?.detectionClasses as string[] | null) ?? null;
  });
  const [faceEnabled, setFaceEnabled] = useState<boolean>(() => {
    const saved = loadCustomParams();
    return (saved?.faceEnabled as boolean) ?? false;
  });
  const [plateEnabled, setPlateEnabled] = useState<boolean>(() => {
    const saved = loadCustomParams();
    return (saved?.plateEnabled as boolean) ?? false;
  });
  const [classSearch, setClassSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  /* ── 计算置灰状态 ── */
  const grayed = useMemo(() => {
    const g: Record<string, boolean> = {};
    // 插件不可用
    g.audio = !MODULE_AVAILABLE.audio;
    g.ocr = !MODULE_AVAILABLE.ocr || !modules.vision;
    g.caption = !modules.vision;
    g.detection = !MODULE_AVAILABLE.detection || !modules.vision;
    // 功能开关
    g.summary = !modules.caption;
    // 高级参数
    g.language = !modules.audio;
    g.sampleFps = !modules.vision;
    g.captionWithContext = !modules.caption;
    g.summaryDetail = !functions.summary || !modules.caption;
    g.detectionClasses = !modules.detection;
    return g;
  }, [modules, functions]);

  /* ── 自定义参数自动保存 ── */
  useEffect(() => {
    if (sceneType === "custom") {
      saveCustomParams({ sceneType, modules, functions, advanced, summaryMode, detectionClasses, faceEnabled, plateEnabled });
    }
  }, [sceneType, modules, functions, advanced, detectionClasses, summaryMode, faceEnabled, plateEnabled]);

  /* ── L1 场景类型变更 → 重设 L2/L3 默认值 ── */
  const handleSceneTypeChange = (ct: ContentType) => {
    setSceneType(ct);
    if (ct === "custom") {
      // 加载上次保存的自定义参数
      const saved = loadCustomParams();
      if (saved?.modules) setModules(saved.modules as Record<ModuleKey, boolean>);
      if (saved?.functions) setFunctions(saved.functions as Record<string, boolean>);
      if (saved?.advanced) setAdvanced({ ...DEFAULT_ADVANCED, ...saved.advanced as Partial<AdvancedParams> });
      if (saved?.summaryMode) setSummaryMode(saved.summaryMode as string);
      return;
    }
    const preset = SCENE_PRESETS[ct];
    if (preset) {
      setModules({ ...preset.modules });
      setFunctions({ ...preset.functions });
      setFaceEnabled(preset.faceEnabled ?? false);
      setPlateEnabled(preset.plateEnabled ?? false);
    }
  };

  /* ── L2 模块切换 ── */
  const toggleModule = (key: ModuleKey) => {
    if (grayed[key]) return;
    setModules((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      // vision 关闭 → ocr / caption / detection 强制关闭
      if (!next.vision) {
        next.ocr = false;
        next.caption = false;
        next.detection = false;
      }
      // caption 关闭 → summary 强制关闭
      if (!next.caption) {
        setFunctions((f) => ({ ...f, summary: false }));
      }
      return next;
    });
    setSceneType("custom");
    setError(null);
  };

  /* ── L3 功能开关 ── */
  const toggleFunction = (key: string) => {
    if (grayed[key]) return;
    setFunctions((prev) => ({ ...prev, [key]: !prev[key] }));
    setSceneType("custom");
    setError(null);
  };

  /* ── L4 高级参数 ── */
  const updateAdvanced = (patch: Partial<AdvancedParams>) => {
    setAdvanced((prev) => ({ ...prev, ...patch }));
    setError(null);
  };

  /* ── 校验 + 提交 ── */
  const validate = (): string | null => {
    if (!modules.vision && !modules.audio) return "视觉分析和音频转录至少开启一个";
    if (!functions.searchIndex && !functions.summary) return "搜索索引和智能摘要至少开启一个";
    if (!modules.vision && modules.caption) return "视觉分析已关闭，画面描述应同时关闭";
    if (!modules.vision && modules.detection) return "视觉分析已关闭，物体检测应同时关闭";
    if (!modules.caption && functions.summary) return "画面描述已关闭，智能摘要应同时关闭";
    return null;
  };

  const handleSubmit = async () => {
    const err = validate();
    if (err) { setError(err); return; }

    const buildParams = (): PipelineParams => ({
      content_type: sceneType,
      vision_enabled: modules.vision,
      audio_enabled: modules.audio,
      ocr_enabled: modules.ocr,
      caption_enabled: modules.caption,
      detection_enabled: modules.detection,
      detection_classes: modules.detection ? detectionClasses : null,
      face_enabled: modules.detection ? faceEnabled : false,
      plate_enabled: modules.detection ? plateEnabled : false,
      search_index_enabled: functions.searchIndex,
      summary_enabled: functions.summary,
      summary_mode: summaryMode,
      language: advanced.language,
      sample_fps: advanced.sampleFps,
      segment_threshold: advanced.segmentThreshold,
      caption_with_context: advanced.captionWithContext,
      summary_detail: advanced.summaryDetail,
      encode_profile: advanced.encodeProfile,
    });

    setSubmitting(true);
    setError(null);

    try {
      if (!videoId) {
        // 无视频 → 先上传再启动
        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".mp4,.mov,.avi,.mkv,.webm";
        input.onchange = async () => {
          const file = input.files?.[0];
          ac.abort();  // 取消 focus 监听
          if (!file) { setSubmitting(false); return; }
          try {
            const result = await api.upload(file, buildParams());
            // 上传已携带参数，视频自动 pending 等待参数
            // 直接调用 updateParams 启动
            await api.updateParams(result.id, buildParams());
            onUploadDone?.(result.id);
            onParamsSet();
            onClose();
          } catch (e2) {
            setError(e2 instanceof Error ? e2.message : "上传失败");
          } finally {
            setSubmitting(false);
          }
        };
        const ac = new AbortController();
        window.addEventListener("focus", () => setTimeout(() => setSubmitting(false), 500), { signal: ac.signal, once: true });
        input.click();
      } else {
        // 已有视频 → 直接更新参数
        await api.updateParams(videoId, buildParams());
        onParamsSet();
        onClose();
      }

      // 持久化自定义参数
      if (sceneType === "custom") {
        saveCustomParams({ sceneType, modules, functions, advanced, summaryMode, detectionClasses, faceEnabled, plateEnabled });
      } else {
        localStorage.removeItem(CUSTOM_PARAMS_KEY);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动失败");
    } finally {
      if (videoId) setSubmitting(false);
    }
  };

  /* ── 切换开关子组件 ── */
  const Toggle = ({ checked, onChange, disabled }: { checked: boolean; onChange: () => void; disabled: boolean }) => (
    <div
      className={`relative w-9 h-5 rounded-full transition-colors duration-200 ${
        disabled ? "bg-gray-150 cursor-not-allowed opacity-40" : checked ? "bg-[#1a65e1] cursor-pointer" : "bg-gray-200 cursor-pointer"
      }`}
      onClick={() => !disabled && onChange()}
    >
      <div
        className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-transform duration-200 ${
          checked ? "translate-x-[18px]" : "translate-x-[2px]"
        }`}
      />
    </div>
  );

  const presetLabel = sceneType === "custom" ? "自定义" : (SCENE_PRESETS[sceneType]?.label ?? "自定义");

  return (
    <div className="w-[380px] h-full flex flex-col">
      {/* Header — dark to match slide panel */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-white/10 shrink-0">
        <h2 className="font-bold text-white text-base">参数设置</h2>
        <button onClick={onClose} className="text-white/50 hover:text-white transition-colors cursor-pointer">
          <IconClose />
        </button>
      </div>

      {/* Scrollable content — light background */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5 bg-[var(--color-surface)] text-gray-900">
        {/* L1: 场景类型 */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">场景类型</h3>
          <div className="flex gap-1.5 flex-wrap">
            {CONTENT_TYPES.map((ct) => (
              <button
                key={ct.value}
                onClick={() => handleSceneTypeChange(ct.value as ContentType)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
                  sceneType === ct.value
                    ? "bg-[#1a65e1] text-white shadow-sm"
                    : "bg-gray-100/60 text-gray-600 hover:bg-gray-100"
                }`}
              >
                {ct.label}
              </button>
            ))}
            <button
              onClick={() => handleSceneTypeChange("custom" as ContentType)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all ${
                sceneType === "custom"
                  ? "bg-[#1a65e1] text-white shadow-sm"
                  : "bg-gray-100/60 text-gray-600 hover:bg-gray-100"
              }`}
            >
              自定义
            </button>
          </div>
        </section>

        {/* L2: 感知模块 */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">感知模块</h3>
          <div className="space-y-1.5">
            {([
              { key: "vision" as ModuleKey, label: "视觉分析", hint: "帧处理总开关" },
              { key: "audio" as ModuleKey, label: "音频转录", hint: grayed.audio ? "插件未启用" : "语音转文字" },
              { key: "ocr" as ModuleKey, label: "文字识别", hint: grayed.ocr ? (MODULE_AVAILABLE.ocr ? "依赖视觉分析" : "插件未启用") : "提取画面文字" },
              { key: "caption" as ModuleKey, label: "画面描述", hint: grayed.caption ? "依赖视觉分析" : "VLM 场景描述" },
              { key: "detection" as ModuleKey, label: "物体检测", hint: grayed.detection ? (MODULE_AVAILABLE.detection ? "依赖视觉分析" : "插件未启用") : "YOLO11 逐帧检测与 ByteTrack 追踪" },
            ] as const).map((mod) => {
              const isOn = modules[mod.key];
              const isGrayed = grayed[mod.key];
              return (
                <div
                  key={mod.key}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all select-none ${
                    isGrayed ? "bg-gray-50/60 border border-gray-100/60" :
                    isOn ? "bg-blue-50 border border-blue-200" : "bg-gray-100/40 border border-gray-200/60"
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <span className={`text-xs font-medium block ${isGrayed ? "text-gray-350" : isOn ? "text-gray-900" : "text-gray-500"}`}>
                      {mod.label}
                    </span>
                    <span className="text-[10px] text-gray-400 truncate block">{mod.hint}</span>
                  </div>
                  <Toggle
                    checked={isOn}
                    onChange={() => toggleModule(mod.key)}
                    disabled={isGrayed}
                  />
                </div>
              );
            })}
          </div>

          {/* 物体检测 → 目标类别选择（仅检测开启时显示） */}
          {modules.detection && (
            <div className={`mt-2 ml-2 pl-3 border-l-2 rounded-r-lg py-2 pr-2 transition-all ${
              grayed.detectionClasses ? "border-gray-150 bg-gray-50/30 opacity-40" : "border-blue-300 bg-blue-50/30"
            }`}>
              <div className="flex items-center justify-between mb-2">
                <span className={`text-[11px] font-medium ${grayed.detectionClasses ? "text-gray-350" : "text-gray-500"}`}>
                  目标类别
                </span>
                <div className="flex gap-1">
                  <button
                    onClick={() => !grayed.detectionClasses && setDetectionClasses(null)}
                    disabled={grayed.detectionClasses}
                    className={`px-2 py-0.5 text-[10px] font-medium rounded-md transition-all ${
                      grayed.detectionClasses ? "text-gray-300 cursor-not-allowed" :
                      detectionClasses === null ? "bg-[#1a65e1] text-white" : "bg-gray-100/60 text-gray-500 hover:bg-gray-100"
                    }`}
                  >
                    全部
                  </button>
                  <button
                    onClick={() => !grayed.detectionClasses && setDetectionClasses([])}
                    disabled={grayed.detectionClasses}
                    className={`px-2 py-0.5 text-[10px] font-medium rounded-md transition-all ${
                      grayed.detectionClasses ? "text-gray-300 cursor-not-allowed" :
                      detectionClasses !== null ? "bg-[#1a65e1] text-white" : "bg-gray-100/60 text-gray-500 hover:bg-gray-100"
                    }`}
                  >
                    自定义
                  </button>
                </div>
              </div>

              {/* 自定义模式：已选类别 + 常用类别 + 搜索 */}
              {detectionClasses !== null && (
                <div className="space-y-2">
                  {/* 已选类别（可移除） */}
                  {detectionClasses.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {detectionClasses.map((cls) => (
                        <span
                          key={cls}
                          onClick={() => setDetectionClasses((prev) => (prev ?? []).filter((c) => c !== cls))}
                          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-medium bg-[#1a65e1] text-white rounded-md cursor-pointer hover:bg-blue-700 transition-colors"
                        >
                          {cls}
                          <svg className="w-2.5 h-2.5 opacity-70" viewBox="0 0 12 12" fill="currentColor">
                            <path d="M3 3l6 6M9 3l-6 6" stroke="white" strokeWidth="1.5" fill="none" />
                          </svg>
                        </span>
                      ))}
                    </div>
                  )}

                  {/* 搜索输入 */}
                  <div className="relative">
                    <input
                      type="text"
                      value={classSearch}
                      onChange={(e) => setClassSearch(e.target.value)}
                      placeholder="搜索匹配 80 类…"
                      className="w-full px-2.5 py-1 text-[11px] border border-gray-200 rounded-md focus:outline-none focus:border-blue-400 bg-white/80 placeholder:text-gray-350"
                    />
                    {classSearch && (() => {
                      const q = classSearch.toLowerCase();
                      const matches = COCO_ALL.filter(
                        (c) => c.toLowerCase().includes(q) && !(detectionClasses ?? []).includes(c),
                      ).slice(0, 6);
                      if (!matches.length) return null;
                      return (
                        <div className="absolute top-full left-0 right-0 mt-0.5 bg-white border border-gray-200 rounded-md shadow-lg z-10 max-h-[140px] overflow-y-auto custom-scrollbar">
                          {matches.map((c) => (
                            <button
                              key={c}
                              onClick={() => {
                                setDetectionClasses((prev) => [...(prev ?? []), c]);
                                setClassSearch("");
                              }}
                              className="w-full text-left px-2.5 py-1 text-[11px] hover:bg-blue-50 text-gray-600 transition-colors"
                            >
                              {c}
                            </button>
                          ))}
                        </div>
                      );
                    })()}
                  </div>

                  {/* 常用类别 chips */}
                  <div className="flex flex-wrap gap-1">
                    {COMMON_CLASSES.filter((c) => !(detectionClasses ?? []).includes(c)).map((cls) => (
                      <button
                        key={cls}
                        onClick={() => setDetectionClasses((prev) => [...(prev ?? []), cls])}
                        className="px-1.5 py-0.5 text-[10px] font-medium bg-gray-100/60 text-gray-500 rounded-md hover:bg-blue-100 hover:text-blue-700 transition-colors"
                      >
                        + {cls}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 人脸识别子开关 — 检测开启时显示 */}
          {modules.detection && (
            <div className={`mt-2 ml-2 pl-3 border-l-2 rounded-r-lg py-2 pr-2 transition-all ${
              !MODULE_AVAILABLE.face ? "border-gray-150 bg-gray-50/30 opacity-40" : "border-purple-300 bg-purple-50/30"
            }`}>
              <div className="flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <span className={`text-[11px] font-medium block ${!MODULE_AVAILABLE.face ? "text-gray-350" : "text-gray-500"}`}>
                    人脸识别
                  </span>
                  <span className="text-[10px] text-gray-400 truncate block">
                    {MODULE_AVAILABLE.face ? "SCRFD 检测 + ArcFace 身份聚类" : "插件未启用"}
                  </span>
                </div>
                <Toggle
                  checked={faceEnabled}
                  onChange={() => { setFaceEnabled(!faceEnabled); setSceneType("custom"); }}
                  disabled={!MODULE_AVAILABLE.face}
                />
              </div>
            </div>
          )}

          {/* 车牌识别子开关 — 检测开启时显示 */}
          {modules.detection && (
            <div className={`mt-1.5 ml-2 pl-3 border-l-2 rounded-r-lg py-2 pr-2 transition-all ${
              !MODULE_AVAILABLE.plate ? "border-gray-150 bg-gray-50/30 opacity-40" : "border-green-300 bg-green-50/30"
            }`}>
              <div className="flex items-center justify-between">
                <div className="flex-1 min-w-0">
                  <span className={`text-[11px] font-medium block ${!MODULE_AVAILABLE.plate ? "text-gray-350" : "text-gray-500"}`}>
                    车牌识别
                  </span>
                  <span className="text-[10px] text-gray-400 truncate block">
                    {MODULE_AVAILABLE.plate ? "PaddleOCR 车牌检测与文字识别" : "插件未启用"}
                  </span>
                </div>
                <Toggle
                  checked={plateEnabled}
                  onChange={() => { setPlateEnabled(!plateEnabled); setSceneType("custom"); }}
                  disabled={!MODULE_AVAILABLE.plate}
                />
              </div>
            </div>
          )}
        </section>

        {/* L3: 功能开关 */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">功能开关</h3>
          <div className="space-y-1.5">
            {([
              { key: "searchIndex", label: "搜索索引", hint: "建立向量索引，支持语义搜索" },
              { key: "summary", label: "智能摘要", hint: grayed.summary ? "依赖画面描述" : "生成全局结构化摘要" },
            ] as const).map((fn) => {
              const isOn = functions[fn.key];
              const isGrayed = grayed[fn.key];
              return (
                <div
                  key={fn.key}
                  className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all select-none ${
                    isGrayed ? "bg-gray-50/60 border border-gray-100/60" :
                    isOn ? "bg-blue-50 border border-blue-200" : "bg-gray-100/40 border border-gray-200/60"
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <span className={`text-xs font-medium block ${isGrayed ? "text-gray-350" : isOn ? "text-gray-900" : "text-gray-500"}`}>
                      {fn.label}
                    </span>
                    <span className="text-[10px] text-gray-400 truncate block">{fn.hint}</span>
                  </div>
                  <Toggle
                    checked={isOn}
                    onChange={() => toggleFunction(fn.key)}
                    disabled={isGrayed}
                  />
                </div>
              );
            })}
            {!functions.searchIndex && !functions.summary && (
              <p className="text-[11px] text-red-400 mt-1">搜索索引和智能摘要至少开启一个</p>
            )}
          </div>

          {/* 摘要模式选择（仅智能摘要开启时显示） */}
          {functions.summary && (
            <div className="mt-3 pt-3 border-t border-gray-200/60">
              <p className="text-[11px] font-medium text-gray-500 mb-2">摘要模式</p>
              <div className="space-y-1.5">
                {([
                  { key: "native_video", label: "原生视频理解", desc: "本地 Qwen2.5-VL 直接观看视频片段，输出结构化摘要" },
                  { key: "vlm_llm", label: "VLM + LLM", desc: "传统看图说话 + LLM 拼凑摘要（需 API）" },
                ] as const).map((opt) => (
                  <label
                    key={opt.key}
                    className={`flex items-start gap-2.5 px-3 py-2 rounded-lg cursor-pointer transition-all border ${
                      summaryMode === opt.key
                        ? "bg-blue-50 border-blue-300"
                        : "bg-white/60 border-gray-200/60 hover:border-gray-300"
                    }`}
                  >
                    <input
                      type="radio"
                      name="summaryMode"
                      value={opt.key}
                      checked={summaryMode === opt.key}
                      onChange={() => setSummaryMode(opt.key)}
                      className="mt-0.5 accent-blue-500"
                    />
                    <div className="min-w-0">
                      <span className="text-xs font-medium text-gray-800 block">{opt.label}</span>
                      <span className="text-[10px] text-gray-400 block">{opt.desc}</span>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* L4: 高级参数 */}
        <section>
          <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">高级参数</h3>
          <div className="space-y-3">
            {/* 识别语言 */}
            <div>
              <label className={`text-xs mb-1 block ${grayed.language ? "text-gray-300" : "text-gray-400"}`}>
                识别语言
              </label>
              <div className="flex gap-1.5 flex-wrap">
                {LANGUAGES.map((l) => (
                  <button
                    key={l.value}
                    onClick={() => !grayed.language && updateAdvanced({ language: l.value })}
                    disabled={grayed.language}
                    className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-all ${
                      grayed.language ? "bg-gray-50 text-gray-300 cursor-not-allowed" :
                      advanced.language === l.value ? "bg-[#1a65e1] text-white shadow-sm" : "bg-gray-100/60 text-gray-600 hover:bg-gray-100"
                    }`}
                  >
                    {l.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 采样帧率 */}
            <div>
              <label className={`text-xs mb-1 block ${grayed.sampleFps ? "text-gray-300" : "text-gray-400"}`}>
                采样帧率 <span className="font-mono">{advanced.sampleFps.toFixed(1)} fps</span>
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  value={advanced.sampleFps}
                  onChange={(e) => updateAdvanced({ sampleFps: parseFloat(e.target.value) })}
                  min={0.5}
                  max={3.0}
                  step={0.5}
                  disabled={grayed.sampleFps}
                  className={`flex-1 ${grayed.sampleFps ? "opacity-30" : "accent-[#1a65e1]"}`}
                />
              </div>
              <div className="flex justify-between text-[9px] text-gray-350 mt-0.5">
                <span>0.5 快</span><span>1.5-2.0 推荐</span><span>3.0 精</span>
              </div>
            </div>

            {/* 场景切换敏感度 */}
            <div>
              <label className="text-xs text-gray-400 mb-1 block">
                场景切换敏感度 <span className="font-mono">{advanced.segmentThreshold.toFixed(1)}</span>
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  value={advanced.segmentThreshold}
                  onChange={(e) => updateAdvanced({ segmentThreshold: parseFloat(e.target.value) })}
                  min={0.2}
                  max={0.8}
                  step={0.1}
                  className="flex-1 accent-[#1a65e1]"
                />
              </div>
              <div className="flex justify-between text-[9px] text-gray-350 mt-0.5">
                <span>0.2 敏感</span><span>0.4-0.6 推荐</span><span>0.8 保守</span>
              </div>
            </div>

            {/* 记忆上下文 */}
            <div className="flex items-center justify-between">
              <span className={`text-xs ${grayed.captionWithContext ? "text-gray-300" : "text-gray-400"}`}>
                记忆上下文
              </span>
              <Toggle
                checked={advanced.captionWithContext}
                onChange={() => updateAdvanced({ captionWithContext: !advanced.captionWithContext })}
                disabled={grayed.captionWithContext}
              />
            </div>

            {/* 摘要详细度 */}
            <div>
              <label className={`text-xs mb-1 block ${grayed.summaryDetail ? "text-gray-300" : "text-gray-400"}`}>
                摘要详细度
              </label>
              <div className="flex gap-1.5 flex-wrap">
                {SUMMARY_DETAILS.map((d) => (
                  <button
                    key={d.value}
                    onClick={() => !grayed.summaryDetail && updateAdvanced({ summaryDetail: d.value })}
                    disabled={grayed.summaryDetail}
                    className={`px-3 py-1 text-xs font-medium rounded-lg transition-all ${
                      grayed.summaryDetail ? "bg-gray-50 text-gray-300 cursor-not-allowed" :
                      advanced.summaryDetail === d.value ? "bg-[#1a65e1] text-white shadow-sm" : "bg-gray-100/60 text-gray-600 hover:bg-gray-100"
                    }`}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 处理速度（编码预设） */}
            <div>
              <label className="text-xs text-gray-400 mb-1 block">
                处理速度
              </label>
              <div className="flex gap-1.5">
                {([
                  { key: "fast", label: "快速", hint: "~3min / 1h视频" },
                  { key: "balanced", label: "平衡", hint: "~5min" },
                  { key: "precise", label: "精准", hint: "~7min" },
                ] as const).map((opt) => (
                  <button
                    key={opt.key}
                    onClick={() => updateAdvanced({ encodeProfile: opt.key })}
                    className={`flex-1 px-2 py-2 rounded-lg transition-all border text-center ${
                      advanced.encodeProfile === opt.key
                        ? "bg-[#1a65e1] border-[#1a65e1] text-white shadow-sm"
                        : advanced.encodeProfile === null && opt.key === "balanced"
                          ? "bg-blue-50 border-blue-200 text-gray-600"
                          : "bg-gray-100/40 border-gray-200/60 text-gray-500 hover:border-gray-300"
                    }`}
                  >
                    <div className="text-xs font-medium">{opt.label}</div>
                    <div className={`text-[9px] mt-0.5 ${advanced.encodeProfile === opt.key ? "text-blue-100" : "text-gray-400"}`}>
                      {opt.hint}
                    </div>
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-gray-350 mt-1">
                {advanced.encodeProfile === null ? "使用全局默认 (设置页可改)" : `已选: ${advanced.encodeProfile === "fast" ? "快速 · 低分辨率" : advanced.encodeProfile === "precise" ? "精准 · 高分辨率" : "平衡 · 中等分辨率"}`}
              </p>
            </div>
          </div>
        </section>
      </div>

      {/* Error */}
      {error && (
        <div className="px-5 py-2 shrink-0">
          <p className="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">{error}</p>
        </div>
      )}

      {/* Footer */}
      <div className="px-5 py-3 border-t border-gray-200 shrink-0 flex justify-end items-center">
        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="px-5 py-2 text-xs font-medium bg-[#1a65e1] text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 transition-colors shadow-sm"
        >
          {submitting ? "启动中..." : "参数启动"}
        </button>
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════
   SettingsPage — 系统设置（页面视图）
   ════════════════════════════════════════════════════════════════ */

