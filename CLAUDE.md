# Cerno Project Context for AI Agents

## One-Line Summary

Cerno is a **video analytics engine** (v0.20) that ingests videos (singly or in batch groups), runs a **declarative operation DAG** (15 operations with event-driven orchestration), generates **4-path encodings** (frame-level 1fps + chunk-level sliding window + text-level caption semantics + track-level crop embeddings), runs **YOLO11 object detection + BoT-SORT tracking with online ReID** as an optional add-on, adds **face recognition** (SCRFD + ArcFace R50 identity clustering) and **license plate recognition** (HyperLPR3, with PaddleOCR alternative) as optional perception modules, enables **7-path parallel semantic search** (frame + chunk + text + label + track + plate, chunk 配置关闭默认不启用) + **face image search** (POST /search/face, ArcFace 512d) + **universal image search** (POST /search/image, Qwen3-VL-Embedding 2048-dim), provides **global ReID tracklet stitching** (合并被遮挡/缩放/切换拆分的同一身份 track, L3 可开关), **multi-format video compatibility** (容器 remux + 编码 proxy, 按需生成, 零浪费), exposes everything via **FastAPI + PostgreSQL/pgvector**, and provides a **4-level parameter system** (scene type → perception modules → function switches → advanced params) that controls pipeline execution. **Multi-video batch upload** (v0.19) supports grouping videos, one-click group pipeline trigger, cross-video search, and independent detection panel switching.

## Quick File Map

