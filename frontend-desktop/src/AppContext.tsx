/* ════════════════════════════════════════════════════════════
   AppContext — 应用壳共享状态（v0.34 桌面重构）
   4 页导航 + 跨页选视频（文件库/任务中心 → 工作台）+ 共享视频列表 +
   上传/删除/拖拽编排。Workbench 内部工作台状态（播放/搜索/检测/摘要）
   仍由其自身持有，此处只放跨页关注点。
   ════════════════════════════════════════════════════════════ */

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./services/api";
import type { VideoListItem, VideoGroup, VideoResponse } from "./types";
import { useYunzhi } from "./platform/YunzhiProvider";
import type { YunzhiResource } from "./platform/yunzhi-bridge";

export type Page = "files" | "workbench" | "search" | "tasks" | "settings" | "imagelib";
export type SettingsTab = "system" | "model";

/* 图片素材库跨页跳转意图：打开页面并可（可选）定位到指定目标/切到告警历史 Tab */
export interface ImageLibraryIntent {
  subjectId?: string;
  openAlerts?: boolean;   // 打开详情时直接切到「告警历史」Tab（全局搜索/Toast 跳转用）
}

interface AppCtx {
  page: Page;
  navigate: (p: Page) => void;
  /* 系统设置 4 子页（系统/模型参数/参数预设/API 密钥）—— 拆入左侧导航 */
  settingsTab: SettingsTab;
  navigateSettings: (tab: SettingsTab) => void;
  /* 跨页选视频：跳工作台并（可选）自动打开参数面板 */
  selectedVideoId: string | null;
  initialVersionId: string | null;
  openWorkbench: (videoId: string, opts?: { openParams?: boolean; versionId?: string; reparse?: boolean; seekTo?: { start: number; end?: number | null }; selectTrack?: { trackId: number; className: string; start: number }; searchQuery?: string; faceFile?: File; imageFile?: File; frameSelect?: { start: number }; searchMode?: "plate" | "ocr" | "semantic" }) => void;
  paramsTick: number;
  consumeParamsTick: () => void; // 参数面板自动打开意图一次性消费（预览/切页不再重复弹）
  reparseIntent: boolean;        // 自动打开的参数面板是否走「重新解析」模式（已完成文件重配置参数 → reanalyze 建新版本）
  consumeReparseIntent: () => void;
  openSeekTarget: { videoId: string; start: number; end: number | null } | null; // 跨页 seek：全局搜索→工作台（带目标视频 id，等 vid 落到目标才定位，防作用到旧视频元素）
  consumeOpenSeek: () => void;
  /* 跨页 track 选中：全局搜索 track 结果点击 → 工作台选中 track（bbox+时间轴高亮，一次性消费） */
  pendingTrackSelect: { videoId: string; trackId: number; className: string; start: number } | null;
  consumePendingTrackSelect: () => void;
  /* 跨页搜索关键词同步：全局搜索→工作台视频搜索卡片（一次性消费）。
     携带目标视频 id：Workbench 常驻挂载后 vid（版本行）晚一拍才切到目标，
     卡片/消费方都等到对上才动作，防止拿旧视频 id 搜索或被 stale 重置清空 */
  pendingSearchQuery: string | null;
  pendingSearchVideoId: string | null; // 搜索意图目标视频（openWorkbench 的 videoId）
  pendingSearchTick: number;       // 搜索意图递增戳（同视频同关键词重复跳转时保证 effect 重新触发）
  consumePendingSearchQuery: () => void;
  /* 跨页画面结果选中：全局搜索 frame 结果点击 → 工作台视频搜索卡片联动高亮对应画面结果（一次性消费）。
     携带目标帧时间（precise_start ?? scene_range_start），卡片搜完按时间匹配结果后高亮 */
  pendingSearchFrameSelect: { videoId: string; start: number } | null;
  consumePendingSearchFrameSelect: () => void;
  /* 跨页搜索模式：全局搜索目标类型 → 卡片进入对应模式（plate/ocr/semantic），
     否则卡片拿 query 在语义模式搜车牌/文字会空白 */
  pendingSearchMode: "plate" | "ocr" | "semantic" | null;
  consumePendingSearchMode: () => void;
  pendingFaceFile: File | null;
  pendingImageFile: File | null;
  consumePendingSearchFiles: () => void;
  /* 共享视频列表（4s 轮询 + 组重建） */
  videos: VideoListItem[];
  videoGroups: VideoGroup[];
  caseGroups: VideoGroup[];
  refreshCaseGroups: () => void;
  /* 案例库选中案例（跨页持久化） */
  selectedTree: string;   // "all" | "ungrouped" | "g:<groupId>"
  setSelectedTree: (t: string) => void;
  /* 侧栏徽章：案例库灰=仅上传未提交 / 视频解析蓝=处理中 / 任务中心 黄=排队中 绿=新完成 红=失败 */
  pendingFileCount: number;    // 案例库灰：仅上传未提交（pending 且未入队 且 未版本化）
  queuedTaskCount: number;     // 任务中心黄：排队中（pipeline_tasks queued 等 worker）
  newCompletedCount: number;   // 任务中心绿：新完成，进入任务中心页即清零
  failedTaskCount: number;     // 任务中心红：处理失败（实时计数）
  taskHighlightIds: string[];  // 进入任务中心时待高亮的「新完成」行 id（表格淡绿高亮）
  runningTaskCount: number;  // 处理中数：视频解析蓝色「1」徽章 + 退出确认（仅 status=processing）
  refreshList: () => void;
  /* ═══ v0.6 图片素材库：跨页跳转意图 + 高优告警红点（下一阶段接轮询） ═══ */
  imageLibIntent: ImageLibraryIntent | null;
  consumeImageLibIntent: () => void;
  openImageLibrary: (opts?: ImageLibraryIntent) => void;
  imageLibAlertCount: number;   // 新高优告警数（如"在逃命中"）→ 侧栏红点；告警阶段接入
  clearImageLibAlerts: () => void;
  /* 上传：统一入口，上传后跳工作台 + 打开参数 */
  isUploading: boolean;
  uploadFiles: (files: FileList | File[], groupId?: string, opts?: { stay?: boolean }) => Promise<string[]>;
  registerExternalFiles: (items: YunzhiResource[]) => Promise<void>;
  handleUploadClick: (groupId?: string, opts?: { stay?: boolean }) => void;
  /* 删除协调 */
  removeVideoState: (id: string) => void;
  deleteVideo: (id: string) => Promise<void>;
}

