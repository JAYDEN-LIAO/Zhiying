# Cerno — Universal Video Analytics Engine

A general-purpose video analytics engine for semantic search and structured summarization. Designed for single-GPU setups (8–32 GB VRAM).

## Quick Start

```bash
# 1. Start database
docker-compose up -d db

# 2. Set API keys (only needed for vlm_llm summary mode)
set DASHSCOPE_API_KEY=sk-xxx   # Qwen-VL API (vlm_llm captioning)
set DEEPSEEK_API_KEY=sk-xxx    # LLM summarizer (vlm_llm mode)

# 3. Start backend server
uvicorn main:app --reload

# 4. (New tab) Start frontend dev server
cd frontend && npm install && npm run dev

# 5. Upload a video via curl
curl -X POST -F "file=@demo.mp4" http://localhost:8000/api/v1/videos/upload

# 6. Get summary
curl http://localhost:8000/api/v1/videos/{video_id}

# 7. Semantic search
curl -X POST -H "Content-Type: application/json" \
  -d '{"query":"a man in black"}' \
  http://localhost:8000/api/v1/search/semantic
```

> **Note on API Keys**: Place keys in a `.env` file at project root (gitignored).  
> Keys are only required when using the `vlm_llm` summary mode; the default `native_video` mode runs entirely on local GPU.

## Core Features

| Feature | Endpoint | Status |
|---|---|---|
| Video Upload & Pipeline | `POST /api/v1/videos/upload` + `PUT /videos/{id}/params` | ✅ |
| Video Detail + Summary | `GET /api/v1/videos/{id}` | ✅ |
| Processing Status | `GET /api/v1/videos/{id}/status` | ✅ |
| Video Streaming (Range) | `GET /api/v1/videos/{id}/stream` | ✅ |
| Scene Thumbnail | `GET /api/v1/videos/{id}/thumbnail/{scene_index}` | ✅ |
| Video List | `GET /api/v1/videos/` | ✅ |
| Video Delete | `DELETE /api/v1/videos/{id}` | ✅ |
| Parameter Configuration | `PUT /api/v1/videos/{id}/params` | ✅ |
| Video Reuse (same file) | `POST /api/v1/videos/reuse` | ✅ |
| Video Metadata | `GET /api/v1/videos/{id}/metadata` | ✅ |
| Multi-Format Video Support | Remux + Lazy H.264 Proxy (NVENC) + smart stream routing | ✅ |
| Semantic Search (6-path: frame+chunk+text+label+track+plate) | `POST /api/v1/search/semantic` | ✅ |
| Object Detection + Tracking | YOLO11s + BoT-SORT (10fps, batch128, 640px) + Canvas overlay | ✅ |
| Face Recognition | SCRFD + ArcFace R50 (512d) identity clustering | ✅ |
| License Plate Recognition | HyperLPR3 (ONNX Runtime) detection + text recognition | ✅ |
| Face Image Search | `POST /api/v1/search/face` (upload image → ArcFace 512d) | ✅ |
| Plate Text Search | `POST /api/v1/search/semantic` (plate path, Levenshtein + ILIKE) | ✅ |
| Track Thumbnail Download | `GET /api/v1/videos/{id}/export/track/{tid}/thumbnail` | ✅ |
| Track Video Export (zip) | `GET/POST /api/v1/videos/{id}/export/track/{tid}` | ✅ |
| Video Clip Export | `GET/POST /api/v1/videos/{id}/export/clip` | ✅ |
| Scene Thumbnails Export (zip) | `GET/POST /api/v1/videos/{id}/export/thumbnails` | ✅ |
| System Settings (API keys + Pipeline) | `GET/PUT /api/v1/settings` + `GET /api/v1/settings/pipeline` | ✅ |
| Frontend Dashboard | React 19 + Vite + Tailwind CSS 4 (unified objects view + face toggle) | ✅ |
| Track Crop Embedding (track search) | `POST /api/v1/search/semantic` (track path) | ✅ |
| Incremental Processing | summary/search re-run on completed videos | ✅ |

## Architecture Overview

