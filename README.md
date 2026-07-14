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
| Video Upload & Pipeline | `POST /api/v1/videos/upload` | ✅ |
| Video Detail + Summary | `GET /api/v1/videos/{id}` | ✅ |
| Processing Status | `GET /api/v1/videos/{id}/status` | ✅ |
| Video Streaming (Range) | `GET /api/v1/videos/{id}/stream` | ✅ |
| Video List | `GET /api/v1/videos/` | ✅ |
| Video Delete | `DELETE /api/v1/videos/{id}` | ✅ |
| Semantic Search | `POST /api/v1/search/semantic` | ✅ |
| Fulltext Search | `GET /api/v1/search/text?q=...` | ✅ |
| Hybrid Search (vector+text) | `POST /api/v1/search/hybrid` | ✅ |
| Frontend Dashboard | React 19 + Vite + Tailwind CSS | ✅ |

## Architecture Overview

```
Upload → Pipeline → DB → Search → Frontend
         ├─ QC + Scene Segmentation
         ├─ VLM Captioning (API)
         ├─ Embedding (local GPU, 2048-dim)
         └─ LLM Summarization (API)
```

- **5-stage pipeline** orchestrated by `PipelineEngine`
- **9 abstract plugin interfaces** with dynamic factory loading
- **PostgreSQL + pgvector** for vector storage and HNSW/IVFFlat search
- **Config-driven**: switch models or API providers via `config.yaml`
- **React frontend** with video player, pipeline progress visualization, and semantic search panel

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
| Scene Segmentation | Time-based (fixed interval) / TransNetV2 |
| Video Processing | FFmpeg (asyncio subprocess) |

## Project Structure

```
cerno/
├── main.py               # FastAPI entry point
├── api/                  # Route definitions
│   ├── router.py         # Route assembly
│   ├── routes.py         # All API endpoints
│   └── deps.py           # FastAPI dependencies (DB session)
├── core/                 # DB models, schemas, search, config
│   ├── db.py             # Async engine, init_db(), triggers
│   ├── models.py         # ORM: Video, Scene, Transcript
│   ├── schemas.py        # Pydantic DTOs + JSONB validation
│   ├── repository.py     # data access layer
│   ├── search.py         # pgvector + GIN search SQL
│   └── config_schema.py  # Pydantic config validation
├── pipeline/             # Pipeline orchestrator + phases
│   ├── engine.py         # 5-stage PipelineEngine
│   ├── phase1_qc.py      # QC + segmentation
│   ├── phase3_alignment.py
│   ├── phase4_caption.py # Caption + embed
│   ├── phase5_summary.py # LLM summarization
│   └── search_engine.py  # Multi-recall + RRF fusion
├── plugins/              # Plugin implementations + factory
│   ├── factory.py        # Dynamic plugin loader
│   ├── captioner/        # Qwen API captioner
│   ├── embedder/         # Qwen3-VL-Embedding (local GPU)
│   ├── summarizer/       # DeepSeek API
│   ├── segmenter/        # Time-based / TransNetV2
│   └── qc/               # FFmpeg-based QC
├── services/             # Business logic layer
├── utils/                # FFmpeg tools
├── frontend/             # React + Vite + Tailwind dashboard
│   ├── src/
│   │   ├── Dashboard.tsx # Main workspace
│   │   ├── services/api.ts
│   │   └── types/
│   ├── package.json
│   └── vite.config.ts
├── config/               # YAML config, prompts, schema
└── docs/                 # Design documents
```

## Development Status

- **Demo-ready**: Video summarization & semantic search verified on 4060 8GB
- **P0 complete**: Pipeline core, search engine, API routes, frontend dashboard
- **Planned**: Object detection (YOLO), OCR, Grounding, Audio transcription, Export APIs
