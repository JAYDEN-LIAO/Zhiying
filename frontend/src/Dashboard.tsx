/* ════════════════════════════════════════════════════════════
   Dashboard — Cerno 视觉工作台主组件
   v0.9: 新增检测物体面板 + Track 时间轴独立布局
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { api } from "./services/api";
import type { VideoListItem, VideoResponse, DetectionData } from "./types";
import type { PipelineSwitches } from "./mockData";
import { fmtDuration } from "./utils/helpers";
import { IconPlay, IconClose } from "./components/icons";
import { LeftSidebar, type PageView, type PanelType } from "./components/LeftSidebar";
import { ParameterPanel } from "./components/ParameterPanel";
import { PipelineBar } from "./components/PipelineBar";
import { VideoSummaryCard } from "./components/VideoSummaryCard";
import { VideoSearchCard } from "./components/VideoSearchCard";
import { HistoryPanelContent } from "./components/HistoryPanelContent";
import { SettingsPage } from "./components/SettingsPage";
import { DetectionOverlay } from "./components/DetectionOverlay";
import { DetectionPanel } from "./components/DetectionPanel";
import { DetectionTimeline } from "./components/DetectionTimeline";

export default function Dashboard() {
  const [currentPage, setCurrentPage] = useState<PageView>("dashboard");
  const [activePanel, setActivePanel] = useState<PanelType | null>(null);
  const [currentVideoId, setCurrentVideoId] = useState<string | null>(null);
  const [currentVideo, setCurrentVideo] = useState<VideoResponse | null>(null);
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listKey, setListKey] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [seekTarget, setSeekTarget] = useState<{ start: number; end: number | null } | null>(null);
  const [hasPendingParams, setHasPendingParams] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  /* ── Shared detection state (lifted from DetectionOverlay) ── */
  const [detectionData, setDetectionData] = useState<DetectionData | null>(null);
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [tracked, setTracked] = useState<{ class_name: string; track_id: number } | null>(null);
  const [classFilter, setClassFilter] = useState<string | null>(null);

  const handleTrackSelect = useCallback((trackId: number, className: string, seekTo?: number) => {
    if (trackId < 0) {
      setSelectedTrackId(null);
      setTracked(null);
      return;
    }
    setSelectedTrackId(trackId);
    setTracked({ class_name: className, track_id: trackId });
    if (seekTo !== undefined && videoRef.current) {
      videoRef.current.currentTime = seekTo;
    }
  }, []);

  const isPending = currentVideo?.status === "pending";
  const isProcessing = currentVideo?.status === "processing" || isPending;
  const isCompleted = currentVideo?.status === "completed";
  const showDetection = !!(currentVideo?.detection_enabled && isCompleted);

  /* ── Compute pipeline switches ── */
  const pipelineSwitches: PipelineSwitches = useMemo(() => {
    if (!currentVideo) return { vision_enabled: true, audio_enabled: false, caption_enabled: true, search_index_enabled: true, summary_enabled: true };
    return {
      vision_enabled: currentVideo.vision_enabled,
      audio_enabled: currentVideo.audio_enabled,
      caption_enabled: currentVideo.caption_enabled,
      search_index_enabled: currentVideo.search_index_enabled,
      summary_enabled: currentVideo.summary_enabled,
    };
  }, [currentVideo]);

  /* ── Fetch detection data ── */
  useEffect(() => {
    if (!showDetection || !currentVideoId) {
      setDetectionData(null);
      setSelectedTrackId(null);
      setTracked(null);
      setClassFilter(null);
      return;
    }
    setClassFilter(null);  // new video → reset to "全部"
    api.fetchDetectionData(currentVideoId)
      .then((d) => setDetectionData(d))
      .catch(() => setDetectionData(null));
  }, [currentVideoId, showDetection]);

  /* ── Fetch video list ── */
  useEffect(() => {
    setListLoading(true);
    api.listVideos()
      .then((data) => setVideos(data ?? []))
      .catch(() => {})
      .finally(() => setListLoading(false));
  }, [listKey]);

  /* ── Fetch video detail ── */
  useEffect(() => {
    if (!currentVideoId) { setCurrentVideo(null); return; }
    let cancelled = false;
    let timer: ReturnType<typeof setInterval> | null = null;
    const fetchVideo = async () => {
      try {
        const data = await api.getVideo(currentVideoId);
        if (!cancelled) {
          setCurrentVideo(data);
          setVideos((prev) => prev.map((v) =>
            v.id === data.id ? { ...v, status: data.status, progress: data.progress, summary_one_liner: data.summary?.one_liner ?? v.summary_one_liner } : v
          ));
          if (data.status !== "processing" && data.status !== "pending") {
            if (timer) clearInterval(timer);
          }
        }
      } catch { /* retry */ }
    };
    fetchVideo();
    timer = setInterval(fetchVideo, 3000);
    return () => { cancelled = true; if (timer) clearInterval(timer); };
  }, [currentVideoId]);

  /* ── Seek ── */
  useEffect(() => {
    if (!seekTarget || !videoRef.current) return;
    videoRef.current.currentTime = seekTarget.start;
    videoRef.current.play().catch(() => {});
  }, [seekTarget]);

  /* ── Nav ── */
  const handleNavigate = useCallback((page: PageView) => { setCurrentPage(page); setActivePanel(null); }, []);
  const handleTogglePanel = useCallback((panel: PanelType) => { setActivePanel((prev) => (prev === panel ? null : panel)); }, []);

  const handleSelect = useCallback((id: string) => {
    if (id === currentVideoId) return;
    setCurrentVideoId(id);
    setCurrentVideo(null);
    setHasPendingParams(false);
  }, [currentVideoId]);

  const handleDelete = useCallback((deletedId: string) => {
    if (currentVideoId === deletedId) { setCurrentVideoId(null); setCurrentVideo(null); }
  }, [currentVideoId]);

  const handleUpload = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file"; input.accept = ".mp4,.mov,.avi,.mkv,.webm";
    input.onchange = async () => {
      const file = input.files?.[0]; if (!file) return;
      setIsUploading(true);
      try {
        const result = await api.upload(file);
        setCurrentVideoId(result.id); setCurrentVideo(result);
        setListKey((k) => k + 1);
        setHasPendingParams(true); setActivePanel("params");
      } catch (err) { alert(err instanceof Error ? err.message : "上传失败"); }
      setIsUploading(false);
    };
    input.click();
  }, []);

  /* ── Labels ── */
  const ctLabel: Record<string, string> = { general: "通用", meeting: "会议", surveillance: "监控", text_recognition: "文字识别", custom: "自定义" };
  const langLabel: Record<string, string> = { auto: "自动", zh: "中文", en: "English", ja: "日本語", ko: "한국어" };
  const statLabel = currentVideo?.file_name ?? "等待选择";
  const statValue = currentVideo?.duration != null ? fmtDuration(currentVideo.duration) : "—";

  return (
    <div className="dashboard-container relative h-screen">
      <div className="fluid-blob fluid-blob-blue" />
      <div className="fluid-blob fluid-blob-green" />
      <div className="fluid-blob fluid-blob-warm" />
      <div className="fluid-blob fluid-blob-left" />
      <div className="fluid-blob fluid-blob-left-2" />
      <div className="fluid-blob fluid-blob-right" />

      {/* ── Header ── */}
      <div className="absolute left-[112px] top-[24px] flex items-center gap-3 pointer-events-none">
        <img src="/cerno.svg" alt="Cerno" className="h-14 w-auto shrink-0 -mt-1" />
        <div className="relative" style={{ width: '5em', height: '1.5em' }}>
          <span className="absolute left-0 top-0 transition-all duration-300 ease-out whitespace-nowrap text-lg font-bold text-gray-500"
                style={{ opacity: currentPage === 'dashboard' ? 1 : 0, transform: currentPage === 'dashboard' ? 'translateY(0)' : 'translateY(-0.5em)' }}>
            工作台
          </span>
          <span className="absolute left-0 top-0 transition-all duration-300 ease-out whitespace-nowrap text-lg font-bold text-gray-500"
                style={{ opacity: currentPage === 'dashboard' ? 0 : 1, transform: currentPage === 'dashboard' ? 'translateY(0.5em)' : 'translateY(0)' }}>
            系统设置
          </span>
        </div>
      </div>

      {/* ── Divider + Upload ── */}
      <div className="absolute left-[112px] right-4 top-[80px] z-20 pointer-events-none">
        <div className="h-px bg-gray-300/60 w-full" />
        <button
          onClick={handleUpload}
          className="pointer-events-auto absolute -top-[52px] w-[126px] h-[34px] rounded-lg bg-emerald-500 text-white flex items-center justify-center hover:bg-emerald-400 transition-all shadow-md group"
          style={{ right: '16px', display: currentPage !== "dashboard" ? "none" : undefined }}
          title="上传视频"
        >
          <svg className="w-5 h-5 transition-transform duration-300 group-hover:rotate-45" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2.5" strokeLinecap="round">
            <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>

      {/* ── Left Sidebar + Slide-out Panels ── */}
      <div className="relative flex-shrink-0 z-20 ml-4 my-4">
        <div className="relative z-10 h-full">
          <LeftSidebar currentPage={currentPage} activePanel={activePanel} onNavigate={handleNavigate} onTogglePanel={handleTogglePanel} onUpload={handleUpload} />
        </div>

        {/* Parameter Panel */}
        <div className="absolute top-0 overflow-hidden bg-[#e8f0fc] rounded-r-[24px] shadow-lg"
             style={{ left: 32, width: activePanel === "params" ? 420 : 0, height: "100%", border: "1px solid rgba(203, 213, 225, 0.8)", borderLeft: "none", borderColor: activePanel === "params" ? "rgba(203, 213, 225, 0.8)" : "transparent", boxShadow: activePanel === "params" ? "4px 0 24px rgba(0,0,0,0.3)" : "none", transition: "width 500ms cubic-bezier(0.4, 0, 0.2, 1)" }}>
          <div style={{ position: "absolute", left: activePanel === "params" ? 0 : -420, top: 0, width: 420, height: "100%", paddingLeft: 32, transition: "left 500ms cubic-bezier(0.4, 0, 0.2, 1)" }}>
            <ParameterPanel videoId={currentVideoId} onClose={() => { setActivePanel(null); setHasPendingParams(false); }} onParamsSet={() => setHasPendingParams(false)} onUploadDone={(newId: string) => { setCurrentVideoId(newId); setCurrentVideo(null); setListKey((k) => k + 1); }} />
          </div>
        </div>

        {/* History Panel */}
        <div className="absolute top-0 overflow-hidden bg-[#e8f0fc] rounded-r-[24px] shadow-lg"
             style={{ left: 32, width: activePanel === "history" ? 380 : 0, height: "100%", border: "1px solid rgba(203, 213, 225, 0.8)", borderLeft: "none", borderColor: activePanel === "history" ? "rgba(203, 213, 225, 0.8)" : "transparent", boxShadow: activePanel === "history" ? "4px 0 24px rgba(0,0,0,0.3)" : "none", transition: "width 500ms cubic-bezier(0.4, 0, 0.2, 1)" }}>
          <div style={{ position: "absolute", left: activePanel === "history" ? 0 : -380, top: 0, width: 380, height: "100%", paddingLeft: 32, transition: "left 500ms cubic-bezier(0.4, 0, 0.2, 1)" }}>
            <div className="flex flex-col" style={{ height: "100%" }}>
              <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 shrink-0">
                <h2 className="font-bold text-gray-900 text-base">历史记录</h2>
                <button onClick={() => setActivePanel(null)} className="text-gray-400 hover:text-gray-600 transition-colors"><IconClose /></button>
              </div>
              <HistoryPanelContent videos={videos} currentVideoId={currentVideoId} loading={listLoading} onSelect={(id) => { handleSelect(id); setActivePanel(null); }} onDelete={handleDelete} />
            </div>
          </div>
        </div>
      </div>

      {/* ── Click-outside backdrop ── */}
      {activePanel !== null && !hasPendingParams && (
        <div className="absolute inset-0 z-[15]" onClick={() => setActivePanel(null)} />
      )}

      {/* ════════════════════════════════════════════════════════
         Page Content
         ════════════════════════════════════════════════════════ */}
      {currentPage === "dashboard" ? (
        <div className="flex-1 flex min-h-0 z-10">
          {/* ── Main Column: video + timeline + pipeline ── */}
          <main className="flex-1 flex flex-col min-w-0">
            <div className="flex-1 pt-[96px] pl-8 pr-2 pb-4 flex flex-col min-h-0 relative">
              {/* Stats bar — absolutely positioned, doesn't affect video alignment */}
              {currentVideo ? (
                <div className="absolute top-[23px] right-4 flex items-center gap-2.5 z-10">
                  <span className="font-semibold text-xs text-gray-700">{ctLabel[currentVideo.content_type] || currentVideo.content_type}</span>
                  <span className="text-gray-300 text-xs">·</span>
                  <span className="text-xs text-gray-600">{currentVideo.summary_enabled ? (currentVideo.summary_mode === "vlm_llm" ? "VLM+LLM" : "原生") : ""}{currentVideo.search_index_enabled ? (currentVideo.summary_enabled ? " + 搜索" : "搜索") : (currentVideo.summary_enabled ? "摘要" : "")}</span>
                  <span className="text-gray-300 text-xs">·</span>
                  <span className="text-xs text-gray-600">{langLabel[currentVideo.language] || currentVideo.language}</span>
                  <span className="text-gray-300 text-xs">·</span>
                  <span className="text-xs text-gray-600">{currentVideo.sample_fps.toFixed(1)}fps</span>
                  <span className="text-gray-300 text-xs">·</span>
                  <span className="text-xs text-gray-600">阈值 {(currentVideo.segment_threshold ?? 0.5).toFixed(1)}</span>
                  <div className="w-0.5 h-8 mx-1 bg-gray-300 rounded-full flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium text-gray-800">{statLabel}</p>
                    <p className="text-gray-500 text-sm font-mono">{statValue}</p>
                  </div>
                </div>
              ) : (
                <div className="absolute top-[23px] right-4 z-10">
                  <div className="flex items-start gap-3">
                    <div className="w-0.5 h-8 mt-0.5 bg-gray-300 rounded-full flex-shrink-0" />
                    <div><p className="text-sm font-medium text-gray-800">等待选择</p><p className="text-gray-500 text-sm font-mono">—</p></div>
                  </div>
                </div>
              )}

              {/* ── Video Player (top at 96px, aligned with objects panel) ── */}
              <div className="w-full aspect-video relative rounded-2xl overflow-hidden bg-black shadow-inner shrink-0">
                {currentVideoId && currentVideo ? (
                  <div className="relative w-full h-full">
                    <video
                      ref={videoRef}
                      key={currentVideoId}
                      className="w-full h-full object-contain bg-black"
                      src={api.getVideoStreamUrl(currentVideoId)}
                      controls autoPlay={false} preload="auto" playsInline
                    >您的浏览器不支持视频播放</video>
                    <DetectionOverlay
                      videoRef={videoRef}
                      videoId={currentVideoId}
                      enabled={currentVideo.detection_enabled ?? false}
                      data={detectionData}
                      selectedTrackId={selectedTrackId}
                      onTrackSelect={(tid, cls) => handleTrackSelect(tid, cls)}
                    />
                  </div>
                ) : isUploading ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-4">
                    <div className="w-12 h-12 rounded-full bg-black/30 flex items-center justify-center shadow-lg">
                      <svg className="w-6 h-6 text-white animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                    </div>
                    <p className="text-sm text-gray-400">视频上传中...</p>
                  </div>
                ) : (
                  <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
                    <div className="w-16 h-16 rounded-full bg-black/40 flex items-center justify-center shadow-lg"><IconPlay /></div>
                    <p className="text-sm text-gray-400">上传或选择视频开始</p>
                  </div>
                )}
              </div>

              {/* ── Track Timeline — always same component, handles empty state internally ── */}
              <DetectionTimeline
                videoId={currentVideoId ?? ""}
                videoRef={videoRef}
                selectedTrackId={selectedTrackId}
                classFilter={classFilter}
                onTrackSelect={handleTrackSelect}
                data={detectionData}
              />

              {/* ── Pipeline Bar (pushed to bottom, aligns with objects panel bottom) ── */}
              <div className="shrink-0 mt-auto">
                <PipelineBar progress={currentVideo?.progress ?? 0} statusDetail={currentVideo?.status_detail} switches={pipelineSwitches} subtitle={currentVideo?.status === "pending" ? "等待参数配置..." : null} />
              </div>
            </div>
          </main>

          {/* ── Objects Panel — always visible, same width in all states ── */}
          <div className="pt-[96px] pb-4 pr-0 flex-shrink-0">
            <DetectionPanel
              video={currentVideo}
              data={detectionData}
              selectedTrackId={selectedTrackId}
              classFilter={classFilter}
              onClassFilterChange={setClassFilter}
              onTrackSelect={handleTrackSelect}
            />
          </div>

          {/* ── Right Sidebar: Summary + Search ── */}
          <aside className="w-[460px] pr-4 pt-[96px] pb-4 pl-1 flex flex-col gap-1 flex-shrink-0 h-full">
            <div className="flex-1 min-h-0"><VideoSummaryCard video={currentVideo} /></div>
            <div className="flex-1 min-h-0"><VideoSearchCard video={currentVideo} onSeekTo={(start: number, end: number | null) => setSeekTarget({ start, end })} /></div>
          </aside>
        </div>
      ) : (
        <SettingsPage />
      )}
    </div>
  );
}
