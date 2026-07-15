# Cerno Project Context for AI Agents

## One-Line Summary

Cerno is a **video analytics engine** (v0.6) that ingests videos, runs a 5-stage async pipeline (QC → segmentation → captioning → embedding → summarization), generates **3-path encodings** (frame-level 1fps + chunk-level sliding window + text-level caption semantics), enables **3-path parallel semantic search** (frame + text, chunk 配置关闭默认不启用), exposes everything via **FastAPI + PostgreSQL/pgvector**, and provides a **4-level parameter system** (scene type → perception modules → function switches → advanced params) that controls pipeline execution.

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
core/search.py             — 3 search functions: frame/chunk/text (废弃的全文/混合/模糊已移除)
core/repository.py         — Data access layer + bulk_insert_frames/chunks
core/db.py                 — Async engine, init_db(), incremental migration (pgvector, text_embedding)
core/config_loader.py      — Loads config.yaml, merges .env secrets via _ENV_OVERRIDES
core/prompt_loader.py      — Prompt template loader (config/prompts.yaml)
core/status_tracker.py     — Pipeline progress + status_detail persistence (PHASE_WEIGHTS mapping)
core/exceptions.py         — Custom exceptions
pipeline/engine.py         — PipelineEngine orchestrator (5-stage + 3-path encode_frames)
pipeline/phase1_qc.py      — QC + audio extraction + scene segmentation
pipeline/phase3_alignment.py — Transcript-to-scene alignment
pipeline/phase4_caption.py — Caption + Embed (core logic)
pipeline/phase5_summary.py — LLM summarization
pipeline/search_engine.py  — 3-path parallel recall (frame/chunk/text) + label 预留 + scene-merge dedup
plugins/factory.py         — Dynamic plugin loader (CATEGORY_MAP, _MODULE_OVERRIDES, _CLASS_OVERRIDES)
config/config.yaml         — Main config: server/db/storage/plugins/pipeline
config/config_schema.py    — Pydantic config validation
config/prompts.yaml        — Caption/Summarizer/Grounding prompt templates
frontend/src/Dashboard.tsx — Main workspace (orchestrator, ~380 lines)
frontend/src/components/    — Split components: icons, LeftSidebar, ParameterPanel, PipelineBar,
                              VideoSummaryCard, VideoSearchCard, HistoryPanelContent, SettingsPage
frontend/src/utils/helpers.ts — Shared helpers (fmtDuration, fmtDate, formatSec)
frontend/src/services/api.ts — API wrapper + polling helper
frontend/src/types/index.ts — TypeScript types (mirrors backend schemas)
frontend/src/mockData.ts   — Pipeline stage definitions + computePipelineStages() dynamic function
```

## Data Flow

```
POST /videos/upload (multipart file)
  → save to disk
  → create Video record (status=pending, default params)
  → parameter panel auto-opens in frontend

PUT /videos/{id}/params (after user configures)
  → validate via PipelineParams (core/schemas.py model_validator)
  → update Video record with Scene Type / Perception Modules / Function Switches / Advanced Params
  → background task: PipelineEngine.run()   (for pending videos)
  → background task: PipelineEngine.run_incremental()   (for completed videos, only summary/search_index)

PipelineEngine.run() (with gate control from L2/L3 params):
  initialize()    → Load 9 plugins (embedder reuses app.state shared instance)
  _phase1()       → QC (FFmpeg) + audio extraction + scene segmentation (TransNetV2)
                   → writes status_detail: "质检完成", "正在转录音频", "镜头分割完成: N 个场景"
  _extract_keyframes() ← gated by vision_enabled → FFmpeg pipe → memory @1fps, 3-7 caption frames, thumbnails
                   → writes status_detail: "正在抽取第 X/Y 个场景的关键帧"
  _phase3()       ← gated by audio_enabled → Transcript-to-scene alignment
                   → writes status_detail: "对齐完成: X/Y 个场景已分配转录文本"
  _phase4()       ← gated by vision_enabled + caption_enabled → Caption (API, with memory window)
                   → writes status_detail: "正在描述第 X/Y 个场景"
  _phase5()       ← gated by summary_enabled + caption_enabled → LLM summary (API)
                   → writes status_detail: "正在生成摘要（N 个场景）..."
  _persist()      → Write scenes (bulk) + transcript + artifacts to DB
  _encode_frames() ← gated by search_index_enabled + vision_enabled → 2 active + 1 config-gated paths:
                   → writes status_detail: "正在编码第 X/Y 个场景的帧向量"
    a. Frame path:  encode_image(1fps) → frame_embeddings table
    b. Chunk path:  config pipeline.chunk_encoding 控制, 默认关闭
       (开启时: -c copy 流复制 → 480p 5fps 预处理 → encode_video → chunks)
    c. Text path:   encode_text(caption+ocr+transcript) → scenes.text_embedding

Search (3-path parallel):
  text query → embedder.encode_text() → 2048-dim vector (shared, once)
  → 3 parallel tasks:
    _frame_search()  → frame_embeddings table, 1fps per-frame precision
    _chunk_search()  → chunks table, sliding window process semantics
    _text_search()   → scenes.text_embedding, caption+ocr+transcript 语义
    _label_search()  → JSONB @> entities.label (future YOLO, 预留)
  → merge by scene: frame clusters (≤4s gap), dedup overlaps, keep best score
  → enrich with scene metadata → return results with precision_level
