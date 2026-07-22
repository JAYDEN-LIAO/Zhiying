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
| Semantic Search (5-path: frame+chunk+text+label+track) | `POST /api/v1/search/semantic` | ✅ |
| Object Detection + Tracking | YOLO11s + BoT-SORT + Canvas overlay | ✅ |
| System Settings (API keys) | `GET/PUT /api/v1/settings` | ✅ |
| Frontend Dashboard | React 19 + Vite + Tailwind CSS 4 | ✅ |
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
         │    ├─ native_video (默认): Qwen2.5-VL-7B 本地 GPU 直接观看视频 → 结构化 JSON
         │    └─ vlm_llm (备选): Qwen-VL-Max API 看图说话 → 自然语言描述
         ├─ Embedding — 3 encoding paths:
         │    ├─ Frame-level: encode_image (1fps, per-frame)
         │    ├─ Chunk-level: encode_video (sliding window, 默认关闭)
         │    └─ Text-level: encode_text(caption+ocr+transcript)
         └─ Summarization — 双模式 (runners/summary.py 内部策略):
              ├─ native_video (默认): 纯 Python 聚合器 (Counter 频率统计, 去重)
              └─ vlm_llm (备选): DeepSeek API LLM 拼凑摘要
```

- **Declarative pipeline** orchestrated by `PipelineEngine` (DAG executor), with 4-path frame/chunk/text/track encoding
- **8 abstract plugin interfaces** with dynamic factory loading
- **PostgreSQL + pgvector** with 8 tables: videos, scenes, transcripts, frame_embeddings, chunks, frame_detections, tracks, track_embeddings
- **5-path parallel semantic search**: frame (1fps precision) + chunk (process semantics) + text (caption+ocr+transcript semantics) + label (JSONB @> entities) + track (crop cross-modal embedding, 返回具体物体)
- **Config-driven**: switch models or API providers via `config.yaml`; switch summary mode via frontend parameter panel (`summary_mode` field)
- **Pipeline real-time status** — each phase writes human-readable progress descriptions (`status_detail`) to the database, displayed in the frontend in real time
- **React frontend** with video player, pipeline progress bar with real-time status details, semantic search with thumbnail results, parameter panel, summary mode selector, and settings page

## Tech Stack

| Component | Technology |
|---|---|
| Backend Framework | FastAPI (Python 3.12) |
| Frontend Framework | React 19 + TypeScript |
| Build Tool | Vite 6 |
| CSS | Tailwind CSS 4 |
| Database | PostgreSQL 17 + pgvector 0.8 |
| Vector Embedding | Qwen3-VL-Embedding-2B (local GPU) |
| Object Detection | YOLO11s (local GPU) |
| Object Tracking | BoT-SORT (motion-only with_reid=false, 15fps, track_buffer=120) |
| Captioning | Qwen2.5-VL-7B (local GPU, default) / Qwen-VL-Max (API, vlm_llm mode) |
| Summarization | Pure Python aggregator (default) / DeepSeek Chat (API, vlm_llm mode) |
| Scene Segmentation | TransNetV2 / Time-based (fixed interval) |
| Audio Transcription | faster-whisper (plugin ready, opt-in) |
| Video Processing | FFmpeg (asyncio subprocess) |

## Project Structure

```
cerno/
├── main.py               # FastAPI entry point
├── api/                  # Route definitions
│   ├── router.py         # Route assembly (sub-routers under /api/v1)
│   ├── routes.py         # Transitional re-export
│   ├── deps.py           # FastAPI dependencies (DB session)
│   ├── schemas.py        # Shared API DTOs
│   ├── video_routes.py   # Video CRUD + upload + stream + thumbnail
│   ├── search_routes.py  # Semantic search + pipeline/operations
│   ├── settings_routes.py# System settings (API keys)
│   ├── export_routes.py  # (stub) planned export endpoints
│   └── maintenance_routes.py  # (stub) planned health/reindex endpoints
├── core/                 # DB models, schemas, search, config
│   ├── db.py             # Async engine, init_db(), incremental migration
│   ├── models.py         # ORM: Video, Scene, Transcript, FrameEmbedding, Chunk
│   ├── schemas.py        # Pydantic DTOs + JSONB validation
│   ├── repository.py     # Data access layer + bulk_insert_frames/chunks
│   ├── search.py         # 3 search functions: frame/chunk/text
│   ├── interfaces.py     # 8 abstract plugin base classes
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
│   ├── engine.py         # DAG executor: gate filter → topo sort → batch execute
│   ├── operations.py     # Operation registry: ALL_OPERATIONS with gates/deps/labels
│   ├── runners/          # 12 operation runners (one per processing unit)
│   │   ├── duration.py, segmentation.py, transcription.py
│   │   ├── keyframe.py, alignment.py, caption.py, summary.py
│   │   ├── detection.py (YOLO11 + BoT-SORT)
│   │   └── frame_encode.py, chunk_encode.py, text_encode.py
│   └── search_engine.py  # 5-path parallel recall (frame+chunk+text+label+track) + scene-merge dedup
├── plugins/              # Plugin implementations + factory
│   ├── factory.py        # Dynamic plugin loader
│   ├── captioner/        # Qwen25VL captioner (local GPU) + Qwen API captioner
│   ├── embedder/         # Qwen3-VL-Embedding (local GPU)
│   ├── summarizer/       # DeepSeek API
│   ├── segmenter/        # TransNetV2 / Time-based
│   ├── transcriber/      # faster-whisper
│   ├── detector/         # YOLO11s + BoT-SORT
│   ├── ocr/              # (stub) PaddleOCR
│   └── grounding/        # (stub) Florence-2
├── services/             # Business logic layer
│   ├── video_service.py  # Video processing orchestration
│   └── export_service.py # (stub) export logic
├── utils/                # FFmpeg tools, video utilities
├── frontend/             # React + Vite + Tailwind dashboard
│   ├── public/
│   │   └── cerno.svg     # App logo
│   ├── src/
│   │   ├── Dashboard.tsx # Main workspace (~380 lines, orchestrates state + render)
│   │   ├── components/   # Extracted UI components
│   │   │   ├── icons.tsx, LeftSidebar.tsx, ParameterPanel.tsx
│   │   │   ├── PipelineBar.tsx, VideoSummaryCard.tsx, VideoSearchCard.tsx
│   │   │   ├── HistoryPanelContent.tsx, SettingsPage.tsx
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

