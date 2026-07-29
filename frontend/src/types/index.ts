/* ════════════════════════════════════════════════════════════
   Cerno TypeScript types — mirrors backend core/schemas.py
   ════════════════════════════════════════════════════════════ */

/* ── Enums ── */

export type VideoStatus = "pending" | "processing" | "completed" | "failed";
export type ContentType = "general" | "meeting" | "surveillance" | "text_recognition" | "custom";

/* ── Format / Proxy status (v0.13) ── */

export interface ProxyStatus {
  status: string;    // "none" | "processing" | "ready" | "failed"
  progress: number;  // 0.0 ~ 1.0
  proxy_path: string | null;
}

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
  detection_classes: string[] | null;
  face_enabled: boolean;
  plate_enabled: boolean;
  summary_enabled: boolean;
  summary_mode: string;
  search_index_enabled: boolean;
  sample_fps: number;
  language: string;
  encode_profile: string | null;
  /* ── Format info (v0.13) ── */
  container_format: string | null;
  video_codec: string | null;
  proxy_status: string;
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
  detection_classes: string[] | null;
  face_enabled: boolean;
  plate_enabled: boolean;
  summary_enabled: boolean;
  summary_mode: string;
  search_index_enabled: boolean;
  sample_fps: number;
  segment_threshold: number;
  caption_with_context: boolean;
  summary_detail: string;
  encode_profile: string | null;
  status_detail: string | null;
  qc_result: unknown | null;
  summary: VideoSummary | null;
  /* ── Format info (v0.13) ── */
  container_format: string | null;
  video_codec: string | null;
  audio_codec: string | null;
  has_audio: boolean;
  remuxed_path: string | null;
  proxy_path: string | null;
  proxy_status: string;
  proxy_progress: number;
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
  precision_level: "frame" | "chunk" | "text" | "label" | "track" | "plate" | "scene";
  match_paths: string[];
  caption: string | null;
  ocr_text: string | null;
  aligned_transcript: string | null;
  similarity: number | null;
  thumbnail_url: string | null;
  track_id?: number;
  class_name?: string;
  bbox?: { x1: number; y1: number; x2: number; y2: number };
  plate_text?: string;
  plate_type?: string;
  char_confidences?: number[];
}

/* ── Face search result (POST /api/v1/search/face) ── */

export interface FaceSearchResult {
  identity_id: number;
  video_id: string;
  identity_label: string;
  face_count: number;
  first_seen: number;
  last_seen: number;
  avg_quality: number;
  similarity: number;
  best_face_timestamp: number | null;
  best_face_bbox: { x1: number; y1: number; x2: number; y2: number } | null;
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
  face_enabled: boolean;
  plate_enabled: boolean;
  search_index_enabled: boolean;
  summary_enabled: boolean;
  summary_mode: string;
  language: string;
  sample_fps: number;
  segment_threshold: number;
  caption_with_context: boolean;
  summary_detail: string;
  encode_profile: string | null;
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
  segments?: { start: number; end: number }[];
}

export interface DetectionData {
  has_detection: boolean;
  tracks: Track[];
  detections: Record<string, Detection[]>;  // key: integer timestamp string
}

/* ── Face Recognition ── */

export interface FaceIdentity {
  id: number;
  label: string;            // "人物 A", "人物 B", ...
  face_count: number;
  first_seen: number;
  last_seen: number;
  avg_quality: number;
  best_face_timestamp: number | null;
  best_face_bbox: { x1: number; y1: number; x2: number; y2: number } | null;
  best_thumbnail_url: string | null;
}

export interface FaceDetectionItem {
  identity_id: number | null;
  track_id: number;
  bbox: { x1: number; y1: number; x2: number; y2: number };
  quality: number;
  thumbnail_url: string | null;
}

export interface FaceData {
  has_face: boolean;
  identities: FaceIdentity[];
  detections: Record<string, FaceDetectionItem[]>;  // key: timestamp string
}

/* ── License Plate Recognition ── */

export interface PlateDetectionItem {
  id: number;
  track_id: number;
  class_name: string;
  timestamp_sec: number;
  plate_text: string;
  plate_type: string;        // blue / yellow / green / white / black
  char_confidences: number[] | null;
  bbox: { x1: number; y1: number; x2: number; y2: number };
  confidence: number;
  thumbnail_url: string | null;
}

export interface PlateData {
  has_plate: boolean;
  detections: PlateDetectionItem[];
}

/* ── Video Metadata (GET /api/v1/videos/{id}/metadata) ── */

export interface VideoStreamMeta {
  codec: string | null;
  codec_profile: string | null;
  codec_level: string | null;
  codec_tier: string | null;
  resolution: string | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  bitrate: number | null;
  pixel_format: string | null;
  color_space: string | null;
  color_primaries: string | null;
  transfer_characteristics: string | null;
  chroma_subsampling: string | null;
  bit_depth: number | null;
  display_aspect_ratio: string | null;
  rotation: number | null;
  encoder: string | null;
}

export interface AudioStreamMeta {
  codec: string | null;
  channels: number | null;
  channel_layout: string | null;
  sample_rate: number | null;
  bitrate: number | null;
  language: string | null;
}

export interface SubtitleStreamMeta {
  format: string | null;
  language: string | null;
  title: string | null;
  forced: boolean;
}

export interface VideoMetadata {
  container: string | null;
  format_name: string | null;
  duration: number | null;
  file_size: number | null;
  overall_bitrate: number | null;
  video_streams: VideoStreamMeta[];
  audio_streams: AudioStreamMeta[];
  subtitle_streams: SubtitleStreamMeta[];
  device: {
    make?: string;
    model?: string;
    software?: string;
    gps_latitude?: number;
    gps_longitude?: number;
    gps_altitude?: number;
  } | null;
  timestamps: {
    created?: string;
    modified?: string;
  } | null;
  raw: Record<string, unknown> | null;
  source_analysis: SourceAnalysis | null;
  ai_detect: AIDetectResult | null;
}

/* ── Source Analysis & AI Detection (v0.17) ── */

export interface SourceAnalysis {
  source_type: "phone" | "camera" | "screen_recording" | "surveillance" | "non_camera_source" | "unknown";
  source_label: string;
  confidence: "high" | "medium" | "low";
  evidence: string[];
  surveillance_brand: string | null;
  surveillance_method: string | null;
}

export interface AIDetectSignal {
  source: string;
  confidence: string;
  description: string;
  tool: string | null;
}

export interface AIDetectResult {
  status: "not_run" | "analyzing" | "completed" | "error";
  score: number | null;
  verdict: "ai_generated" | "likely_ai" | "no_signal" | "error" | null;
  signals: AIDetectSignal[];
  software_info: [string, string][];
  error_message: string | null;
  deep_analysis_used: boolean;
}

/* ── Export (POST /api/v1/videos/{id}/export/*) ── */

export interface ExportClipRequest {
  start_sec: number;
  end_sec: number;
  output_format?: string;
}

export interface ExportFramesRequest {
  timestamps: number[];
  format?: string;
}

export interface ExportTrackRequest {
  draw_bbox?: boolean;
}

export interface ExportThumbnailsRequest {
  scene_indices?: number[] | null;
}
