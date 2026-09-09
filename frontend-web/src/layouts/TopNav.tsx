import { useState } from "react";
import { Link, NavLink, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../services/api";
import { IconBolt, IconClock, IconFolder, IconHome, IconVideo } from "../components/icons";
import type { PipelineParams } from "../types";

/* ════════════════════════════════════════════════════════════
   TopNav — 顶部导航栏
   最左：返回首页（图标）
   左：Logo + 智能解析 Tab（全局搜索模块已移除）
   右（仅解析详情页显示）：更换视频 · 重新解析（闪电）
   最右：历史记录
   重新解析：读取当前视频 ID 发起 reanalyze，
   完成后带 refresh 时间戳回跳触发工作台重新轮询
   ════════════════════════════════════════════════════════════ */

const TABS = [{ to: "/", label: "智能解析", icon: <IconVideo />, end: true }];

/* 默认解析参数（参数配置弹窗已移除，使用内置默认值） */
const DEFAULTS = {
  ocrEnabled: false,
  detectionEnabled: true,
  faceEnabled: false,
  plateEnabled: false,
  summaryEnabled: true,
  sampleFps: 1,
  confidence: 0.5,
};

/* 默认解析参数 → 后端 PipelineParams（reanalyze 载荷） */
function buildPipelineParams(): PipelineParams {
  const p = DEFAULTS;
  return {
    content_type: "general",
    vision_enabled: true,
    audio_enabled: false,
    ocr_enabled: p.ocrEnabled,
    caption_enabled: false,
    detection_enabled: p.detectionEnabled,
    detection_classes: null,
    face_enabled: p.faceEnabled,
    plate_enabled: p.plateEnabled,
    search_index_enabled: true,
    summary_enabled: p.summaryEnabled,
    summary_mode: "vlm_llm",
    language: "auto",
    sample_fps: p.sampleFps,
    segment_threshold: p.confidence,
    caption_with_context: true,
    summary_detail: "standard",
    encode_profile: null,
    apply_to_group: false,
  };
}

export function TopNav({
  onOpenHistory,
  onOpenPicker,
}: {
  onOpenHistory: () => void;
  onOpenPicker: () => void;
}) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const videoId = params.get("video") ?? "";
  const [reanalyzing, setReanalyzing] = useState(false);

  /* 对当前视频按全局参数重新发起分析任务 */
  const reanalyze = async () => {
    if (!videoId || reanalyzing) return;
    setReanalyzing(true);
    try {
      await api.reanalyze(videoId, buildPipelineParams());
      navigate(`/?video=${videoId}&refresh=${Date.now()}`);
    } catch (err) {
      alert(err instanceof Error ? err.message : "重新解析失败");
    } finally {
      setReanalyzing(false);
    }
  };

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border-light bg-white/85 px-5 backdrop-blur">
      {/* 返回首页（最左） */}
      <Link to="/" title="返回首页" className="shrink-0 rounded-lg p-2 text-gray-500 transition-colors hover:bg-surface hover:text-primary">
        <IconHome />
      </Link>

      {/* Logo */}
      <div className="flex items-center gap-2">
        <img src="/zhiying_logo.png" alt="智能分析" className="h-8 w-auto" />
        <span className="text-[15px] font-semibold italic text-[#2b3a63] tracking-wide">智能分析</span>
      </div>

      {/* 功能 Tab */}
      <nav className="flex flex-1 items-center gap-1">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.end}
            className={({ isActive }) =>
              `flex items-center gap-2 rounded-lg px-4 py-1.5 text-sm transition-colors ${
                isActive
                  ? "bg-primary-soft font-medium text-primary"
                  : "text-gray-600 hover:bg-surface"
              }`
            }
          >
            {t.icon}
            {t.label}
          </NavLink>
        ))}
      </nav>

      {/* 右侧功能区（更换视频/重新解析仅解析详情页显示） */}
      <div className="flex items-center gap-2">
        {videoId && (
          <>
            {/* 更换视频（文件库单选，与重新解析同样式；原地刷新播放器与数据面板） */}
            <button
              onClick={onOpenPicker}
              title="从文件库更换当前视频"
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary/85"
            >
              <IconFolder />
              更换视频
            </button>

            {/* 重新解析（对当前视频重新发起分析） */}
            <button
              onClick={() => void reanalyze()}
              disabled={reanalyzing}
              title="按当前参数配置重新解析该视频"
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary/85 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <IconBolt />
              {reanalyzing ? "发起中…" : "重新解析"}
            </button>
          </>
        )}

        {/* 历史记录（最右侧，次级按钮：浅蓝底 + 蓝边框） */}
        <button
          onClick={onOpenHistory}
          title="历史记录"
          className="ml-1 flex items-center gap-1.5 rounded-lg border border-primary bg-[#F0F5FF] px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary/10"
        >
          <IconClock />
          历史记录
        </button>
      </div>
    </header>
  );
}
