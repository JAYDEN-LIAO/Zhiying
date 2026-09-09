import type {
  Detection,
  DetectionData,
  DetectionRange,
  FaceData,
  FaceSearchResult,
  FileItem,
  PipelineParams,
  SearchResults,
  SearchResultItem,
  TaskItem,
  VideoGroup,
  VideoResponse,
  VideoStatus,
} from "../types";

/* ════════════════════════════════════════════════════════════
   mock.ts — 本地演示数据层（后端不可达时自动降级）
   视频：public/mock/flower.mp4（MDN CC0 示例视频，7.35s）
   覆盖：文件库树 / 视频详情 / 检测轨迹 / 识别框时间窗 /
        任务列表 / 重新解析状态机（processing → completed 流转）
   ════════════════════════════════════════════════════════════ */

export const MOCK_VIDEO_ID = "mock-flower-001";
const MOCK_VIDEO_URL = "/mock/flower.mp4";
const MOCK_DURATION = 7.35;

export function isMockId(id: string): boolean {
  return id.startsWith("mock-");
}

/* ── 文件库树 ── */

const MOCK_GROUPS: VideoGroup[] = [
  { groupId: "g-garden", name: "花园监控", number: "CAM-01", owner: "演示", file_count: 2, created_at: "2026-09-01T09:00:00Z", videoIds: [MOCK_VIDEO_ID, "mock-garden-002"] },
  { groupId: "g-street", name: "街道卡口", number: "CAM-07", owner: "演示", file_count: 2, created_at: "2026-09-01T09:30:00Z", videoIds: ["mock-street-003", "mock-street-004"] },
];

const MOCK_FILES: FileItem[] = [
  { id: MOCK_VIDEO_ID, name: "garden_flower_001.mp4", file_ext: ".mp4", group_id: "g-garden", duration: MOCK_DURATION, file_size: 1128375, created_at: "2026-09-01T10:00:00Z", current_version_no: 1, current_status: "completed", current_progress: 100, current_summary: { one_liner: "花园特写：粉色大丽菊随风轻摆，结尾有蜜蜂访花。" }, versions_count: 1 },
  { id: "mock-garden-002", name: "garden_path_002.mp4", file_ext: ".mp4", group_id: "g-garden", duration: 52, file_size: 8421000, created_at: "2026-09-01T10:05:00Z", current_version_no: 1, current_status: "completed", current_progress: 100, current_summary: { one_liner: "花园小径空镜。" }, versions_count: 1 },
  { id: "mock-street-003", name: "street_cross_0215.mp4", file_ext: ".mp4", group_id: "g-street", duration: 62, file_size: 15300000, created_at: "2026-09-01T11:00:00Z", current_version_no: 1, current_status: "processing", current_progress: 45, current_summary: null, versions_count: 1 },
  { id: "mock-street-004", name: "street_cross_0216.mp4", file_ext: ".mp4", group_id: "g-street", duration: 48, file_size: 12100000, created_at: "2026-09-01T11:10:00Z", current_version_no: null, current_status: "pending", current_progress: 0, current_summary: null, versions_count: 0, queued: true },
  { id: "mock-loose-005", name: "drone_shot_008.mp4", file_ext: ".mp4", group_id: null, duration: 120, file_size: 48000000, created_at: "2026-08-30T15:00:00Z", current_version_no: 1, current_status: "completed", current_progress: 100, current_summary: { one_liner: "航拍城市空镜。" }, versions_count: 1 },
];

const FILE_MAP = new Map(MOCK_FILES.map((f) => [f.id, f]));

/* ── 已完成视频的 AI 结构化标签（列表卡片「智能解析标签」演示数据） ── */

export const MOCK_FILE_TAGS: Record<string, string[]> = {
  [MOCK_VIDEO_ID]: ["👤 行人×1", "🚗 车辆", "⚠️ 奔跑"],
  "mock-garden-002": ["🌿 空镜"],
  "mock-loose-005": ["👤 行人×2", "🛣️ 道路"],
};

/* ── 检测轨迹（仅演示主视频有识别数据；COCO 类名 → 自动中文化/配色） ── */

interface MockTrack {
  track_id: number;
  class_name: string;
  display_seq: number;
  first_seen: number;
  last_seen: number;
  segments: { start: number; end: number }[];
  /** t 时刻的归一化 bbox */
  bboxAt: (t: number) => { x1: number; y1: number; x2: number; y2: number };
}

