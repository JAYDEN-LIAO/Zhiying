/* ════════════════════════════════════════════════════════════
   API service layer — real backend calls
   ════════════════════════════════════════════════════════════ */

import type {
  APIResponse,
  VideoListItem,
  VideoResponse,
  VideoStatusResponse,
  SearchResults,
  PipelineParams,
  SettingsData,
  DetectionData,
  VideoMetadata,
  ExportClipRequest,
  ExportFramesRequest,
  ExportTrackRequest,
  ExportThumbnailsRequest,
} from "../types";

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

  /* ── Upload a video (does NOT start pipeline) ── */
  upload(file: File, params?: Partial<PipelineParams>) {
    const form = new FormData();
    form.append("file", file);
    form.append("content_type", params?.content_type ?? "general");
    form.append("language", params?.language ?? "auto");
    form.append("audio_enabled", String(params?.audio_enabled ?? false));
    form.append("vision_enabled", String(params?.vision_enabled ?? true));
    form.append("ocr_enabled", String(params?.ocr_enabled ?? false));
    form.append("caption_enabled", String(params?.caption_enabled ?? true));
    form.append("summary_enabled", String(params?.summary_enabled ?? true));
    form.append("summary_mode", params?.summary_mode ?? "native_video");
    form.append("detection_enabled", String(params?.detection_enabled ?? false));
    if (params?.detection_classes?.length) {
      form.append("detection_classes", JSON.stringify(params.detection_classes));
    }
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
    return request<void>(`${BASE}/videos/${videoId}`, { method: "DELETE" });
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
        search_types: options?.search_types ?? ["frame", "chunk", "text", "track", "label"],
        top_k: options?.top_k ?? 20,
        min_similarity: options?.min_similarity ?? 0.3,
      }),
    });
  },

  /* ── Get video stream URL ── */
  getVideoStreamUrl(videoId: string): string {
    return `${BASE}/videos/${videoId}/stream`;
  },

  /* ── Detection data ── */
  fetchDetectionData(videoId: string) {
    return request<DetectionData>(`${BASE}/videos/${videoId}/detection/data`);
  },

  /* ── Settings ── */
  getSettings() {
    return request<SettingsData>(`${BASE}/settings`);
  },

  updateSettings(api_keys: Record<string, string>) {
    return request<SettingsData>(`${BASE}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_keys }),
    });
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
  getTrackExportUrl(videoId: string, trackId: number, drawBbox = true): string {
    return `${BASE}/videos/${videoId}/export/track/${trackId}?draw_bbox=${drawBbox}`;
  },
  getTrackThumbnailUrl(videoId: string, trackId: number): string {
    return `${BASE}/videos/${videoId}/export/track/${trackId}/thumbnail`;
  },
  getThumbnailsExportUrl(videoId: string): string {
    return `${BASE}/videos/${videoId}/export/thumbnails`;
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

  const fetchVideo = async () => {
    try {
      const data = await api.getVideo(videoId);
      if (!cancelled) {
        onUpdate(data);
        if (data.status !== "processing" && data.status !== "pending") {
          if (timer) clearInterval(timer);
        }
      }
    } catch (err) {
      if (!cancelled) onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  };

  fetchVideo();
  timer = setInterval(fetchVideo, intervalMs);

  return () => {
    cancelled = true;
    if (timer) clearInterval(timer);
  };
}
