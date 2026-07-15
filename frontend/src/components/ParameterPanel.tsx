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
  modules: { vision: boolean; audio: boolean; ocr: boolean; caption: boolean };
  functions: { searchIndex: boolean; summary: boolean };
}> = {
  general: {
    label: "通用",
    desc: "均衡模式，适合未知内容类型",
    modules: { vision: true, audio: false, ocr: false, caption: true },
    functions: { searchIndex: true, summary: true },
  },
  meeting: {
    label: "会议",
    desc: "以语音和对话为核心（含课堂、访谈、教程）",
    modules: { vision: true, audio: true, ocr: true, caption: true },
    functions: { searchIndex: true, summary: true },
  },
  surveillance: {
    label: "监控",
    desc: "固定机位，无音频轨道，纯视觉分析",
    modules: { vision: true, audio: false, ocr: false, caption: true },
    functions: { searchIndex: true, summary: false },
  },
  text_recognition: {
    label: "文字识别",
    desc: "扫描视频中的文件、聊天截图、票据、PPT 等文字",
    modules: { vision: true, audio: false, ocr: true, caption: false },
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
  detection: false,
};

type ModuleKey = "vision" | "audio" | "ocr" | "caption";

interface AdvancedParams {
  language: string;
  sampleFps: number;
  segmentThreshold: number;
  captionWithContext: boolean;
  summaryDetail: string;
}

const DEFAULT_ADVANCED: AdvancedParams = {
  language: "auto",
  sampleFps: 1.0,
  segmentThreshold: 0.5,
  captionWithContext: true,
  summaryDetail: "standard",
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
    if (saved?.modules) return saved.modules as Record<ModuleKey, boolean>;
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
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  /* ── 计算置灰状态 ── */
  const grayed = useMemo(() => {
    const g: Record<string, boolean> = {};
    // 插件不可用
    g.audio = !MODULE_AVAILABLE.audio;
    g.ocr = !MODULE_AVAILABLE.ocr || !modules.vision;
    g.caption = !modules.vision;
    g.detection = true;
    // 功能开关
    g.summary = !modules.caption;
    // 高级参数
    g.language = !modules.audio;
    g.sampleFps = !modules.vision;
    g.captionWithContext = !modules.caption;
    g.summaryDetail = !functions.summary || !modules.caption;
    return g;
  }, [modules, functions]);

  /* ── 自定义参数自动保存 ── */
  useEffect(() => {
    if (sceneType === "custom") {
      saveCustomParams({ sceneType, modules, functions, advanced });
    }
  }, [sceneType, modules, functions, advanced]);

  /* ── L1 场景类型变更 → 重设 L2/L3 默认值 ── */
  const handleSceneTypeChange = (ct: ContentType) => {
    setSceneType(ct);
    if (ct === "custom") {
      // 加载上次保存的自定义参数
      const saved = loadCustomParams();
      if (saved?.modules) setModules(saved.modules as Record<ModuleKey, boolean>);
      if (saved?.functions) setFunctions(saved.functions as Record<string, boolean>);
      if (saved?.advanced) setAdvanced({ ...DEFAULT_ADVANCED, ...saved.advanced as Partial<AdvancedParams> });
      return;
    }
    const preset = SCENE_PRESETS[ct];
    if (preset) {
      setModules({ ...preset.modules });
      setFunctions({ ...preset.functions });
    }
  };

  /* ── L2 模块切换 ── */
  const toggleModule = (key: ModuleKey) => {
    if (grayed[key]) return;
    setModules((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      // vision 关闭 → ocr / caption 强制关闭
      if (!next.vision) {
        next.ocr = false;
        next.caption = false;
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
      search_index_enabled: functions.searchIndex,
      summary_enabled: functions.summary,
      language: advanced.language,
      sample_fps: advanced.sampleFps,
      segment_threshold: advanced.segmentThreshold,
      caption_with_context: advanced.captionWithContext,
      summary_detail: advanced.summaryDetail,
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
        const onBlur = () => setTimeout(() => setSubmitting(false), 500);
        window.addEventListener("focus", onBlur, { once: true });
        input.click();
      } else {
        // 已有视频 → 直接更新参数
        await api.updateParams(videoId, buildParams());
        onParamsSet();
        onClose();
      }

      // 持久化自定义参数
      if (sceneType === "custom") {
        saveCustomParams({ sceneType, modules, functions, advanced });
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
    <div className="w-[380px] h-full flex flex-col text-gray-900">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 shrink-0">
        <h2 className="font-bold text-gray-900 text-base">参数设置</h2>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
          <IconClose />
        </button>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar px-5 py-4 space-y-5">
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
              { key: "detection" as ModuleKey, label: "物体检测", hint: "YOLO 插件未实现" },
            ] as const).map((mod) => {
              const isOn = mod.key === "detection" ? false : modules[mod.key];
              const isGrayed = mod.key === "detection" ? true : grayed[mod.key];
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
                    onChange={() => mod.key !== "detection" && toggleModule(mod.key)}
                    disabled={isGrayed}
                  />
                </div>
              );
            })}
          </div>
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

