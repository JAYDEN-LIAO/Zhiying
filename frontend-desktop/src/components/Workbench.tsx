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
import type { VideoResponse, PipelineStage, Track, VersionInfo } from "../types";
import { fmtDuration, fmtDate, versionName } from "../utils/helpers";
import { zhLabel } from "../labels";
import { IconDownload, IconBolt, IconBoltSolid } from "./icons";
import { AddSubjectDrawer, type AddSubjectDrawerData } from "./AddSubjectDrawer";
import { ExportMenu } from "./ExportMenu";
import { VideoPlayer } from "./VideoPlayer";
import { DetectionTimeline } from "./DetectionTimeline";
import { PipelineBar } from "./PipelineBar";
import { VideoSummaryCard } from "./VideoSummaryCard";
import { VideoInfoCard } from "./VideoInfoCard";
import { DetectionPanel } from "./DetectionPanel";
import { VideoSearchCard } from "./VideoSearchCard";
import { SplitPane } from "./SplitPane";
import { SingleAnalyzeDialog, type UnifiedParams } from "./FileLibrary";
import { useApp } from "../AppContext";
import { useHEVCCapability } from "../hooks/useHEVCCapability";
import { useVideoPolling } from "../hooks/useVideoPolling";
import { useProxyStatus } from "../hooks/useProxyStatus";
import { useDetectionData } from "../hooks/useDetectionData";
import { useStreamReady } from "../hooks/useStreamReady";

const ctLabel: Record<string, string> = { general: "通用", meeting: "会议", surveillance: "监控", text_recognition: "文字识别", custom: "自定义" };
const langLabel: Record<string, string> = { auto: "自动", zh: "中文", en: "English", ja: "日本語", ko: "한국어" };

/* ── v0.6 沉淀底图：截取 <video> 当前帧为 JPEG Blob（同源 stream 可 canvas 绘制） ── */
async function captureVideoFrame(video: HTMLVideoElement | null): Promise<Blob | null> {
  if (!video || !video.videoWidth || !video.videoHeight) return null;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0);
    return await new Promise<Blob | null>((resolve) => canvas.toBlob((b) => resolve(b ?? null), "image/jpeg", 0.9));
  } catch {
    return null;
  }
}