```
main.py                    — FastAPI app, lifespan, exception handlers, shared embedder (captioner on-demand)
api/routes.py              — Transitional re-export (endpoints split into sub-routers)
api/routes.py              — Transitional re-export (endpoints split into sub-routers)
api/video_routes.py        — Video CRUD + upload (probe同步+异步remux/proxy) + stream (hevc_ok智能路由) + proxy-status + thumbnail
api/search_routes.py       — Semantic search + pipeline/operations endpoints
api/settings_routes.py     — System settings (API keys) endpoints
api/router.py              — Assembles sub-routers under /api/v1 prefix
api/deps.py                — FastAPI dependency injection (get_db)
api/schemas.py             — Shared API DTOs (APIResponse, search/status models, ProxyStatusResponse)
api/detection_routes.py    — Detection data API endpoint (GET /videos/{id}/detection/data)
api/export_routes.py       — Export endpoints: clip/frames/track/thumbnails (7 endpoints, GET+POST)
api/face_routes.py          — Face data API (GET face/data + face/thumbnail)
api/plate_routes.py         — Plate data API (GET plate/data + plate/thumbnail)
api/maintenance_routes.py  — (stub) planned health/reindex endpoints
core/models.py             — ORM: Video (+8 format fields + group_id FK), VideoGroup, Scene, Transcript, FrameEmbedding, Chunk, FrameDetection, Track, TrackEmbedding, FaceIdentity, FaceDetection, PlateDetection (12 tables)
core/schemas.py            — Pydantic v2 DTOs + JSONB validation models + FormatInfo/ProxyStatus
core/interfaces.py         — 10 abstract base classes (ABCs) + Scene/VideoContext dataclasses
core/search.py             — 6 search functions: frame/chunk/text/track/plate/face (async def)
core/repository.py         — Data access layer + bulk_insert_frames/chunks
core/db.py                 — Async engine, init_db(), incremental migration (extensions: pgvector, pg_trgm, fuzzystrmatch)
core/config_loader.py      — Loads config.yaml, merges .env secrets via _ENV_OVERRIDES
core/prompt_loader.py      — Prompt template loader (config/prompts.yaml)
core/status_tracker.py     — Pipeline progress + dynamic operation-based weight calculation
core/exceptions.py         — Custom exceptions
pipeline/engine.py         — DAG executor: EventDrivenScheduler (event-driven, ~200 lines), reads remuxed_path
pipeline/operations.py     — Operation registry: ALL_OPERATIONS with gates/deps/labels (v0.14 gate fixes)
pipeline/runners/          — 15 operation runners (one per processing unit):
  runners/base.py            — OperationRunner ABC + PipelineContext + Operation dataclass
  runners/duration.py        — ffprobe duration detection
  runners/segmentation.py    — TransNetV2 (≤30min) / time-based (>30min) 自适应
  runners/transcription.py   — Audio extraction + faster-whisper transcription
  runners/keyframe.py        — 1fps frame pool extraction + thumbnails (cv2 + asyncio.to_thread)
  runners/alignment.py       — Transcript word-to-scene alignment
  runners/caption.py         — Dual-mode: native_video / vlm_llm (gated by summary_enabled)
  runners/summary.py         — Dual-mode: Python aggregator / DeepSeek API LLM
  runners/frame_encode.py    — 1fps batch image encoding (embedder @336×224) → frame_embeddings
  runners/chunk_encode.py    — Sliding window video encoding → chunks (config-gated)
  runners/text_encode.py     — Text semantic encoding (gated: 有文本源才跑)
  runners/detection.py       — YOLO11 + BoT-SORT (10fps/128batch/640px), 生产者-消费者并发, 与 search_encode 共享 NVDEC 流, 每 2s 缓存 track crop 供 track_encode
  runners/track_encode.py    — Track crop embedding + 全局 tracklet 缝合 (读检测缓存多帧 640×384 → mean pool → cosine 合并)
  runners/face.py            — SCRFD face detection + ArcFace R50 embedding + identity clustering
  runners/plate.py           — HyperLPR3 license plate detection + text recognition
  runners/search_encode.py   — 纯搜索路径：队列消费 detection 共享流帧 1fps + 批量编码，不依赖 segmentation/keyframes
pipeline/search_engine.py  — 7-path parallel recall (frame/chunk/text/label/track/plate + image) + scene-merge dedup, search_image_only() for no-cluster per-frame image search
plugins/factory.py         — Dynamic plugin loader (CATEGORY_MAP, _MODULE_OVERRIDES, _CLASS_OVERRIDES)
plugins/detector/yolo.py   — YOLO11s detector (batch GPU inference, asyncio.to_thread)
plugins/face/insightface_face.py  — InsightFace SCRFD + ArcFace R50 recognizer
plugins/plate/hyperlpr_plate.py  — HyperLPR3 license plate detector + recognizer (primary)
plugins/plate/paddle_plate.py    — PaddleOCR license plate detector (alternative)
plugins/embedder/qwen_vl_embedder.py — Qwen3-VL-Embedding (336×224 encode, 内存路径, 零磁盘I/O)
services/video_service.py  — Pipeline 调用与后台调度
services/format_service.py — 格式兼容: probe(ffprobe) / remux(容器标准化, -c copy) / proxy(按需h264_nvenc)
services/export_service.py — 导出业务逻辑 (clip/frames/track/thumbnails zip)
utils/video_util.py        — FFmpeg 工具函数 + stream_frames() (NVDEC MJPEG pipe / cv2 fallback)
utils/metadata.py          — 视频元数据提取 (pymediainfo → exiftool → ffprobe 三级)
utils/video_source.py      — 视频来源分析: 规则引擎分类 phone/camera/surveillance/... + 监控品牌（文件头魔数嗅探 IMKH→海康威视, magic_bytes>filename>metadata）
config/config.yaml         — Main config: server/db/storage/plugins/pipeline (detection_fps:10, batch:128)
config/config_schema.py    — Pydantic config validation
config/prompts.yaml        — Caption/Summarizer/Grounding prompt templates
frontend/src/Dashboard.tsx — Main workspace (orchestrator, ~430 lines, hevcOk探测+proxy轮询+streamReady+group state+detectionVideoId+header dropdown)
frontend/src/components/    — Split components (20 files):
                              icons, Sidebar, Header, SlideOutPanel,
                              ParameterPanel, PipelineBar, VideoSection, VideoPlayer,
                              VideoSummaryCard, VideoSearchCard, HistoryPanelContent, SettingsPage,
                              DetectionOverlay, DetectionPanel, DetectionTimeline,
                              VideoInfoCard, ExportMenu, RightPanel
frontend/src/labels.ts        — COCO 类名英→中映射 + 统一颜色表 (zh/zhLabel/colorOf)
frontend/src/utils/helpers.ts — Shared helpers (fmtDuration, fmtDate, formatSec)
frontend/src/services/api.ts — API wrapper + polling helper (getVideoStreamUrl hevc_ok, getProxyStatus)
frontend/src/types/index.ts — TypeScript types (mirrors backend schemas + ProxyStatus)
frontend/src/mockData.ts   — Pipeline stage definitions + computePipelineStages() dynamic function
```

## Data Flow

