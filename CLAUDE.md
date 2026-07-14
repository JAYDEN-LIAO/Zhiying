# Cerno Project Context for AI Agents

## One-Line Summary

Cerno is a **video analytics engine** (v0.5) that ingests videos, runs a 5-stage async pipeline (QC → segmentation → captioning → embedding → summarization), generates **3-path encodings** (frame-level 1fps + chunk-level sliding window + text-level caption semantics), enables **4-path parallel semantic search** over scene content, and exposes everything via **FastAPI + PostgreSQL/pgvector**.

## Quick File Map

```
main.py                    — FastAPI app, lifespan, exception handlers, shared embedder
api/routes.py              — ALL API endpoints (video CRUD, upload, stream, thumbnail, 3 search modes)
api/router.py              — Re-exports from api/routes.py
api/deps.py                — FastAPI dependency injection (get_db)
api/video_routes.py        — (stub) planned video route extraction
api/search_routes.py       — (stub) planned search route extraction
api/export_routes.py       — (stub) planned export endpoints
api/maintenance_routes.py  — (stub) planned health/reindex endpoints
core/models.py             — ORM: Video, Scene, Transcript, FrameEmbedding, Chunk (5 tables)
core/schemas.py            — Pydantic v2 DTOs + JSONB validation models
core/interfaces.py         — 9 abstract base classes (BaseQC, BaseCaptioner, ...)
core/search.py             — 7 search functions: vector/fulltext/hybrid/fuzzy/frame/chunk/text
core/repository.py         — Data access layer + bulk_insert_frames/chunks
core/db.py                 — Async engine, init_db(), triggers, incremental migration (text_embedding)
core/config_loader.py      — Loads config.yaml, merges .env secrets via _ENV_OVERRIDES
core/prompt_loader.py      — Prompt template loader (config/prompts.yaml)
core/status_tracker.py     — Pipeline progress persistence (PHASE_WEIGHTS mapping)
core/exceptions.py         — Custom exceptions
pipeline/engine.py         — PipelineEngine orchestrator (5-stage + 3-path encode_frames)
pipeline/phase1_qc.py      — QC + audio extraction + scene segmentation
pipeline/phase3_alignment.py — Transcript-to-scene alignment
pipeline/phase4_caption.py — Caption + Embed (core logic)
pipeline/phase5_summary.py — LLM summarization
pipeline/search_engine.py  — 4-path parallel recall (frame/chunk/text/label) + scene-merge + dedup
plugins/factory.py         — Dynamic plugin loader (CATEGORY_MAP, _MODULE_OVERRIDES, _CLASS_OVERRIDES)
config/config.yaml         — Main config: server/db/storage/plugins/pipeline
config/config_schema.py    — Pydantic config validation
config/prompts.yaml        — Caption/Summarizer/Grounding prompt templates
frontend/src/Dashboard.tsx — Main workspace: video player, PipelineBar, VideoSummaryCard, VideoSearchCard, HistoryPanel
frontend/src/services/api.ts — API wrapper + polling helper
frontend/src/types/index.ts — TypeScript types (mirrors backend schemas)
frontend/src/mockData.ts   — Pipeline stage definitions (6 stages: qc/segment/align/caption/embed/summary)
```

## Data Flow

```
POST /videos/upload (multipart file)
  → save to disk
  → create Video record (status=pending, with perception switches)
  → background task: PipelineEngine.run()

PipelineEngine.run():
  initialize()    → Load 9 plugins (embedder reuses app.state shared instance)
  _phase1()       → QC (FFmpeg) + audio extraction + scene segmentation (TransNetV2)
  _extract_keyframes() → FFmpeg pipe → memory @1fps, 3-7 caption frames, thumbnails
  _phase3()       → Transcript-to-scene alignment
  _phase4()       → Caption (API, with memory window) + Embed (local GPU)
  _phase5()       → LLM summary (API)
  _persist()      → Write scenes (bulk) + transcript + artifacts to DB
  _encode_frames() → 3 encoding paths (after persist, search-only):
    a. Frame path:  encode_image(1fps) → frame_embeddings table
    b. Chunk path:  create temp clip → encode_video(clip) → chunks table
       Adaptive window: ≤5s skip, 5-60s window=duration/2, >60s window=30s
    c. Text path:   encode_text(caption) → scenes.text_embedding

Search (4-path parallel):
  text query → embedder.encode_text() → 2048-dim vector (shared, once)
  → 4 parallel tasks:
    _frame_search()  → frame_embeddings table, 1fps per-frame precision
    _chunk_search()  → chunks table, sliding window process semantics
    _text_search()   → scenes.text_embedding, caption text semantics
    _label_search()  → JSONB @> entities.label (future YOLO)
  → merge by scene: frame clusters (≤4s gap), dedup overlaps, keep best score
  → enrich with scene metadata → return results with precision_level
```

## Key Conventions

- **All plugin interfaces are async**. Sync model inference MUST use `asyncio.to_thread()` — never call sync code directly in async methods.
- **Plugin config is YAML-driven**. `config/config.yaml` `plugins.{name}.backend` selects the implementation. `null` means the module is disabled.
- **API keys never in code**. Use `.env` file (gitignored) or environment variables. See `core/config_loader.py` `_ENV_OVERRIDES`.
- **Vector dim**: 2048 (Qwen3-VL-Embedding-2B output). No pgvector HNSW index (exceeds 2000-dim limit; exact scan <1ms at demo scale).
- **Trigger**: `scenes.search_vector` is auto-populated by a `BEFORE INSERT OR UPDATE` trigger in PostgreSQL (created during `init_db()`).
- **Shared embedder**: Embedder is loaded once in `app.state.embedder` during lifespan startup. Pipeline and SearchEngine both reuse this instance — never call `load_plugin("embedder")` directly in business logic.
- **Incremental migration**: `init_db()` uses `ALTER TABLE ADD COLUMN IF NOT EXISTS` for schema evolution (e.g., `text_embedding` column).
- **Three encoding paths exist**: Frame (1fps per-frame), Chunk (sliding window clips), Text (caption semantics). All three are encoded in `_encode_frames()` after `_persist()`.
- **Perception switches**: Video model has `audio/vision/ocr/grounding/caption/summary_enabled` booleans. Pipeline phases check these before executing.