/* ═══════════════ ① 顶部卡 ═══════════════ */
function WbHeader({
  videoName, groupName, curVersionName, hasVideo, isPending, isProcessing, isCompleted, onReanalyze, onOpenHistory, onOpenExport,
}: {
  videoName: string; groupName: string | null; curVersionName: string; hasVideo: boolean; isPending: boolean; isProcessing: boolean; isCompleted: boolean;
  onReanalyze: () => void; onOpenHistory: () => void; onOpenExport: () => void;
}) {
  return (
    <div className="case-card flex items-center justify-between flex-wrap gap-y-1.5 px-5 py-2 min-h-[56px] shrink-0">
      <div className="flex items-center gap-3 min-w-0">
        <div className="shrink-0">
          <h1 className="text-[16px] font-semibold text-gray-900 leading-tight">视频解析</h1>
          <p className="text-[11.5px] text-gray-500 leading-tight">AI 视频语义分析与检索</p>
        </div>
        <span className="w-px h-6 bg-gray-200 mx-1" />
        {hasVideo ? (
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[13px] text-gray-700 truncate max-w-[240px]">{videoName}</span>
            {groupName && <span className="text-[11.5px] text-gray-500 shrink-0">所属案例：{groupName}</span>}
          </div>
        ) : (
          <span className="text-[12.5px] text-gray-500">未选择视频</span>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-[11.5px] text-[#4f7cff] font-medium bg-[#eaf1ff] rounded px-2 py-1 truncate max-w-[200px]" title={curVersionName}>{curVersionName || "未选择版本"}</span>
        <button className="g-btn" onClick={onOpenHistory} disabled={!hasVideo} title="解析版本历史">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
          历史记录
        </button>
        <button className="g-btn" onClick={onOpenExport} disabled={!hasVideo}><IconDownload />导出</button>
        <button className="g-btn g-btn-primary" onClick={onReanalyze} disabled={!hasVideo || isProcessing} title={isPending ? "配置参数并启动解析" : "重新配置参数解析"}>
          {isCompleted ? <IconBoltSolid /> : <IconBolt />}
          {isPending ? "解析" : "重新解析"}
        </button>
      </div>
    </div>
  );
}

/* ═══════════════ ② 左舞台卡（播放器 + 时间轴） ═══════════════ */
function WbStage({ player, timeline }: { player: React.ReactNode; timeline: React.ReactNode }) {
  return (
    <div className="case-card h-full flex flex-col p-2 min-h-0 overflow-hidden">
      <SplitPane direction="col" initial={70} min={45} max={85} className="h-full w-full">
        {player}
        {timeline}
      </SplitPane>
    </div>
  );
}

/* ═══════════════ ③ 右摘要卡（摘要 ⇄ 文字识别，外框标题切换） ═══════════════ */
function WbSummary({ currentVideo, onSeekTo }: { currentVideo: VideoResponse | null; onSeekTo: (start: number, end: number | null) => void }) {
  const [tab, setTab] = useState<"summary" | "ocr">("summary");
  // 切换视频 → 根据开启状态自动选中（OCR 开启且摘要未开 → 文字识别；否则 → 摘要）
  useEffect(() => {
    if (!currentVideo) return;
    setTab(currentVideo.ocr_enabled && !currentVideo.summary_enabled ? "ocr" : "summary");
  }, [currentVideo?.id, currentVideo?.ocr_enabled, currentVideo?.summary_enabled]);

  const ocrEnabled = !!currentVideo?.ocr_enabled;
  const title = tab === "ocr" ? "文字识别" : "视频摘要";

  return (
    <div className="case-card h-full flex flex-col min-h-0 overflow-hidden">
      <div className="g-card-title">
        <div className="flex items-center gap-1.5">
          <svg className="w-4 h-4 text-[#4f7cff]" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6M9 8h6M5 19V5a2 2 0 012-2h10a2 2 0 012 2v14l-3-2-2 2-2-2-2 2-2-2-3 2z" /></svg>
          <span className="text-[13px] font-semibold text-gray-800">{title}</span>
        </div>
        <div className="flex items-center gap-1">
          {ocrEnabled && (
            <button
              className={"text-[11px] px-2 py-0.5 rounded-full transition-colors " + (tab === "ocr" ? "bg-[#4f7cff] text-white" : "bg-gray-100 text-gray-500 hover:bg-gray-200")}
              onClick={() => setTab("ocr")}
            >文字识别</button>
          )}
          <button
            className={"text-[11px] px-2 py-0.5 rounded-full transition-colors " + (tab === "summary" ? "bg-[#4f7cff] text-white" : "bg-gray-100 text-gray-500 hover:bg-gray-200")}
            onClick={() => setTab("summary")}
          >摘要</button>
          {currentVideo?.summary?.tags != null && currentVideo.summary.tags.length > 0 && tab === "summary" && (
            <div className="sum-tags !mt-0 ml-1 overflow-hidden">
              {currentVideo.summary.tags.slice(0, 4).map((tag) => (
                <span key={tag} className="sum-tag">{tag}</span>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-2">
        <VideoSummaryCard video={currentVideo} onSeekTo={(ts) => onSeekTo(ts, null)} tab={tab} />
      </div>
    </div>
  );
}

/* ═══════════════ ④ 右分析卡（物体检测 | 视频搜索） ═══════════════ */
function WbAnalysis({ detection, search }: { detection: React.ReactNode; search: React.ReactNode }) {
  return (
    <div className="case-card h-full flex flex-col p-2 min-h-0 overflow-hidden">
      <SplitPane direction="row" initial={42} min={32} max={68} className="h-full w-full">
        <div className="w-full h-full flex flex-col bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="flex-1 min-h-0 min-w-0 overflow-hidden flex flex-col">{detection}</div>
        </div>
        <div className="w-full h-full flex flex-col bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="flex-1 min-h-0 min-w-0 overflow-hidden flex flex-col">{search}</div>
        </div>
      </SplitPane>
    </div>
  );
}

export function Workbench() {
  const { selectedVideoId, initialVersionId, paramsTick, consumeParamsTick, reparseIntent, consumeReparseIntent, openSeekTarget, consumeOpenSeek, pendingTrackSelect, consumePendingTrackSelect, pendingSearchQuery, consumePendingSearchQuery, pendingFaceFile, pendingImageFile, consumePendingSearchFiles, videos, videoGroups, caseGroups, navigate, openWorkbench, handleUploadClick, isUploading } = useApp();
  const currentVideoId = selectedVideoId;

  /* ── 版本切换（v0.34）：打开文件 → 拉取版本链 → 默认当前版本 ── */
  const [versions, setVersions] = useState<VersionInfo[]>([]);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const vid = activeVersionId ?? currentVideoId; // 有效分析版本行 id
  const activeVersion = versions.find((v) => v.id === vid);
  const curVersionName = activeVersion ? versionName(activeVersion) : "";

  useEffect(() => {
    setVersions([]);
    setActiveVersionId(null);
    if (!currentVideoId) return;
    let cancelled = false;
    api.listVersions(currentVideoId)
      .then((vs) => {
        if (cancelled || !vs?.length) return;
        setVersions(vs);
        // 跳转定位版本：任务中心跳转带 initialVersionId → 精确定位该版本行
        const targeted = initialVersionId ? vs.find((v) => v.id === initialVersionId) : undefined;
        if (targeted) {
          setActiveVersionId(targeted.id);
          return;
        }
        // 默认当前版本 = 最新 completed，否则最新 version_no
        const cur = [...vs].sort((a, b) => (b.version_no ?? 0) - (a.version_no ?? 0))
          .find((v) => v.status === "completed");
        const pick = cur ?? [...vs].sort((a, b) => (b.version_no ?? 0) - (a.version_no ?? 0))[0];
        if (pick) setActiveVersionId(pick.id);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [currentVideoId, initialVersionId]);

  /* ── 视频详情与状态 ── */
  const [currentVideo, setCurrentVideo] = useState<VideoResponse | null>(null);
  const [pipelineStages, setPipelineStages] = useState<PipelineStage[]>([]);
  const [seekTarget, setSeekTarget] = useState<{ start: number; end: number | null } | null>(null);
  // 跨视频 pending seek：等主视频切到目标版本且元素就绪后再定位（避免首击 seek 到旧元素被重置）
  const [pendingSeek, setPendingSeek] = useState<{ videoId: string; start: number; end: number | null } | null>(null);
  const [topPanel, setTopPanel] = useState<"history" | "export" | null>(null);
  const [paramsOpen, setParamsOpen] = useState(false);
  const [reparseMode, setReparseMode] = useState(false); // 重新解析：参数窗提交时建新版本
  const [deleting, setDeleting] = useState(false);
  const [showStageInfo, setShowStageInfo] = useState(false); // 播放器信息浮层
  const [addSubjectDrawer, setAddSubjectDrawer] = useState<AddSubjectDrawerData | null>(null); // v0.6 沉淀素材库
  const videoRef = useRef<HTMLVideoElement>(null);
  // 搜索结果发起的跨视频切换 → 重置 effect 跳过（保留结果/定位，由 handler 精确控制状态）
  const suppressWorkbenchResetRef = useRef(false);
  // 跨视频切换刚发生时标记目标视频，供 seek 类 handler 决定走 pendingSeek 而非立即 seek
  const justSwitchedToRef = useRef<string | null>(null);

  /* ── 组感知状态（v0.19） ── */
  const [currentGroupVideos, setCurrentGroupVideos] = useState<string[]>([]);
  const [detectionVideoId, setDetectionVideoId] = useState<string | null>(null);
  const [detectionVideo, setDetectionVideo] = useState<VideoResponse | null>(null);

  /* ── track/face 选择状态 ── */
  const [selectedTrackId, setSelectedTrackId] = useState<number | null>(null);
  const [classFilter, setClassFilter] = useState<string | null>(null);
  const [faceViewOpen, setFaceViewOpen] = useState(false);
  const [expandedFaceId, setExpandedFaceId] = useState<number | null>(null);

  /* ── 视频切换时重置工作台状态（搜索结果跨视频切换在 suppress 窗口内跳过，保留结果/定位） ── */
  useEffect(() => {
    if (suppressWorkbenchResetRef.current) {
      setCurrentVideo(null);  // 清旧数据防闪烁；其余状态由搜索结果 handler 保留
      return;
    }
    setCurrentVideo(null);
    setSelectedTrackId(null);
    setClassFilter(null);
    setFaceViewOpen(false);
    setExpandedFaceId(null);
    setSeekTarget(null);
    setTopPanel(null);
    setParamsOpen(false);
    setShowStageInfo(false);
    if (currentVideoId) setCurrentGroupVideos([currentVideoId]);
    else setCurrentGroupVideos([]);
    setDetectionVideoId(null);
    setReparseMode(false);
  }, [vid]);

  /* ── 自动打开参数面板（上传/智能解析后）——一次性消费：弹过即归零，
     预览（openParams=false）或切页回来不再重复弹 ── */
  useEffect(() => {
    if (paramsTick > 0 && currentVideoId) {
      setParamsOpen(true);
      // 已完成文件从案例库点「重新配置参数解析」→ 参数面板直接进重新解析模式（提交建新版本）
      if (reparseIntent) setReparseMode(true);
      consumeParamsTick();
      consumeReparseIntent();
    }
  }, [paramsTick, currentVideoId, consumeParamsTick, consumeReparseIntent, reparseIntent]);

  /* ── 跨页 seek（全局搜索→工作台）：等视频就绪后定位到目标时间，一次性消费 ── */
  useEffect(() => {
    if (!openSeekTarget || !vid) return;
    let cancelled = false;
    let attempts = 0;
    const apply = () => {
      const video = videoRef.current;
      if (!video || video.readyState < 1) return false;
      video.currentTime = openSeekTarget.start;
      if (openSeekTarget.end != null) video.play().catch(() => {});
      return true;
    };
    if (apply()) { consumeOpenSeek(); return; }
    const iv = setInterval(() => {
      if (cancelled) { clearInterval(iv); return; }
      if (apply()) { clearInterval(iv); consumeOpenSeek(); return; }
      if (++attempts >= 40) { clearInterval(iv); consumeOpenSeek(); }
    }, 150);
    return () => { cancelled = true; clearInterval(iv); };
  }, [openSeekTarget, vid, consumeOpenSeek]);

  /* ── 跨页 track 选中（全局搜索 track 结果→工作台）：等 vid 切到目标后再 setSelectedTrackId，
     让检测栏 bbox 高亮 + 时间轴高亮，与 Workbench VideoSearchCard.onTrackResult 一致 ── */
  useEffect(() => {
    if (!pendingTrackSelect) return;
    if (!vid || vid !== pendingTrackSelect.videoId) return;  // 跨视频：等 vid 落到目标再触发
    setSelectedTrackId(pendingTrackSelect.trackId);
    consumePendingTrackSelect();
  }, [pendingTrackSelect, vid, consumePendingTrackSelect]);

  /* ── 跨页搜索关键词同步：全局搜索→视频搜索卡片（一次性消费，不依赖 track 选中） ── */
  useEffect(() => {
    if ((!pendingSearchQuery && !pendingFaceFile && !pendingImageFile) || !vid) return;
    consumePendingSearchQuery();
    consumePendingSearchFiles();
  }, [pendingSearchQuery, pendingFaceFile, pendingImageFile, vid, consumePendingSearchQuery, consumePendingSearchFiles]);

  /* ── 派生布尔 ── */
  const isPending = currentVideo?.status === "pending";
  const isProcessing = currentVideo?.status === "processing";
  const isCompleted = currentVideo?.status === "completed";
  const showDetection = !!(currentVideo?.detection_enabled && isCompleted);

  /* ── Hooks ── */
  const hevcOk = useHEVCCapability();

  useVideoPolling({
    videoId: vid,
    onUpdate: useCallback((data: VideoResponse) => {
      setCurrentVideo(data);
      // 版本历史状态同步：处理中 → 终态时刷新版本链（否则历史面板徽章卡在"处理中"）
      if (data.status === "completed" || data.status === "failed") {
        api.listVersions(currentVideoId ?? data.id)
          .then((vs) => { if (vs?.length) setVersions(vs); })
          .catch(() => {});
      }
    }, [currentVideoId]),
  });

  const needsProxy = useMemo(() => {
    if (!currentVideo) return false;
    const vc = currentVideo.video_codec;
    return !!vc && vc !== "h264" && !hevcOk;
  }, [currentVideo?.video_codec, hevcOk]);

  const proxyStatus = useProxyStatus(
    vid,
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

  const actualDetectionId = detectionVideoId ?? vid;
  const actualDetectionFace = detectionVideo?.face_enabled ?? currentVideo?.face_enabled ?? false;
  const actualDetectionPlate = detectionVideo?.plate_enabled ?? currentVideo?.plate_enabled ?? false;
  const { detectionData, faceData, plateData } = useDetectionData(
    actualDetectionId,
    showDetection,
    actualDetectionFace,
    actualDetectionPlate,
  );

  useEffect(() => {
    if (!vid) { setPipelineStages([]); return; }
    let cancelled = false;
    api.getPipelineOperations(vid)
      .then((stages) => { if (!cancelled) setPipelineStages(stages); })
      .catch(() => { if (!cancelled) setPipelineStages([]); });
    return () => { cancelled = true; };
  }, [vid, currentVideo?.updated_at]);

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

  /* ── v0.6 沉淀：选中 track → 图片素材库（优先 track 缩略图，其次截当前帧为底图） ── */
  const handleAddTrackToLibrary = useCallback(async (track: Track, thumbnailUrl?: string | null) => {
    const kind: "person" | "other" = track.class_name === "person" ? "person" : "other";
    let blob: Blob | null = null;
    if (thumbnailUrl) {
      try {
        const res = await fetch(thumbnailUrl);
        if (res.ok) blob = await res.blob();
      } catch { /* 缩略图加载失败 → 回退截当前帧 */ }
    }
    if (!blob) blob = await captureVideoFrame(videoRef.current);
    setAddSubjectDrawer({
      kind,
      presetName: zhLabel(track.class_name, track.display_seq ?? track.track_id),
      image: blob ? { blob } : null,
      source: "track",
      sourceVideoId: vid,
      videoName: currentVideo?.file_name ?? null,
    });
  }, [vid, currentVideo?.file_name]);

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

  /* ── 跨视频 pending seek：等主视频切到目标版本（vid/currentVideo 落到目标）且元素就绪后再定位，
     避免首击 seek 作用到旧 <video> 元素、随后 src 切换被重置 ── */
  useEffect(() => {
    if (!pendingSeek) return;
    const targetReady = vid === pendingSeek.videoId || currentVideo?.id === pendingSeek.videoId;
    if (!targetReady) return;  // 等 vid/currentVideo 变化重新触发
    const applySeek = () => {
      const video = videoRef.current;
      if (!video || video.readyState < 1) return false;
      video.currentTime = pendingSeek.start;
      if (pendingSeek.end != null) video.play().catch(() => {});
      return true;
    };
    if (applySeek()) { setPendingSeek(null); return; }
    let attempts = 0;
    const iv = setInterval(() => {
      if (applySeek()) { clearInterval(iv); setPendingSeek(null); return; }
      if (++attempts >= 40) clearInterval(iv);
    }, 150);
    return () => clearInterval(iv);
  }, [pendingSeek, vid, currentVideo]);

  /* 搜索结果跨视频切换 → 短暂抑制重置：覆盖「切主视频 → activeVersionId 置空 → 解析新版本」的
     vid 级联，等数据落定后恢复，保住 seek/选中态（搜索结果自己的 suppress 保留结果列表） */
  const suppressWorkbenchReset = useCallback(() => {
    suppressWorkbenchResetRef.current = true;
    window.setTimeout(() => { suppressWorkbenchResetRef.current = false; }, 800);
  }, []);

  /* ── 跨视频切换（搜索跨视频结果用）：切主视频（播放器/时间轴/检测/摘要同步）+ 组状态 ── */
  const handleGroupVideoSwitch = useCallback((videoId: string) => {
    if (videoId === currentVideoId) return;
    const group = videoGroups.find((g) => g.videoIds.includes(videoId));
    setCurrentGroupVideos(group ? group.videoIds : [videoId]);
    justSwitchedToRef.current = videoId;      // 标记：本次 seek 目标是该视频（走 pendingSeek）
    suppressWorkbenchReset();
    openWorkbench(videoId, { versionId: videoId });  // 精确定位点击的版本行，vid 落定后即目标
    setDetectionVideoId(null);
  }, [currentVideoId, videoGroups, openWorkbench, suppressWorkbenchReset]);

  /* ── 搜索 track 结果点击 ── */
  const handleSearchTrackResult = useCallback((videoId: string, trackId: number, className: string, start: number) => {
    if (videoId && videoId !== currentVideoId) handleGroupVideoSwitch(videoId);
    const target = justSwitchedToRef.current;
    if (target) {
      justSwitchedToRef.current = null;
      setPendingSeek({ videoId: target, start, end: null });  // 跨视频：等新视频就绪再定位
    } else {
      setSeekTarget({ start, end: null });
    }
    setDetectionVideoId(null);
    setSelectedTrackId(trackId);
  }, [currentVideoId, handleGroupVideoSwitch]);

  /* ── 搜索人脸结果点击 ── */
  const handleFaceResult = useCallback((videoId: string, identityId: number, ts: number) => {
    if (videoId && videoId !== currentVideoId) handleGroupVideoSwitch(videoId);
    const target = justSwitchedToRef.current;
    if (target) {
      justSwitchedToRef.current = null;
      setPendingSeek({ videoId: target, start: ts, end: null });
    } else {
      setSeekTarget({ start: ts, end: null });
    }
    setDetectionVideoId(null);
    setFaceViewOpen(true);
    setExpandedFaceId(identityId);
  }, [currentVideoId, handleGroupVideoSwitch]);

  const handleSeekTo = useCallback((start: number, end: number | null) => {
    const target = justSwitchedToRef.current;
    if (target) {
      justSwitchedToRef.current = null;
      setPendingSeek({ videoId: target, start, end });  // 跨视频：等新视频就绪再定位
    } else {
      setSeekTarget({ start, end });
      if (videoRef.current) videoRef.current.currentTime = start;
    }
  }, []);

  const handleDelete = useCallback(async () => {
    if (!vid) return;
    if (!window.confirm("确定删除该视频（含全部解析版本）？将同时释放磁盘空间。")) return;
    setDeleting(true);
    try {
      // 删除整个文件链（根行 currentVideoId → 全部版本），而非仅当前版本行
      await api.deleteFile(currentVideoId ?? vid);
      navigate("files");
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
    }
    setDeleting(false);
  }, [vid, currentVideoId, navigate]);

  const groupName = currentVideo?.group_id
    ? (caseGroups.find((g) => g.groupId === currentVideo.group_id)?.name ?? null)
    : null;

  /* 无视频空态：舞台区 CTA 占位（合并渲染树后搜索卡恒为同一实例，结果跨切换保留） */
  const emptyStage = (
    <div className="w-full h-full flex items-center justify-center bg-[#0b0f16] rounded-lg">
      <button
        className="w-[300px] h-[110px] rounded-lg border-2 border-dashed border-gray-700 flex flex-col items-center justify-center gap-1.5 transition-colors cursor-pointer hover:border-[#4f7cff]/60"
        onClick={() => navigate("files")}
      >
        <svg className="w-7 h-7 text-gray-500" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" /></svg>
        <span className="text-[12.5px] text-gray-400">前往案例库选择视频</span>
      </button>
    </div>
  );

  return (
    <div className="h-full flex flex-col gap-2 p-2 relative">
      {/* ① 顶部卡：标题/介绍/视频名/状态 + 历史记录/重新解析/导出 */}
      <WbHeader
        videoName={currentVideo?.file_name ?? ""}
        groupName={groupName}
        curVersionName={curVersionName}
        hasVideo={!!currentVideo}
        isPending={isPending}
        isProcessing={isProcessing}
        isCompleted={isCompleted}
        // 解析：pending 视频 = 原地配置参数并启动（reparse=false）；已完成/失败 = 重新解析建新版本
        onReanalyze={() => { setReparseMode(!isPending); setParamsOpen(true); }}
        onOpenHistory={() => setTopPanel((p) => (p === "history" ? null : "history"))}
        onOpenExport={() => setTopPanel((p) => (p === "export" ? null : "export"))}
      />

      {/* 顶部下沿滑出面板（历史记录 / 导出） */}
      {topPanel && (
        <>
          <div className="absolute inset-0 z-40" onClick={() => setTopPanel(null)} />
          <div className="absolute right-2 top-[68px] z-50 case-card overflow-hidden" style={{ width: 300 }}>
            {topPanel === "history" ? (
              <div className="flex flex-col" style={{ maxHeight: "48vh" }}>
                <div className="g-card-title"><span className="g-card-tt text-[13px]">历史记录（切换版本）</span></div>
                <div className="p-2 space-y-1.5 overflow-auto">
                  {[...versions].sort((a, b) => (b.version_no ?? 0) - (a.version_no ?? 0)).map((v) => (
                    <div key={v.id}
                      className={"border rounded-lg px-2.5 py-2 cursor-pointer transition-colors " +
                        (vid === v.id ? "border-[#4f7cff] bg-[#4f7cff]/5" : "border-gray-200 hover:border-gray-300")}
                      onClick={() => { setActiveVersionId(v.id); setTopPanel(null); }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className={"text-[12.5px] font-medium truncate " + (vid === v.id ? "text-[#4f7cff]" : "text-gray-700")}>{versionName(v)}</span>
                        <span className={"g-badge " + (v.status === "completed" ? "ok" : v.status === "processing" ? "run" : v.status === "failed" ? "err" : "wait")}>
                          {v.status === "completed" ? "已完成" : v.status === "processing" ? "处理中" : v.status === "failed" ? "失败" : v.status}
                        </span>
                      </div>
                      <div className="text-[10.5px] text-gray-500 mt-0.5 font-mono">{fmtDate(v.created_at)}</div>
                    </div>
                  ))}
                  {versions.length === 0 && <div className="text-gray-400 text-[12px] py-2">暂无历史版本</div>}
                </div>
              </div>
            ) : (
              <ExportMenu videoId={vid!} onClose={() => setTopPanel(null)} />
            )}
          </div>
        </>
      )}

      {/* ② 主体：左舞台卡 6:4 | 右侧 摘要卡 + 分析卡（全部拖拽保留） */}
      <div className="flex-1 min-h-0">
        <SplitPane direction="row" initial={60} min={32} max={72} className="h-full w-full">
          {/* 左舞台卡：播放器 + 时间轴 */}
          <WbStage
            player={currentVideoId ? (
              <div className="relative w-full h-full bg-black overflow-hidden rounded-lg">
                <VideoPlayer
                  videoId={vid!}
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
                {/* 分析进度浮层（完整 PipelineBar：阶段点 + 状态 + 百分比） */}
                {isProcessing && (
                  <div className="analyse-overlay">
                    <PipelineBar
                      dark
                      progress={currentVideo?.progress ?? 0}
                      statusDetail={currentVideo?.status_detail}
                      stages={pipelineStages}
                      subtitle={`管道处理中… ${Math.round((currentVideo?.progress ?? 0) * 100)}%`}
                    />
                  </div>
                )}
                {/* 视频信息浮层 */}
                <button className="stage-info-badge" title="视频信息" onClick={() => setShowStageInfo((v) => !v)}>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                    <circle cx="12" cy="12" r="10" /><path strokeLinecap="round" d="M12 16v-4m0-4h.01" />
                  </svg>
                </button>
                {showStageInfo && currentVideo && (
                  <div className="stage-info-card absolute top-12 right-3 z-20 w-[320px] rounded-lg overflow-hidden">
                    <div className="p-2 max-h-[55vh] overflow-auto">
                      <VideoInfoCard videoId={vid!} video={currentVideo} />
                    </div>
                  </div>
                )}
              </div>
            ) : emptyStage}
            timeline={currentVideoId ? (
              <div className="w-full h-full bg-[#0b0f16] p-3 flex flex-col gap-2 min-h-0 rounded-lg overflow-hidden">
                <div className="flex items-center justify-between mb-1 shrink-0">
                  <span className="text-[12px] font-semibold text-white/80">时间轴</span>
                  <span className="text-[11px] text-white/40 font-mono">
                    {currentVideo?.duration != null ? fmtDuration(currentVideo.duration) : ""}
                  </span>
                </div>
                <DetectionTimeline
                  videoId={vid!}
                  videoRef={videoRef}
                  selectedTrackId={selectedTrackId}
                  selectedFaceTrackIds={selectedFaceTrackIds}
                  classFilter={classFilter}
                  onTrackSelect={handleTrackSelect}
                  data={detectionData}
                  faceData={faceData}
                  streamReady={streamReady}
                />
              </div>
            ) : <div className="w-full h-full bg-[#0b0f16] rounded-lg" />}
          />

          {/* 右侧：摘要卡 + 分析卡（col 拖拽） */}
          <div className="h-full min-w-0">
            <SplitPane direction="col" initial={22} min={12} max={45} className="h-full w-full">
              <WbSummary currentVideo={currentVideo} onSeekTo={handleSeekTo} />
              <WbAnalysis
                detection={
                  /* 恒渲染 DetectionPanel：其内部已按 无视频/未开启/处理中/无数据 分态渲染「物体检测」标题（与摘要/搜索卡一致） */
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
                    onAddToLibrary={handleAddTrackToLibrary}
                  />
                }
                search={
                  /* 恒为同一实例：空态↔有视频 切换不重建，搜索结果/范围跨切换保留 */
                  <VideoSearchCard
                    video={currentVideo}
                    videoId={vid}
                    onSeekTo={handleSeekTo}
                    onTrackResult={handleSearchTrackResult}
                    onFaceResult={handleFaceResult}
                    allVideos={videos}
                    caseGroups={caseGroups}
                    onGroupVideoSwitch={handleGroupVideoSwitch}
                    initialQuery={pendingSearchQuery}
                    initialFaceFile={pendingFaceFile}
                    initialImageFile={pendingImageFile}
                  />
                }
              />
            </SplitPane>
          </div>
        </SplitPane>
      </div>

      {/* ── 参数面板 Modal（新紧凑面板 v0.37） ── */}
      {paramsOpen && currentVideo && (
        <SingleAnalyzeDialog
          title={reparseMode ? "重新解析" : (currentVideo.status === "completed" ? "重新分析" : "视频解析")}
          reparse={reparseMode}
          initial={{
            content_type: currentVideo.content_type,
            detection_enabled: currentVideo.detection_enabled,
            face_enabled: currentVideo.face_enabled,
            plate_enabled: currentVideo.plate_enabled,
            ocr_enabled: currentVideo.ocr_enabled,
            search_index_enabled: currentVideo.search_index_enabled,
            summary_enabled: currentVideo.summary_enabled,
          }}
          onClose={() => { setParamsOpen(false); setReparseMode(false); }}
          onSubmit={async (params, reparse) => {
            try {
              if (reparse) {
                await api.reanalyze(vid!, params);
                const vs = await api.listVersions(currentVideoId ?? vid!);
                if (vs?.length) setVersions(vs);
              } else {
                await api.updateParams(vid!, params);
              }
              setParamsOpen(false);
              setReparseMode(false);
            } catch (err) {
              alert(err instanceof Error ? err.message : "解析失败");
            }
          }}
        />
      )}

      {/* ── v0.6 沉淀：选中 track → 加入图片素材库 Drawer ── */}
      <AddSubjectDrawer data={addSubjectDrawer} onClose={() => setAddSubjectDrawer(null)} />
    </div>
  );
}