```
POST /videos/upload (multipart file)
  → save to disk
  → sync probe (ffprobe, <100ms) → save format_info to DB
  → create Video record (status=pending, default params, group_id=NULL)
  → async: remux (容器标准化, -c copy) + proxy (按需, 非HEVC浏览器请求时触发)
  → parameter panel auto-opens in frontend

POST /videos/upload/batch (multipart, multiple files, v0.19)
  → create VideoGroup record
  → concurrent per-file processing (semaphore=5, independent DB sessions):
      save to disk → create Video record (same group_id) → sync probe
  → after all complete: async remux/proxy
  → frontend: group card in history, header dropdown for video switching

PUT /videos/{id}/params (after user configures)
  → validate via PipelineParams (core/schemas.py model_validator)
  → update Video record with Scene Type / Perception Modules / Function Switches / Advanced Params
  → if video is in a group (v0.19): same params + pipeline trigger applied to all PENDING siblings
  → background task: PipelineEngine.run()   (for pending videos)
  → background task: PipelineEngine.run_incremental()   (for completed videos, only summary/search_index)

PipelineEngine.run() (DAG-based, gate-driven from L2/L3 params, v0.15):
  Gate Filter → EventDrivenScheduler
    Each operation runs as its own asyncio task, awaits upstream done events:
    duration (0.1s)
      ├─ search_encode (depends duration, 与 detection 共享 NVDEC 流, 队列消费) ──→ frame_embeddings
      ├─ detection (depends duration, producer-consumer, 与 search_encode 共享流)
      └─ segmentation → keyframes (stream_frames async generator)
            │     └─ caption (gated by summary_enabled) → summary
            ├─ frame_encode (depends segmentation, 通过 asyncio.Queue 与 keyframes 并发编码)
            └─ text_encode + chunk_encode (gated by summary)
                └─ track_encode (depends detection + frame_encode)
                    └─ face + plate (parallel, depends detection)
  → _persist() → mark_completed()

Key v0.15 DAG changes:
  - search_encode gate: 新增 not v.summary_enabled（修复摘要+搜索双编码 bug）
  - keyframes→frame_encode: 生产者-消费者模式 via asyncio.Queue(512)，并发抽取+编码
  - frame_encode depends_on=["segmentation"]（原 ["keyframes"]），与 keyframes 同批启动
  - NVDEC: MJPEG pipe (~100KB/帧) 替代 raw NV12，默认启用
  - embedder: _pool_last_token 逐行 L2 归一化修复 + float32 输出 + PIL resize 8线程并行
  - encode_batch_size: 512（120GB VRAM）
  - encode_profiles: 三档速度预设 (fast 336×224 / balanced 504×336 / precise 672×448)

GET /videos/{id}/stream?hevc_ok={bool} (v0.13):
  FormatService.get_stream_target() 智能路由:
    H.264 → 原文件直出
    HEVC + hevcOk=true → remuxed (MP4容器) 或原文件 (MP4/HEVC)
    HEVC + hevcOk=false → proxy (H.264代理), 无则按需触发+返回202
    浏览器原生格式 (WebM/VP9 etc.) → 直出, 零处理

Each operation declared in pipeline/operations.py with:
  - gate: lambda video, config → bool (parameter-driven enable/disable)
  - depends_on: list[str] (DAG dependency edges)
  - required_plugins: list[str] (auto-loaded by engine)
  - label/description: (frontend progress bar labels)

Adding a new perception module (e.g. YOLO detector):
  1. Write runner class in pipeline/runners/detection.py
  2. Add one Operation(...) entry to pipeline/operations.py ALL_OPERATIONS
  3. Add column to Video model + field to PipelineParams (unavoidable)
  → engine.py needs ZERO changes.

Search (7-path parallel, v0.18):
  text query → embedder.encode_text() → 2048-dim vector (shared, once)
  → 6 parallel tasks (text search):
    _frame_search()  → frame_embeddings table, 1fps per-frame precision
    _chunk_search()  → chunks table, sliding window process semantics（默认关闭）
    _text_search()   → scenes.text_embedding, caption+ocr+transcript 语义
    _label_search()  → JSONB @> entities.label (精确匹配场景内物体标签)
    _track_search()  → track_embeddings table, crop跨模态嵌入, 返回具体物体
    _plate_search()  → plate_detections table, Levenshtein 编辑距离 ≤ 2 模糊匹配
  → Face image search: POST /search/face (multipart image → ArcFace 512d → face_identities 表)
  → Universal image search: POST /search/image (任一图片→Qwen3-VL-Embedding 2048-dim→frame_embeddings)
    └─ 专用 search_image_only() 路径：帧结果不做时间聚类，不补充 scene 信息，每帧独立返回精确到秒
    └─ 默认搜索路径 ["frame", "track"]，不触发 text/label/plate（依赖 query 字符串）
  → merge: frame clusters (≤4s gap), chunk/text去重叠, track/plate 独立去重
  → enrich with scene metadata → return results with precision_level
```