- **v0.10 — Track encoding + Global ReID**: TrackEncodeRunner (最佳帧 crop + Qwen3-VL-Embedding 2048-dim). 全局离线 ReID 合并 (5 约束: 同类 + 时间不重叠 + 间隔≤180s + cos≥0.85 + 空间门). 5-path semantic search (frame+chunk+text+label+track). track 搜索独立去重, 返回具体物体 (class_name#id + crop 缩略图). EventDrivenScheduler: 异步事件驱动替代拓扑分批.
- **v0.9 — YOLO detection + tracking**: YOLO11s + BoT-SORT (15fps 独立帧率, dual-gate). 前端 DetectionOverlay (Canvas bbox + 插值 + 拖尾) + DetectionPanel (物体列表 + 分类筛选) + DetectionTimeline (时间轴 + 播放头 + 选中滚动). demo 验证通过.
- **v0.8 — DAG architecture refactor**: 声明式操作 DAG 引擎 (11 operations + gate-driven orchestration). 操作注册表 (pipeline/operations.py) + runners 目录. StatusTracker 动态权重. API 路由拆分. QC 模块移除.
- **v0.7 — Summary architecture overhaul**: 双模式摘要系统 — native_video (Qwen2.5-VL-7B 本地 GPU 原生视频理解 + 纯 Python 聚合) / vlm_llm (传统 VLM+LLM, API 驱动). 前端 summary_mode 选择器. Embedder 全局共享.
- **v0.6 — Search architecture consolidation**: 3-path semantic search (frame+text+chunk), 废弃全文/混合/模糊检索, encode_text 扩大至 caption+ocr+transcript, 路径感知排序.
- **Planned**: OCR (PaddleOCR), Grounding (Florence-2), Export APIs (clip/JSON/Markdown)