const MOCK_TRACKS: MockTrack[] = [
  {
    track_id: 101,
    class_name: "potted plant",
    display_seq: 1,
    first_seen: 0,
    last_seen: 7.3,
    segments: [
      { start: 0, end: 3.2 },
      { start: 4.1, end: 7.3 },
    ],
    /* 画面中央的主花丛，轻微呼吸缩放 */
    bboxAt: (t) => {
      const b = 0.02 * Math.sin(t * 2.2);
      const w = 0.52 + b;
      const h = 0.64 + b;
      return { x1: 0.5 - w / 2, y1: 0.42 - h / 2, x2: 0.5 + w / 2, y2: 0.42 + h / 2 };
    },
  },
  {
    track_id: 102,
    class_name: "bird",
    display_seq: 1,
    first_seen: 3.8,
    last_seen: 6.5,
    segments: [{ start: 3.8, end: 6.5 }],
    /* 小目标从右下飞向左上（模拟结尾的蜜蜂） */
    bboxAt: (t) => {
      const k = (t - 3.8) / (6.5 - 3.8);
      const cx = 0.85 - 0.5 * k;
      const cy = 0.75 - 0.55 * k;
      return { x1: cx - 0.06, y1: cy - 0.06, x2: cx + 0.06, y2: cy + 0.06 };
    },
  },
  {
    track_id: 103,
    class_name: "vase",
    display_seq: 1,
    first_seen: 0.4,
    last_seen: 3.0,
    segments: [{ start: 0.4, end: 3.0 }],
    /* 左下角的花茎叶区域，缓慢向右漂移 */
    bboxAt: (t) => {
      const d = 0.03 * (t / 3);
      return { x1: 0.06 + d, y1: 0.52, x2: 0.36 + d, y2: 0.96 };
    },
  },
];

/* ── 视频详情 ── */

const MOCK_SUMMARY = {
  one_liner: "花园特写：一朵粉色大丽菊在绿叶间随风轻摆，结尾处有蜜蜂停留访花。",
  scenes_summary: [],
  tags: ["花园", "花卉", "特写"],
  main_topics: ["花卉特写"],
  main_entities: ["大丽菊", "蜜蜂"],
};

function mockVideo(id: string, status: VideoStatus, progress: number): VideoResponse {
  const file = FILE_MAP.get(id) ?? MOCK_FILES[0];
  return {
    id,
    status,
    progress,
    error_message: null,
    file_path: `D:/mock-library/${file.group_id ?? "loose"}/${file.name}`,
    file_name: file.name,
    file_size: file.file_size ?? 1128375,
    duration: MOCK_DURATION,
    content_type: "general",
    language: "auto",
    audio_enabled: false,
    vision_enabled: true,
    ocr_enabled: false,
    grounding_enabled: false,
    caption_enabled: false,
    detection_enabled: id === MOCK_VIDEO_ID,
    detection_classes: null,
    face_enabled: false,
    plate_enabled: false,
    summary_enabled: false,
    summary_mode: "vlm_llm",
    search_index_enabled: true,
    sample_fps: 1,
    segment_threshold: 0.5,
    caption_with_context: true,
    summary_detail: "standard",
    encode_profile: null,
    status_detail: null,
    group_id: file.group_id,
    external_file_id: null,
    qc_result: null,
    suggested_scene_key: null,
    suggested_scene_label: null,
    suggested_confidence: null,
    suggested_params: null,
    summary: id === MOCK_VIDEO_ID ? MOCK_SUMMARY : null,
    container_format: "mp4",
    video_codec: "h264",
    audio_codec: null,
    has_audio: false,
    remuxed_path: null,
    proxy_path: null,
    proxy_status: "ready",
    proxy_progress: 1,
    created_at: file.created_at ?? "2026-09-01T10:00:00Z",
    updated_at: "2026-09-01T10:30:00Z",
  };
}

/* ── 重新解析状态机：发起后 8s 内 processing（进度递增），之后 completed ── */

let reanalyzeAt: number | null = null;
const REANALYZE_SEC = 8;

function mockGetVideo(id: string): VideoResponse {
  if (id === MOCK_VIDEO_ID && reanalyzeAt != null) {
    const elapsed = (Date.now() - reanalyzeAt) / 1000;
    if (elapsed < REANALYZE_SEC) {
      return mockVideo(id, "processing", Math.min(96, Math.round((elapsed / REANALYZE_SEC) * 100)));
    }
    reanalyzeAt = null;
  }
  return mockVideo(id, "completed", 100);
}

/* ── 视频内搜索（语义/画搜共用；帧命中 ×2 + 轨迹命中 ×1） ── */