## Key Conventions

- **All plugin interfaces are async**. Sync model inference MUST use `asyncio.to_thread()` — never call sync code directly in async methods.
- **Plugin config is YAML-driven**. `config/config.yaml` `plugins.{name}.backend` selects the implementation. `null` means the module is disabled.
- **API keys never in code**. Use `.env` file (gitignored) or environment variables. See `core/config_loader.py` `_ENV_OVERRIDES`.
- **Vector dim**: 2048 (Qwen3-VL-Embedding-8B output). No pgvector HNSW index (exceeds 2000-dim limit; exact scan <1ms at demo scale).
- **Trigger**: ~~`scenes.search_vector`~~ 已移除（tsvector 全文检索已废弃）
- **Shared embedder**: Embedder is loaded once during lifespan startup (`app.state.embedder`). Pipeline and SearchEngine reuse this shared instance — never call `load_plugin("embedder")` directly in business logic. Captioner preload is disabled by default (commented out in main.py for faster startup); pipeline loads it on-demand when summary is enabled.
- **Incremental migration**: `init_db()` uses `ALTER TABLE ADD COLUMN IF NOT EXISTS` for schema evolution (e.g., `text_embedding`, `status_detail` columns).
- **Four encoding paths exist**: Frame (1fps per-frame), Chunk (config-gated, default disabled, `-c copy` + 480p 5fps preprocessing + encode_video), Text (caption+ocr+transcript 语义), Track (crop cross-modal embedding). All four reuse the shared embedder.
- **Parameter system (v0.15)**: 4-level hierarchy — L1=Scene Type (general/meeting/surveillance/text_recognition/custom), L2=Perception Modules (vision/audio/ocr/caption/detection + face/plate sub-switches under detection), L3=Function Switches (search_index/summary/track_stitch + summary_mode[native_video/vlm_llm]), L4=Advanced Params (language/sample_fps/segment_threshold/caption_with_context/summary_detail + encode_profile[fast/balanced/precise/NULL])。Detection uses dual-gating: server-level (config.yaml backend: yolo/null) AND per-video (detection_enabled toggle). Face/plate use three-level gate: config backend + detection_enabled + face_enabled/plate_enabled. Upper levels set defaults for lower levels. Pipeline uses `PipelineParams` Pydantic model with cross-field validation.
- **Operation DAG (v0.15)**: Pipeline uses EventDrivenScheduler — 15 operations (duration/segmentation/transcription/keyframes/alignment/caption/summary/frame_encode/chunk_encode/text_encode/detection/search_encode/track_encode/face/plate) declared in `pipeline/operations.py` with gate conditions, dependencies, and labels. Each operation runs as its own asyncio task, awaiting upstream `asyncio.Event` signals. Engine filters by gate → spawns ready tasks → event-driven execution (no static batches). `topological_batches` handles missing deps gracefully. Search and summary paths are fully decoupled: `search_encode` (depends duration, gated by `not v.summary_enabled`, shares NVDEC stream with detection) runs parallel to `segmentation → keyframes → caption → summary`. `keyframes`→`frame_encode` 通过 `asyncio.Queue(512)` 生产者-消费者并发编码，`frame_encode` depends_on=["segmentation"] 与 keyframes 同批启动。Adding a new perception module only requires a new runner + one Operation entry — engine.py is never touched.
- **Summary dual-mode (v0.10)**: `summary_mode` 控制 caption+summary 路径。`native_video`（默认）→ CaptionRunner 内部路由到 Qwen3-VL-8B 本地 GPU（按需加载，用完释放），SummaryRunner 内部路由到纯 Python 聚合器。`vlm_llm` → CaptionRunner 动态切换为 Qwen-VL-Max API captioner，SummaryRunner 内部路由到 DeepSeek API。双模式切换完全封装在 runner 内部，engine.py 不感知。native_video 使用 ffmpeg 输入级 seek（-ss 在 -i 之前）精确切段，避免场景重复描述。Summary mode 变更需新建视频记录（不可增量）。
- **Multi-format support (v0.13)**: 两层处理 — remux (容器标准化, -c copy 流复制, 音频转 AAC 如需) + proxy (编码兼容, NVENC h264, 按需生成)。前端 canPlayType() 探测 HEVC 能力, 服务端 hevc_ok 智能路由。所有 format 处理异步执行不阻塞上传。Pipeline 优先读 remuxed MP4 (更好的 demux 性能)。
- **NVDEC hardware decode (v0.15)**: MJPEG pipe 输出 (~100KB/帧)，替代旧 raw NV12 (3.1MB/帧)。`stream_frames_nvdec` → FFmpeg `fps + scale_cuda + hwdownload + mjpeg` → asyncio pipe → JPEG parse → RGB ndarray。默认启用 (pipeline.use_nvdec: true)，不可用时自动 fallback 到 cv2。
- **ReID 系统 (v0.20, 双层)**: 在线 ReID + 全局 tracklet 缝合。
  - **在线 ReID**: BoT-SORT `with_reid: true`, `model: "auto"` → yolo26s.pt 是 end2end Detect head，backbone hook 不可用 → fallback 到 `yolo26n-cls.pt`（ImageNet 分类特征）。`appearance_thresh: 0.6`, `track_buffer: 45`, `match_thresh: 0.5`。每帧 min(IoU距离, ReID余弦距离) 加权匹配，遮挡/交叉时保持身份。
  - **全局 tracklet 缝合** (track_encode Phase 2): detection 每 2s 缓存每 track 的 640×384 人像 crop（`VideoContext.track_crop_cache`）→ track_encode 零 FFmpeg seek 读取，挑 20%/50%/80% 附近 3 帧 → Qwen3-VL-Embedding → mean pool 成 1 个 2048-dim → cosine 相似度矩阵合并。合并条件: 同类 + sim ≥ 0.85 + 时序不重叠。时序检查用 segments 真实检测片段，`MAX_OVERLAP_SEC=1.0` + `HIGH_SIM_OVERRIDE=0.90` 容忍镜头缩放/切换/遮挡边缘的短暂双跟踪伪影。由 L3 `track_stitch_enabled` 控制，完成后修改需新建记录。
