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
        search_types: options?.search_types ?? ["frame", "chunk", "text"],
        top_k: options?.top_k ?? 20,
        min_similarity: options?.min_similarity ?? 0.3,
      }),
    });
  },

  /* ── Get video stream URL ── */
  getVideoStreamUrl(videoId: string): string {
    return `${BASE}/videos/${videoId}/stream`;
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
};

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