function mockSearchResults(query: string): SearchResults {
  const q = query.trim();
  const base: SearchResultItem[] = [
    {
      scene_id: 1,
      video_id: MOCK_VIDEO_ID,
      scene_index: 0,
      scene_range_start: 0.5,
      scene_range_end: 2.0,
      precise_start: 0.5,
      precise_end: null,
      precision_level: "frame" as const,
      match_paths: [],
      caption: "粉色大丽菊特写，花瓣随风轻摆",
      ocr_text: null,
      aligned_transcript: null,
      similarity: q ? 0.88 : 0.92,
      thumbnail_url: null,
    },
    {
      scene_id: 2,
      video_id: MOCK_VIDEO_ID,
      scene_index: 0,
      scene_range_start: 4.0,
      scene_range_end: 6.5,
      precise_start: 5.2,
      precise_end: null,
      precision_level: "frame" as const,
      match_paths: [],
      caption: "蜜蜂飞近花朵停留访花",
      ocr_text: null,
      aligned_transcript: null,
      similarity: q ? 0.81 : 0.85,
      thumbnail_url: null,
    },
    {
      scene_id: 3,
      video_id: MOCK_VIDEO_ID,
      scene_index: 0,
      scene_range_start: 0,
      scene_range_end: 7.3,
      precise_start: 0,
      precise_end: null,
      precision_level: "track" as const,
      match_paths: [],
      caption: null,
      ocr_text: null,
      aligned_transcript: null,
      similarity: 0.79,
      thumbnail_url: null,
      track_id: 101,
      class_name: "potted plant",
      display_seq: 1,
    },
  ];
  return { results: base.map((r) => ({ ...r, video_id: MOCK_VIDEO_ID })), total: base.length, query_time_ms: 38 };
}

function mockFaceData(): FaceData {
  return { has_face: false, identities: [], track_to_identity: {} };
}

/* ── 识别框时间窗（0.1s 精度 key，与 DetectionCanvas 匹配协议一致） ── */

function mockDetectionRange(videoId: string, start: number, end: number): DetectionRange {
  const detections: Record<string, Detection[]> = {};
  if (videoId !== MOCK_VIDEO_ID) {
    return { has_detection: false, start_sec: start, end_sec: end, detections };
  }
  const from = Math.max(0, Math.round(start * 10));
  const to = Math.min(Math.round(MOCK_DURATION * 10), Math.round(end * 10));
  for (let i = from; i <= to; i++) {
    const t = i / 10;
    const list: Detection[] = [];
    for (const tr of MOCK_TRACKS) {
      if (t >= tr.first_seen && t <= tr.last_seen) {
        list.push({ bbox: tr.bboxAt(t), class_name: tr.class_name, track_id: tr.track_id, display_seq: tr.display_seq });
      }
    }
    if (list.length > 0) detections[t.toFixed(1)] = list;
  }
  return { has_detection: true, start_sec: start, end_sec: end, detections };
}

function mockTracks(videoId: string): DetectionData {
  if (videoId !== MOCK_VIDEO_ID) return { has_detection: false, tracks: [] };
  return {
    has_detection: true,
    tracks: MOCK_TRACKS.map(({ track_id, class_name, display_seq, first_seen, last_seen, segments }) => ({
      track_id,
      class_name,
      display_seq,
      first_seen,
      last_seen,
      frame_count: Math.round((last_seen - first_seen) * 10),
      segments,
    })),
  };
}

/* ── 任务列表（历史记录演示数据：完成/进行中/排队/失败） ── */

const MOCK_PARAMS = { content_type: "general", sample_fps: 1, search_index_enabled: true, summary_enabled: true, detection_enabled: true };

const MOCK_TASKS: TaskItem[] = [
  { id: MOCK_VIDEO_ID, version_no: 1, file_name: "garden_flower_001.mp4", group_name: "花园监控", status: "completed", progress: 100, error_message: null, params: MOCK_PARAMS, created_at: "2026-09-01T10:00:00Z", updated_at: "2026-09-01T10:30:00Z", duration_sec: MOCK_DURATION },
  { id: "mock-street-003", version_no: 1, file_name: "street_cross_0215.mp4", group_name: "街道卡口", status: "processing", progress: 45, error_message: null, params: { ...MOCK_PARAMS, summary_enabled: false }, created_at: "2026-09-01T11:00:00Z", updated_at: "2026-09-01T11:05:00Z", duration_sec: 62 },
  { id: "mock-street-004", version_no: null, file_name: "street_cross_0216.mp4", group_name: "街道卡口", status: "pending", progress: 0, error_message: null, params: null, created_at: "2026-09-01T11:10:00Z", updated_at: "2026-09-01T11:10:00Z", duration_sec: 48, queued: true },
  { id: "mock-loose-005", version_no: 1, file_name: "drone_shot_008.mp4", group_name: null, status: "failed", progress: 0, error_message: "转码失败：源视频流损坏（演示用错误信息）", params: MOCK_PARAMS, created_at: "2026-08-30T15:20:00Z", updated_at: "2026-08-30T15:26:00Z", duration_sec: 31 },
];

