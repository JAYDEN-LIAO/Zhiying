# Cerno — Universal Video Analytics Engine

A general-purpose video analytics engine for semantic search and structured summarization. Designed for single-GPU setups (8–32 GB VRAM).

## Quick Start

```bash
# 1. Start database
docker-compose up -d db

# 2. Set API keys
set DASHSCOPE_API_KEY=sk-xxx   # Qwen-VL for captioning
set DEEPSEEK_API_KEY=sk-xxx    # for summarization

# 3. Start server
uvicorn main:app --reload

# 4. Upload a video
curl -X POST -F "file=@demo.mp4" http://localhost:8000/api/v1/videos/upload

# 5. Get summary
curl http://localhost:8000/api/v1/videos/{video_id}

# 6. Semantic search
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
| Semantic Search | `POST /api/v1/search/semantic` | ✅ |
| Fulltext Search | `GET /api/v1/search/text?q=...` | ✅ |
| Hybrid Search (vector+text) | `POST /api/v1/search/hybrid` | ✅ |

## Architecture Overview

```
Upload → Pipeline → DB → Search
         ├─ QC + Scene Segmentation
         ├─ VLM Captioning (API)
         ├─ Embedding (local GPU, 2048-dim)
         └─ LLM Summarization (API)
```

- **5-stage pipeline** orchestrated by `PipelineEngine`
- **9 abstract plugin interfaces** with dynamic factory loading
- **PostgreSQL + pgvector** for vector storage and HNSW/IVFFlat search
- **Config-driven**: switch models or API providers via `config.yaml`

## Tech Stack

| Component | Technology |
|---|---|
| Framework | FastAPI (Python 3.12) |
| Database | PostgreSQL 17 + pgvector 0.8 |
| Vector Embedding | Qwen3-VL-Embedding-2B (local GPU) |
| Captioning | Qwen-VL-Max (DashScope API) |
| Summarization | DeepSeek Chat (API) |
| Scene Segmentation | Time-based (fixed interval) |
| Video Processing | FFmpeg (asyncio subprocess) |

## Project Structure

```
cerno/
├── main.py               # FastAPI entry point
├── api/                  # Route definitions
├── core/                 # DB models, schemas, search, config
├── pipeline/             # Pipeline orchestrator + phases
├── plugins/              # Plugin implementations + factory
├── services/             # Business logic layer
├── utils/                # FFmpeg tools
├── config/               # YAML config, prompts, secrets
└── docs/                 # Design documents
```

## Development Status

- **Demo-ready**: Video summarization & semantic search verified on 4060 8GB
- **P0 complete**: Pipeline core, search engine, API routes
- **Planned**: Object detection (YOLO), OCR, Grounding, Audio transcription, Export APIs