```
Upload → Pipeline (DAG) → DB → Search → Frontend
         ├─ Duration detection (ffprobe)
         ├─ [搜索路径]  Search Encode @1fps — 与 detection 共享 NVDEC 流 (队列消费)
         ├─ [摘要路径]  Scene Segmentation (TransNetV2) + Audio Transcription (faster-whisper)
         │    ├─ Keyframe Extraction @1fps (NVDEC MJPEG pipe / cv2 stream)
         │    ├─ Captioning — 双模式 (runners/caption.py 内部策略):
         │    │    ├─ native_video (默认): Qwen3-VL-8B 本地 GPU → 结构化 JSON
         │    │    └─ vlm_llm (备选): Qwen-VL-Max API 看图说话
         │    └─ Summarization — 双模式 (runners/summary.py 内部策略)
         ├─ Object Detection — YOLO11s + BoT-SORT (可选，双门控):
         │    └─ 逐帧检测 → 跨帧追踪 → 前端 Canvas 框选
         ├─ Embedding — 4 encoding paths (分辨率可配置, 3-档预设):
         │    ├─ Frame-level: search_encode 自抽帧 + frame_encode 队列消费 (1fps, per-frame)
         │    ├─ Chunk-level: encode_video (sliding window, 默认关闭, 需摘要)
         │    ├─ Text-level: encode_text(caption+ocr+transcript, 需摘要)
         │    └─ Track-level: encode_image(crop) (cross-modal, track search)
         ├─ Face Recognition (可选 — 三门控: config + detection_enabled + face_enabled):
         │    └─ Person crop → SCRFD detect → ArcFace R50 512d embed → identity clustering
         ├─ License Plate (可选 — 三门控: config + detection_enabled + plate_enabled):
         │    └─ Vehicle crop → HyperLPR3 detect + recognize → plate text + type + confidence
         └─ Shared GPU models (embedder 启动时预加载; captioner 按需加载):
              ├─ Qwen3-VL-Embedding-8B (embedder, FP16, ~16GB, preloaded)
              ├─ Qwen3-VL-8B-Instruct (captioner, BF16, ~16GB, on-demand)
              └─ SCRFD + ArcFace R50 (face recognizer, ONNX, preloaded)
```

- **Declarative pipeline** orchestrated by `PipelineEngine` (DAG executor), with 4-path frame/chunk/text/track encoding + face recognition + license plate recognition (15 operations total). Search and summary paths fully decoupled — `search_encode` (gated by `not v.summary_enabled`) shares a single NVDEC stream with `detection` (detection pushes 1fps sampled frames to search queue, search_encode encodes in batches of 64). Producer-consumer pattern (`asyncio.Queue`) for frame extraction vs YOLO inference overlap. NVDEC MJPEG pipe for GPU-accelerated frame extraction.
- **10 abstract plugin interfaces** with dynamic factory loading
- **PostgreSQL + pgvector** with 11 tables: videos, scenes, transcripts, frame_embeddings, chunks, frame_detections, tracks, track_embeddings, face_identities, face_detections, plate_detections
- **6-path parallel semantic search**: frame (1fps precision) + chunk (process semantics) + text (caption+ocr+transcript semantics) + label (JSONB @> entities) + track (crop cross-modal embedding) + plate (Levenshtein + ILIKE); **face image search**: POST /search/face (upload image → ArcFace 512d identity matching)
- **4-level parameter system**: Scene Type → Perception Modules → Function Switches → Advanced Params (含 encode_profile 速度预设: fast/balanced/precise), with face/plate sub-switches under detection
- **Multi-format video support** — two-layer: container remux (-c copy, instant) + codec proxy (NVENC H.264, lazy on-demand). Frontend canPlayType() HEVC detection + smart stream routing (hevc_ok param). Probe sync (<100ms), remux/proxy async — upload never blocked.
- **Pipeline real-time status** — each phase writes human-readable progress descriptions (`status_detail`) to the database, displayed in the frontend in real time
- **React frontend** with video player, pipeline progress bar with real-time status details, semantic search with thumbnail results, 4-level parameter panel (含速度预设), summary mode selector, and settings page (含 Pipeline 调优)
- **Export API** — clip export (stream copy), frame export (zip), track segment export (zip), scene thumbnail export (zip), track thumbnail download
- **Video metadata extraction** — three-tier extraction (pymediainfo → exiftool → ffprobe), GPS/device/codec info via GET /metadata endpoint

## Tech Stack

| Component | Technology |
|---|---|
| Backend Framework | FastAPI (Python 3.13) |
| Frontend Framework | React 19 + TypeScript |
| Build Tool | Vite 6 |
| CSS | Tailwind CSS 4 |
| Database | PostgreSQL 17 + pgvector 0.8 |
| Vector Embedding | Qwen3-VL-Embedding-8B (local GPU) |
| Object Detection | YOLO11s (local GPU) |
| Object Tracking | BoT-SORT (motion-only with_reid=false, 10fps, track_buffer=120, match_thresh=0.4) |
| Captioning | Qwen3-VL-8B (local GPU, default) / Qwen-VL-Max (API, vlm_llm mode) |
| Summarization | Pure Python aggregator (default) / DeepSeek Chat (API, vlm_llm mode) |
| Scene Segmentation | TransNetV2 / Time-based (fixed interval) |
| Audio Transcription | faster-whisper (plugin ready, opt-in) |
| Video Processing | FFmpeg (asyncio subprocess) |
| Metadata Extraction | pymediainfo + exiftool (optional) |

