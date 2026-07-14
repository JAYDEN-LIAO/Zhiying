/* ════════════════════════════════════════════════════════════
   API service layer — real backend calls
   ════════════════════════════════════════════════════════════ */

import type {
  APIResponse,
  VideoListItem,
  VideoResponse,
  VideoStatusResponse,
  SearchResults,
  VideoStatus,
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

  /* ── Upload a video ── */
  upload(
    file: File,
    params?: {
      preset?: string;
      content_type?: string;
      language?: string;
      audio_enabled?: boolean;
      vision_enabled?: boolean;
      caption_enabled?: boolean;
      summary_enabled?: boolean;
    },
  ) {
    const form = new FormData();
    form.append("file", file);
    form.append("preset", params?.preset ?? "standard");
    form.append("content_type", params?.content_type ?? "general");
    form.append("language", params?.language ?? "auto");
    form.append("audio_enabled", String(params?.audio_enabled ?? true));
    form.append("vision_enabled", String(params?.vision_enabled ?? true));
    form.append("caption_enabled", String(params?.caption_enabled ?? true));
    form.append("summary_enabled", String(params?.summary_enabled ?? true));

    return request<VideoResponse>(`${BASE}/videos/upload`, {
      method: "POST",
      body: form,
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
