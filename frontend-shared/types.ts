/* ════════════════════════════════════════════════════════════
   Zhiying TypeScript types — mirrors backend core/schemas.py
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
  /* ── Group (v0.19 多视频处理) ── */
  group_id: string | null;
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
  /* ── Group (v0.19 多视频处理) ── */
  group_id: string | null;
  /* ── 云智平台外部文件 ID (v0.25.x) ── */
  external_file_id: number | null;
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

export interface PipelineStage {
  name: string;
  label: string;
  description: string;
  progress_start: number;
  progress_end: number;
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
  confidence?: number;  // v0.30: 通用置信度 = 相似度 × 路径权重（跨路径可排行，与返回顺序一致）
  thumbnail_url: string | null;
  track_id?: number;
  class_name?: string;
  display_seq?: number | null;
  bbox?: { x1: number; y1: number; x2: number; y2: number };
  plate_text?: string;
  plate_type?: string;
  char_confidences?: number[];
}

/* ── Face search result (POST /api/v1/search/face) ── */

export interface FaceAppearance {
  timestamp_sec: number;
  bbox: { x1: number; y1: number; x2: number; y2: number } | null;
  track_id: number | null;
}

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
  appearances?: FaceAppearance[];
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

/* ── Video Group (v0.19 多视频处理) ── */

export interface VideoGroup {
  id?: string;
  groupId: string;
  name?: string | null;
  number?: string | null;
  owner?: string | null;
  file_count?: number;
  created_at?: string | null;
  videoIds: string[];
}

/* ═══ v0.34 文件库 / 多版本 / 任务中心 ═══ */

export interface FileItem {
  id: string;                       // 文件 ID = file_id（独立文件 = 自身 id）
  name: string;
  file_ext?: string | null;         // 真实扩展名（后缀展示用，重命名不影响）
  group_id: string | null;
  duration: number | null;
  file_size: number | null;
  created_at: string | null;
  current_version_no: number | null;
  current_status: string | null;
  current_progress: number;
  current_summary: { one_liner?: string } | null;
  versions_count: number;
}

