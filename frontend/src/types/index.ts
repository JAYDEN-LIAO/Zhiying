/* ════════════════════════════════════════════════════════════
   Cerno TypeScript types — mirrors backend core/schemas.py
   ════════════════════════════════════════════════════════════ */

/* ── Enums ── */

export type VideoStatus = "pending" | "processing" | "completed" | "failed";
export type ContentType = "general" | "meeting" | "surveillance" | "text_recognition" | "custom";

/* ── Generic API response envelope ── */

export interface APIResponse<T> {
  code: number;
  message: string;
  data: T | null;
}

/* ── Video list item (GET /api/v1/videos/) ── */

export interface VideoListItem {
  id: string;
  status: VideoStatus;
  progress: number;
  file_name: string;
  duration: number | null;
  content_type: ContentType;
  scene_count: number | null;
  summary_one_liner: string | null;
  audio_enabled: boolean;
  caption_enabled: boolean;
  detection_enabled: boolean;
  summary_enabled: boolean;
  summary_mode: string;
  search_index_enabled: boolean;
  sample_fps: number;
  language: string;
  created_at: string;
  updated_at: string;
}

/* ── Video detail (GET /api/v1/videos/{id}) ── */

export interface SceneSummaryItem {
  scene_index: number;
  start_sec: number;
  end_sec: number;
  description: string;
  keywords: string[];
}

export interface VideoSummary {
  one_liner: string;
  scenes_summary: SceneSummaryItem[];
  tags: string[];
  main_topics: string[];
  main_entities: string[];
}

export interface SceneResponse {
  id: number;
  video_id: string;
  scene_index: number;
  start_sec: number;
  end_sec: number;
  keyframe_path: string | null;
  ocr_text: string | null;
  aligned_transcript: string | null;
  caption: string | null;
  prev_caption: string | null;
  created_at: string;
}

export interface VideoResponse {
  id: string;
  status: VideoStatus;
  progress: number;
  error_message: string | null;
  file_path: string;
  file_name: string;
  file_size: number;
  duration: number | null;
  content_type: ContentType;
  language: string;
  audio_enabled: boolean;
  vision_enabled: boolean;
  ocr_enabled: boolean;
  grounding_enabled: boolean;
  caption_enabled: boolean;
  detection_enabled: boolean;
  summary_enabled: boolean;
  summary_mode: string;
  search_index_enabled: boolean;
  sample_fps: number;
  segment_threshold: number;
  caption_with_context: boolean;
  summary_detail: string;
  status_detail: string | null;
  qc_result: unknown | null;
  summary: VideoSummary | null;
  created_at: string;
  updated_at: string;
}

/* ── Status (GET /api/v1/videos/{id}/status) ── */

export interface VideoStatusResponse {
  video_id: string;
  status: string;
  progress: number;
  current_phase: string | null;
  phase_description: string | null;
  error_message: string | null;
  updated_at: string | null;
}

/* ── Search (POST /api/v1/search/semantic) ── */

export interface SearchResultItem {
  scene_id: number;
  video_id: string;
  scene_index: number;
  scene_range_start: number;
  scene_range_end: number;
  precise_start: number | null;
  precise_end: number | null;
  precision_level: "frame" | "chunk" | "text" | "label" | "scene";
  match_paths: string[];
  caption: string | null;
  ocr_text: string | null;
  aligned_transcript: string | null;
  similarity: number | null;
  thumbnail_url: string | null;
}

export interface SearchResults {
  results: SearchResultItem[];
  total: number;
  query_time_ms: number;
}

/* ── Upload response ── */

export interface PipelineParams {
  content_type: ContentType;
  vision_enabled: boolean;
  audio_enabled: boolean;
  ocr_enabled: boolean;
  caption_enabled: boolean;
  detection_enabled: boolean;
  detection_classes: string[] | null;
  search_index_enabled: boolean;
  summary_enabled: boolean;
  summary_mode: string;
  language: string;
  sample_fps: number;
  segment_threshold: number;
  caption_with_context: boolean;
  summary_detail: string;
}

/* ── Settings ── */

export interface ApiKeyInfo {
  id: string;
  label: string;
  configured: boolean;
  masked_value: string | null;
}

export interface SettingsData {
  api_keys: Record<string, ApiKeyInfo>;
}

/* ── Detection & Tracking ── */

export interface Detection {
  bbox: { x1: number; y1: number; x2: number; y2: number };
  class_name: string;
  track_id: number;
}

export interface Track {
  track_id: number;
  class_name: string;
  first_seen: number;
  last_seen: number;
  frame_count: number;
}

export interface DetectionData {
  has_detection: boolean;
  tracks: Track[];
  detections: Record<string, Detection[]>;  // key: integer timestamp string
}
