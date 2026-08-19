/* ════════════════════════════════════════════════════════════
   API service layer — real backend calls
   ════════════════════════════════════════════════════════════ */

import type {
  APIResponse,
  VideoListItem,
  VideoResponse,
  VideoStatusResponse,
  PipelineStage,
  SearchResults,
  PipelineParams,
  SettingsData,
  SettingsUpdate,
  PipelinePreset,
  PipelineConfigInfo,
  DetectionData,
  DetectionRange,
  FaceData,
  PlateData,
  OcrData,
  FaceSearchResult,
  VideoMetadata,
  ProxyStatus,
  ExportClipRequest,
  ExportFramesRequest,
  ExportTrackRequest,
  ExportThumbnailsRequest,
  VideoGroup,
  FileItem,
  VersionInfo,
  TaskItem,
  CaseAssetItem,
} from "./types";

const BASE = "/api/v1";

/* ── Unwrap the {code, message, data} envelope ── */

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  const json: APIResponse<T> = await res.json();
  if (json.code !== 0) {
    throw new Error(json.message || `API error (code ${json.code})`);
  }
  return json.data as T;
}

/* ════════════════════════════════════════════════════════════
   API
   ════════════════════════════════════════════════════════════ */

export const api = {
  /* ── Health（根路径挂载，非 {code,message,data} 信封；返回 version 供 header 展示） ── */
  async getHealth(): Promise<{ status: string; service: string; version: string; database: string }> {
    const res = await fetch("/health");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  },

  /* ── List all videos ── */
  listVideos() {
    return request<VideoListItem[]>(`${BASE}/videos/`);
  },

  /* ── Get video detail ── */
  getVideo(videoId: string) {
    return request<VideoResponse>(`${BASE}/videos/${videoId}`);
  },

  /* ── Get lightweight status ── */
  getVideoStatus(videoId: string) {
    return request<VideoStatusResponse>(`${BASE}/videos/${videoId}/status`);
  },

  getPipelineOperations(videoId: string) {
    return request<PipelineStage[]>(BASE + "/pipeline/operations?video_id=" + encodeURIComponent(videoId));
  },

  /* ── Batch upload multiple videos (v0.19) ── */
  async uploadBatch(files: File[], params?: Partial<PipelineParams>, groupId?: string): Promise<VideoResponse[]> {
    const form = new FormData();
    for (const file of files) {
      form.append("files", file);
    }
    form.append("content_type", params?.content_type ?? "general");
    form.append("language", params?.language ?? "auto");
    form.append("audio_enabled", String(params?.audio_enabled ?? false));
    form.append("vision_enabled", String(params?.vision_enabled ?? true));
    form.append("ocr_enabled", String(params?.ocr_enabled ?? false));
    // 画面描述已并入智能摘要（v0.33 合并）：caption 默认跟随 summary
    form.append("caption_enabled", String(params?.caption_enabled ?? params?.summary_enabled ?? true));
    form.append("summary_enabled", String(params?.summary_enabled ?? true));
    form.append("summary_mode", params?.summary_mode ?? "vlm_llm");
    form.append("detection_enabled", String(params?.detection_enabled ?? false));
    if (params?.detection_classes?.length) {
      form.append("detection_classes", JSON.stringify(params.detection_classes));
    }
    form.append("face_enabled", String(params?.face_enabled ?? false));
    form.append("plate_enabled", String(params?.plate_enabled ?? false));
    form.append("search_index_enabled", String(params?.search_index_enabled ?? true));
    form.append("sample_fps", String(params?.sample_fps ?? 1.0));
    form.append("segment_threshold", String(params?.segment_threshold ?? 0.5));
    form.append("caption_with_context", String(params?.caption_with_context ?? true));
    form.append("summary_detail", params?.summary_detail ?? "standard");
    if (groupId) form.append("group_id", groupId);

    return request<VideoResponse[]>(`${BASE}/videos/upload/batch`, {
      method: "POST",
      body: form,
    });
  },

  /* ── 批量解析：精确启动指定待处理视频管道（不走组同步，v0.35 案例库批量解析） ── */
  analyzeBatch(videoIds: string[], params?: Partial<PipelineParams>): Promise<{ started: number; skipped: number }> {
    return request(`${BASE}/videos/analyze-batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_ids: videoIds, ...(params ? { params } : {}) }),
    });
  },

  /* ── Upload a video (does NOT start pipeline) ── */
  upload(file: File, params?: Partial<PipelineParams>, groupId?: string) {
    const form = new FormData();
    form.append("file", file);
    if (groupId) form.append("group_id", groupId);
    form.append("content_type", params?.content_type ?? "general");
    form.append("language", params?.language ?? "auto");
    form.append("audio_enabled", String(params?.audio_enabled ?? false));
    form.append("vision_enabled", String(params?.vision_enabled ?? true));
    form.append("ocr_enabled", String(params?.ocr_enabled ?? false));
    // 画面描述已并入智能摘要（v0.33 合并）：caption 默认跟随 summary
    form.append("caption_enabled", String(params?.caption_enabled ?? params?.summary_enabled ?? true));
    form.append("summary_enabled", String(params?.summary_enabled ?? true));
    form.append("summary_mode", params?.summary_mode ?? "vlm_llm");
    form.append("detection_enabled", String(params?.detection_enabled ?? false));
    if (params?.detection_classes?.length) {
      form.append("detection_classes", JSON.stringify(params.detection_classes));
    }
    form.append("face_enabled", String(params?.face_enabled ?? false));
    form.append("plate_enabled", String(params?.plate_enabled ?? false));
    form.append("search_index_enabled", String(params?.search_index_enabled ?? true));
    form.append("sample_fps", String(params?.sample_fps ?? 1.0));
    form.append("segment_threshold", String(params?.segment_threshold ?? 0.5));
    form.append("caption_with_context", String(params?.caption_with_context ?? true));
    form.append("summary_detail", params?.summary_detail ?? "standard");

    return request<VideoResponse>(`${BASE}/videos/upload`, {
      method: "POST",
      body: form,
    });
  },

  /* ── 注册平台共享路径视频（云智 Bridge 选文件 → 就地引用，不上传字节） ── */
  registerFromPath(filePath: string, fileName?: string, externalFileId?: number, params?: Partial<PipelineParams>) {
    return request<VideoResponse>(`${BASE}/videos/register-external`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file_path: filePath,
        file_name: fileName,
        external_file_id: externalFileId,
        ...params,
      }),
    });
  },

  /* ── 按云智平台文件库资源 ID 查找视频（Bridge context.resource.id → 自动跳转目标） ── */
  getVideoByExternalId(fileId: number) {
    return request<VideoResponse>(`${BASE}/videos/external/${fileId}`);
  },

  /* ── Set params & start pipeline ── */
  updateParams(videoId: string, params: PipelineParams) {
    return request<VideoResponse>(`${BASE}/videos/${videoId}/params`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
  },

  /* ── Reuse a video (create new processing from existing file) ── */
  reuseVideo(sourceVideoId: string, params: Partial<PipelineParams>) {
    return request<VideoResponse>(`${BASE}/videos/reuse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_video_id: sourceVideoId, ...params }),
    });
  },

  /* ── Delete a video ── */
  deleteVideo(videoId: string) {
    return request<{ freed_bytes: number }>(`${BASE}/videos/${videoId}`, { method: "DELETE" });
  },

  /* ── Semantic search ── */
  searchSemantic(
    query: string,
    options?: {
      search_types?: string[];
      top_k?: number;
      min_similarity?: number;
      video_ids?: string[];
    },
  ) {
    return request<SearchResults>(`${BASE}/search/semantic`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        video_ids: options?.video_ids,
        search_types: options?.search_types ?? ["frame", "chunk", "text", "track", "label", "plate", "ocr"],
        top_k: options?.top_k ?? 20,
        min_similarity: options?.min_similarity ?? 0.3,
      }),
    });
  },

  /* ── Get video stream URL (v0.13: hevc_ok for browser capability) ── */
  getVideoStreamUrl(videoId: string, hevcOk: boolean = false): string {
    return `${BASE}/videos/${videoId}/stream?hevc_ok=${hevcOk}`;
  },

  /* ── Proxy transcode status ── */
  getProxyStatus(videoId: string) {
    return request<ProxyStatus>(`${BASE}/videos/${videoId}/proxy-status`);
  },

  /* ── Detection tracks (轻量摘要，v0.22) ── */
  fetchDetectionTracks(videoId: string) {
    return request<DetectionData>(`${BASE}/videos/${videoId}/detection/tracks`);
  },

  /* ── Detection time window (Overlay 按需加载，v0.22) ── */
  fetchDetectionRange(videoId: string, startSec: number, endSec: number) {
    return request<DetectionRange>(
      `${BASE}/videos/${videoId}/detection/detections?start_sec=${startSec}&end_sec=${endSec}`,
    );
  },

  /* ── Face search ── */
  async searchFace(file: File, videoIds?: string[], topK?: number): Promise<FaceSearchResult[]> {
    const form = new FormData();
    form.append("file", file);
    if (videoIds) form.append("video_ids", videoIds.join(","));
    if (topK != null) form.append("top_k", String(topK));
    const res = await fetch(`${BASE}/search/face`, { method: "POST", body: form });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    const json = await res.json();
    if (json.code !== 0) throw new Error(json.message || "API error");
    return json.data ?? [];
  },

  /* ── Image search (通用图搜) ── */
  async searchImage(file: File, options?: {
    video_ids?: string[];
    search_types?: string[];
    top_k?: number;
    min_similarity?: number;
  }): Promise<SearchResults> {
    const form = new FormData();
    form.append("file", file);
    if (options?.video_ids) form.append("video_ids", options.video_ids.join(","));
    if (options?.search_types?.length) form.append("search_types", options.search_types.join(","));
    if (options?.top_k != null) form.append("top_k", String(options.top_k));
    if (options?.min_similarity != null) form.append("min_similarity", String(options.min_similarity));
    return request<SearchResults>(`${BASE}/search/image`, { method: "POST", body: form });
  },

  /* ── Face data ── */
  fetchFaceData(videoId: string) {
    return request<FaceData>(`${BASE}/videos/${videoId}/face/data`);
  },

  /* ── Plate data ── */
  fetchPlateData(videoId: string) {
    return request<PlateData>(`${BASE}/videos/${videoId}/plate/data`);
  },

  /* ── OCR 画面文字数据 (v0.34) ── */
  fetchOcrData(videoId: string) {
    return request<OcrData>(`${BASE}/videos/${videoId}/ocr/data`);
  },

  /* ── Settings ── */
  getSettings() {
    return request<SettingsData>(`${BASE}/settings`);
  },

  updateSettings(payload: SettingsUpdate) {
    return request<SettingsData>(`${BASE}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  },

  /* 当前生效管道配置（含 embedding_profile 档位，v0.34候选 档位感知） */
  getPipelineConfig() {
    return request<PipelineConfigInfo>(`${BASE}/settings/pipeline`);
  },

  /* ── 参数预设（v0.22） ── */
  getPresets() {
    return request<PipelinePreset[]>(`${BASE}/settings/presets`);
  },

  createPreset(name: string) {
    return request<PipelinePreset>(`${BASE}/settings/presets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  },

  renamePreset(id: string, name: string) {
    return request<PipelinePreset>(`${BASE}/settings/presets/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  },

  deletePreset(id: string) {
    return request<{ deleted: string }>(`${BASE}/settings/presets/${id}`, { method: "DELETE" });
  },

  applyPreset(id: string) {
    return request<PipelinePreset>(`${BASE}/settings/presets/${id}/apply`, { method: "POST" });
  },

  /* ── Video metadata ── */
  fetchVideoMetadata(videoId: string) {
    return request<VideoMetadata>(`${BASE}/videos/${videoId}/metadata`);
  },

  /* ── Export: video clip ── */
  async exportClip(videoId: string, params: ExportClipRequest): Promise<Blob> {
    return downloadBlob(`${BASE}/videos/${videoId}/export/clip`, params);
  },

  /* ── Export: frames ── */
  async exportFrames(videoId: string, params: ExportFramesRequest): Promise<Blob> {
    return downloadBlob(`${BASE}/videos/${videoId}/export/frames`, params);
  },

  /* ── Export: track clip ── */
  async exportTrack(videoId: string, trackId: number, params: ExportTrackRequest): Promise<Blob> {
    return downloadBlob(`${BASE}/videos/${videoId}/export/track/${trackId}`, params);
  },

  /* ── Export: thumbnails ── */
  async exportThumbnails(videoId: string, params: ExportThumbnailsRequest): Promise<Blob> {
    return downloadBlob(`${BASE}/videos/${videoId}/export/thumbnails`, params);
  },

  /* ── Export: track thumbnail (GET, returns JPEG blob) ── */
  async exportTrackThumbnail(videoId: string, trackId: number): Promise<Blob> {
    const res = await fetch(`${BASE}/videos/${videoId}/export/track/${trackId}/thumbnail`);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    return res.blob();
  },

  /* ── Export URL helpers (GET endpoints for browser direct navigation) ── */
  getClipExportUrl(videoId: string, startSec: number, endSec: number): string {
    return `${BASE}/videos/${videoId}/export/clip?start_sec=${startSec}&end_sec=${endSec}`;
  },
  getTrackExportUrl(videoId: string, trackId: number, drawBbox = true, displayId?: number): string {
    const url = `${BASE}/videos/${videoId}/export/track/${trackId}?draw_bbox=${drawBbox}`;
    return displayId ? `${url}&display_id=${displayId}` : url;
  },
  getTrackThumbnailUrl(videoId: string, trackId: number, displayId?: number): string {
    const url = `${BASE}/videos/${videoId}/export/track/${trackId}/thumbnail`;
    return displayId ? `${url}?display_id=${displayId}` : url;
  },
  getThumbnailsExportUrl(videoId: string): string {
    return `${BASE}/videos/${videoId}/export/thumbnails`;
  },

  /* ═══ v0.34 文件库 / 多版本 / 任务中心 ═══ */
  listGroups() {
    return request<VideoGroup[]>(`${BASE}/groups`).then((items) =>
      (items ?? []).map((g) => ({
        groupId: g.id ?? g.groupId,
        id: g.id ?? g.groupId,
        name: g.name,
        number: g.number,
        owner: g.owner,
        file_count: g.file_count,
        created_at: g.created_at,
        videoIds: g.videoIds ?? [],
      })),
    );
  },
  createGroup(body: { name: string; number?: string; owner?: string }) {
    return request<VideoGroup>(`${BASE}/groups`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  },
  updateGroup(groupId: string, body: { name: string; number?: string; owner?: string }) {
    return request<VideoGroup>(`${BASE}/groups/${groupId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  },
  deleteGroup(groupId: string) {
    return request<{ ok: boolean }>(`${BASE}/groups/${groupId}`, { method: "DELETE" });
  },
  listFiles() {
    return request<FileItem[]>(`${BASE}/files`);
  },
  deleteFile(fileId: string) {
    return request<{ ok: boolean; freed_bytes?: number }>(`${BASE}/files/${fileId}`, { method: "DELETE" });
  },
  renameFile(fileId: string, name: string) {
    return request<{ ok: boolean; renamed?: number }>(`${BASE}/files/${fileId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  },
  listVersions(videoId: string) {
    return request<VersionInfo[]>(`${BASE}/videos/${videoId}/versions`);
  },
  reanalyze(videoId: string, params: PipelineParams) {
    return request<VideoResponse>(`${BASE}/videos/${videoId}/reanalyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
  },
  listTasks(scope?: "all" | "active" | "history") {
    const q = scope && scope !== "all" ? `?scope=${scope}` : "";
    return request<TaskItem[]>(`${BASE}/tasks${q}`);
  },
  getTaskLog(taskId: string) {
    return request<{ log: { seq: number; level: string; message: string; created_at: string }[] }>(`${BASE}/tasks/${taskId}/log`);
  },
  retryTask(taskId: string) {
    return request<{ ok: boolean }>(`${BASE}/tasks/${taskId}/retry`, { method: "POST" });
  },
  /* ═══ 任务导出报告（v0.34） ═══ */
  async exportTaskReport(taskId: string, fileName: string): Promise<void> {
    const res = await fetch(`${BASE}/tasks/${taskId}/report`);
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail || `HTTP ${res.status}`);
    }
    const blob = await res.blob();
    downloadFile(blob, `report_${sanitizeFile(fileName)}.md`);
  },
  async exportTasksBatch(taskIds: string[], zipName: string): Promise<void> {
    const blob = await downloadBlob(`${BASE}/tasks/export-batch`, { task_ids: taskIds });
    downloadFile(blob, zipName);
  },
  /* ═══ 案例素材（图片等非视频） ═══ */
  getGroupAssets(groupId: string): Promise<{ videos: FileItem[]; images: CaseAssetItem[] }> {
    return request(`${BASE}/groups/${groupId}/assets`);
  },
  uploadGroupAssets(groupId: string, files: File[]): Promise<CaseAssetItem[]> {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    return request<CaseAssetItem[]>(`${BASE}/groups/${groupId}/assets`, { method: "POST", body: form });
  },
  getAssetFileUrl(groupId: string, assetId: string): string {
    return `${BASE}/groups/${groupId}/assets/${assetId}/file`;
  },
  deleteGroupAsset(groupId: string, assetId: string) {
    return request<{ ok: boolean }>(`${BASE}/groups/${groupId}/assets/${assetId}`, { method: "DELETE" });
  },
  renameGroupAsset(groupId: string, assetId: string, name: string) {
    return request<{ ok: boolean }>(`${BASE}/groups/${groupId}/assets/${assetId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  },
};

/* ── Binary download helper (POST → blob) ── */

async function downloadBlob(url: string, body: unknown): Promise<Blob> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.detail || `HTTP ${res.status}`);
  }
  return res.blob();
}

/* ── Trigger browser file download from a Blob ── */

/* 文件名清洗：去路径分隔符/控制字符，保留下划线连字符点 */
function sanitizeFile(name: string): string {
  return name.replace(/[\\/:"*?<>| -]/g, "_").slice(0, 80) || "task";
}

export function downloadFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/* ── Polling helper ── */

export function pollVideoUntilDone(
  videoId: string,
  onUpdate: (video: VideoResponse) => void,
  onError?: (err: Error) => void,
  intervalMs = 3000,
): () => void {
  let cancelled = false;
  let timer: ReturnType<typeof setInterval> | null = null;

  const stop = () => { if (timer) { clearInterval(timer); timer = null; } };

  const fetchVideo = async () => {
    try {
      const data = await api.getVideo(videoId);
      if (!cancelled) {
        onUpdate(data);
        if (data.status !== "processing" && data.status !== "pending") {
          stop();
        }
      }
    } catch (err) {
      if (!cancelled) {
        onError?.(err instanceof Error ? err : new Error(String(err)));
        // 请求失败（视频删除/后端不可达）无法继续探测完成状态 → 停表，
        // 避免 interval 无限空转（原实现只靠成功分支停表）
        stop();
      }
    }
  };

  fetchVideo();
  timer = setInterval(fetchVideo, intervalMs);

  return () => {
    cancelled = true;
    if (timer) clearInterval(timer);
  };
}

/* ═══ 案例素材（图片等非视频） ═══ */
