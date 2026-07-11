# Cerno Architecture

> Version: 0.1 | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector

## System Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client (CLI/Browser)                     │
└──────────────────┬────────────────────────────┬─────────────────┘
                   │ POST /videos/upload        │ POST /search/semantic
                   ▼                            ▼
┌─────────────────────────────┐  ┌─────────────────────────────┐
│     FastAPI (main.py)       │  │   Embedder (local GPU)      │
│                             │  │   encode_text("query")      │
│  ┌─ api/routes.py ────────┐ │  │        → 2048-dim vector    │
│  │ upload_video()         │ │  └──────────┬──────────────────┘
│  │ get_video()            │ │             │
│  │ search_semantic()      │ │  ┌──────────▼──────────────────┐
│  │ search_text()          │ │  │   SearchEngine              │
│  └───────────┬───────────┘ │  │   ┌─ vector cosine search   │
└──────────────┬─────────────┘  │   ├─ fulltext tsvector       │
               │                │   └─ RRF fusion              │
               ▼                └──────────┬──────────────────┘
┌─────────────────────────────┐            │
│  VideoService               │            ▼
│  process_video(video_id)    │  ┌─────────────────────────────┐
│    → PipelineEngine.run()   │  │  PostgreSQL + pgvector      │
└──────────┬──────────────────┘  │                             │
           │                     │  videos (metadata, summary) │
           ▼                     │  scenes (embedding, caption)│
┌─────────────────────────────┐  │  transcripts (full text)   │
│  PipelineEngine             │  └─────────────────────────────┘
│  5-stage async workflow     │
│                             │
│  Phase 1: QC + Segmentation│
│  Phase 3: Transcript Align  │
│  Phase 4: Caption + Embed   │
│  Phase 5: Summarize         │
│  Persist: Write to DB       │
└─────────────────────────────┘
```

## Pipeline Detail

```
Phase 1 (QC + Split)
  ┌─ QC (FFmpeg blackdetect/silencedetect) → qc_result
  ├─ Transcribe (faster-whisper, optional) → words[]
  └─ Segment (time-based or TransNetV2) → scenes[]

  ↓

Keyframe Extraction
  └─ FFmpeg pipe → memory (numpy array, no disk I/O)

  ↓

Phase 3 (Alignment, optional)
  └─ Align words[] to scenes by timestamps → scene.aligned_transcript

  ↓

Phase 4 (Understanding)
  ├─ Caption (Qwen-VL API) → scene.caption
  └─ Embed (Qwen3-VL-Embedding, local GPU) → scene.embedding (2048-dim)

  ↓

Phase 5 (Summarization)
  └─ LLM (DeepSeek API) → structured JSON summary

  ↓

Persist
  ├─ bulk_insert_scenes → scenes table
  ├─ insert transcript → transcripts table
  └─ update video → videos table (duration, qc_result, summary)
```

## Module Dependency

```
main.py
  └─ api/router.py → api/routes.py
        ├─ core/deps.py           (DB session injection)
        ├─ services/video_service.py
        │     └─ pipeline/engine.py
        │           ├─ pipeline/phase1_qc.py
        │           ├─ pipeline/phase4_caption.py
        │           ├─ pipeline/phase5_summary.py
        │           └─ plugins/factory.py
        │                 └─ plugins/captioner/qwen_api_captioner.py
        │                 └─ plugins/embedder/qwen_vl_embedder.py
        │                 └─ plugins/summarizer/vllm_summarizer.py
        │                 └─ plugins/segmenter/time_based.py
        │                 └─ plugins/qc/basic_qc.py
        └─ pipeline/search_engine.py
              ├─ core/search.py
              └─ plugins/embedder/qwen_vl_embedder.py

core/
  ├─ interfaces.py         ← All plugin ABCs
  ├─ models.py             ← ORM: Video, Scene, Transcript
  ├─ schemas.py            ← Pydantic DTOs
  ├─ repository.py         ← DB access layer
  ├─ search.py             ← Raw SQL search functions
  ├─ config_loader.py      ← YAML + .env loading
  ├─ prompt_loader.py      ← Prompt templates
  ├─ status_tracker.py     ← Pipeline progress
  └─ exceptions.py         ← Custom exceptions
```

## Plugin System

```
plugins/factory.py:
  load_plugin(config, "captioner")
    → import plugins.captioner.qwen_api_captioner
    → instantiate QwenAPICaptioner(base_url, api_key, ...)
    → return instance (or None if disabled)

config.yaml controls which backends to load:

  captioner:  qwen_api       → calls Qwen-VL-Max API
  embedder:   qwen3_vl_embedding → runs local GPU model
  summarizer: vllm           → calls DeepSeek API via OpenAI-compatible endpoint
  segmenter:  time_based     → fixed-interval (no DL deps)
  qc:         native_qc      → FFmpeg-based
  transcriber: null          → disabled (placeholder)
  detector:   null           → disabled (placeholder)
  ocr:        null           → disabled (placeholder)
  grounding:  null           → disabled (placeholder)
```

## Search Architecture

```
User Query "a man in black"
  ↓
Embedder.encode_text() → 2048-dim vector
  ↓
SearchEngine.search()
  ├─ vector recall: pgvector cosine_distance (scenes.embedding)
  ├─ fulltext recall: ts_rank (scenes.search_vector, GIN-indexed)
  ├─ label recall: JSONB @> entities.label (if entities exist)
  └─ RRF fusion → ranked results
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Plugin + Factory** | Swap models via config.yaml, zero code changes |
| **pgvector over standalone vector DB** | Simpler deployment, transactional consistency |
| **Local GPU for Embedder** | 2048-dim encoding every scene; API latency unacceptable |
| **API for Captioner/Summarizer** | Better quality, zero GPU footprint on 4060 8GB |
| **FFmpeg pipe → memory** | No frame files on disk, reduces I/O |
| **Fixed-interval segmentation** | Zero DL deps (avoids TensorFlow for demo) |
| **Enabled modules only** | pipeline checks each plugin; null = skip gracefully |

## Current Status

| Module | Status | Note |
|---|---|---|
| Pipeline Core | ✅ | Phase 1→4→5 verified E2E |
| Semantic Search | ✅ | 234ms latency (cached embedder) |
| Fulltext Search | ✅ | tsvector via DB trigger |
| API Routes | ✅ | Upload, status, detail, 3 search modes |
| Object Detection | 📋 | YOLO plugin shell only |
| OCR | 📋 | PaddleOCR shell only |
| Grounding | 📋 | Florence-2 shell only |
| Audio Transcription | 📋 | faster-whisper shell only |
| Export APIs | 📋 | Clip, JSON, Markdown, Merge |
| Health / Reindex | 📋 | maintenance_routes.py shell |
