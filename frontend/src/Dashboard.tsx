/* ════════════════════════════════════════════════════════════
   Dashboard — slim orchestrator (v2.0)
   Layout: Sidebar | Header | VideoSection + RightPanel
   State management: custom hooks
   ════════════════════════════════════════════════════════════ */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { api } from "./services/api";
import type { VideoListItem, VideoResponse, VideoGroup, PipelineStage } from "./types";
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
import { useYunzhi } from "./platform/YunzhiProvider";
import type { YunzhiResource } from "./platform/yunzhi-bridge";

export default function Dashboard() {
  /* ── Navigation & Panels ── */
  const [currentPage, setCurrentPage] = useState<PageView>("dashboard");
  const [activePanel, setActivePanel] = useState<PanelType | null>(null);
  const navigate = useCallback((page: PageView) => { setCurrentPage(page); setActivePanel(null); }, []);

  /* ── Video selection ── */
  const [currentVideoId, setCurrentVideoId] = useState<string | null>(null);
  const [currentVideo, setCurrentVideo] = useState<VideoResponse | null>(null);
  const [pipelineStages, setPipelineStages] = useState<PipelineStage[]>([]);
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

  /* ── 云智平台 Bridge（mock=true 独立开发走本地上传；false 走平台文件库选文件） ── */
  const { mock: yunzhiMock, selectFiles: yunzhiSelectFiles } = useYunzhi();

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
    let cancelled = false;
    setDetectionVideo(null);
    api.getVideo(detectionVideoId)
      .then((data) => { if (!cancelled) setDetectionVideo(data); })
      .catch(() => { if (!cancelled) setDetectionVideo(null); });
    return () => { cancelled = true; };
  }, [detectionVideoId]);

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

  // Pipeline plan comes from the backend gate/weight calculation.
  useEffect(() => {
    if (!currentVideoId) {
      setPipelineStages([]);
      return;
    }
    let cancelled = false;
    api.getPipelineOperations(currentVideoId)
      .then((stages) => { if (!cancelled) setPipelineStages(stages); })
      .catch(() => { if (!cancelled) setPipelineStages([]); });
    return () => { cancelled = true; };
  }, [currentVideoId, currentVideo?.updated_at]);

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
    if (detectionVideoId === deletedId) { setDetectionVideoId(null); setDetectionVideo(null); }
    // ★ 同步清理 videoGroups
    setVideoGroups(prev => {
      const updated = prev.map(g => ({
        ...g,
        videoIds: g.videoIds.filter(id => id !== deletedId),
      })).filter(g => g.videoIds.length > 0);
      return updated;
    });
  }, [currentVideoId, detectionVideoId]);

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

  /* ── 上传文件 (单/多, Header 选择与拖拽共用) ── */
  const handleFiles = useCallback(async (fileList: FileList | File[]) => {
    const files = Array.from(fileList);
    if (files.length === 0) return;
    // 从设置页拖入/点"开始"时先切回工作台
    setCurrentPage("dashboard");
    setActivePanel(null);
    setIsUploading(true);
    try {
      if (files.length === 1) {
        const result = await api.upload(files[0]);
        setCurrentVideoId(result.id);
        setCurrentVideo(result);
      } else {
        const results = await api.uploadBatch(files);
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
  }, []);

  /* ── 注册平台共享路径视频（云智 Bridge 选文件 → 就地引用，不上传字节） ── */
  const registerExternal = useCallback(async (items: YunzhiResource[]) => {
    const files = items.filter((i) => i.resourceType === "FILE" && i.absolutePath);
    if (files.length === 0) {
      alert("请选择文件（不是文件夹）");
      return;
    }
    setCurrentPage("dashboard");
    setActivePanel(null);
    setIsUploading(true);
    try {
      if (files.length === 1) {
        const result = await api.registerFromPath(files[0].absolutePath!, files[0].name);
        setCurrentVideoId(result.id);
        setCurrentVideo(result);
      } else {
        const results = await Promise.all(
          files.map((f) => api.registerFromPath(f.absolutePath!, f.name))
        );
        setCurrentVideoId(results[0].id);
        setCurrentVideo(results[0]);
        if (results[0].group_id) {
          setVideoGroups((prev) => [...prev, {
            groupId: results[0].group_id!,
            videoIds: results.map((r) => r.id),
          }]);
        }
      }
      setListKey((k) => k + 1);
      setHasPendingParams(true);
      setActivePanel("params");
    } catch (err) {
      alert(err instanceof Error ? err.message : "注册共享文件失败");
    }
    setIsUploading(false);
  }, []);

  /* ── Upload (v0.19 支持多选; 云智宿主模式走 Bridge 文件库选文件) ── */
  const handleUpload = useCallback(() => {
    if (!yunzhiMock) {
      // 平台宿主模式：Bridge 从文件库选文件 → 就地注册
      void yunzhiSelectFiles()
        .then((items) => registerExternal(items))
        .catch((err) => {
          if (!(err instanceof Error && /用户取消/.test(err.message))) {
            alert(err instanceof Error ? err.message : "平台文件选择失败");
          }
        });
      return;
    }
    // 独立开发模式：本地文件选择
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".mp4,.mov,.avi,.mkv,.webm";
    input.multiple = true;
    input.onchange = () => {
      handleFiles(input.files ?? []);
      input.value = ""; // 允许重复选择同一文件
    };
    input.click();
  }, [handleFiles, registerExternal, yunzhiMock, yunzhiSelectFiles]);

  /* ── 拖拽上传 (单个/多个视频直接拖入窗口) ── */
  const [dragActive, setDragActive] = useState(false);
  const dragDepthRef = useRef(0);

  useEffect(() => {
    const hasFiles = (e: DragEvent) => !!e.dataTransfer?.types?.includes("Files");
    const onDragEnter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      dragDepthRef.current += 1;
      setDragActive(true);
    };
    const onDragOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault(); // 必须阻止默认行为才能触发 drop
      if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    };
    const onDragLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
      if (dragDepthRef.current === 0) setDragActive(false);
    };
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      dragDepthRef.current = 0;
      setDragActive(false);
      const files = e.dataTransfer?.files;
      if (!files || files.length === 0) return;
      // 过滤出视频文件 (与上传 input accept 一致)
      const videos = Array.from(files).filter(
        (f) => /\.(mp4|mov|avi|mkv|webm)$/i.test(f.name) || f.type.startsWith("video/"),
      );
      if (videos.length > 0) handleFiles(videos);
    };
    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [handleFiles]);

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
        <button onClick={() => setShowExport((v) => !v)} className="w-6 h-6 rounded-lg flex items-center justify-center text-gray-400 hover:text-teal-600 hover:bg-teal-50 transition-all cursor-pointer" title="导出">
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
                    className="text-[11px] text-teal-300 hover:text-white cursor-pointer flex items-center gap-0.5 shrink-0 transition-colors">
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
              pipelineStages={pipelineStages} videoRef={videoRef}
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

      {/* ── 拖拽上传遮罩 ── */}
      {dragActive && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm pointer-events-none">
          <div className="flex flex-col items-center gap-3 px-10 py-8 rounded-2xl border-2 border-dashed border-teal-400 bg-teal-950/70 shadow-2xl">
            <svg className="w-10 h-10 text-teal-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 3v12" /><path d="m7 8 5-5 5 5" /><path d="M5 21h14" />
            </svg>
            <div className="text-white text-lg font-semibold">松开以上传视频</div>
            <div className="text-white/60 text-sm">支持单个或多个视频 · MP4 / MOV / AVI / MKV / WEBM</div>
          </div>
        </div>
      )}
    </div>
  );
}