const AppContext = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp 必须在 <AppProvider> 内使用");
  return ctx;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<Page>("files");
  const [settingsTab, setSettingsTab] = useState<SettingsTab>("system");
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [initialVersionId, setInitialVersionId] = useState<string | null>(null); // 跳转精确定位版本行（任务中心）
  const [paramsTick, setParamsTick] = useState(0);
  const [reparseIntent, setReparseIntent] = useState(false);
  const [openSeekTarget, setOpenSeekTarget] = useState<{ videoId: string; start: number; end: number | null } | null>(null);
  const [pendingTrackSelect, setPendingTrackSelect] = useState<{ videoId: string; trackId: number; className: string; start: number } | null>(null);
  const [pendingSearchQuery, setPendingSearchQuery] = useState<string | null>(null);
  const [pendingSearchVideoId, setPendingSearchVideoId] = useState<string | null>(null);
  const [pendingSearchTick, setPendingSearchTick] = useState(0);
  const [pendingSearchFrameSelect, setPendingSearchFrameSelect] = useState<{ videoId: string; start: number } | null>(null);
  const [pendingSearchMode, setPendingSearchMode] = useState<"plate" | "ocr" | "semantic" | null>(null);
  const [pendingFaceFile, setPendingFaceFile] = useState<File | null>(null);
  const [pendingImageFile, setPendingImageFile] = useState<File | null>(null);
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [videoGroups, setVideoGroups] = useState<VideoGroup[]>([]);
  const [caseGroups, setCaseGroups] = useState<VideoGroup[]>([]);
  const [selectedTree, setSelectedTree] = useState<string>("all");
  const [pendingFileCount, setPendingFileCount] = useState(0);   // 案例库灰：仅上传未提交
  const [queuedTaskCount, setQueuedTaskCount] = useState(0);     // 任务中心黄：排队中
  const [newCompletedCount, setNewCompletedCount] = useState(0); // 任务中心绿：新完成
  const [failedTaskCount, setFailedTaskCount] = useState(0);     // 任务中心红：失败（实时）
  const [taskHighlightIds, setTaskHighlightIds] = useState<string[]>([]); // 进任务中心时待高亮的行 id
  const [runningTaskCount, setRunningTaskCount] = useState(0); // 处理中数（视频解析蓝「1」+ 退出确认）
  const pageRef = useRef<Page>(page);          // 轮询闭包内读当前页（防 stale）
  const baselineRef = useRef<Set<string>>(new Set());   // 已「看过」的已完成任务 id（绿数基线）
  const initializedRef = useRef(false);        // 首轮轮询基线初始化（防首启误报绿数）
  const freshCompletedRef = useRef<string[]>([]); // 本轮计为新完成的 id（进任务中心时高亮用）
  const selectedVideoIdRef = useRef<string | null>(selectedVideoId);
  const processingVideoIdRef = useRef<string | null>(null); // 最近一个处理中视频 id（点视频解析自动定位）
  pageRef.current = page;
  selectedVideoIdRef.current = selectedVideoId;
  const [listKey, setListKey] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  /* ═══ v0.6 图片素材库：跨页跳转意图（一次性消费）+ 高优告警红点（告警阶段接轮询） ═══ */
  const [imageLibIntent, setImageLibIntent] = useState<ImageLibraryIntent | null>(null);
  const [imageLibAlertCount, setImageLibAlertCount] = useState(0);

  const { mock: yunzhiMock, selectFiles: yunzhiSelectFiles } = useYunzhi();

  const navigate = useCallback((p: Page) => {
    if (p === "tasks") {
      // 进入任务中心：捕获本次待高亮的「新完成」行 + 推进基线（绿数即时清零）
      setTaskHighlightIds(freshCompletedRef.current);
      setNewCompletedCount(0);
      baselineRef.current = new Set([...baselineRef.current, ...freshCompletedRef.current]);
    } else if (pageRef.current === "tasks") {
      setTaskHighlightIds([]); // 离开任务中心清高亮（防快速折返误高亮旧行）
    }
    /* 进入图片素材库：高优告警红点视为已读清零（与 openImageLibrary 一致） */
    if (p === "imagelib") setImageLibAlertCount(0);
    /* 进入视频解析页面时的选中优先级：
       - 已有明确选中视频（搜索结果/任务/文件库跳转或上次选中）→ 保留它，处理中视频不抢占
       - 没有任何选中 → 有处理中则切到处理中视频，否则空态
       例外：openWorkbench(videoId, ...) 走特定 videoId，不经过这里 */
    if (p === "workbench" && !selectedVideoIdRef.current && processingVideoIdRef.current) {
      setSelectedVideoId(processingVideoIdRef.current);
      setInitialVersionId(null);
    }
    setPage(p);
  }, []);

  const navigateSettings = useCallback((tab: SettingsTab) => {
    setSettingsTab(tab);
    setPage("settings");
  }, []);

  const openWorkbench = useCallback((videoId: string, opts?: { openParams?: boolean; versionId?: string; reparse?: boolean; seekTo?: { start: number; end?: number | null }; selectTrack?: { trackId: number; className: string; start: number }; searchQuery?: string; faceFile?: File; imageFile?: File; frameSelect?: { start: number }; searchMode?: "plate" | "ocr" | "semantic" }) => {
    setSelectedVideoId(videoId);
    setInitialVersionId(opts?.versionId ?? null); // 精确定位版本行（任务中心跳转）
    setPage("workbench");
    setReparseIntent(opts?.reparse ?? false);      // 参数面板自动打开时是否走「重新解析」（已完成文件重配参数）
    if (opts?.openParams) setParamsTick((t) => t + 1);
    setOpenSeekTarget(opts?.seekTo ? { videoId, start: opts.seekTo.start, end: opts.seekTo.end ?? null } : null); // 跨页 seek：全局搜索→工作台定位时间（携带目标视频 id）
    /* track 选中意图：全局搜索 track 结果点击 → 工作台高亮 bbox+时间轴。
       若未传 selectTrack，主动清空旧意图（避免上一轮残留导致新打开仍带高亮） */
    setPendingTrackSelect(opts?.selectTrack ? { videoId, ...opts.selectTrack } : null);
    /* 搜索关键词同步：全局搜索→工作台视频搜索卡片自动填充并搜索 */
    setPendingSearchQuery(opts?.searchQuery ?? null);
    setPendingFaceFile(opts?.faceFile ?? null);
    setPendingImageFile(opts?.imageFile ?? null);
    setPendingSearchVideoId(opts?.searchQuery || opts?.faceFile || opts?.imageFile ? videoId : null);
    /* 跨页画面结果选中意图：画面类结果跳转时带目标帧时间；无则清空旧意图（防上一轮残留误高亮） */
    setPendingSearchFrameSelect(opts?.frameSelect ? { videoId, ...opts.frameSelect } : null);
    /* 跨页搜索模式：仅文字搜索带 query 时才有效（plate/ocr/semantic），否则清空 */
    setPendingSearchMode(opts?.searchQuery ? (opts?.searchMode ?? "semantic") : null);
    if (opts?.searchQuery || opts?.faceFile || opts?.imageFile) setPendingSearchTick((t) => t + 1);
  }, []);

  /* 参数面板自动打开意图一次性消费：弹过一次后归零，避免预览/切页回来重复弹 */
  const consumeParamsTick = useCallback(() => setParamsTick(0), []);
  const consumeReparseIntent = useCallback(() => setReparseIntent(false), []);
  const consumeOpenSeek = useCallback(() => setOpenSeekTarget(null), []);
  const consumePendingTrackSelect = useCallback(() => setPendingTrackSelect(null), []);
  const consumePendingSearchQuery = useCallback(() => setPendingSearchQuery(null), []);
  const consumePendingSearchFrameSelect = useCallback(() => setPendingSearchFrameSelect(null), []);
  const consumePendingSearchMode = useCallback(() => setPendingSearchMode(null), []);
  const consumePendingSearchFiles = useCallback(() => { setPendingFaceFile(null); setPendingImageFile(null); }, []);

  /* ═══ v0.6 图片素材库：打开页面并（可选）携带定位意图；意图一次性消费，切页回来不重复弹 ═══ */
  const openImageLibrary = useCallback((opts?: ImageLibraryIntent) => {
    setImageLibIntent(opts && (opts.subjectId || opts.openAlerts) ? opts : null);
    setPage("imagelib");
  }, []);
  const consumeImageLibIntent = useCallback(() => setImageLibIntent(null), []);
  const clearImageLibAlerts = useCallback(() => setImageLibAlertCount(0), []);

  /* ── 视频列表 + 组重建（原 Dashboard 逻辑） ── */
  useEffect(() => {
    api.listVideos().then((data) => setVideos(data ?? [])).catch(() => {});
  }, [listKey]);

  useEffect(() => {
    const iv = setInterval(() => {
      api.listVideos().then((data) => { if (data) setVideos(data); }).catch(() => {});
      // 侧栏徽章：一次拉全量任务，派生 待处理(蓝)/排队中(黄)/新完成(绿)/运行中
      api.listTasks("all").then((data) => {
        const tasks = data ?? [];
        const proc = tasks.filter((t) => t.status === "processing");
        setRunningTaskCount(proc.length);
        processingVideoIdRef.current = proc.length > 0 ? proc[0].id : null; // 视频解析自动定位用
        // 案例库灰 = 仅上传未提交：pending 且未入队 且 未版本化（版本化孤儿行不算）
        setPendingFileCount(tasks.filter((t) => t.status === "pending" && !t.queued && t.version_no == null).length);
        // 任务中心黄 = 排队中；红 = 处理失败（实时计数）
        setQueuedTaskCount(tasks.filter((t) => !!t.queued).length);
        setFailedTaskCount(tasks.filter((t) => t.status === "failed").length);
        const completed = tasks.filter((t) => t.status === "completed");
        if (!initializedRef.current) {
          // 首轮：当前已完成全视为已看过基线，避免首启误报绿数
          baselineRef.current = new Set(completed.map((t) => t.id));
          initializedRef.current = true;
          setNewCompletedCount(0);
        } else if (pageRef.current === "tasks") {
          // 正在任务中心浏览：新完成即时吸收，绿数恒 0
          baselineRef.current = new Set(completed.map((t) => t.id));
          setNewCompletedCount(0);
        } else {
          const fresh = completed.filter((t) => !baselineRef.current.has(t.id));
          freshCompletedRef.current = fresh.map((t) => t.id);
          setNewCompletedCount(fresh.length);
        }
      }).catch(() => {});
    }, 1500);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const groupMap = new Map<string, string[]>();
    for (const v of videos) {
      if (v.group_id) {
        const existing = groupMap.get(v.group_id) ?? [];
        existing.push(v.id);
        groupMap.set(v.group_id, existing);
      }
    }
    setVideoGroups(Array.from(groupMap, ([groupId, ids]) => ({ groupId, videoIds: ids })));
  }, [videos]);

  const refreshList = useCallback(() => setListKey((k) => k + 1), []);

  const loadCaseGroups = useCallback(() => {
    api.listGroups().then((data) => setCaseGroups(data ?? [])).catch(() => {});
  }, []);
  useEffect(() => { loadCaseGroups(); }, [loadCaseGroups]);
  useEffect(() => { if (caseGroups.length === 0) loadCaseGroups(); /* eslint-disable-line */ }, [videos.length]);

  /* ── 删除协调（原 Dashboard handleDelete） ── */
  const removeVideoState = useCallback((id: string) => {
    setVideos((prev) => prev.filter((v) => v.id !== id));
    setSelectedVideoId((cur) => (cur === id ? null : cur));
  }, []);

  const deleteVideo = useCallback(async (id: string) => {
    await api.deleteVideo(id);
    removeVideoState(id);
    refreshList();
  }, [removeVideoState, refreshList]);

  /* ── 上传（原 Dashboard handleFiles + registerExternal） ── */
  const uploadFiles = useCallback(async (fileList: FileList | File[], groupId?: string, opts?: { stay?: boolean }) => {
    const files = Array.from(fileList);
    if (files.length === 0) return [];
    setIsUploading(true);
    try {
      let newIds: string[];
      if (files.length === 1) {
        const r = await api.upload(files[0], undefined, groupId);
        newIds = [r.id];
      } else {
        const results = await api.uploadBatch(files, undefined, groupId);
        newIds = results.map((r) => r.id);
      }
      refreshList();
      // 文件库归档场景 stay=true → 不跳转工作台（视频留待「智能解析」再配置）
      if (!opts?.stay) openWorkbench(newIds[0], { openParams: true });
      return newIds;
    } catch (err) {
      alert(err instanceof Error ? err.message : "上传失败");
      return [];
    } finally {
      setIsUploading(false);
    }
  }, [refreshList, openWorkbench]);

  const registerExternalFiles = useCallback(async (items: YunzhiResource[]) => {
    const files = items.filter((i) => i.resourceType === "FILE" && i.absolutePath);
    if (files.length === 0) { alert("请选择文件（不是文件夹）"); return; }
    setIsUploading(true);
    try {
      if (files.length === 1) {
        const r = await api.registerFromPath(files[0].absolutePath!, files[0].name, files[0].id);
        refreshList();
        openWorkbench(r.id, { openParams: true });
      } else {
        const settled = await Promise.allSettled(files.map((f) => api.registerFromPath(f.absolutePath!, f.name, f.id)));
        const results = settled.filter((r): r is PromiseFulfilledResult<VideoResponse> => r.status === "fulfilled").map((r) => r.value);
        const failed = settled.length - results.length;
        if (results.length === 0) throw new Error("所选文件全部注册失败");
        refreshList();
        openWorkbench(results[0].id, { openParams: true });
        if (failed > 0) alert(`其中 ${failed} 个文件注册失败，其余已成功`);
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : "注册共享文件失败");
    }
    setIsUploading(false);
  }, [refreshList, openWorkbench]);

  const handleUploadClick = useCallback((groupId?: string, opts?: { stay?: boolean }) => {
    if (!yunzhiMock) {
      void yunzhiSelectFiles()
        .then((items) => registerExternalFiles(items))
        .catch((err) => {
          if (!(err instanceof Error && /用户取消/.test(err.message))) {
            alert(err instanceof Error ? err.message : "平台文件选择失败");
          }
        });
      return;
    }
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".mp4,.mov,.avi,.mkv,.webm";
    input.multiple = true;
    input.onchange = () => { uploadFiles(input.files ?? [], groupId, opts); input.value = ""; };
    input.click();
  }, [yunzhiMock, yunzhiSelectFiles, registerExternalFiles, uploadFiles]);

  const value: AppCtx = {
    page, navigate, settingsTab, navigateSettings,
    selectedVideoId, openWorkbench, initialVersionId, paramsTick, consumeParamsTick,
    reparseIntent, consumeReparseIntent, openSeekTarget, consumeOpenSeek,
    pendingTrackSelect, consumePendingTrackSelect,
    pendingSearchQuery, pendingSearchVideoId, pendingSearchTick, consumePendingSearchQuery,
    pendingSearchFrameSelect, consumePendingSearchFrameSelect,
    pendingSearchMode, consumePendingSearchMode,
    pendingFaceFile, pendingImageFile, consumePendingSearchFiles,
    videos, videoGroups, caseGroups, refreshCaseGroups: loadCaseGroups,
    selectedTree, setSelectedTree,
  pendingFileCount, queuedTaskCount, newCompletedCount, failedTaskCount, taskHighlightIds, runningTaskCount, refreshList,
    imageLibIntent, consumeImageLibIntent, openImageLibrary, imageLibAlertCount, clearImageLibAlerts,
    isUploading, uploadFiles, registerExternalFiles, handleUploadClick,
    removeVideoState, deleteVideo,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