- **Encoder presets (v0.15)**: 三档速度预设控制编码分辨率+批大小 — fast (336×224, batch=512) / balanced (504×336, batch=512, default) / precise (672×448, batch=256)。逐视频通过 `encode_profile` 参数选择，全局默认在 config.yaml `pipeline.default_encode_profile`。前端参数面板 L4 "处理速度" 控件 + Settings 页 Pipeline 调优展示。
- **Performance optimizations (v0.15)**: Embedder 编码分辨率可配置（encode_width×encode_height，三档预设: fast 336×224 / balanced 504×336 / precise 672×448，默认 balanced）。PIL resize 8 线程并行。_pool_last_token 逐行 L2 归一化 + float32 输出。Detection 帧缩放到 640×384。Detection fps 10, batch_size 128, 生产者-消费者并发。Long video (>30min) 自动 time-based 分段。NVDEC 硬件解码默认启用（MJPEG pipe ~100KB/帧，自动 fallback cv2）。keyframes→frame_encode 通过 asyncio.Queue 生产者-消费者并发。encode_batch_size 512（120GB VRAM）。Captioner 按需加载。
- **Incremental processing**: Completed videos can re-run summary or search index independently via `run_incremental()`. Non-L3 param changes (including summary_mode) require creating a new video record (reuse file via `POST /videos/reuse`).

## Database Tables (12)

