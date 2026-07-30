/* ════════════════════════════════════════════════════════════
   Dashboard — slim orchestrator (v2.0)
   Layout: Sidebar | Header | VideoSection + RightPanel
   State management: custom hooks + DetectionContext
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { api } from "./services/api";
import type { VideoListItem, VideoResponse, VideoGroup } from "./types";
import { fmtDuration } from "./utils/helpers";
import { IconDownload } from "./components/icons";
import { ExportMenu } from "./components/ExportMenu";
import { Sidebar, type PageView, type PanelType } from "./components/Sidebar";
import { Header } from "./components/Header";
import { SlideOutPanel } from "./components/SlideOutPanel";
import { ParameterPanel } from "./components/ParameterPanel";
import { HistoryPanelContent } from "./components/HistoryPanelContent";
import { VideoSection } from "./components/VideoSection";
import { RightPanel } from "./components/RightPanel";
import { SettingsPage } from "./components/SettingsPage";
import { useHEVCCapability } from "./hooks/useHEVCCapability";
import { useVideoPolling } from "./hooks/useVideoPolling";
import { useProxyStatus } from "./hooks/useProxyStatus";
import { useDetectionData } from "./hooks/useDetectionData";
import { useStreamReady } from "./hooks/useStreamReady";

export default function Dashboard() {
  /* ── Navigation & Panels ── */
  const [currentPage, setCurrentPage] = useState<PageView>("dashboard");
  const [activePanel, setActivePanel] = useState<PanelType | null>(null);
  const navigate = useCallback((page: PageView) => { setCurrentPage(page); setActivePanel(null); }, []);

  /* ── Video selection ── */
  const [currentVideoId, setCurrentVideoId] = useState<string | null>(null);
  const [currentVideo, setCurrentVideo] = useState<VideoResponse | null>(null);
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [listKey, setListKey] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [hasPendingParams, setHasPendingParams] = useState(false);
  const [seekTarget, setSeekTarget] = useState<{ start: number; end: number | null } | null>(null);
  const [showExport, setShowExport] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  /* ── Group state (v0.19 多视频处理) ── */
  const [videoGroups, setVideoGroups] = useState<VideoGroup[]>([]);
  const [currentGroupVideos, setCurrentGroupVideos] = useState<string[]>([]);
  const [drillGroupId, setDrillGroupId] = useState<string | null>(null);
  const [detectionVideoId, setDetectionVideoId] = useState<string | null>(null);
  const [detectionVideo, setDetectionVideo] = useState<VideoResponse | null>(null);

  /* ── Panel toggle (must be after currentVideo / drillGroupId declarations) ── */
  const togglePanel = useCallback((panel: PanelType) => {
    const isCurrentlyOpen = activePanel === panel;
    setActivePanel(isCurrentlyOpen ? null : panel);
    if (panel === "history") {
      if (isCurrentlyOpen) {
        setDrillGroupId(null);
      } else {
        setDrillGroupId(currentVideo?.group_id ?? null);
      }
    }
  }, [activePanel, currentVideo?.group_id]);

  /* ── Compute derived booleans ── */
  const isPending = currentVideo?.status === "pending";
  const isProcessing = currentVideo?.status === "processing" || isPending;
  const isCompleted = currentVideo?.status === "completed";
  const showDetection = !!(currentVideo?.detection_enabled && isCompleted);

  /* ── Hooks ── */
  const hevcOk = useHEVCCapability();

  // Video detail polling
  useVideoPolling({
    videoId: currentVideoId,
    onUpdate: useCallback((data: VideoResponse) => {
      setCurrentVideo(data);
      setVideos((prev) => prev.map((v) =>
        v.id === data.id
          ? { ...v, status: data.status, progress: data.progress, summary_one_liner: data.summary?.one_liner ?? v.summary_one_liner }
          : v
      ));
    }, []),
  });

  // Proxy status polling
  const needsProxy = useMemo(() => {
    if (!currentVideo) return false;
    const vc = currentVideo.video_codec;
    return !!vc && vc !== "h264" && !hevcOk;
  }, [currentVideo?.video_codec, hevcOk]);

  const proxyStatus = useProxyStatus(
    currentVideoId,
    needsProxy,
    useCallback(() => { if (videoRef.current) videoRef.current.load(); }, []),
  );

  // Stream readiness
  const streamReady = useStreamReady(currentVideo, hevcOk);

  // Detection video sync (v0.19 — 独立于当前播放视频)
  useEffect(() => {
    if (!detectionVideoId) { setDetectionVideo(null); return; }
    const found = videos.find(v => v.id === detectionVideoId);
    if (found) api.getVideo(detectionVideoId).then(setDetectionVideo);
  }, [detectionVideoId, videos]);

  // Detection data (使用 detectionVideoId，若未设置则跟随 currentVideoId)
  const actualDetectionId = detectionVideoId ?? currentVideoId;
  const actualDetectionFace = detectionVideo?.face_enabled ?? currentVideo?.face_enabled ?? false;
  const actualDetectionPlate = detectionVideo?.plate_enabled ?? currentVideo?.plate_enabled ?? false;
  const { detectionData, faceData, plateData } = useDetectionData(
    actualDetectionId,
    showDetection,
    actualDetectionFace,
    actualDetectionPlate,
  );

  // Pipeline switches
  const pipelineSwitches = useMemo(() => {
    if (!currentVideo) return { vision_enabled: true, audio_enabled: false, caption_enabled: true, search_index_enabled: true, summary_enabled: true };
    return {
      vision_enabled: currentVideo.vision_enabled,
      audio_enabled: currentVideo.audio_enabled,
      caption_enabled: currentVideo.caption_enabled,
      search_index_enabled: currentVideo.search_index_enabled,
      summary_enabled: currentVideo.summary_enabled,
    };
  }, [currentVideo]);

  /* ── Track selection state ── */
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [classFilter, setClassFilter] = useState<string | null>(null);

  const handleTrackSelect = useCallback((trackId: number, className: string, seekTo?: number) => {
    if (trackId < 0) {
      setSelectedTrackId(null);
      return;
    }
    setSelectedTrackId(trackId);
    if (seekTo !== undefined && videoRef.current) {
      videoRef.current.currentTime = seekTo;
    }
  }, []);

  /* ── Fetch video list ── */
  useEffect(() => {
    api.listVideos()
      .then((data) => setVideos(data ?? []))
      .catch(() => {});
  }, [listKey]);

  /* ── Periodic refresh for real-time status updates ── */
  useEffect(() => {
    const interval = setInterval(() => {
      api.listVideos().then((data) => { if (data) setVideos(data); }).catch(() => {});
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  /* ── Rebuild videoGroups from API data (persist across reload) ── */
  useEffect(() => {
    const groupMap = new Map<string, string[]>();
    for (const v of videos) {
      if (v.group_id) {
        const existing = groupMap.get(v.group_id) ?? [];
        existing.push(v.id);
        groupMap.set(v.group_id, existing);
      }
    }
    const rebuilt: VideoGroup[] = [];
    for (const [groupId, videoIds] of groupMap) {
      rebuilt.push({ groupId, videoIds });
    }
    setVideoGroups(rebuilt);
  }, [videos]);

  /* ── Seek ── */
  useEffect(() => {
    if (!seekTarget || !videoRef.current) return;
    videoRef.current.currentTime = seekTarget.start;
    // end 为 null 表示单帧定位（如图搜结果），不自动播放
    if (seekTarget.end != null) {
      videoRef.current.play().catch(() => {});
    }
  }, [seekTarget]);

  /* ── Video selection (v0.19 支持分组) ── */
  const handleSelect = useCallback((id: string, groupId?: string) => {
    if (id === currentVideoId) return;
    setCurrentVideoId(id);
    setCurrentVideo(null);
    setHasPendingParams(false);
    setSelectedTrackId(null);
    setClassFilter(null);
    // 优先使用传入的 groupId，否则从 videos 列表查找视频自身的 group_id
    const resolvedGroupId = groupId ?? videos.find(v => v.id === id)?.group_id ?? undefined;
    if (resolvedGroupId) {
      const group = videoGroups.find(g => g.groupId === resolvedGroupId);
      setCurrentGroupVideos(group?.videoIds ?? [id]);
    } else {
      setCurrentGroupVideos([id]);
    }
  }, [currentVideoId, videoGroups, videos]);

  const handleDelete = useCallback((deletedId: string) => {
    if (currentVideoId === deletedId) { setCurrentVideoId(null); setCurrentVideo(null); }
    // ★ 同步清理 videoGroups
    setVideoGroups(prev => {
      const updated = prev.map(g => ({
        ...g,
        videoIds: g.videoIds.filter(id => id !== deletedId),
      })).filter(g => g.videoIds.length > 0);
      return updated;
    });
  }, [currentVideoId]);

  /* ── Group video switch (v0.19) ── */
  const handleGroupVideoSwitch = useCallback((videoId: string) => {
    if (videoId === currentVideoId) return;
    const group = videoGroups.find(g => g.videoIds.includes(videoId));
    if (group) {
      setCurrentGroupVideos(group.videoIds);
    } else {
      setCurrentGroupVideos([videoId]);
    }
    setCurrentVideoId(videoId);
    setCurrentVideo(null);
    setHasPendingParams(false);
    setSelectedTrackId(null);
    setClassFilter(null);
    setSeekTarget(null);
    // 检测面板跟随切换（如未独立设置）
    if (!detectionVideoId || group?.videoIds.includes(detectionVideoId)) {
      setDetectionVideoId(null);
    }
  }, [currentVideoId, videoGroups, detectionVideoId]);

  /* ── Upload (v0.19 支持多选) ── */
  const handleUpload = useCallback(() => {
    // 从设置页点"开始"时先切回工作台
    setCurrentPage("dashboard");
    setActivePanel(null);
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".mp4,.mov,.avi,.mkv,.webm";
    input.multiple = true;
    input.onchange = async () => {
      const files = input.files;
      if (!files || files.length === 0) return;
      setIsUploading(true);
      try {
        if (files.length === 1) {
          const result = await api.upload(files[0]);
          setCurrentVideoId(result.id);
          setCurrentVideo(result);
        } else {
          const results = await api.uploadBatch(Array.from(files));
          setCurrentVideoId(results[0].id);
          setCurrentVideo(results[0]);
          setVideoGroups(prev => [...prev, {
            groupId: results[0].group_id!,
            videoIds: results.map(r => r.id),
          }]);
        }
        setListKey((k) => k + 1);
        setHasPendingParams(true);
        setActivePanel("params");
      } catch (err) {
        alert(err instanceof Error ? err.message : "上传失败");
      }
      setIsUploading(false);
    };
    input.click();
  }, []);

  /* ── Labels for stats bar ── */
  const ctLabel: Record<string, string> = { general: "通用", meeting: "会议", surveillance: "监控", text_recognition: "文字识别", custom: "自定义" };
  const langLabel: Record<string, string> = { auto: "自动", zh: "中文", en: "English", ja: "日本語", ko: "한국어" };

  const statsContent = currentVideo ? (
    <div className="header-stats-wrap">
      <div className="header-stats">
        <span className="header-stats-name">{currentVideo.file_name}</span>
        <span className="header-stats-meta">
          {currentVideo.duration != null ? fmtDuration(currentVideo.duration) : "—"}
          <span className="sep">·</span>
          <span>{ctLabel[currentVideo.content_type] || currentVideo.content_type}</span>
          <span className="sep">·</span>
          <span>{langLabel[currentVideo.language] || currentVideo.language}</span>
          <span className="sep">·</span>
          <span>{currentVideo.sample_fps.toFixed(1)}fps</span>
          {currentVideo.summary_enabled && <><span className="sep">·</span><span>{currentVideo.summary_mode === "vlm_llm" ? "VLM+LLM" : "原生"}{currentVideo.search_index_enabled ? "+搜索" : ""}</span></>}
          {!currentVideo.summary_enabled && currentVideo.search_index_enabled && <><span className="sep">·</span><span>搜索</span></>}
        </span>
      </div>
      <div className="relative flex-shrink-0">
        <button onClick={() => setShowExport((v) => !v)} className="w-6 h-6 rounded-lg flex items-center justify-center text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-all cursor-pointer" title="导出">
          <IconDownload />
        </button>
        {showExport && <div className="fixed inset-0 z-40" onClick={() => setShowExport(false)} />}
        {showExport && currentVideoId && (
          <div className="absolute right-0 top-full mt-1 z-50">
            <ExportMenu videoId={currentVideoId} onClose={() => setShowExport(false)} />
          </div>
        )}
      </div>
    </div>
  ) : null;

  return (
    <div className="app">
      {/* ── Sidebar ── */}
      <Sidebar currentPage={currentPage} activePanel={activePanel} onNavigate={navigate} onTogglePanel={togglePanel} />

      {/* ── Slide-out panels ── */}
      <div className="relative flex-shrink-0 z-20">
        <SlideOutPanel open={activePanel === "params"} width={380}>
          <div className="h-full flex flex-col slide-panel-content" style={{ paddingLeft: 12 }}>
            <ParameterPanel
              videoId={currentVideoId}
              onClose={() => { setActivePanel(null); setHasPendingParams(false); }}
              onParamsSet={() => setHasPendingParams(false)}
              onUploadDone={(newId: string) => { setCurrentVideoId(newId); setCurrentVideo(null); setListKey((k) => k + 1); }}
            />
          </div>
        </SlideOutPanel>

        <SlideOutPanel open={activePanel === "history"} width={380}>
          <div className="h-full flex flex-col slide-panel-content" style={{ paddingLeft: 12 }}>
            <div className="flex items-center gap-3 px-5 py-4 border-b border-white/10 shrink-0">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <h2 className="font-bold text-white text-base shrink-0">历史记录</h2>
                {drillGroupId && (
                  <button onClick={() => setDrillGroupId(null)}
                    className="text-[11px] text-blue-300 hover:text-white cursor-pointer flex items-center gap-0.5 shrink-0 transition-colors">
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2"><path d="M19 12H5" /><polyline points="12 19 5 12 12 5" /></svg>
                    返回全部
                  </button>
                )}
              </div>
              <button onClick={() => setActivePanel(null)} className="text-white/50 hover:text-white transition-colors cursor-pointer shrink-0">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>
            <HistoryPanelContent videos={videos} currentVideoId={currentVideoId} loading={false}
              videoGroups={videoGroups} drillGroupId={drillGroupId} onDrillChange={setDrillGroupId}
              onSelect={(id: string, groupId?: string) => { handleSelect(id, groupId); if (!groupId) setActivePanel(null); }} onDelete={handleDelete} />
          </div>
        </SlideOutPanel>
      </div>

      {/* Click-outside backdrop — always close on blank click */}
      {activePanel !== null && (
        <div className="absolute inset-0 z-[15]" onClick={() => setActivePanel(null)} />
      )}

      {/* ── Header ── */}
      <Header isUploading={isUploading} onUpload={handleUpload} currentPage={currentPage} statsBar={statsContent} />

      {/* ════════════════════════════════════════════════════════════
         Page content
         ════════════════════════════════════════════════════════════ */}
      {currentPage === "dashboard" ? (
        <>
          {/* ── Main content area ── */}
          <main className="main-area">
            {/* ── Video Section (center column) ── */}
            <VideoSection
              videoId={currentVideoId} video={currentVideo} streamReady={streamReady}
              hevcOk={hevcOk} isUploading={isUploading}
              detectionEnabled={currentVideo?.detection_enabled ?? false}
              hasDetection={showDetection} detectionData={detectionData}
              faceData={faceData} selectedTrackId={selectedTrackId}
              classFilter={classFilter} proxyStatus={proxyStatus}
              pipelineSwitches={pipelineSwitches} videoRef={videoRef}
              onTrackSelect={handleTrackSelect}
            />
          </main>

          {/* ── Right Panels (v0.19 组感知) ── */}
          <RightPanel
            videoId={currentVideoId} video={currentVideo}
            detectionData={detectionData} faceData={faceData} plateData={plateData}
            selectedTrackId={selectedTrackId} classFilter={classFilter}
            onClassFilterChange={setClassFilter} onTrackSelect={handleTrackSelect}
            groupVideos={currentGroupVideos} videos={videos}
            detectionVideoId={detectionVideoId}
            onDetectionVideoChange={(vid) => {
              setDetectionVideoId(vid);
              // 同步 detectionVideo 对象
              if (vid) api.getVideo(vid).then(setDetectionVideo);
              else setDetectionVideo(null);
            }}
            onGroupVideoSwitch={handleGroupVideoSwitch}
            onSeekTo={(start, end) => {
              setSeekTarget({ start, end });
              // Direct seek in click context — avoids autoplay-blocked play()
              if (videoRef.current) videoRef.current.currentTime = start;
            }}
          />
        </>
      ) : (
        <SettingsPage />
      )}
    </div>
  );
}
