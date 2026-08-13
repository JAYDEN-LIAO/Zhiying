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

export type Page = "files" | "workbench" | "tasks" | "settings";
export type SettingsTab = "system" | "model";

interface AppCtx {
  page: Page;
  navigate: (p: Page) => void;
  /* 系统设置 4 子页（系统/模型参数/参数预设/API 密钥）—— 拆入左侧导航 */
  settingsTab: SettingsTab;
  navigateSettings: (tab: SettingsTab) => void;
  /* 跨页选视频：跳工作台并（可选）自动打开参数面板 */
  selectedVideoId: string | null;
  initialVersionId: string | null;
  openWorkbench: (videoId: string, opts?: { openParams?: boolean; versionId?: string }) => void;
  paramsTick: number;
  consumeParamsTick: () => void; // 参数面板自动打开意图一次性消费（预览/切页不再重复弹）
  /* 共享视频列表（4s 轮询 + 组重建） */
  videos: VideoListItem[];
  videoGroups: VideoGroup[];
  caseGroups: VideoGroup[];
  refreshCaseGroups: () => void;
  activeTaskCount: number;
  refreshList: () => void;
  /* 上传：统一入口，上传后跳工作台 + 打开参数 */
  isUploading: boolean;
  uploadFiles: (files: FileList | File[], groupId?: string, opts?: { stay?: boolean }) => Promise<void>;
  registerExternalFiles: (items: YunzhiResource[]) => Promise<void>;
  handleUploadClick: (groupId?: string, opts?: { stay?: boolean }) => void;
  /* 删除协调 */
  removeVideoState: (id: string) => void;
  deleteVideo: (id: string) => Promise<void>;
  /* 拖拽上传遮罩 */
  dragActive: boolean;
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
  const [videos, setVideos] = useState<VideoListItem[]>([]);
  const [videoGroups, setVideoGroups] = useState<VideoGroup[]>([]);
  const [caseGroups, setCaseGroups] = useState<VideoGroup[]>([]);
  const [activeTaskCount, setActiveTaskCount] = useState(0); // 任务中心 active 数（含多版本处理中，侧栏徽章用）
  const [listKey, setListKey] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const dragDepthRef = useRef(0);

  const { mock: yunzhiMock, selectFiles: yunzhiSelectFiles } = useYunzhi();

  const navigate = useCallback((p: Page) => setPage(p), []);

  const navigateSettings = useCallback((tab: SettingsTab) => {
    setSettingsTab(tab);
    setPage("settings");
  }, []);

  const openWorkbench = useCallback((videoId: string, opts?: { openParams?: boolean; versionId?: string }) => {
    setSelectedVideoId(videoId);
    setInitialVersionId(opts?.versionId ?? null); // 精确定位版本行（任务中心跳转）
    setPage("workbench");
    if (opts?.openParams) setParamsTick((t) => t + 1);
  }, []);

  /* 参数面板自动打开意图一次性消费：弹过一次后归零，避免预览/切页回来重复弹 */
  const consumeParamsTick = useCallback(() => setParamsTick(0), []);

  /* ── 视频列表 + 组重建（原 Dashboard 逻辑） ── */
  useEffect(() => {
    api.listVideos().then((data) => setVideos(data ?? [])).catch(() => {});
  }, [listKey]);

  useEffect(() => {
    const iv = setInterval(() => {
      api.listVideos().then((data) => { if (data) setVideos(data); }).catch(() => {});
      // 任务徽章：按任务中心 active 列表（含多版本文件的处理中版本），而非根行状态
      api.listTasks("active").then((data) => setActiveTaskCount(data?.length ?? 0)).catch(() => {});
    }, 4000);
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
    if (files.length === 0) return;
    setIsUploading(true);
    try {
      let newId: string;
      if (files.length === 1) {
        const r = await api.upload(files[0], undefined, groupId);
        newId = r.id;
      } else {
        const results = await api.uploadBatch(files, undefined, groupId);
        newId = results[0].id;
      }
      refreshList();
      // 文件库归档场景 stay=true → 不跳转工作台（视频留待「智能解析」再配置）
      if (!opts?.stay) openWorkbench(newId, { openParams: true });
    } catch (err) {
      alert(err instanceof Error ? err.message : "上传失败");
    }
    setIsUploading(false);
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

  /* ── 窗口级拖拽上传（原 Dashboard 逻辑） ── */
  useEffect(() => {
    const hasFiles = (e: DragEvent) => !!e.dataTransfer?.types?.includes("Files");
    const onDragEnter = (e: DragEvent) => { if (!hasFiles(e)) return; dragDepthRef.current += 1; setDragActive(true); };
    const onDragOver = (e: DragEvent) => { if (!hasFiles(e)) return; e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = "copy"; };
    const onDragLeave = (e: DragEvent) => { if (!hasFiles(e)) return; dragDepthRef.current = Math.max(0, dragDepthRef.current - 1); if (dragDepthRef.current === 0) setDragActive(false); };
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      dragDepthRef.current = 0;
      setDragActive(false);
      const files = e.dataTransfer?.files;
      if (!files || files.length === 0) return;
      const vids = Array.from(files).filter((f) => /\.(mp4|mov|avi|mkv|webm)$/i.test(f.name) || f.type.startsWith("video/"));
      if (vids.length > 0) void uploadFiles(vids);
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
  }, [uploadFiles]);

  const value: AppCtx = {
    page, navigate, settingsTab, navigateSettings,
    selectedVideoId, openWorkbench, initialVersionId, paramsTick, consumeParamsTick,
    videos, videoGroups, caseGroups, refreshCaseGroups: loadCaseGroups, activeTaskCount, refreshList,
    isUploading, uploadFiles, registerExternalFiles, handleUploadClick,
    removeVideoState, deleteVideo,
    dragActive,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