export interface VersionInfo {
  id: string;                       // 版本行 videos.id（作 task_id）
  video_id: string | null;
  version_no: number | null;
  status: string;
  progress: number;
  error_message: string | null;
  file_name: string | null;
  group_id: string | null;
  params: Record<string, unknown> | null;
  detection_enabled: boolean;
  face_enabled: boolean;
  plate_enabled: boolean;
  search_index_enabled: boolean;
  summary_enabled: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface TaskItem {
  id: string;                       // 版本行 videos.id
  version_no: number | null;
  file_name: string | null;
  group_name: string | null;
  status: string;
  progress: number;
  error_message: string | null;
  params: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
  duration_sec: number | null;          // 真实处理时长（秒）
  queued?: boolean;                     // 在全局管道队列等待 worker（侧栏黄徽章）
  detection_enabled?: boolean;
  face_enabled?: boolean;
  plate_enabled?: boolean;
  search_index_enabled?: boolean;
  summary_enabled?: boolean;
}

export interface TaskLogLine {
  seq: number;
  level: string;
  message: string;
  created_at: string;
}

/* ── Settings ── */

export interface ApiKeyInfo {
  id: string;
  label: string;
  configured: boolean;
  masked_value: string | null;
}

export interface ProviderInfo {
  id: string;
  label: string;
  base_url: string;
  model: string;
}

export interface StorageInfo {
  video_dir: string;
  artifact_dir: string;
}

export interface EncodeProfileSettings {
  encode_width: number;
  encode_height: number;
  encode_batch_size: number;
}

export interface PipelineSettings {
  /* 编码三档模板 + 默认档 */
  encode_profiles: Record<string, EncodeProfileSettings>;
  default_encode_profile: string;
  /* 物体检测 */
  detection_fps: number;
  detector_batch_size: number;
  confidence_threshold: number;
  iou_threshold: number;
  /* 全局开关 */
  use_nvdec: boolean;
  chunk_encoding: boolean;
  /* 模型参数 */
  quantization: string;
  yolo_imgsz: number;
  max_concurrent_videos: number;
  /* 场景分割（v0.33 起全局设置，从逐视频高级参数移入） */
  sample_fps: number;
  segment_threshold: number;
}

export interface EncodeProfileSettingsUpdate {
  encode_width?: string;
  encode_height?: string;
  encode_batch_size?: string;
}

/* 编辑态更新载荷：数值/字符串字段为字符串，空字符串 = 删除覆盖（回退 config 默认）；布尔为显式开关 */
export interface PipelineSettingsUpdate {
  encode_profiles?: Record<string, EncodeProfileSettingsUpdate>;
  default_encode_profile?: string;
  detection_fps?: string;
  detector_batch_size?: string;
  confidence_threshold?: string;
  iou_threshold?: string;
  use_nvdec?: boolean;
  chunk_encoding?: boolean;
  quantization?: string;
  yolo_imgsz?: string;
  max_concurrent_videos?: string;
  sample_fps?: string;
  segment_threshold?: string;
}

export interface SettingsData {
  api_keys: Record<string, ApiKeyInfo>;
  providers: Record<string, ProviderInfo>;
  storage: StorageInfo;
  pipeline: PipelineSettings;
}

export interface ProviderSettingsEdit {
  base_url?: string;
  model?: string;
}

export interface SettingsUpdate {
  api_keys?: Record<string, string>;
  providers?: Record<string, ProviderSettingsEdit>;
  storage?: Partial<StorageInfo>;
  pipeline?: PipelineSettingsUpdate;
}

/* ── 参数预设 (v0.22: 多套命名参数快照，一键套用) ── */

export interface PipelinePreset {
  id: string;
  name: string;
  pipeline: Record<string, unknown> | null;
  created_at: string | null;
}

/* ── Detection & Tracking ── */

export interface Detection {
  bbox: { x1: number; y1: number; x2: number; y2: number };
  class_name: string;
  track_id: number;
  /* 类内展示序号（每视频每类别 1..N；旧数据为 null → 前端回退 track_id）*/
  display_seq?: number | null;
}

export interface Track {
  track_id: number;
  class_name: string;
  display_seq?: number | null;
  first_seen: number;
  last_seen: number;
  frame_count: number;
  segments?: { start: number; end: number }[];
  /* ── v0.22: 后端预计算缩略图信息（替代前端 getThumbBbox 全表扫描） ── */
  best_thumb_ts?: number;
  best_bbox?: { x1: number; y1: number; x2: number; y2: number };
  thumbnail_url?: string | null;
}

export interface DetectionData {
  has_detection: boolean;
  tracks: Track[];
  // v0.22 (S2): 删除全量 detections dict —— Overlay 改走 /detection/detections 时间窗按需加载
}

/* ── Detection time window (v0.22, GET /detection/detections) ── */

export interface DetectionRange {
  has_detection: boolean;
  start_sec: number;
  end_sec: number;
  detections: Record<string, Detection[]>;  // key: 0.1s 精度时间戳字符串
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
  // v0.30: 按 track 聚合的出现时间段（检测栏人脸行展开显示）
  appearances?: { track_id: number | null; start_sec: number; end_sec: number }[];
}

export interface FaceData {
  has_face: boolean;
  identities: FaceIdentity[];
  // v0.30: track_id → {identity_id}，person track 条目据此显示身份标签（替代 👤）
  track_to_identity?: Record<number, { identity_id: number }>;
  // v0.22 (S1): 删除 per-frame detections 字段——后端不再返回（前端零消费，防大 JSON 炸弹）
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

export interface CaseAssetItem {
  id: string;
  group_id: string | null;
  kind: string;
  name: string;
  path: string;
  file_ext?: string | null;         // 真实扩展名（后缀展示用）
  file_size: number;
  created_at: string | null;
}