| Table | Key Columns | Purpose |
|---|---|---|
| `video_groups` | id(UUID PK), name, created_at, updated_at | 视频分组 — 批量上传时自动创建，组内单个视频删除自动清理空组 |
| `videos` | id, status, progress, status_detail, summary(JSONB), content_type, summary_mode (native_video/vlm_llm), perception switches (vision/audio/ocr/grounding/caption/detection_enabled/summary_enabled), function switches (search_index_enabled, **track_stitch_enabled**), advanced params (sample_fps, segment_threshold, caption_with_context, summary_detail, encode_profile), language, format fields (container_format, video_codec, audio_codec, has_audio, remuxed_path, proxy_path, proxy_status, proxy_progress), **group_id(UUID FK → video_groups.id)** | Video master |
| `scenes` | id, video_id(FK), scene_index, text_embedding(Vector2048), caption, ocr_text, aligned_transcript, entities(JSONB) | Core search grain (text_embedding = caption+ocr+transcript 语义) |
| `transcripts` | id, video_id(FK, UNIQUE), full_text, words(JSONB) | Speech transcripts |
| `frame_embeddings` | id, video_id(FK), timestamp_sec, embedding(Vector2048), is_keyframe | 1fps frame vectors |
| `chunks` | id, video_id(FK), chunk_index, start_sec, end_sec, embedding(Vector2048) | Sliding window vectors |
| `frame_detections` | id, video_id(FK), track_id, timestamp_sec, class_name, confidence, bbox(JSONB) | Per-frame YOLO detection results (10fps, indexed by timestamp) |
| `tracks` | id, video_id(FK), track_id, class_name, first_seen, last_seen, frame_count, segments(JSONB) | BoT-SORT cross-frame track summaries |
| `track_embeddings` | id, video_id(FK), track_id, class_name, embedding(Vector2048), timestamp_sec, bbox(JSONB) | Track crop cross-modal vectors, for track-path search |
| `face_identities` | id, video_id(FK), identity_label, face_embedding(Vector512), face_count, first_seen, last_seen, avg_quality, best_face_bbox(JSONB) | Clustered face identities (ArcFace R50 512d), "人物 A/B/C..." |
| `face_detections` | id, video_id(FK), identity_id(FK), track_id, timestamp_sec, bbox(JSONB), quality_score, face_embedding(Vector512) | Per-frame face detections, linked to YOLO person tracks |
| `plate_detections` | id, video_id(FK), track_id, class_name, timestamp_sec, plate_text, plate_type, char_confidences(JSONB), bbox(JSONB), detection_confidence | HyperLPR3 license plate recognition results (per-vehicle-track, pre-ReID merge) |

## Current Implementation Status

