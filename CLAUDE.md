# Cerno Project Context for AI Agents

## One-Line Summary

Cerno is a **video analytics engine** that ingests videos, runs a 5-stage async pipeline (QC → segmentation → captioning → embedding → summarization), enables **semantic search** over scene content, and exposes everything via **FastAPI + PostgreSQL/pgvector**.

## Quick File Map

```
main.py                    — FastAPI app, lifespan, exception handlers
api/routes.py              — ALL API endpoints (upload, status, search)
core/interfaces.py         — 9 abstract base classes (BaseQC, BaseCaptioner, ...)
core/models.py             — ORM: Video, Scene, Transcript
core/search.py             — pgvector cosine + GIN fulltext search SQL
core/config_loader.py      — Loads config.yaml, merges .env secrets
pipeline/engine.py         — PipelineEngine orchestrator (5-stage async)
pipeline/phase4_caption.py — Caption + Embed (core logic)
pipeline/phase5_summary.py — LLM summarization
pipeline/search_engine.py  — Multi-recall + RRF fusion
plugins/factory.py         — Dynamic plugin loader (strategy pattern)
```

## Data Flow

```
POST /videos/upload (multipart file)
  → save to disk
  → create Video record (status=pending)
  → background task: PipelineEngine.run()

PipelineEngine.run():
  _phase1()   → QC + scene segmentation
  _extract_keyframes() → FFmpeg pipe → memory (numpy)
  _phase4()   → Caption (API) + Embed (local GPU)
  _phase5()   → Summary (API)
  _persist()  → Write scenes + transcript + artifacts to DB

Search:
  text → embedder.encode_text() → 2048-dim vector
  → pgvector cosine_search → ranked scenes
```

## Key Conventions

- **All plugin interfaces are async**. Sync model inference MUST use `asyncio.to_thread()` — never call sync code directly in async methods.
- **Plugin config is YAML-driven**. `config/config.yaml` `plugins.{name}.backend` selects the implementation. `null` means the module is disabled.
- **API keys never in code**. Use `.env` file (gitignored) or environment variables. See `core/config_loader.py` `_ENV_OVERRIDES`.
- **Vector dim**: 2048 (Qwen3-VL-Embedding-2B output). No pgvector index (exceeds 2000-dim limit; exact scan <1ms at demo scale).
- **Trigger**: `scenes.search_vector` is auto-populated by a `BEFORE INSERT OR UPDATE` trigger in PostgreSQL (created during `init_db()`).

## Current Implementation Status

| Area | Status | Files |
|---|---|---|
| Pipeline core | ✅ Complete | engine.py, phase1, phase4, phase5 |
| Semantic search | ✅ Verified | search_engine.py + api/routes.py |
| Captioner (API) | ✅ Verified | plugins/captioner/qwen_api_captioner.py |
| Embedder (local GPU) | ✅ Verified | plugins/embedder/qwen_vl_embedder.py |
| Summarizer (API) | ✅ Verified | plugins/summarizer/vllm_summarizer.py |
| Segmenter (time-based) | ✅ Verified | plugins/segmenter/time_based.py |
| QC (FFmpeg) | ✅ Verified | plugins/qc/basic_qc.py |
| DB + migrations | ✅ Done | db.py, models.py, init_db() |
| Object Detection (YOLO) | ⬜ Shell only | plugins/detector/ + pipeline/phase2_perception.py |
| OCR | ⬜ Shell only | plugins/ocr/ |
| Grounding | ⬜ Shell only | plugins/grounding/ |
| Audio Transcription | ⬜ Shell only | plugins/transcriber/ |
| Export APIs | ⬜ Shell only | api/export_routes.py, services/export_service.py |
| Health/Reindex | ⬜ Shell only | api/maintenance_routes.py |

## Agent Instructions

> Read this section last. It tells you how to behave in this project.

1. **Don't modify `.env`** — it contains API keys and is gitignored.
2. **Don't delete empty `__init__.py` files** — they're intentional package markers.
3. **Don't delete empty route/service files** (`api/export_routes.py`, etc.) — they're planned stubs.
4. **Config-driven design**: when adding a model, add a new backend plugin file and register it in `plugins/factory.py` `_MODULE_OVERRIDES` / `_CLASS_OVERRIDES`. No hardcoded model references in business logic.
5. **Sync vs Async**: all `core/interfaces.py` methods are `async def`. If your plugin runs synchronous model inference, wrap it with `asyncio.to_thread()`. Never call `model.predict()` directly in an async function.
6. **Search paths**: `config_loader.py` and `prompt_loader.py` use `Path(__file__).resolve().parent.parent` to locate the project root. Keep this convention.
7. **Vector dimension**: 2048. DB column is `Vector(2048)`. No pgvector index (limit is 2000, but full scan is fine for demo scale).
8. **When adding new dependencies**: add to `requirements.txt` AND to `Dockerfile`.

## Python Environment

- Python 3.12
- FastAPI, SQLAlchemy async, asyncpg, pgvector
- transformers, torch (CUDA 12.4), modelscope
- openai, httpx, Pillow
- pytest, pytest-asyncio