```

## Key Conventions

- **All plugin interfaces are async**. Sync model inference MUST use `asyncio.to_thread()` — never call sync code directly in async methods.
- **Plugin config is YAML-driven**. `config/config.yaml` `plugins.{name}.backend` selects the implementation. `null` means the module is disabled.
- **API keys never in code**. Use `.env` file (gitignored) or environment variables. See `core/config_loader.py` `_ENV_OVERRIDES`.
- **Vector dim**: 2048 (Qwen3-VL-Embedding-2B output). No pgvector HNSW index (exceeds 2000-dim limit; exact scan <1ms at demo scale).
- **Trigger**: ~~`scenes.search_vector`~~ 已移除（tsvector 全文检索已废弃）
- **Shared embedder**: Embedder is loaded once in `app.state.embedder` during lifespan startup. Pipeline and SearchEngine both reuse this instance — never call `load_plugin("embedder")` directly in business logic.
- **Incremental migration**: `init_db()` uses `ALTER TABLE ADD COLUMN IF NOT EXISTS` for schema evolution (e.g., `text_embedding`, `status_detail` columns).
- **Three encoding paths exist**: Frame (1fps per-frame), Chunk (config-gated, default disabled, `-c copy` + 480p 5fps preprocessing + encode_video), Text (caption+ocr+transcript 语义). All three reuse the shared embedder.
- **Parameter system (v0.6)**: 4-level hierarchy — L1=Scene Type (general/meeting/surveillance/text_recognition/custom), L2=Perception Modules (vision/audio/ocr/caption, plus detection-grayed), L3=Function Switches (search_index/summary), L4=Advanced Params (language/sample_fps/segment_threshold/caption_with_context/summary_detail). Upper levels set defaults for lower levels. Pipeline uses `PipelineParams` Pydantic model with cross-field validation.
- **Incremental processing**: Completed videos can re-run summary or search index independently via `run_incremental()`. Non-incremental param changes require creating a new video record (reuse file via `POST /videos/reuse`).

## Database Tables (5)

| Table | Key Columns | Purpose |
|---|---|---|
| `videos` | id, status, progress, status_detail, qc_result(JSONB), summary(JSONB), content_type, perception switches (vision/audio/ocr/grounding/caption/summary_enabled), function switches (search_index_enabled), advanced params (sample_fps, segment_threshold, caption_with_context, summary_detail), language | Video master |
| `scenes` | id, video_id(FK), scene_index, text_embedding(Vector2048), caption, ocr_text, aligned_transcript | Core search grain (text_embedding = caption+ocr+transcript 语义) |
| `transcripts` | id, video_id(FK, UNIQUE), full_text, words(JSONB) | Speech transcripts |
| `frame_embeddings` | id, video_id(FK), timestamp_sec, embedding(Vector2048), is_keyframe | 1fps frame vectors |
| `chunks` | id, video_id(FK), chunk_index, start_sec, end_sec, embedding(Vector2048) | Sliding window vectors |

## Current Implementation Status

| Area | Status | Files |
|---|---|---|
| Pipeline core | ✅ Complete | engine.py, phase1, phase4, phase5 |
| Frame/Chunk/Text encoding | ✅ Complete | engine.py _encode_frames(), core/repository.py |
| Semantic search (3-path) | ✅ Verified | search_engine.py + api/routes.py (frame+chunk+text, label 预留) |
| Captioner (API) | ✅ Verified | plugins/captioner/qwen_api_captioner.py |
| Embedder (local GPU) | ✅ Verified | plugins/embedder/qwen_vl_embedder.py |
| Summarizer (API) | ✅ Verified | plugins/summarizer/vllm_summarizer.py |
| Segmenter (TransNetV2) | ✅ Verified | plugins/segmenter/transnet_v2.py |
| Segmenter (time-based) | ✅ Verified | plugins/segmenter/time_based.py |
| QC (FFmpeg) | ✅ Verified | plugins/qc/basic_qc.py |
| Transcriber (faster-whisper) | ✅ Plugin ready | plugins/transcriber/faster_whisper.py |
| DB + migrations | ✅ Done | db.py, models.py, init_db() |
| Prompt templates | ✅ Done | config/prompts.yaml |
| Pipeline real-time status | ✅ Done | status_tracker.py writes status_detail; phases 1/3/4/5 + keyframe + encoding report progress |
| Parameter system (4-level) | ✅ Done | core/schemas.py PipelineParams + model_validator; config/presets.yaml; frontend ParameterPanel with cascade |
| Incremental processing | ✅ Done | pipeline/engine.py run_incremental(); services/video_service.py incremental_process() |
| Settings API + API key mgmt | ✅ Done | core/settings_service.py; GET/PUT /api/v1/settings |
| Frontend dashboard | ✅ Done | Dashboard.tsx + 8 extracted components in components/ (React 19 + Tailwind 4) — 参数面板四级联动, 动态 PipelineBar, 系统设置页, 历史记录自动刷新 |
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
8. **Three encoding paths**: Frame (encode_image), Chunk (config-gated, default disabled, -c copy + encode_video), Text (encode_text). All three reuse the shared embedder.
9. **When adding new dependencies**: add to `requirements.txt` AND to `Dockerfile`.
10. **Search result format**: All results include `precision_level` (frame/chunk/text/label), `precise_start/end` (text 也有 scene 起止作为锚点), `match_paths`, and `thumbnail_url`. Merge 时帧簇优先，text 与非重叠帧的 text 按路径权重排序。
11. **Frontend**: Dashboard.tsx (~380 lines) orchestrates all state and renders imported components from `components/`. Component files: icons, LeftSidebar, ParameterPanel, PipelineBar, VideoSummaryCard, VideoSearchCard, HistoryPanelContent, SettingsPage. Utility functions in `utils/helpers.ts`. TypeScript types in `types/index.ts` mirror backend Pydantic schemas.

## Python Environment

- Python 3.12
- FastAPI, SQLAlchemy async, asyncpg, pgvector
- transformers, torch (CUDA 12.4), modelscope, qwen-vl-utils
- openai, httpx, Pillow
- pytest, pytest-asyncio
