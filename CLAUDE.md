# Cerno Project Context for AI Agents

## One-Line Summary

Cerno is a **video analytics engine** (v0.10) that ingests videos, runs a **declarative operation DAG** (12 operations with event-driven orchestration), generates **4-path encodings** (frame-level 1fps + chunk-level sliding window + text-level caption semantics + track-level crop embeddings), runs **YOLO11 object detection + BoT-SORT tracking** as an optional add-on with **global ReID merge** (Qwen3-VL-Embedding cross-modal matching), enables **5-path parallel semantic search** (frame + chunk + text + label + track, chunk 配置关闭默认不启用), exposes everything via **FastAPI + PostgreSQL/pgvector**, and provides a **4-level parameter system** (scene type → perception modules → function switches → advanced params) that controls pipeline execution.

## Quick File Map

```
main.py                    — FastAPI app, lifespan, exception handlers, shared embedder
api/routes.py              — Transitional re-export (endpoints split into sub-routers)
api/video_routes.py        — Video CRUD + upload + stream + thumbnail endpoints
api/search_routes.py       — Semantic search + pipeline/operations endpoints
api/settings_routes.py     — System settings (API keys) endpoints
api/router.py              — Assembles sub-routers under /api/v1 prefix
api/deps.py                — FastAPI dependency injection (get_db)
api/schemas.py             — Shared API DTOs (APIResponse, search/status models)
api/detection_routes.py    — Detection data API endpoint (GET /videos/{id}/detection/data)
api/export_routes.py       — Export endpoints: clip/frames/track/thumbnails (7 endpoints, GET+POST)
api/maintenance_routes.py  — (stub) planned health/reindex endpoints
core/models.py             — ORM: Video, Scene, Transcript, FrameEmbedding, Chunk, FrameDetection, Track, TrackEmbedding (8 tables)
core/schemas.py            — Pydantic v2 DTOs + JSONB validation models
core/interfaces.py         — 8 abstract base classes (ABCs) + Scene/VideoContext dataclasses
core/search.py             — 4 search functions: frame/chunk/text/track
core/repository.py         — Data access layer + bulk_insert_frames/chunks
core/db.py                 — Async engine, init_db(), incremental migration (pgvector, text_embedding)
core/config_loader.py      — Loads config.yaml, merges .env secrets via _ENV_OVERRIDES
core/prompt_loader.py      — Prompt template loader (config/prompts.yaml)
core/status_tracker.py     — Pipeline progress + dynamic operation-based weight calculation
core/exceptions.py         — Custom exceptions
pipeline/engine.py         — DAG executor: EventDrivenScheduler (event-driven, ~200 lines)
pipeline/operations.py     — Operation registry: ALL_OPERATIONS declaration with gates/deps/labels
pipeline/runners/          — 12 operation runners (one per processing unit):
  runners/base.py            — OperationRunner ABC + PipelineContext + Operation dataclass
  runners/duration.py        — ffprobe duration detection
  runners/segmentation.py    — TransNetV2 scene segmentation
  runners/transcription.py   — Audio extraction + faster-whisper transcription
  runners/keyframe.py        — 1fps frame pool extraction + thumbnails
  runners/alignment.py       — Transcript word-to-scene alignment
  runners/caption.py         — Dual-mode: native_video (Qwen2.5-VL GPU) / vlm_llm (Qwen API)
  runners/summary.py         — Dual-mode: Python aggregator / DeepSeek API LLM
  runners/frame_encode.py    — 1fps batch image encoding → frame_embeddings
  runners/chunk_encode.py    — Sliding window video encoding → chunks (config-gated)
  runners/text_encode.py     — Text semantic encoding → scenes.text_embedding
  runners/detection.py       — YOLO11 object detection + BoT-SORT tracking + scene entity aggregation
  runners/track_encode.py    — Track crop cross-modal embedding + global ReID merge
pipeline/search_engine.py  — 5-path parallel recall (frame/chunk/text/label/track) + scene-merge dedup
plugins/factory.py         — Dynamic plugin loader (CATEGORY_MAP, _MODULE_OVERRIDES, _CLASS_OVERRIDES)
plugins/detector/yolo.py   — YOLO11s detector (batch GPU inference, asyncio.to_thread)
config/config.yaml         — Main config: server/db/storage/plugins/pipeline
config/config_schema.py    — Pydantic config validation
config/prompts.yaml        — Caption/Summarizer/Grounding prompt templates
frontend/src/Dashboard.tsx — Main workspace (orchestrator, ~400 lines)
frontend/src/components/    — Split components: icons, LeftSidebar, ParameterPanel, PipelineBar,
                              VideoSummaryCard, VideoSearchCard, HistoryPanelContent, SettingsPage,
                              DetectionOverlay, DetectionPanel, DetectionTimeline,
                              MetadataPanel, ExportMenu
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

PipelineEngine.run() (DAG-based, gate-driven from L2/L3 params):
  Gate Filter → EventDrivenScheduler (v0.10)
    Each operation runs as its own asyncio task, awaits upstream done events:
    duration → segmentation + transcription (parallel)
      → keyframes + alignment (parallel)
        → detection + caption + frame_encode (parallel, chunk_encode gated by config)
          → summary + text_encode (parallel)
            → track_encode (depends on detection + frame_encode)
  → _persist() → mark_completed()

Each operation declared in pipeline/operations.py with:
  - gate: lambda video, config → bool (parameter-driven enable/disable)
  - depends_on: list[str] (DAG dependency edges)
  - required_plugins: list[str] (auto-loaded by engine)
  - label/description: (frontend progress bar labels)

Adding a new perception module (e.g. YOLO detector):
  1. Write runner class in pipeline/runners/detection.py
  2. Add one Operation(...) entry to pipeline/operations.py ALL_OPERATIONS
  3. Add column to Video model + field to PipelineParams (unavoidable)
  → engine.py needs ZERO changes.

Search (5-path parallel, v0.10):
  text query → embedder.encode_text() → 2048-dim vector (shared, once)
  → 5 parallel tasks:
    _frame_search()  → frame_embeddings table, 1fps per-frame precision
    _chunk_search()  → chunks table, sliding window process semantics
    _text_search()   → scenes.text_embedding, caption+ocr+transcript 语义
    _label_search()  → JSONB @> entities.label (精确匹配场景内物体标签)
    _track_search()  → track_embeddings table, crop跨模态嵌入, 返回具体物体
  → merge: frame clusters (≤4s gap), chunk/text去重叠, track独立按 (video_id, track_id) 去重
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
- **Four encoding paths exist**: Frame (1fps per-frame), Chunk (config-gated, default disabled, `-c copy` + 480p 5fps preprocessing + encode_video), Text (caption+ocr+transcript 语义), Track (crop cross-modal embedding). All four reuse the shared embedder.
- **Parameter system (v0.10)**: 4-level hierarchy — L1=Scene Type (general/meeting/surveillance/text_recognition/custom), L2=Perception Modules (vision/audio/ocr/caption/detection, plus detection-grayed), L3=Function Switches (search_index/summary + summary_mode[native_video/vlm_llm]), L4=Advanced Params (language/sample_fps/segment_threshold/caption_with_context/summary_detail). Detection uses dual-gating: server-level (config.yaml backend: yolo/null) AND per-video (detection_enabled toggle). Upper levels set defaults for lower levels. Pipeline uses `PipelineParams` Pydantic model with cross-field validation.
- **Operation DAG (v0.10)**: Pipeline uses EventDrivenScheduler — 12 operations declared in `pipeline/operations.py` with gate conditions, dependencies, and labels. Each operation runs as its own asyncio task, awaiting upstream `asyncio.Event` signals. Engine filters by gate → spawns ready tasks → event-driven execution (no static batches). Detection operation uses dual-gate pattern (config AND video.detection_enabled). Adding a new perception module only requires a new runner + one Operation entry — engine.py is never touched.
- **Summary dual-mode (v0.10)**: `summary_mode` 控制 caption+summary 路径。`native_video`（默认）→ CaptionRunner 内部路由到 Qwen2.5-VL-7B 本地 GPU，SummaryRunner 内部路由到纯 Python 聚合器。`vlm_llm` → CaptionRunner 动态切换为 Qwen-VL-Max API captioner，SummaryRunner 内部路由到 DeepSeek API。双模式切换完全封装在 runner 内部，engine.py 不感知。Summary mode 变更需新建视频记录（不可增量）。
- **Incremental processing**: Completed videos can re-run summary or search index independently via `run_incremental()`. Non-L3 param changes (including summary_mode) require creating a new video record (reuse file via `POST /videos/reuse`).

## Database Tables (8)

| Table | Key Columns | Purpose |
|---|---|---|
| `videos` | id, status, progress, status_detail, summary(JSONB), content_type, summary_mode (native_video/vlm_llm), perception switches (vision/audio/ocr/grounding/caption/detection_enabled/summary_enabled), function switches (search_index_enabled), advanced params (sample_fps, segment_threshold, caption_with_context, summary_detail), language | Video master |
| `scenes` | id, video_id(FK), scene_index, text_embedding(Vector2048), caption, ocr_text, aligned_transcript, entities(JSONB) | Core search grain (text_embedding = caption+ocr+transcript 语义) |
| `transcripts` | id, video_id(FK, UNIQUE), full_text, words(JSONB) | Speech transcripts |
| `frame_embeddings` | id, video_id(FK), timestamp_sec, embedding(Vector2048), is_keyframe | 1fps frame vectors |
| `chunks` | id, video_id(FK), chunk_index, start_sec, end_sec, embedding(Vector2048) | Sliding window vectors |
| `frame_detections` | id, video_id(FK), track_id, timestamp_sec, class_name, confidence, bbox(JSONB) | Per-frame YOLO detection results (15fps, indexed by timestamp) |
| `tracks` | id, video_id(FK), track_id, class_name, first_seen, last_seen, frame_count, segments(JSONB) | BoT-SORT cross-frame track summaries |
| `track_embeddings` | id, video_id(FK), track_id, class_name, embedding(Vector2048), timestamp_sec, bbox(JSONB) | Track crop cross-modal vectors, for track-path search + global ReID |

## Current Implementation Status

| Area | Status | Files |
|---|---|---|
| Pipeline core (DAG) | ✅ Complete (EventDrivenScheduler v0.10) | engine.py, operations.py, runners/* (12 ops) |
| Frame/Chunk/Text encoding | ✅ Complete | runners/frame_encode, chunk_encode, text_encode |
| Object Detection + Tracking | ✅ Complete | plugins/detector/yolo.py, runners/detection.py, api/detection_routes.py, DetectionOverlay.tsx |
| Track Encoding + Global ReID | ✅ Complete | runners/track_encode.py (Phase 1: crop embedding, Phase 2: global offline ReID merge) |
| Semantic search (5-path + label) | ✅ Verified | search_engine.py + api/search_routes.py (frame+chunk+text+label+track) |
| Captioner (local GPU + API) | ✅ Verified | plugins/captioner/qwen25_vl_captioner.py + qwen_api_captioner.py |
| Embedder (local GPU) | ✅ Verified | plugins/embedder/qwen_vl_embedder.py — preloaded at startup, shared via app.state.embedder |
| Summarizer (aggregator + API) | ✅ Verified | runners/summary.py dual-path: Python aggregator (default) + vllm_summarizer.py (vlm_llm fallback) |
| Segmenter (TransNetV2) | ✅ Verified | plugins/segmenter/transnet_v2.py |
| Segmenter (time-based) | ✅ Verified | plugins/segmenter/time_based.py |
| Transcriber (faster-whisper) | ✅ Plugin ready | plugins/transcriber/faster_whisper.py |
| DB + migrations | ✅ Done | db.py, models.py, init_db() |
| Prompt templates | ✅ Done | config/prompts.yaml |
| Pipeline real-time status | ✅ Done | status_tracker.py with dynamic weight allocation + sub_progress per-operation interpolation |
| Parameter system (4-level) | ✅ Done | core/schemas.py PipelineParams + model_validator; config/presets.yaml; frontend ParameterPanel with cascade |
| Incremental processing | ✅ Done | pipeline/engine.py run_incremental(); services/video_service.py incremental_process() |
| Settings API + API key mgmt | ✅ Done | core/settings_service.py; GET/PUT /api/v1/settings |
| Frontend dashboard | ✅ Done | Dashboard.tsx + 15 components (React 19 + Tailwind 4) — 参数面板四级联动, 动态 PipelineBar, 系统设置页, 历史记录搜索, Canvas bbox 渲染, 物体列表+时间轴, 元数据卡片, 导出菜单 |
| Object Detection (YOLO) | ✅ Done | plugins/detector/yolo.py — YOLO11s + ByteTrack/BoT-SORT, dual-gate control, frontend DetectionOverlay |
| Global ReID merge | ✅ Done | runners/track_encode.py — Qwen3-VL-Embedding cross-modal merge (0.85 cos threshold, 180s time gate, 5 constraints) |
| Track search path | ✅ Done | core/search.py track_vector_search + search_engine.py _track_search — encode_text(query) vs track crop embeddings, 返回具体物体 |
| Video Metadata Extraction | ✅ Done | utils/metadata.py — 三级提取 (pymediainfo → exiftool → ffprobe), GPS/device/codec |
| Clip Export | ✅ Done | services/export_service.py + api/export_routes.py — 流复制视频片段导出 |
| Frames/Thumbnails Export | ✅ Done | 帧序列 zip / 全部场景缩略图 zip 导出 |
| Track Segments Export | ✅ Done | 按 segments 字段分段导出 track 视频 → zip |
| Track Thumbnail Download | ✅ Done | 全尺寸物体裁剪图下载 |
| OCR | ⬜ Shell only | plugins/ocr/ |
| Grounding | ⬜ Shell only | plugins/grounding/ |
| Health/Reindex | ⬜ Shell only | api/maintenance_routes.py |

## Agent Instructions

> Read this section last. It tells you how to behave in this project.

1. **Don't modify `.env`** — it contains API keys and is gitignored.
2. **Don't delete empty `__init__.py` files** — they're intentional package markers.
3. **Don't delete empty route/service files** (`api/maintenance_routes.py`) — it's a planned stub for future endpoints. `api/export_routes.py` was a stub but is now active (7 endpoints for clip/frames/track/thumbnails). `api/video_routes.py` and `api/search_routes.py` are active route files, NOT stubs.
4. **Config-driven design + operation registration**: when adding a new perception module, write a runner class in `pipeline/runners/`, add one `Operation(...)` entry to `pipeline/operations.py` `ALL_OPERATIONS`. For new plugin backends, register in `plugins/factory.py` `CATEGORY_MAP` / `_MODULE_OVERRIDES` / `_CLASS_OVERRIDES`. No hardcoded model references in business logic.
5. **Sync vs Async**: all `core/interfaces.py` methods are `async def`. If your plugin runs synchronous model inference, wrap it with `asyncio.to_thread()`. Never call `model.predict()` directly in an async function.
6. **Search paths**: `config_loader.py` and `prompt_loader.py` use `Path(__file__).resolve().parent.parent` to locate the project root. Keep this convention.
7. **Vector dimension**: 2048. All vector columns (scenes.text_embedding, frame_embeddings.embedding, chunks.embedding, track_embeddings.embedding) use `Vector(2048)`. No pgvector HNSW/IVFFlat index (2048 > 2000 limit, but full scan is fine for demo scale).
8. **Four encoding paths**: Frame (encode_image), Chunk (config-gated, default disabled, -c copy + encode_video), Text (encode_text). All three reuse the shared embedder.
9. **When adding new dependencies**: add to `requirements.txt` AND to `Dockerfile`.
10. **Search result format**: All results include `precision_level` (frame/chunk/text/label), `precise_start/end` (text 也有 scene 起止作为锚点), `match_paths`, and `thumbnail_url`. Merge 时帧簇优先，text 与非重叠帧的 text 按路径权重排序。
11. **Frontend**: Dashboard.tsx (~400 lines) orchestrates all state and renders imported components from `components/`. Component files: icons, LeftSidebar, ParameterPanel, PipelineBar, VideoSummaryCard, VideoSearchCard, DetectionPanel, DetectionTimeline, HistoryPanelContent, SettingsPage, DetectionOverlay, MetadataPanel, ExportMenu. Utility functions in `utils/helpers.ts`. TypeScript types in `types/index.ts` mirror backend Pydantic schemas.
12. **Detection gate pattern**: New perception modules that are optional should follow the dual-gate pattern: config-level enable/disable (`plugins.{name}.backend: yolo` vs `null`) AND per-video toggle (`detection_enabled` in PipelineParams). Gate function checks both. This allows server-wide opt-out while letting users control per-video.
13. **Canvas overlay pattern**: The DetectionOverlay uses a `canvas` with `pointerEvents: "none"` for pure rendering, with click/mousemove handlers attached via native `addEventListener` to the parent container. This allows clicks to pass through to video controls while still enabling bbox interaction.

## Python Environment

- Python 3.12
- FastAPI, SQLAlchemy async, asyncpg, pgvector
- transformers, torch (CUDA 12.4), modelscope, qwen-vl-utils
- openai, httpx, Pillow
- pytest, pytest-asyncio
