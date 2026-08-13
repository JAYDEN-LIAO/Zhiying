/* ════════════════════════════════════════════════════════════
   Workbench — 视频解析（工作台）页（v0.34 桌面重构 · 照 demo 骨架）
   结构（智影 v2 demo Workbench.jsx）：
     顶栏：视频解析 + 视频名 + 所属分组 | 重新解析/参数 + 上传
     外层 SplitPane row 60%：左=主舞台  右=侧栏
       左舞台 col 70%：上=播放器(+分析进度浮层)  下=时间轴+管道条
       右栏 col 20%：  上=视频摘要⇄信息 toggle 卡  下=检索区
       检索区 row 42%：左=物体检测  右=视频搜索
   注：Zhiying 无 per-video 版本系统 → demo 的「版本切换器/历史记录」
   以「摘要⇄信息 toggle」承载（历史记录=视频信息）。状态逻辑=原 Dashboard。
   ════════════════════════════════════════════════════════════ */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../services/api";
import type { VideoResponse, PipelineStage } from "../types";
import { fmtDuration } from "../utils/helpers";
import { IconDownload, IconPlus } from "./icons";
import { ExportMenu } from "./ExportMenu";
import { ParameterPanel } from "./ParameterPanel";
import { VideoPlayer } from "./VideoPlayer";
import { DetectionTimeline } from "./DetectionTimeline";
import { PipelineBar } from "./PipelineBar";
import { VideoSummaryCard } from "./VideoSummaryCard";
import { VideoInfoCard } from "./VideoInfoCard";
import { DetectionPanel } from "./DetectionPanel";
import { VideoSearchCard } from "./VideoSearchCard";
import { SplitPane } from "./SplitPane";
import { useApp } from "../AppContext";
import { useHEVCCapability } from "../hooks/useHEVCCapability";
import { useVideoPolling } from "../hooks/useVideoPolling";
import { useProxyStatus } from "../hooks/useProxyStatus";
import { useDetectionData } from "../hooks/useDetectionData";
import { useStreamReady } from "../hooks/useStreamReady";

const ctLabel: Record<string, string> = { general: "通用", meeting: "会议", surveillance: "监控", text_recognition: "文字识别", custom: "自定义" };
const langLabel: Record<string, string> = { auto: "自动", zh: "中文", en: "English", ja: "日本語", ko: "한국어" };