| Area | Status | Files |
|---|---|---|
| Pipeline core (DAG) | ✅ Complete (EventDrivenScheduler v0.10) | engine.py, operations.py, runners/* (15 ops) |
| Frame/Chunk/Text encoding | ✅ Complete | runners/frame_encode, chunk_encode, text_encode |
| Object Detection + Tracking | ✅ Complete | plugins/detector/yolo.py, runners/detection.py, api/detection_routes.py, DetectionOverlay.tsx |
| Track Encoding (crop→embed) | ✅ Complete | runners/track_encode.py — 读检测缓存多帧 640×384 crop → mean pool → Qwen3-VL-Embedding 2048-dim（零 FFmpeg seek）|
| Global ReID Tracklet Stitch | ✅ Complete | track_encode Phase 2 — cosine ≥ 0.85 + 同类 + 时序不重叠（segments 真实片段, 容忍 ≤1s 双跟踪伪影）；L3 track_stitch_enabled 开关；合并更新 tracks/frame_detections/track_embeddings |
| Semantic search (7-path) | ✅ Verified | search_engine.py + api/search_routes.py (frame+chunk+text+label+track+plate+image) |
| Captioner (local GPU + API) | ✅ Verified | plugins/captioner/qwen25_vl_captioner.py + qwen_api_captioner.py |
| Embedder (local GPU) | ✅ Verified | plugins/embedder/qwen_vl_embedder.py — preloaded at startup, shared via app.state.embedder |
| Summarizer (aggregator + API) | ✅ Verified | runners/summary.py dual-path: Python aggregator (default) + vllm_summarizer.py (vlm_llm fallback) |
| Segmenter (TransNetV2) | ✅ Verified | plugins/segmenter/transnet_v2.py |
| Segmenter (time-based) | ✅ Verified | plugins/segmenter/time_based.py |
| Transcriber (faster-whisper) | ✅ Plugin ready | plugins/transcriber/faster_whisper.py |
| DB + migrations | ✅ Done | db.py, models.py, init_db() |
| Prompt templates | ✅ Done | config/prompts.yaml |
| Pipeline real-time status | ✅ Done | status_tracker.py with dynamic weight allocation + sub_progress per-operation interpolation |
| Parameter system (4-level) | ✅ Done | core/schemas.py PipelineParams + model_validator; core/schemas.py PipelineParams; frontend ParameterPanel with cascade |
| Incremental processing | ✅ Done | pipeline/engine.py run_incremental(); services/video_service.py incremental_process() |
| Settings API + API key mgmt | ✅ Done | core/settings_service.py; GET/PUT /api/v1/settings |
| Frontend dashboard | ✅ Done | Dashboard.tsx + 20 components + 8 hooks (React 19 + Tailwind 4) — 参数面板四级联动+人脸/车牌子开关, 动态 PipelineBar, 检测面板统一物体列表(车辆内联车牌)+人脸切换, Canvas bbox 渲染(物体框+人脸虚线), 时间轴人脸标记点, 人脸图片搜索(👤按钮), 系统设置页, 历史记录搜索, 元数据卡片, 导出菜单 |
| Object Detection + Tracking | ✅ Done | plugins/detector/yolo.py — YOLO11s + BoT-SORT, dual-gate control, 10fps 默认, 生产者-消费者并发 + 单 NVDEC 流共享, frontend DetectionOverlay |
| Track search path | ✅ Done | core/search.py track_vector_search + search_engine.py _track_search — encode_text(query) vs track crop embeddings, 返回具体物体 |
| Face Recognition | ✅ Done | plugins/face/insightface_face.py — InsightFace SCRFD + ArcFace R50 (512d), FaceRunner identity clustering with label→DB ID mapping |
| License Plate Recognition | ✅ Done | plugins/plate/hyperlpr_plate.py — HyperLPR3 detection + text recognition (paddle_plate.py alternative), PlateRunner |
| Face Image Search | ✅ Done | POST /api/v1/search/face — upload image → ArcFace 512d → face_identities cosine match |
| Universal Image Search | ✅ Done | POST /api/v1/search/image — 上传任意图片 → Qwen3-VL-Embedding 2048-dim → frame_embeddings 余弦匹配。专用 search_image_only() 路径：帧不聚类、不补 scene 信息，每帧独立精确到秒 |
| Frontend Chinese Labels | ✅ Done | frontend/src/labels.ts 统一映射中心, zh()/zhLabel()/colorOf() 取代 3份重复 CLASS_COLORS, DetectionPanel/Overlay/Timeline/VideoSearchCard/ParameterPanel 改为中文展示 |
| Plate Text Search | ✅ Done | core/search.py plate_text_search — Levenshtein 编辑距离 + ILIKE 子串匹配 |
| Video Metadata Extraction | ✅ Done | utils/metadata.py — 三级提取 (pymediainfo → exiftool → ffprobe), GPS/device/codec |
| Clip Export | ✅ Done | services/export_service.py + api/export_routes.py — 流复制视频片段导出 |
| Frames/Thumbnails Export | ✅ Done | 帧序列 zip / 全部场景缩略图 zip 导出 |
| Track Segments Export | ✅ Done | 按 segments 字段分段导出 track 视频 → zip |
| Track Thumbnail Download | ✅ Done | 全尺寸物体裁剪图下载 |
| Multi-format Support (v0.13) | ✅ Done | services/format_service.py — remux + lazy proxy; api/video_routes.py — stream智能路由 + proxy-status; frontend — hevcOk探测 + streamReady |
| Performance Optimizations (v0.15) | ✅ Done | embedder 可配置 336-672×224-448 (三档预设); PIL resize 8线程并行; NVDEC MJPEG pipe 默认启用; keyframes→frame_encode 生产者-消费者并发; float32 输出; batch_size 512 |
| Multi-Video Group (v0.19) | ✅ Done | core/models.py VideoGroup ORM; api/video_routes.py POST /videos/upload/batch (并发处理, 信号量5); 组参数同步启动同组所有 pending 视频; frontend 分组历史卡片(堆叠/展开/CSS transition), Header 组切换下拉, 搜索范围选择器(当前/组内/全部), DetectionPanel 独立视频选择器, 搜索结果跨视频跳转; summary one_liner 时间轴格式 |
| OCR | ⬜ Shell only | plugins/ocr/ |
| Grounding | ⬜ Shell only | plugins/grounding/ |
| Health/Reindex | ⬜ Shell only | api/maintenance_routes.py |

## Agent Instructions

> Read this section last. It tells you how to behave in this project.

1. **Don't modify `.env`** — it contains API keys and is gitignored.
2. **Don't delete empty `__init__.py` files** — they're intentional package markers.
3. **Don't delete empty route/service files** (`api/maintenance_routes.py`) — it's a planned stub for future endpoints. `api/export_routes.py` was a stub but is now active (7 endpoints for clip/frames/track/thumbnails). `api/video_routes.py` and `api/search_routes.py` are active route files, NOT stubs.
4. **Config-driven design + operation registration**: when adding a new perception module, write a runner class in `pipeline/runners/`, add one `Operation(...)` entry to `pipeline/operations.py` `ALL_OPERATIONS`. For new plugin backends, register in `plugins/factory.py` `CATEGORY_MAP` / `_MODULE_OVERRIDES` / `_CLASS_OVERRIDES`. No hardcoded model references in business logic.
5. **Sync vs Async**: all `core/interfaces.py` methods are `async def`. If your plugin runs synchronous model inference, wrap it with `asyncio.to_thread()`. Never call `model.predict()` directly in an async function.
6. **Search paths**: `config_loader.py` and `prompt_loader.py` use `Path(__file__).resolve().parent.parent` to locate the project root. Keep this convention.
7. **Vector dimension**: 2048. All vector columns (scenes.text_embedding, frame_embeddings.embedding, chunks.embedding, track_embeddings.embedding) use `Vector(2048)`. Face embeddings use `Vector(512)` (ArcFace R50). No pgvector HNSW/IVFFlat index (2048 > 2000 limit, but full scan is fine for demo scale).
8. **Four encoding paths**: Frame (encode_image), Chunk (config-gated, default disabled, -c copy + encode_video), Text (encode_text). All three reuse the shared embedder.
9. **When adding new dependencies**: add to `requirements.txt` AND to `Dockerfile`.
10. **Search result format**: All results include `precision_level` (frame/chunk/text/label), `precise_start/end` (text 也有 scene 起止作为锚点), `match_paths`, and `thumbnail_url`. Merge 时帧簇优先，text 与非重叠帧的 text 按路径权重排序。图搜使用独立 `search_image_only()` 路径：帧不做时间聚类、不补充 scene 信息，`precise_end=None` 表示单帧精确匹配。
11. **Frontend**: Dashboard.tsx (~430 lines) orchestrates all state (including v0.19 group state: videoGroups, currentGroupVideos, detectionVideoId, headerDropdownOpen) and renders imported components from `components/`. Component files (20 files): icons, Sidebar, Header, SlideOutPanel, ParameterPanel, PipelineBar, VideoSection, VideoPlayer, VideoSummaryCard, VideoSearchCard, DetectionPanel, DetectionTimeline, HistoryPanelContent, SettingsPage, DetectionOverlay, VideoInfoCard, ExportMenu, RightPanel. Hooks are in `hooks/` (8 files: useDetectionData/HEVCCapability/ParameterForm/ProxyStatus/Search/StreamReady/VideoPolling). Label/color mapping in `labels.ts` (80 COCO classes zh/zhLabel/colorOf). Utility functions in `utils/helpers.ts`. TypeScript types in `types/index.ts` mirror backend Pydantic schemas.
12. **Detection gate pattern**: New perception modules that are optional should follow the dual-gate pattern: config-level enable/disable (`plugins.{name}.backend: yolo` vs `null`) AND per-video toggle (`detection_enabled` in PipelineParams). Gate function checks both. This allows server-wide opt-out while letting users control per-video.
13. **Canvas overlay pattern**: The DetectionOverlay uses a `canvas` with `pointerEvents: "none"` for pure rendering, with click/mousemove handlers attached via native `addEventListener` to the parent container. This allows clicks to pass through to video controls while still enabling bbox interaction.
14. **Video format handling (v0.13)**: Video format processing is TWO-LAYER — remux (container standardization, `-c copy` stream copy, audio → AAC if needed) and proxy (codec compatibility, NVENC H.264, lazy on-demand). Probe is synchronous during upload (<100ms). Remux and proxy are async (asyncio.create_task). Stream endpoint routes via `FormatService.get_stream_target(video_id, hevc_ok)`. Frontend detects HEVC support via `canPlayType()` and passes `hevc_ok` query param. Proxy is NEVER eager-generated — only triggered when a non-HEVC client requests the video.
15. **cv2/sync C calls MUST use asyncio.to_thread()**: All cv2 operations (VideoCapture.read, cvtColor, etc.) and other synchronous C calls that take >1ms MUST be wrapped in `asyncio.to_thread()`. This prevents event loop blocking and ensures other asyncio tasks can be scheduled. The keyframe runner's cv2 read loop is the canonical example.
16. **Embedder encode resolution**: 编码分辨率可配置（`config.yaml` `plugins.embedder.params.encode_width/encode_height` 或 `pipeline.encode_profiles`）。默认 balanced: 504×336（~160 vision tokens）。fast: 336×224, precise: 672×448。`encode_images_batch` 支持 per-call `target_size` 覆盖。PIL resize 8 线程并行 + NVDEC `scale_cuda` GPU 缩放，embedder 与 stream decode 分辨率始终保持一致。

## Python Environment

- Python 3.13
- FastAPI, SQLAlchemy async, asyncpg, pgvector
- transformers, torch (CUDA 12.4), modelscope, qwen-vl-utils
- openai, httpx, Pillow
- pytest, pytest-asyncio
