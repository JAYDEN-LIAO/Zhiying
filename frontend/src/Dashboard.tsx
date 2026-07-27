/* ════════════════════════════════════════════════════════════
   Dashboard — Cerno 视觉工作台主组件
   v0.9: 新增检测物体面板 + Track 时间轴独立布局
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { api } from "./services/api";
import type { VideoListItem, VideoResponse, DetectionData, FaceData, PlateData, ProxyStatus } from "./types";
import type { PipelineSwitches } from "./mockData";
import { fmtDuration } from "./utils/helpers";
import { IconPlay, IconClose, IconInfo, IconDownload } from "./components/icons";
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
import { MetadataPanel } from "./components/MetadataPanel";
import { ExportMenu } from "./components/ExportMenu";

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
  const [showMetadata, setShowMetadata] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  /* ── Browser HEVC capability detection (v0.13) ── */
  const [hevcOk, setHevcOk] = useState(false);
  useEffect(() => {
    const v = document.createElement("video");
    setHevcOk(v.canPlayType('video/mp4; codecs="hvc1.1.6.L123.B0"') !== "");
  }, []);

  /* ── Proxy transcode status polling ── */
  const [proxyStatus, setProxyStatus] = useState<ProxyStatus | null>(null);
  useEffect(() => {
    if (!currentVideoId || !currentVideo) return;
    // Only poll if video is not H.264 and client doesn't support HEVC
    const needsProxy =
      currentVideo.video_codec &&
      currentVideo.video_codec !== "h264" &&
      !hevcOk;
    if (!needsProxy) {
      setProxyStatus(null);
      return;
    }
    // Poll once immediately
    api.getProxyStatus(currentVideoId)
      .then(s => setProxyStatus(s))
      .catch(() => { /* ignore */ });
    // Poll every 3s while processing
    const iv = setInterval(() => {
      api.getProxyStatus(currentVideoId)
        .then(s => {
          setProxyStatus(s);
          if (s.status === "ready" || s.status === "failed") clearInterval(iv);
          // 代理就绪 → 强制重载视频
          if (s.status === "ready" && videoRef.current) {
            videoRef.current.load();
          }
        })
        .catch(() => { /* ignore */ });
    }, 3000);
    return () => clearInterval(iv);
  }, [currentVideoId, currentVideo?.video_codec, hevcOk]);

  /* ── Stream readiness: video element only renders when format is ready ── */
  const streamReady = useMemo(() => {
    if (!currentVideo) return false;
    const vc = currentVideo.video_codec;
    const cf = currentVideo.container_format;
    if (!vc) return false;                          // format not probed yet
    if (vc === "h264") return true;                 // H.264: always browser-safe
    // HEVC + hevcOk (Safari/Electron):
    //   MP4 容器 → 原文件直出（HEVC-in-MP4 可硬解）
    //   非 MP4 容器 → 需要 remux，否则浏览器无法识别容器
    if (vc === "hevc" && hevcOk) {
      if (cf === "mp4") return true;
      return !!currentVideo.remuxed_path;
    }
    // Firefox/Chrome (hevcOk=false): 等 proxy
    return currentVideo.proxy_status === "ready";
  }, [currentVideo, hevcOk]);

  // Force video reload when stream becomes ready
  useEffect(() => {
    if (streamReady && videoRef.current) {
      videoRef.current.load();
    }
  }, [streamReady]);

  /* ── Shared detection state (lifted from DetectionOverlay) ── */
  const [detectionData, setDetectionData] = useState<DetectionData | null>(null);
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [tracked, setTracked] = useState<{ class_name: string; track_id: number } | null>(null);
  const [classFilter, setClassFilter] = useState<string | null>(null);
  const [faceData, setFaceData] = useState<FaceData | null>(null);
  const [plateData, setPlateData] = useState<PlateData | null>(null);

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
      setFaceData(null);
      setPlateData(null);
      return;
    }
    setClassFilter(null);  // new video → reset to "全部"
    api.fetchDetectionData(currentVideoId)
      .then((d) => setDetectionData(d))
      .catch(() => setDetectionData(null));
    // face/plate data
    if (currentVideo?.face_enabled) {
      api.fetchFaceData(currentVideoId)
        .then((d) => setFaceData(d))
        .catch(() => setFaceData(null));
    } else {
      setFaceData(null);
    }
    if (currentVideo?.plate_enabled) {
      api.fetchPlateData(currentVideoId)
        .then((d) => setPlateData(d))
        .catch(() => setPlateData(null));
    } else {
      setPlateData(null);
    }
  }, [currentVideoId, showDetection, currentVideo?.face_enabled, currentVideo?.plate_enabled]);

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
          <LeftSidebar currentPage={currentPage} activePanel={activePanel} onNavigate={handleNavigate} onTogglePanel={handleTogglePanel} />
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
            <div className="flex-1 pt-[96px] pl-8 pr-2 pb-4 flex flex-col min-h-0 relative overflow-hidden">
              {/* Stats bar — absolutely positioned, doesn't affect video alignment */}
              {currentVideo ? (
                <div className="absolute top-[18px] right-4 z-10 flex flex-col items-end gap-0.5">
                  {/* Top row: filename + duration + action buttons */}
                  <div className="flex items-center gap-2">
                    <div className="text-right">
                      <p className="text-sm font-semibold text-gray-800 leading-tight">{statLabel}</p>
                      <p className="text-gray-500 text-xs font-mono leading-tight">{statValue}</p>
                    </div>
                    <div className="flex items-center gap-0.5 ml-1">
                      <button onClick={() => { setShowMetadata((v) => !v); setShowExport(false); }}
                        className="w-6 h-6 rounded-lg flex items-center justify-center text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-all"
                        title="视频信息"><IconInfo /></button>
                      <button onClick={() => { setShowExport((v) => !v); setShowMetadata(false); }}
                        className="w-6 h-6 rounded-lg flex items-center justify-center text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-all"
                        title="导出"><IconDownload /></button>
                    </div>
                  </div>
                  {/* Bottom row: tech params */}
                  <div className="flex items-center gap-1.5 text-[10px] text-gray-500">
                    <span className="font-medium text-gray-600">{ctLabel[currentVideo.content_type] || currentVideo.content_type}</span>
                    <span className="text-gray-300">·</span>
                    <span>{currentVideo.summary_enabled ? (currentVideo.summary_mode === "vlm_llm" ? "VLM+LLM" : "原生") : ""}{currentVideo.search_index_enabled ? (currentVideo.summary_enabled ? "+搜索" : "搜索") : (currentVideo.summary_enabled ? "摘要" : "")}</span>
                    <span className="text-gray-300">·</span>
                    <span>{langLabel[currentVideo.language] || currentVideo.language}</span>
                    <span className="text-gray-300">·</span>
                    <span>{currentVideo.sample_fps.toFixed(1)}fps</span>
                    <span className="text-gray-300">·</span>
                    <span>阈值 {(currentVideo.segment_threshold ?? 0.5).toFixed(1)}</span>
                  </div>
                  {/* Dropdown overlays */}
                  {(showMetadata || showExport) && (
                    <div className="fixed inset-0 z-40" onClick={() => { setShowMetadata(false); setShowExport(false); }} />
                  )}
                  <div className="relative">
                    {showMetadata && <MetadataPanel videoId={currentVideoId ?? ""} onClose={() => setShowMetadata(false)} />}
                    {showExport && (
                      <ExportMenu videoId={currentVideoId ?? ""}
                        onClose={() => setShowExport(false)} />
                    )}
                  </div>
                </div>
              ) : (
                <div className="absolute top-[18px] right-4 z-10">
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
                    {/* Format not ready yet — show preparing overlay instead of video */}
                    {!streamReady ? (
                      <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/80 z-20">
                        <div className="w-10 h-10 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                        <p className="text-sm text-white/70 font-medium">
                          {!currentVideo?.video_codec
                            ? "正在分析视频格式…"
                            : "正在准备视频流…"}
                        </p>
                        {proxyStatus && proxyStatus.status === "processing" && (
                          <>
                            <div className="w-48 h-1.5 bg-white/20 rounded-full overflow-hidden">
                              <div
                                className="h-full bg-indigo-400 rounded-full transition-all duration-500"
                                style={{ width: `${Math.round((proxyStatus.progress || 0) * 100)}%` }}
                              />
                            </div>
                            <p className="text-xs text-white/50 font-mono">
                              {Math.round((proxyStatus.progress || 0) * 100)}%
                            </p>
                          </>
                        )}
                      </div>
                    ) : (
                      <video
                        ref={videoRef}
                        key={currentVideoId}
                        className="w-full h-full object-contain bg-black"
                        src={api.getVideoStreamUrl(currentVideoId, hevcOk)}
                        controls autoPlay={false} preload="auto" playsInline
                      >您的浏览器不支持视频播放</video>
                    )}
                    {streamReady && (
                      <DetectionOverlay
                        videoRef={videoRef}
                        videoId={currentVideoId}
                        enabled={currentVideo.detection_enabled ?? false}
                        data={detectionData}
                        selectedTrackId={selectedTrackId}
                        onTrackSelect={(tid, cls) => handleTrackSelect(tid, cls)}
                      />
                    )}
                    {/* ── Proxy failed overlay ── */}
                    {proxyStatus && proxyStatus.status === "failed" && (
                      <div className="absolute inset-0 flex items-center justify-center bg-black/70 backdrop-blur-sm z-30">
                        <p className="text-sm text-red-400">浏览器兼容代理生成失败 — 请使用 Safari 或 Electron 打开</p>
                      </div>
                    )}
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
                faceData={faceData}
              />

              {/* ── Pipeline Bar (pushed to bottom, aligns with objects panel bottom) ── */}
              <div className="shrink-0 mt-auto">
                <PipelineBar progress={currentVideo?.progress ?? 0} statusDetail={currentVideo?.status_detail} switches={pipelineSwitches} subtitle={currentVideo?.status === "pending" ? "等待参数配置..." : null} />
              </div>
            </div>
          </main>

          {/* ── Objects Panel — always visible, same width in all states ── */}
          <div className="pt-[96px] pb-4 pr-0 flex-shrink-0 flex flex-col">
            <div className="flex-1 min-h-0">
            <DetectionPanel
              video={currentVideo}
              data={detectionData}
              selectedTrackId={selectedTrackId}
              classFilter={classFilter}
              onClassFilterChange={setClassFilter}
              onTrackSelect={handleTrackSelect}
              faceData={faceData}
              plateData={plateData}
            />
            </div>
          </div>

          {/* ── Right Sidebar: Summary + Search ── */}
          <aside className="w-[420px] pr-4 pt-[96px] pb-4 pl-1 flex flex-col gap-1 flex-shrink-0 h-full">
            <div className="flex-1 min-h-0"><VideoSummaryCard video={currentVideo} /></div>
            <div className="flex-1 min-h-0"><VideoSearchCard
              video={currentVideo}
              onSeekTo={(start: number, end: number | null) => setSeekTarget({ start, end })}
              onTrackResult={(trackId: number, className: string, start: number) => {
                setSeekTarget({ start, end: null });
                setSelectedTrackId(trackId);
                setTracked({ class_name: className, track_id: trackId });
              }}
            /></div>
          </aside>
        </div>
      ) : (
        <SettingsPage />
      )}
    </div>
  );
}