## Project Structure

```
cerno/
├── main.py               # FastAPI entry point
├── api/                  # Route definitions
│   ├── router.py         # Route assembly (sub-routers under /api/v1)
│   ├── routes.py         # Transitional re-export
│   ├── deps.py           # FastAPI dependencies (DB session)
│   ├── schemas.py        # Shared API DTOs
│   ├── video_routes.py   # Video CRUD + upload + stream + thumbnail + metadata
│   ├── search_routes.py  # Semantic search + pipeline/operations
│   ├── settings_routes.py# System settings (API keys)
│   ├── detection_routes.py # Detection data API (bbox + track thumbnail)
│   ├── export_routes.py  # Export: clip / frames / track / thumbnails (7 endpoints)
│   ├── face_routes.py    # Face data + thumbnail endpoints
│   ├── plate_routes.py   # Plate data + thumbnail endpoints
│   └── maintenance_routes.py  # (stub) planned health/reindex endpoints
├── core/                 # DB models, schemas, search, config
│   ├── db.py             # Async engine, init_db(), incremental migration
│   ├── models.py         # ORM: Video, Scene, Transcript, FrameEmbedding, Chunk
│   ├── schemas.py        # Pydantic DTOs + JSONB validation
│   ├── repository.py     # Data access layer + bulk_insert_frames/chunks
│   ├── search.py         # 4 search functions: frame/chunk/text/track
│   ├── interfaces.py     # 10 abstract plugin base classes
│   ├── config_loader.py  # YAML + .env loading with env var overrides
│   ├── prompt_loader.py  # Prompt template loader
│   ├── status_tracker.py # Pipeline progress persistence
│   ├── settings_service.py # API key management (settings.json backed)
│   └── exceptions.py     # Custom exceptions
├── config/               # Configuration
│   ├── config.yaml       # Main config (server/db/storage/plugins/pipeline)
│   ├── config_schema.py  # Pydantic config validation
│   └── prompts.yaml      # Caption/Summarizer/Grounding prompt templates
├── pipeline/             # Pipeline DAG orchestrator + runners
│   ├── engine.py         # DAG executor: gate filter → EventDrivenScheduler
│   ├── operations.py     # Operation registry: ALL_OPERATIONS with gates/deps/labels
│   ├── runners/          # 15 operation runners (one per processing unit)
│   │   ├── duration.py, segmentation.py, transcription.py
│   │   ├── keyframe.py, alignment.py, caption.py, summary.py
│   │   ├── detection.py (YOLO11 + BoT-SORT)
│   │   ├── frame_encode.py, chunk_encode.py, text_encode.py
│   │   └── plate.py
│   └── search_engine.py  # 6-path parallel recall (frame+chunk+text+label+track+plate) + scene-merge dedup
├── plugins/              # Plugin implementations + factory
│   ├── factory.py        # Dynamic plugin loader
│   ├── captioner/        # Qwen3VL captioner (local GPU) + Qwen API captioner
│   ├── embedder/         # Qwen3-VL-Embedding (local GPU)
│   ├── summarizer/       # DeepSeek API
│   ├── segmenter/        # TransNetV2 / Time-based
│   ├── transcriber/      # faster-whisper
│   ├── detector/         # YOLO11s + BoT-SORT
│   ├── face/             # InsightFace SCRFD + ArcFace R50
│   ├── plate/            # HyperLPR3 (primary) / PaddleOCR (alternative)
│   ├── ocr/              # (stub) PaddleOCR
│   └── grounding/        # (stub) Florence-2
├── services/             # Business logic layer
│   ├── video_service.py  # Video processing orchestration
│   ├── format_service.py # Multi-format support (probe/remux/proxy, lazy on-demand)
│   └── export_service.py # Export business logic (clip/frames/track/thumbnails)
├── utils/                # FFmpeg tools + metadata extraction
│   ├── video_util.py     # FFmpeg subprocess helpers (extract audio/keyframes/duration)
│   └── metadata.py       # Video metadata extraction (pymediainfo/exiftool/ffprobe)
├── frontend/             # React + Vite + Tailwind dashboard
│   ├── public/
│   │   └── cerno.svg     # App logo
│   ├── src/
│   │   ├── Dashboard.tsx # Main workspace (~400 lines, orchestrates state + render)
│   │   ├── components/   # Extracted UI components
│   │   │   ├── icons.tsx, LeftSidebar.tsx, ParameterPanel.tsx
│   │   │   ├── PipelineBar.tsx, VideoSummaryCard.tsx, VideoSearchCard.tsx
│   │   │   ├── HistoryPanelContent.tsx, SettingsPage.tsx
│   │   │   ├── DetectionOverlay.tsx, DetectionPanel.tsx, DetectionTimeline.tsx
│   │   │   ├── MetadataPanel.tsx, ExportMenu.tsx
│   │   ├── utils/helpers.ts  # Shared helpers
│   │   ├── services/api.ts
│   │   ├── types/index.ts
│   │   └── mockData.ts   # Pipeline stage definitions + computePipelineStages()
│   ├── package.json
│   └── vite.config.ts
├── models/               # Local model weights (gitignored)
├── data/                 # Video storage & artifacts (gitignored)
├── config/               # YAML config, prompts, schema
├── tests/                # Test suite (30+ test files)
└── docs/                 # Design documents + search architecture docs
```