export function Workbench() {
  const { selectedVideoId, paramsTick, videos, videoGroups, navigate, deleteVideo, handleUploadClick, isUploading } = useApp();
  const currentVideoId = selectedVideoId;

  /* ── 视频详情与状态 ── */
  const [currentVideo, setCurrentVideo] = useState<VideoResponse | null>(null);
  const [pipelineStages, setPipelineStages] = useState<PipelineStage[]>([]);
  const [seekTarget, setSeekTarget] = useState<{ start: number; end: number | null } | null>(null);
  const [showExport, setShowExport] = useState(false);
  const [paramsOpen, setParamsOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showInfo, setShowInfo] = useState(false); // 右上卡：摘要⇄信息
  const videoRef = useRef<HTMLVideoElement>(null);

  /* ── 组感知状态（v0.19） ── */
  const [currentGroupVideos, setCurrentGroupVideos] = useState<string[]>([]);
  const [detectionVideoId, setDetectionVideoId] = useState<string | null>(null);
  const [detectionVideo, setDetectionVideo] = useState<VideoResponse | null>(null);

  /* ── track/face 选择状态 ── */
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [classFilter, setClassFilter] = useState<string | null>(null);
  const [faceViewOpen, setFaceViewOpen] = useState(false);
  const [expandedFaceId, setExpandedFaceId] = useState<number | null>(null);

  /* ── 视频切换时重置工作台状态 ── */
  useEffect(() => {
    setCurrentVideo(null);
    setSelectedTrackId(null);
    setClassFilter(null);
    setFaceViewOpen(false);
    setExpandedFaceId(null);
    setSeekTarget(null);
    setShowExport(false);
    setParamsOpen(false);
    setShowInfo(false);
    if (currentVideoId) setCurrentGroupVideos([currentVideoId]);
    else setCurrentGroupVideos([]);
    setDetectionVideoId(null);
  }, [currentVideoId]);

  /* ── 自动打开参数面板（上传/智能解析后） ── */
  useEffect(() => {
    if (paramsTick > 0 && currentVideoId) setParamsOpen(true);
  }, [paramsTick, currentVideoId]);

  /* ── 派生布尔 ── */
  const isPending = currentVideo?.status === "pending";
  const isProcessing = currentVideo?.status === "processing" || isPending;
  const isCompleted = currentVideo?.status === "completed";
  const showDetection = !!(currentVideo?.detection_enabled && isCompleted);

  /* ── Hooks ── */
  const hevcOk = useHEVCCapability();

  useVideoPolling({
    videoId: currentVideoId,
    onUpdate: useCallback((data: VideoResponse) => { setCurrentVideo(data); }, []),
  });

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

  const streamReady = useStreamReady(currentVideo, hevcOk);

  useEffect(() => {
    if (!detectionVideoId) { setDetectionVideo(null); return; }
    let cancelled = false;
    setDetectionVideo(null);
    api.getVideo(detectionVideoId)
      .then((data) => { if (!cancelled) setDetectionVideo(data); })
      .catch(() => { if (!cancelled) setDetectionVideo(null); });
    return () => { cancelled = true; };
  }, [detectionVideoId]);

  const actualDetectionId = detectionVideoId ?? currentVideoId;
  const actualDetectionFace = detectionVideo?.face_enabled ?? currentVideo?.face_enabled ?? false;
  const actualDetectionPlate = detectionVideo?.plate_enabled ?? currentVideo?.plate_enabled ?? false;
  const { detectionData, faceData, plateData } = useDetectionData(
    actualDetectionId,
    showDetection,
    actualDetectionFace,
    actualDetectionPlate,
  );

  useEffect(() => {
    if (!currentVideoId) { setPipelineStages([]); return; }
    let cancelled = false;
    api.getPipelineOperations(currentVideoId)
      .then((stages) => { if (!cancelled) setPipelineStages(stages); })
      .catch(() => { if (!cancelled) setPipelineStages([]); });
    return () => { cancelled = true; };
  }, [currentVideoId, currentVideo?.updated_at]);

  /* ── 选中人脸身份 → 归属 person track 集合 ── */
  const selectedFaceTrackIds = useMemo(() => {
    if (expandedFaceId == null || !faceData?.track_to_identity) return [];
    const ids: number[] = [];
    for (const [tid, { identity_id }] of Object.entries(faceData.track_to_identity)) {
      if (identity_id === expandedFaceId) ids.push(Number(tid));
    }
    return ids;
  }, [expandedFaceId, faceData]);

  const handleTrackSelect = useCallback((trackId: number, _className: string, seekTo?: number) => {
    if (trackId < 0) { setSelectedTrackId(null); return; }
    setSelectedTrackId(trackId);
    if (seekTo !== undefined && videoRef.current) videoRef.current.currentTime = seekTo;
  }, []);

  /* ── Seek（跨视频可靠定位） ── */
  useEffect(() => {
    if (!seekTarget) return;
    const applySeek = () => {
      const video = videoRef.current;
      if (!video || video.readyState < 1) return false;
      video.currentTime = seekTarget.start;
      if (seekTarget.end != null) video.play().catch(() => {});
      return true;
    };
    if (applySeek()) return;
    let attempts = 0;
    const iv = setInterval(() => {
      if (applySeek()) { clearInterval(iv); return; }
      if (++attempts >= 40) clearInterval(iv);
    }, 150);
    return () => clearInterval(iv);
  }, [seekTarget]);

  /* ── 组内视频切换（搜索跨视频结果用） ── */
  const handleGroupVideoSwitch = useCallback((videoId: string) => {
    if (videoId === currentVideoId) return;
    const group = videoGroups.find((g) => g.videoIds.includes(videoId));
    setCurrentGroupVideos(group ? group.videoIds : [videoId]);
    setSelectedTrackId(null);
    setClassFilter(null);
    setSeekTarget(null);
    if (!detectionVideoId || group?.videoIds.includes(detectionVideoId)) setDetectionVideoId(null);
  }, [currentVideoId, videoGroups, detectionVideoId]);

  /* ── 搜索 track 结果点击 ── */
  const handleSearchTrackResult = useCallback((videoId: string, trackId: number, className: string, start: number) => {
    if (videoId && videoId !== currentVideoId) handleGroupVideoSwitch(videoId);
    setDetectionVideoId(null);
    setSelectedTrackId(trackId);
    setSeekTarget({ start, end: null });
  }, [currentVideoId, handleGroupVideoSwitch]);

  /* ── 搜索人脸结果点击 ── */
  const handleFaceResult = useCallback((videoId: string, identityId: number, ts: number) => {
    if (videoId && videoId !== currentVideoId) handleGroupVideoSwitch(videoId);
    setDetectionVideoId(null);
    setFaceViewOpen(true);
    setExpandedFaceId(identityId);
    setSeekTarget({ start: ts, end: null });
  }, [currentVideoId, handleGroupVideoSwitch]);

  const handleSeekTo = useCallback((start: number, end: number | null) => {
    setSeekTarget({ start, end });
    if (videoRef.current) videoRef.current.currentTime = start;
  }, []);

  const handleDelete = useCallback(async () => {
    if (!currentVideoId) return;
    if (!window.confirm("确定删除该视频？将同时释放磁盘空间。")) return;
    setDeleting(true);
    try {
      await deleteVideo(currentVideoId);
      navigate("files");
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
    }
    setDeleting(false);
  }, [currentVideoId, deleteVideo, navigate]);

  /* ── 无视频空状态 ── */
  if (!currentVideoId) {
    return (
      <div className="h-full flex flex-col">
        {/* demo 顶栏 */}
        <div className="h-[52px] px-5 bg-white border-b border-gray-200 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <h1 className="text-[15px] font-semibold text-gray-900 shrink-0">视频解析</h1>
            <span className="w-px h-5 bg-gray-200" />
            <span className="text-[12.5px] text-gray-400">未选择视频</span>
          </div>
        </div>
        {/* 播放器空态（demo 风格） */}
        <div className="flex-1 min-h-0 flex flex-col bg-[#0b0f16]">
          <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-3">
            <div className="w-20 h-20 rounded-full border border-gray-700 flex items-center justify-center">
              <svg className="w-9 h-9 ml-1 text-gray-500" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5.14v13.72L19 12 8 5.14z" />
              </svg>
            </div>
            <div className="text-[15px] font-medium text-gray-300 mt-2">上传或选择视频开始分析</div>
            <div className="text-[12.5px] text-gray-500">前往「文件库」选择视频，点击「查看结果」或「智能解析」</div>
            <button
              className="mt-2 w-[300px] h-[110px] rounded-lg border-2 border-dashed border-gray-700 flex flex-col items-center justify-center gap-1.5
                transition-colors cursor-pointer hover:border-[#4f7cff]/60"
              onClick={() => navigate("files")}
            >
              <svg className="w-7 h-7 text-gray-500" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
              </svg>
              <span className="text-[12.5px] text-gray-400">前往文件库选择视频</span>
            </button>
          </div>
        </div>
      </div>
    );
  }

  const groupName = (() => {
    const g = videoGroups.find((grp) => grp.videoIds.includes(currentVideoId));
    if (g && g.videoIds.length > 1) return `分组 ${g.videoIds.length} 个视频`;
    return null;
  })();

  return (
    <div className="h-full flex flex-col">
      {/* ══ demo 顶栏：视频解析 + 名称/所属 | 重新解析 + 上传 ══ */}
      <div className="h-[52px] px-5 bg-white border-b border-gray-200 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <h1 className="text-[15px] font-semibold text-gray-900 shrink-0">视频解析</h1>
          <span className="w-px h-5 bg-gray-200" />
          {currentVideo ? (
            <>
              <span className="text-[12.5px] text-gray-600 truncate max-w-[220px]">{currentVideo.file_name}</span>
              {groupName && <span className="text-[11.5px] text-gray-400">{groupName}</span>}
              <span className={"g-badge " + (isCompleted ? "ok" : isProcessing ? "run" : currentVideo?.status === "failed" ? "err" : "wait")}>
                {isProcessing && <span className="pulse" />}
                {isCompleted ? "已完成" : isProcessing ? "处理中" : currentVideo?.status === "failed" ? "失败" : "等待参数"}
              </span>
            </>
          ) : (
            <span className="text-[12.5px] text-gray-400">未选择视频</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-gray-400 mr-1 hidden xl:inline">
            {currentVideo?.duration != null ? fmtDuration(currentVideo.duration) : ""}
            {currentVideo ? " · " + (ctLabel[currentVideo.content_type] || currentVideo.content_type) + " · " + (langLabel[currentVideo.language] || currentVideo.language) : ""}
          </span>
          <button className="g-btn" onClick={handleUploadClick} disabled={isUploading}>
            <IconPlus />上传
          </button>
          {currentVideo && (
            <>
              <button className="g-btn g-btn-primary" onClick={() => setParamsOpen(true)}>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12a7.5 7.5 0 1112.9 5.3M4.5 12V7.5M4.5 12h4.5M19.5 12a7.5 7.5 0 01-12.9-5.3M19.5 12v4.5M19.5 12H15" />
                </svg>
                {isProcessing ? "重新解析" : "开始解析"}
              </button>
              <div style={{ position: "relative" }}>
                <button className="g-btn" onClick={() => setShowExport((v) => !v)} title="导出"><IconDownload /></button>
                {showExport && <div className="export-overlay" onClick={() => setShowExport(false)} />}
                {showExport && <div className="absolute right-0 top-full mt-1 z-50"><ExportMenu videoId={currentVideoId} onClose={() => setShowExport(false)} /></div>}
              </div>
              <button className="g-btn g-btn-danger" onClick={handleDelete} disabled={deleting}>删除</button>
            </>
          )}
        </div>
      </div>

      {/* ══ 主体：左右可拖拽分栏（demo 骨架） ══ */}
      <div className="flex-1 min-h-0" style={{ padding: 10 }}>
        <SplitPane direction="row" initial={60} min={32} max={72}>
          {/* ── 左主舞台 ── */}
          <div className="w-full h-full min-w-0 flex flex-col bg-[#0b0f16] rounded-lg overflow-hidden">
            <SplitPane direction="col" initial={70} min={45} max={85}>
              {/* 上部：播放器（+分析进度浮层） */}
              <div className="relative w-full h-full bg-black overflow-hidden">
                <VideoPlayer
                  videoId={currentVideoId}
                  video={currentVideo}
                  streamReady={streamReady}
                  hevcOk={hevcOk}
                  isUploading={isUploading}
                  detectionEnabled={currentVideo?.detection_enabled ?? false}
                  hasDetection={showDetection && !!detectionData?.has_detection}
                  selectedTrackId={selectedTrackId}
                  selectedFaceTrackIds={selectedFaceTrackIds}
                  proxyStatus={proxyStatus}
                  videoRef={videoRef}
                  onTrackSelect={handleTrackSelect}
                />
                {/* 分析进度浮层（demo analyse-overlay） */}
                {isProcessing && (
                  <div className="analyse-overlay">
                    <div className="flex items-center gap-3">
                      <div className="g-progress flex-1 !bg-white/10" style={{ height: 6 }}>
                        <div style={{ width: `${currentVideo?.progress ?? 0}%`, background: "#4f7cff" }} />
                      </div>
                      <span className="text-white text-[12px] font-semibold shrink-0">{Math.round(currentVideo?.progress ?? 0)}%</span>
                      <span className="text-white/70 text-[11.5px] shrink-0">管道处理中…</span>
                    </div>
                  </div>
                )}
                {/* 视频信息浮层（demo stage-info-badge） */}
                <button className="stage-info-badge" title="视频信息" onClick={() => setShowInfo((v) => !v)}>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path strokeLinecap="round" d="M12 16v-4m0-4h.01" />
                  </svg>
                </button>
                {showInfo && currentVideo && (
                  <div className="absolute top-12 right-3 z-20 w-[280px] rounded-lg bg-gray-900/95 backdrop-blur border border-white/10 p-3.5 text-white text-[12px] space-y-1.5 shadow-xl">
                    {[["文件名称", currentVideo.file_name], ["时长", currentVideo.duration != null ? fmtDuration(currentVideo.duration) : "-"],
                      ["场景类型", ctLabel[currentVideo.content_type] || currentVideo.content_type],
                      ["状态", isCompleted ? "已完成" : isProcessing ? "处理中 " + Math.round(currentVideo.progress ?? 0) + "%" : currentVideo.status === "failed" ? "失败" : "等待参数"],
                    ].map(([k, v]) => (
                      <div className="flex justify-between gap-3" key={k}>
                        <span className="text-white/50 shrink-0">{k}</span>
                        <span className="truncate text-right">{v}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* 下部：时间轴 + 管道条 */}
              <div className="w-full h-full bg-[#0b0f16] border-t border-white/10 p-3 flex flex-col gap-2 min-h-0">
                <DetectionTimeline
                  videoId={currentVideoId}
                  videoRef={videoRef}
                  selectedTrackId={selectedTrackId}
                  selectedFaceTrackIds={selectedFaceTrackIds}
                  classFilter={classFilter}
                  onTrackSelect={handleTrackSelect}
                  data={detectionData}
                  faceData={faceData}
                  streamReady={streamReady}
                />
                <PipelineBar
                  progress={currentVideo?.progress ?? 0}
                  statusDetail={currentVideo?.status_detail}
                  stages={pipelineStages}
                  subtitle={currentVideo?.status === "pending" ? "等待参数配置..." : null}
                />
              </div>
            </SplitPane>
          </div>

          {/* ── 右侧栏 ── */}
          <div className="min-w-0 flex flex-col bg-gray-50/70 min-h-0">
            <SplitPane direction="col" initial={20} min={10} max={45}>
              {/* 上卡：视频摘要 ⇄ 视频信息 */}
              <div className="w-full h-full flex flex-col bg-white min-h-0 rounded-lg border border-gray-200 overflow-hidden">
                <div className="g-card-title">
                  <div className="flex items-center gap-1">
                    <button className={"g-tab" + (!showInfo ? " active" : "")} style={{ fontSize: 13 }} onClick={() => setShowInfo(false)}>
                      视频摘要 <span className="text-gray-400 text-[11px] font-normal">Summary</span>
                    </button>
                    <button className={"g-tab" + (showInfo ? " active" : "")} style={{ fontSize: 13 }} onClick={() => setShowInfo(true)}>
                      视频信息 <span className="text-gray-400 text-[11px] font-normal">Info</span>
                    </button>
                  </div>
                </div>
                <div className="flex-1 min-h-0 overflow-auto p-2">
                  {showInfo ? <VideoInfoCard videoId={currentVideoId} video={currentVideo} /> : <VideoSummaryCard video={currentVideo} />}
                </div>
              </div>

              {/* 下卡：物体检测 | 视频搜索（内部左右可拖拽） */}
              <div className="w-full h-full min-h-0 p-2">
                <SplitPane direction="row" initial={42} min={25} max={68} className="rounded-lg overflow-hidden">
                  <div className="w-full h-full flex flex-col bg-white rounded-lg border border-gray-200 overflow-hidden">
                    <div className="g-card-title">物体检测 <span className="text-gray-400 text-[11px] font-normal">Object Detection</span></div>
                    <div className="flex-1 min-h-0 overflow-auto">
                      <DetectionPanel
                        video={currentVideo}
                        data={detectionData}
                        selectedTrackId={selectedTrackId}
                        classFilter={classFilter}
                        onClassFilterChange={setClassFilter}
                        onTrackSelect={handleTrackSelect}
                        faceViewOpen={faceViewOpen}
                        expandedFaceId={expandedFaceId}
                        onFaceViewChange={setFaceViewOpen}
                        onExpandedFaceChange={setExpandedFaceId}
                        onSeekTo={handleSeekTo}
                        faceData={faceData}
                        plateData={plateData}
                        groupVideos={currentGroupVideos}
                        videos={videos}
                        detectionVideoId={detectionVideoId}
                        onDetectionVideoChange={setDetectionVideoId}
                      />
                    </div>
                  </div>

                  <div className="w-full h-full flex flex-col bg-white rounded-lg border border-gray-200 overflow-hidden">
                    <div className="g-card-title">视频搜索 <span className="text-gray-400 text-[11px] font-normal">Video Search</span></div>
                    <div className="flex-1 min-h-0 overflow-hidden">
                      <VideoSearchCard
                        video={currentVideo}
                        videoId={currentVideoId}
                        onSeekTo={handleSeekTo}
                        onTrackResult={handleSearchTrackResult}
                        onFaceResult={handleFaceResult}
                        groupVideos={currentGroupVideos}
                        allVideos={videos}
                        onGroupVideoSwitch={handleGroupVideoSwitch}
                      />
                    </div>
                  </div>
                </SplitPane>
              </div>
            </SplitPane>
          </div>
        </SplitPane>
      </div>

      {/* ── 参数面板 Modal ── */}
      {paramsOpen && (
        <div className="g-modal-overlay">
          <div className="g-modal" style={{ height: "min(680px, 86vh)" }}>
            <ParameterPanel
              videoId={currentVideoId}
              onClose={() => setParamsOpen(false)}
              onParamsSet={() => setParamsOpen(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