/* ════════════════════════════════════════════════════════════
   API 包装：真实请求失败（后端不可达）→ 自动降级 Mock 数据
   ════════════════════════════════════════════════════════════ */

/** 判定「后端不可达」（vite 代理 ECONNREFUSED → HTTP 500；直连 → fetch 网络错误） */
function isBackendDown(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return /HTTP 5\d\d|fetch|network|ECONNREFUSED|proxy/i.test(msg);
}

function warnMock(method: string) {
  // eslint-disable-next-line no-console
  console.warn(`[mock] 后端不可达，${method}() 已降级为本地演示数据`);
}

async function withFallback<T>(method: string, real: () => Promise<T>, mock: () => T): Promise<T> {
  try {
    return await real();
  } catch (err) {
    if (isBackendDown(err)) {
      warnMock(method);
      return mock();
    }
    throw err;
  }
}

type ApiShape = {
  getVideoStreamUrl: (videoId: string, hevcOk?: boolean) => string;
  listFiles: () => Promise<FileItem[]>;
  listGroups: () => Promise<VideoGroup[]>;
  getVideo: (videoId: string) => Promise<VideoResponse>;
  fetchDetectionTracks: (videoId: string) => Promise<DetectionData>;
  fetchDetectionRange: (videoId: string, start: number, end: number) => Promise<DetectionRange>;
  fetchFaceData: (videoId: string) => Promise<FaceData>;
  listTasks: (scope?: "all" | "active" | "history") => Promise<TaskItem[]>;
  reanalyze: (videoId: string, params: PipelineParams) => Promise<VideoResponse>;
  searchSemantic: (query: string, options?: Record<string, unknown>) => Promise<SearchResults>;
  searchImage: (file: File, options?: Record<string, unknown>) => Promise<SearchResults>;
  searchFace: (file: File, videoIds?: string[], topK?: number) => Promise<FaceSearchResult[]>;
};

/** 包装真实 api：mock 视频 ID 直连本地文件；后端不可达时数据请求降级 mock */
export function wrapWithMock<T extends ApiShape>(real: T): T {
  const overrides: ApiShape = {
    getVideoStreamUrl: (videoId, hevcOk) =>
      isMockId(videoId) ? MOCK_VIDEO_URL : real.getVideoStreamUrl(videoId, hevcOk),
    listFiles: () => withFallback("listFiles", () => real.listFiles(), () => MOCK_FILES),
    listGroups: () => withFallback("listGroups", () => real.listGroups(), () => MOCK_GROUPS),
    getVideo: (videoId) => withFallback("getVideo", () => real.getVideo(videoId), () => mockGetVideo(videoId)),
    fetchDetectionTracks: (videoId) =>
      withFallback("fetchDetectionTracks", () => real.fetchDetectionTracks(videoId), () => mockTracks(videoId)),
    fetchDetectionRange: (videoId, start, end) =>
      withFallback("fetchDetectionRange", () => real.fetchDetectionRange(videoId, start, end), () =>
        mockDetectionRange(videoId, start, end),
      ),
    fetchFaceData: (videoId) =>
      withFallback("fetchFaceData", () => real.fetchFaceData(videoId), () => mockFaceData()),
    listTasks: (scope) => withFallback("listTasks", () => real.listTasks(scope), () => MOCK_TASKS),
    reanalyze: (videoId, params) =>
      withFallback("reanalyze", () => real.reanalyze(videoId, params), () => {
        if (isMockId(videoId)) {
          reanalyzeAt = Date.now();
          return mockVideo(videoId, "processing", 3);
        }
        return mockVideo(videoId, "completed", 100);
      }),
    searchSemantic: (query, options) =>
      withFallback("searchSemantic", () => real.searchSemantic(query, options), () => mockSearchResults(query)),
    searchImage: (file, options) =>
      withFallback("searchImage", () => real.searchImage(file, options), () => mockSearchResults("")),
    searchFace: (file, videoIds, topK) =>
      withFallback("searchFace", () => real.searchFace(file, videoIds, topK), () => []),
  };
  return { ...real, ...overrides };
}