## Development Status

- **v0.16 — Single NVDEC stream + Performance**: 单 NVDEC 流供 detection 与 search_encode 共享（detection 推送 1fps 采样帧到队列，search_encode 64 帧即编）；生产者-消费者并发（帧提取与 YOLO 推理重叠）；移除全局 ReID（质量差、开销高）；移除以 track 为单位的 FFmpeg fallback 抽帧（替换为直接使用 cache 帧，track_encode 耗时从 257s→43s）；BoT-SORT 调参（new_track_thresh=0.4, match_thresh=0.4）；detection 默认帧率 10fps。
- **v0.16 — Single NVDEC stream + Performance + Speed Presets**: `keyframes`→`frame_encode` 生产者-消费者并发 (asyncio.Queue); `search_encode` gate 修复防双编码; NVDEC MJPEG pipe (~100KB/帧) 默认启用; embedder `_pool_last_token` 逐行 L2 归一化 + float32 + PIL resize 8线程并行; batch_size 512; 三档速度预设 (fast/balanced/precise) 控制分辨率 336-672; 前端 "处理速度" 控件 + Pipeline 调优 Settings 页; `GET /api/v1/settings/pipeline`。
- **v0.14 — Search/Summary Decoupling + Preload**: Search and summary paths fully decoupled — new `search_encode` operation (self-extracting frames @1fps + batch encoding) runs parallel to summary pipeline, depends only on duration. Captioner preloaded at startup alongside embedder (shared instances, no per-pipeline load/unload). Configurable encode batch size (pipeline.encode_batch_size). NVDEC hardware decoding support (optional, pipeline.use_nvdec). 15 operations, 11 DB tables, 10 plugin ABCs.
- **v0.10 — Track encoding + crop embedding**: TrackEncodeRunner (最佳帧 crop + Qwen3-VL-Embedding 2048-dim). 5-path semantic search (frame+chunk+text+label+track). track 搜索独立去重, 返回具体物体 (class_name#id + crop 缩略图). EventDrivenScheduler: 异步事件驱动替代拓扑分批.
- **v0.9 — YOLO detection + tracking**: YOLO11s + BoT-SORT (10fps 独立帧率, dual-gate). 前端 DetectionOverlay (Canvas bbox + 插值 + 拖尾) + DetectionPanel (物体列表 + 分类筛选) + DetectionTimeline (时间轴 + 播放头 + 选中滚动). demo 验证通过.
- **v0.8 — DAG architecture refactor**: 声明式操作 DAG 引擎 (11 operations + gate-driven orchestration). 操作注册表 (pipeline/operations.py) + runners 目录. StatusTracker 动态权重. API 路由拆分. QC 模块移除.
- **v0.7 — Summary architecture overhaul**: 双模式摘要系统 — native_video (Qwen2.5-VL-7B 本地 GPU 原生视频理解 + 纯 Python 聚合) / vlm_llm (传统 VLM+LLM, API 驱动). 前端 summary_mode 选择器. Embedder 全局共享.
- **v0.6 — Search architecture consolidation**: 3-path semantic search (frame+text+chunk), 废弃全文/混合/模糊检索, encode_text 扩大至 caption+ocr+transcript, 路径感知排序.
- **Planned**: Grounding (Florence-2), Health/Reindex endpoints
