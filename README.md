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
| Object Detection + Tracking | YOLO11s + BoT-SORT (8fps, batch128, 640px) + Canvas overlay | ✅ |
| Face Recognition | SCRFD + ArcFace R50 (512d) identity clustering | ✅ |
| License Plate Recognition | HyperLPR3 (ONNX Runtime) detection + text recognition | ✅ |
| Face Image Search | `POST /api/v1/search/face` (upload image → ArcFace 512d) | ✅ |
| Plate Text Search | `POST /api/v1/search/semantic` (plate path, ILIKE) | ✅ |
| Track Thumbnail Download | `GET /api/v1/videos/{id}/export/track/{tid}/thumbnail` | ✅ |
| Track Video Export (zip) | `GET/POST /api/v1/videos/{id}/export/track/{tid}` | ✅ |
| Video Clip Export | `GET/POST /api/v1/videos/{id}/export/clip` | ✅ |
| Scene Thumbnails Export (zip) | `GET/POST /api/v1/videos/{id}/export/thumbnails` | ✅ |
| System Settings (API keys) | `GET/PUT /api/v1/settings` | ✅ |
| Frontend Dashboard | React 19 + Vite + Tailwind CSS 4 (unified objects view + face toggle) | ✅ |
| Track Encoding + Global ReID | `POST /api/v1/search/semantic` (track path) | ✅ |
| Incremental Processing | summary/search re-run on completed videos | ✅ |

## Architecture Overview

```
Upload → Pipeline (DAG) → DB → Search → Frontend
         ├─ Duration detection (ffprobe)
         ├─ Scene Segmentation (TransNetV2) + Audio Transcription (faster-whisper)
         ├─ Keyframe Extraction @1fps (FFmpeg pipe → memory)
         ├─ Object Detection — YOLO11s + BoT-SORT (可选，双门控):
         │    └─ 逐帧检测 → 跨帧追踪 → 前端 Canvas 框选
         ├─ Captioning — 双模式 (runners/caption.py 内部策略):
         │    ├─ native_video (默认): Qwen3-VL-8B 本地 GPU 直接观看视频 → 结构化 JSON
         │    └─ vlm_llm (备选): Qwen-VL-Max API 看图说话 → 自然语言描述
         ├─ Embedding — 4 encoding paths:
         │    ├─ Frame-level: encode_image (1fps, per-frame)
         │    ├─ Chunk-level: encode_video (sliding window, 默认关闭)
         │    ├─ Text-level: encode_text(caption+ocr+transcript)
         │    └─ Track-level: encode_image(crop) (cross-modal, track search)
         ├─ Face Recognition (可选 — 双门控: config + per-video face_enabled):
         │    └─ Person crop → SCRFD detect → ArcFace R50 512d embed → identity clustering
         ├─ License Plate (可选 — 三门控: config + detection_enabled + plate_enabled):
         │    └─ Vehicle crop → HyperLPR3 detect + recognize → plate text + type + confidence
         └─ Summarization — 双模式 (runners/summary.py 内部策略):
              ├─ native_video (默认): 纯 Python 聚合器 (Counter 频率统计, 去重)
              └─ vlm_llm (备选): DeepSeek API LLM 拼凑摘要
```

- **Declarative pipeline** orchestrated by `PipelineEngine` (DAG executor), with 4-path frame/chunk/text/track encoding + face recognition + license plate recognition (14 operations total)
- **10 abstract plugin interfaces** with dynamic factory loading
- **PostgreSQL + pgvector** with 11 tables: videos, scenes, transcripts, frame_embeddings, chunks, frame_detections, tracks, track_embeddings, face_identities, face_detections, plate_detections
- **6-path parallel semantic search**: frame (1fps precision) + chunk (process semantics) + text (caption+ocr+transcript semantics) + label (JSONB @> entities) + track (crop cross-modal embedding) + plate (ILIKE text match); **face image search**: POST /search/face (upload image → ArcFace 512d identity matching)
- **4-level parameter system**: Scene Type → Perception Modules → Function Switches → Advanced Params, with face/plate sub-switches under detection
- **Multi-format video support** — two-layer: container remux (-c copy, instant) + codec proxy (NVENC H.264, lazy on-demand). Frontend canPlayType() HEVC detection + smart stream routing (hevc_ok param). Probe sync (<100ms), remux/proxy async — upload never blocked.
- **Pipeline real-time status** — each phase writes human-readable progress descriptions (`status_detail`) to the database, displayed in the frontend in real time
- **React frontend** with video player, pipeline progress bar with real-time status details, semantic search with thumbnail results, parameter panel, summary mode selector, and settings page
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
| Object Tracking | BoT-SORT (motion-only with_reid=false, 15fps, track_buffer=120) |
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
│   ├── runners/          # 14 operation runners (one per processing unit)
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

- **v0.13 — Multi-Format Support + Performance**: Two-layer format compatibility (container remux + lazy on-demand codec proxy), HEVC-capability detection (frontend canPlayType → hevc_ok routing), DAG parallelism fixes (detection parallel to keyframes), embedder @336×224 (~10x speedup), detection 8fps/batch128/640px, long video (>30min) time-based auto-segmentation, caption skipped without summary, cv2 async threading. 14 operations, 11 DB tables (+8 Video format fields), 10 plugin ABCs.
- **v0.10 — Track encoding + Global ReID**: TrackEncodeRunner (最佳帧 crop + Qwen3-VL-Embedding 2048-dim). 全局离线 ReID 合并 (5 约束: 同类 + 时间不重叠 + 间隔≤180s + cos≥0.85 + 空间门). 5-path semantic search (frame+chunk+text+label+track). track 搜索独立去重, 返回具体物体 (class_name#id + crop 缩略图). EventDrivenScheduler: 异步事件驱动替代拓扑分批.
- **v0.9 — YOLO detection + tracking**: YOLO11s + BoT-SORT (15fps 独立帧率, dual-gate). 前端 DetectionOverlay (Canvas bbox + 插值 + 拖尾) + DetectionPanel (物体列表 + 分类筛选) + DetectionTimeline (时间轴 + 播放头 + 选中滚动). demo 验证通过.
- **v0.8 — DAG architecture refactor**: 声明式操作 DAG 引擎 (11 operations + gate-driven orchestration). 操作注册表 (pipeline/operations.py) + runners 目录. StatusTracker 动态权重. API 路由拆分. QC 模块移除.
- **v0.7 — Summary architecture overhaul**: 双模式摘要系统 — native_video (Qwen2.5-VL-7B 本地 GPU 原生视频理解 + 纯 Python 聚合) / vlm_llm (传统 VLM+LLM, API 驱动). 前端 summary_mode 选择器. Embedder 全局共享.
- **v0.6 — Search architecture consolidation**: 3-path semantic search (frame+text+chunk), 废弃全文/混合/模糊检索, encode_text 扩大至 caption+ocr+transcript, 路径感知排序.
- **Planned**: Grounding (Florence-2), Health/Reindex endpoints
