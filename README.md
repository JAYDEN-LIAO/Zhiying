# Cerno — Universal Video Analytics Engine

A general-purpose video analytics engine for semantic search and structured summarization. Designed for single-GPU setups (8–32 GB VRAM).

## Quick Start

```bash
# 1. Start database
docker-compose up -d db

# 2. Set API keys
set DASHSCOPE_API_KEY=sk-xxx   # Qwen-VL for captioning
set DEEPSEEK_API_KEY=sk-xxx    # for summarization

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
> See `.env.example` or `core/config_loader.py` for details.

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
| Semantic Search (3-path) | `POST /api/v1/search/semantic` | ✅ |
| System Settings (API keys) | `GET/PUT /api/v1/settings` | ✅ |
| Frontend Dashboard | React 19 + Vite + Tailwind CSS 4 | ✅ |
| Incremental Processing | summary/search re-run on completed videos | ✅ |

## Architecture Overview

```
Upload → Pipeline → DB → Search → Frontend
         ├─ QC + Scene Segmentation (TransNetV2)
         ├─ Keyframe Extraction @1fps (FFmpeg pipe → memory)
         ├─ VLM Captioning (API)
         ├─ Embedding — 3 encoding paths:
         │    ├─ Frame-level: encode_image (1fps, per-frame)
         │    ├─ Chunk-level: encode_video (sliding window)
         │    └─ Text-level: encode_text(caption+ocr+transcript)
         └─ LLM Summarization (API)
```

- **5-stage pipeline** orchestrated by `PipelineEngine`, with 3-path frame/chunk/text encoding
- **9 abstract plugin interfaces** with dynamic factory loading
- **PostgreSQL + pgvector** with 5 tables: videos, scenes, transcripts, frame_embeddings, chunks
- **3-path parallel semantic search**: frame (1fps precision) + chunk (process semantics) + text (caption+ocr+transcript semantics). label (JSONB) 预留等待 YOLO 接入
- **Config-driven**: switch models or API providers via `config.yaml`
- **Pipeline real-time status** — each phase writes human-readable progress descriptions (`status_detail`) to the database, displayed in the frontend in real time
- **React frontend** with video player, pipeline progress bar with real-time status details, semantic search with thumbnail results, parameter panel, and settings page

## Tech Stack

| Component | Technology |
|---|---|
| Backend Framework | FastAPI (Python 3.12) |
| Frontend Framework | React 19 + TypeScript |
| Build Tool | Vite 6 |
| CSS | Tailwind CSS 4 |
| Database | PostgreSQL 17 + pgvector 0.8 |
| Vector Embedding | Qwen3-VL-Embedding-2B (local GPU) |
| Captioning | Qwen-VL-Max (DashScope API) |
| Summarization | DeepSeek Chat (API) |
| Scene Segmentation | TransNetV2 / Time-based (fixed interval) |
| Audio Transcription | faster-whisper (plugin ready, opt-in) |
| Video Processing | FFmpeg (asyncio subprocess) |

## Project Structure

```
cerno/
├── main.py               # FastAPI entry point
├── api/                  # Route definitions
│   ├── router.py         # Route assembly (re-exports from routes.py)
│   ├── routes.py         # All API endpoints (video CRUD, search, upload)
│   ├── deps.py           # FastAPI dependencies (DB session)
│   ├── video_routes.py   # (stub) future video route extraction
│   ├── search_routes.py  # (stub) future search route extraction
│   ├── export_routes.py  # (stub) planned export endpoints
│   └── maintenance_routes.py  # (stub) planned health/reindex endpoints
├── core/                 # DB models, schemas, search, config
│   ├── db.py             # Async engine, init_db(), incremental migration
│   ├── models.py         # ORM: Video, Scene, Transcript, FrameEmbedding, Chunk
│   ├── schemas.py        # Pydantic DTOs + JSONB validation
│   ├── repository.py     # Data access layer + bulk_insert_frames/chunks
│   ├── search.py         # 3 search functions: frame/chunk/text
│   ├── interfaces.py     # 9 abstract plugin base classes
│   ├── config_loader.py  # YAML + .env loading with env var overrides
│   ├── prompt_loader.py  # Prompt template loader
│   ├── status_tracker.py # Pipeline progress persistence
│   └── exceptions.py     # Custom exceptions
├── config/               # Configuration
│   ├── config.yaml       # Main config (server/db/storage/plugins/pipeline)
│   ├── config_schema.py  # Pydantic config validation
│   └── prompts.yaml      # Caption/Summarizer/Grounding prompt templates
├── pipeline/             # Pipeline orchestrator + phases
│   ├── engine.py         # 5-stage PipelineEngine + 3-path encoding
│   ├── phase1_qc.py      # QC + segmentation
│   ├── phase3_alignment.py
│   ├── phase4_caption.py # Caption + embed
│   ├── phase5_summary.py # LLM summarization
│   └── search_engine.py  # 3-path parallel recall (frame+chunk+text) + scene-merge dedup
├── plugins/              # Plugin implementations + factory
│   ├── factory.py        # Dynamic plugin loader
│   ├── captioner/        # Qwen API captioner + local VL captioner
│   ├── embedder/         # Qwen3-VL-Embedding (local GPU)
│   ├── summarizer/       # DeepSeek API
│   ├── segmenter/        # TransNetV2 / Time-based
│   ├── transcriber/      # faster-whisper
│   ├── qc/               # FFmpeg-based QC
│   ├── detector/         # (stub) YOLO
│   ├── ocr/              # (stub) PaddleOCR
│   └── grounding/        # (stub) Florence-2
├── services/             # Business logic layer
│   ├── video_service.py  # Video processing orchestration
│   └── export_service.py # (stub) export logic
├── core/
│   └── settings_service.py # API key management (settings.json backed)
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

- **v0.7 — Search architecture consolidation**: 3-path semantic search (frame+text 主力, chunk 配置关闭), 废弃全文/混合/模糊检索, encode_text 扩大至 caption+ocr+transcript, 路径感知排序与跨路去重修复
- **P0 complete**: Pipeline core, search engine (3 search functions: frame/chunk/text), 13 API endpoints, frontend dashboard
- **Planned**: Object detection (YOLO), OCR (PaddleOCR), Grounding (Florence-2), Export APIs (clip/JSON/Markdown)
