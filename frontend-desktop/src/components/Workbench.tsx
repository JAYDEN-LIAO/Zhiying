/* ════════════════════════════════════════════════════════════
   Workbench — 视频解析（工作台）页（v0.34 桌面重构）
   布局照智影 v2 demo 嵌套 SplitPane：
     外层 row 60%  左=主舞台(播放器/时间轴)  右=侧栏(摘要/检索)
     左舞台 col 70%  上=播放器  下=时间轴+管道条
     右栏 col 20%    上=摘要/信息卡  下=检索区
     检索区 row 42%  左=物体检测  右=视频搜索
   状态 = 原 Dashboard 工作台全部逻辑（播放/轮询/检测/人脸/搜索/定位），
   页面/抽屉/导航已上移到 AppContext。
   ════════════════════════════════════════════════════════════ */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../services/api";
import type { VideoResponse, PipelineStage } from "../types";
import { fmtDuration } from "../utils/helpers";
import { IconDownload, IconPlus, IconPlay2 } from "./icons";
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
    if (currentVideoId) {
      setCurrentGroupVideos([currentVideoId]);
    } else {
      setCurrentGroupVideos([]);
    }
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
    onUpdate: useCallback((data: VideoResponse) => {
      setCurrentVideo(data);
    }, []),
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
        <div className="wb-toolbar">
          <span style={{ color: "#64748b", fontSize: 13 }}>未选择视频</span>
          <div style={{ marginLeft: "auto" }}>
            <button className="g-btn g-btn-primary" onClick={() => navigate("files")}><IconPlay2 />前往文件库</button>
          </div>
        </div>
        <div className="g-empty" style={{ flex: 1 }}>
          <IconPlay2 />
          <div className="g-empty-title">当前无分析视频</div>
          <div className="g-empty-desc">前往「文件库」选择视频，点击「查看结果」或「智能解析」开始分析</div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* ── 顶栏工具栏 ── */}
      <div className="wb-toolbar">
        {currentVideo && (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{currentVideo.file_name}</span>
              {currentVideo.duration != null && <span style={{ fontSize: 11, color: "#94a3b8" }}>{fmtDuration(currentVideo.duration)}</span>}
              <span className={"g-badge " + (isCompleted ? "ok" : isProcessing ? "run" : currentVideo.status === "failed" ? "err" : "wait")}>
                {isProcessing && <span className="pulse" />}
                {isCompleted ? "已完成" : isProcessing ? "处理中" : currentVideo.status === "failed" ? "失败" : "等待参数"}
              </span>
              <span style={{ fontSize: 11, color: "#64748b" }}>{ctLabel[currentVideo.content_type] || currentVideo.content_type} · {langLabel[currentVideo.language] || currentVideo.language}</span>
            </div>
          </>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <button className="g-btn" onClick={handleUploadClick} disabled={isUploading}><IconPlus />上传</button>
          {currentVideo && (
            <>
              <button className="g-btn g-btn-primary" onClick={() => setParamsOpen(true)}>{isProcessing ? "参数" : "开始解析"}</button>
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

      {/* ── 嵌套 SplitPane 工作台 ── */}
      <div className="flex-1 min-h-0" style={{ padding: 10 }}>
        <SplitPane direction="row" initial={62} min={34} max={72}>
          {/* 左舞台：播放器 / 时间轴 */}
          <SplitPane direction="col" initial={70} min={48} max={85}>
            <div className="video-player-wrap">
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
            </div>
            <div className="pipeline-wrap" style={{ height: "100%", display: "flex", flexDirection: "column", gap: 6, paddingTop: 8 }}>
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

          {/* 右侧栏：摘要 / 检索区 */}
          <SplitPane direction="col" initial={22} min={12} max={45}>
            <div style={{ padding: "0 8px 4px 8px", height: "100%", display: "flex", flexDirection: "column", gap: 8, overflow: "hidden" }}>
              <VideoSummaryCard video={currentVideo} />
              <VideoInfoCard videoId={currentVideoId} video={currentVideo} />
            </div>
            <SplitPane direction="row" initial={42} min={25} max={68}>
              <div style={{ padding: "4px 8px 0 0", height: "100%", minWidth: 0 }}>
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
              <div style={{ padding: "4px 0 0 8px", height: "100%", minWidth: 0 }}>
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
            </SplitPane>
          </SplitPane>
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
              onUploadDone={(newId: string) => {
                setParamsOpen(false);
                // 上传携带参数完成 → 刷新列表（视频已创建，selectedVideoId 不变）
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