## Database Tables (5)

| Table | Key Columns | Purpose |
|---|---|---|
| `videos` | id, status, progress, qc_result(JSONB), summary(JSONB), 6x perception switches | Video master |
| `scenes` | id, video_id(FK), scene_index, embedding(Vector2048), text_embedding(Vector2048), caption, search_vector(TSVECTOR) | Core search grain |
| `transcripts` | id, video_id(FK, UNIQUE), full_text, words(JSONB) | Speech transcripts |
| `frame_embeddings` | id, video_id(FK), timestamp_sec, embedding(Vector2048), is_keyframe | 1fps frame vectors |
| `chunks` | id, video_id(FK), chunk_index, start_sec, end_sec, embedding(Vector2048) | Sliding window vectors |

## Current Implementation Status

| Area | Status | Files |
|---|---|---|
| Pipeline core | ✅ Complete | engine.py, phase1, phase4, phase5 |
| Frame/Chunk/Text encoding | ✅ Complete | engine.py _encode_frames(), core/repository.py |
| Semantic search (4-path) | ✅ Verified | search_engine.py + api/routes.py |
| Fulltext search | ✅ Verified | core/search.py full_text_search() |
| Hybrid search | ✅ Verified | core/search.py hybrid_search() |
| Captioner (API) | ✅ Verified | plugins/captioner/qwen_api_captioner.py |
| Embedder (local GPU) | ✅ Verified | plugins/embedder/qwen_vl_embedder.py |
| Summarizer (API) | ✅ Verified | plugins/summarizer/vllm_summarizer.py |
| Segmenter (TransNetV2) | ✅ Verified | plugins/segmenter/transnet_v2.py |
| Segmenter (time-based) | ✅ Verified | plugins/segmenter/time_based.py |
| QC (FFmpeg) | ✅ Verified | plugins/qc/basic_qc.py |
| Transcriber (faster-whisper) | ✅ Plugin ready | plugins/transcriber/faster_whisper.py |
| DB + migrations | ✅ Done | db.py, models.py, init_db() |
| Prompt templates | ✅ Done | config/prompts.yaml |
| Frontend dashboard | ✅ Done | Dashboard.tsx (React 19 + Tailwind 4) |
| Object Detection (YOLO) | ⬜ Shell only | plugins/detector/ + pipeline/phase2_perception.py |
| OCR | ⬜ Shell only | plugins/ocr/ |
| Grounding | ⬜ Shell only | plugins/grounding/ |
| Export APIs | ⬜ Shell only | api/export_routes.py, services/export_service.py |
| Health/Reindex | ⬜ Shell only | api/maintenance_routes.py |

## Agent Instructions

> Read this section last. It tells you how to behave in this project.

1. **Don't modify `.env`** — it contains API keys and is gitignored.
2. **Don't delete empty `__init__.py` files** — they're intentional package markers.
3. **Don't delete empty route/service files** (`api/video_routes.py`, `api/search_routes.py`, `api/export_routes.py`, etc.) — they're planned stubs for future route modularization.
4. **Config-driven design**: when adding a model, add a new backend plugin file and register it in `plugins/factory.py` `CATEGORY_MAP` / `_MODULE_OVERRIDES` / `_CLASS_OVERRIDES`. No hardcoded model references in business logic.
5. **Sync vs Async**: all `core/interfaces.py` methods are `async def`. If your plugin runs synchronous model inference, wrap it with `asyncio.to_thread()`. Never call `model.predict()` directly in an async function.
6. **Search paths**: `config_loader.py` and `prompt_loader.py` use `Path(__file__).resolve().parent.parent` to locate the project root. Keep this convention.
7. **Vector dimension**: 2048. All vector columns (scenes.embedding, scenes.text_embedding, frame_embeddings.embedding, chunks.embedding) use `Vector(2048)`. No pgvector HNSW/IVFFlat index (2048 > 2000 limit, but full scan is fine for demo scale).
8. **Three encoding paths**: Frame (encode_image), Chunk (encode_video with temp clips), Text (encode_text). All three reuse the shared embedder. Chunk encoding creates temporary mp4 clips via ffmpeg, encodes them, then cleans up.
9. **When adding new dependencies**: add to `requirements.txt` AND to `Dockerfile`.
10. **Search result format**: All results include `precision_level` (frame/chunk/text/label), `precise_start/end`, `match_paths`, and `thumbnail_url`.
11. **Frontend**: Dashboard.tsx contains all major components inline (LeftSidebar, PipelineBar, VideoSummaryCard, VideoSearchCard, HistoryPanel). The `components/` directory has older sub-component shells. TypeScript types in `types/index.ts` mirror backend Pydantic schemas.

## Python Environment

- Python 3.12
- FastAPI, SQLAlchemy async, asyncpg, pgvector
- transformers, torch (CUDA 12.4), modelscope, qwen-vl-utils
- openai, httpx, Pillow
- pytest, pytest-asyncio
