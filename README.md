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
| Batch Video Upload (group) | `POST /api/v1/videos/upload/batch` (multiple files, VideoGroup, group pipeline trigger) | ✅ |
| Group Video Switching | Header dropdown, history group cards (stacked + expand), cross-video search, independent detection panel | ✅ |
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
| Object Detection + Tracking | YOLO11s + BoT-SORT (10fps, batch128, 640px) + Canvas overlay | ✅ |
| Face Recognition | SCRFD + ArcFace R50 (512d) identity clustering | ✅ |
| License Plate Recognition | HyperLPR3 (ONNX Runtime) detection + text recognition | ✅ |
| Face Image Search | `POST /api/v1/search/face` (upload image → ArcFace 512d) | ✅ |
| Universal Image Search | `POST /api/v1/search/image` (upload any image → Qwen3-VL-Embedding 2048-dim → frame_embeddings) | ✅ |
| Plate Text Search | `POST /api/v1/search/semantic` (plate path, Levenshtein + ILIKE) | ✅ |
| Track Thumbnail Download | `GET /api/v1/videos/{id}/export/track/{tid}/thumbnail` | ✅ |
| Track Video Export (zip) | `GET/POST /api/v1/videos/{id}/export/track/{tid}` | ✅ |
| Video Clip Export | `GET/POST /api/v1/videos/{id}/export/clip` | ✅ |
| Scene Thumbnails Export (zip) | `GET/POST /api/v1/videos/{id}/export/thumbnails` | ✅ |
| System Settings (API keys + Pipeline) | `GET/PUT /api/v1/settings` + `GET /api/v1/settings/pipeline` | ✅ |
| Frontend Dashboard | React 19 + Vite + Tailwind CSS 4 (unified objects view + face toggle) | ✅ |
| Track Crop Embedding (track search) | `POST /api/v1/search/semantic` (track path) | ✅ |
| Frontend Labels Chinese Localization | 统一 labels.ts 映射中心，zh()/zhLabel()/colorOf() 函数 | ✅ |
| Incremental Processing | summary/search re-run on completed videos | ✅ |
| Video Source Analysis | Rule engine: phone/camera/screen_recording/surveillance/non_camera_source + 监控品牌识别（文件头魔数嗅探 IMKH→海康威视）| ✅ |
| Global ReID Tracklet Stitching | 合并被遮挡/缩放/镜头切换拆分的同一身份 track（在线 ReID + 全局缝合双层） | ✅ |
| Metadata Caching | Extracted metadata cached to DB (fast path <1ms on repeat requests) | ✅ |
| Storage Hygiene (v0.21) | 删除视频 = DB 级联 + 磁盘文件全回收（引用计数, reuse 共享安全, 空组自动清理, 处理中守卫 409） | ✅ |
| Orphan Storage Sweep | `POST /maintenance/sweep`（dry-run/执行）+ `GET /maintenance/storage` + CLI `scripts/sweep_storage.py` | ✅ |

## Architecture Overview

```
Upload → Probe → Pipeline (DAG) → DB → Search → Frontend
         ├─ Duration detection (ffprobe)
         ├─ [搜索路径]  Search Encode @1fps — 与 detection 共享 NVDEC 流 (队列消费)
         ├─ [摘要路径]  Scene Segmentation (TransNetV2) + Audio Transcription (faster-whisper)
         │    ├─ Keyframe Extraction @1fps (NVDEC MJPEG pipe / cv2 stream)
         │    ├─ Captioning — 双模式 (runners/caption.py 内部策略):
         │    │    ├─ native_video (默认): Qwen3-VL-8B 本地 GPU → 结构化 JSON
         │    │    └─ vlm_llm (备选): Qwen-VL-Max API 看图说话
         │    └─ Summarization — 双模式 (runners/summary.py 内部策略)
         ├─ Object Detection — YOLO11s + BoT-SORT (可选，双门控):
         │    └─ 逐帧检测 → 跨帧追踪 → 前端 Canvas 框选
         ├─ Embedding — 4 encoding paths (分辨率可配置, 3-档预设):
         │    ├─ Frame-level: search_encode 自抽帧 + frame_encode 队列消费 (1fps, per-frame)
         │    ├─ Chunk-level: encode_video (sliding window, 默认关闭, 需摘要)
         │    ├─ Text-level: encode_text(caption+ocr+transcript, 需摘要)
         │    └─ Track-level: encode_image(crop) (cross-modal, track search)
         ├─ Face Recognition (可选 — 三门控: config + detection_enabled + face_enabled):
         │    └─ Person crop → SCRFD detect → ArcFace R50 512d embed → identity clustering
         ├─ License Plate (可选 — 三门控: config + detection_enabled + plate_enabled):
         │    └─ Vehicle crop → HyperLPR3 detect + recognize → plate text + type + confidence
         ├─ Global ReID Stitch (track_encode Phase 2, L3 可开关):
         │    └─ 检测缓存多帧 crop → mean pool → cosine 合并同一身份 tracklet
         ├─ Source Analysis (rule engine, on first GET /metadata):
         │    └─ classify_video_source() → phone/camera/surveillance/non_camera
         ├─ StorageManager (v0.21): 删除即清盘 + 孤儿清扫
         │    ├─ 引用追踪: 以 DB 三列 (file/remux/proxy) 判定, reuse 共享安全
         │    ├─ 删除守卫: processing/running → 409; 空组同事务清理
         │    └─ sweep: 磁盘 vs DB 对账 (附属目录按 video_id, mtime 保护上传竞态)
         └─ Shared GPU models (embedder 启动时预加载; captioner 按需加载):
              ├─ Qwen3-VL-Embedding-8B (embedder, FP16, ~16GB, preloaded)
              ├─ Qwen3-VL-8B-Instruct (captioner, BF16, ~16GB, on-demand)
              └─ SCRFD + ArcFace R50 (face recognizer, ONNX, preloaded)
```

- **声明式 DAG 引擎** — 15 个操作注册在 `pipeline/operations.py`（gate 条件 + 依赖边），EventDrivenScheduler 事件驱动执行；搜索/摘要路径解耦，与 detection 共享单 NVDEC 流（生产者-消费者并发）。
- **插件化** — 10 个插件 ABC + 工厂动态加载（config.yaml 换后端零代码改动）；4 条编码路径（frame/chunk/text/track）+ 7 路检索 + 人脸/车牌 + 4 级参数系统。
- **存储卫生 (v0.21)** — 删除即清盘（DB 级联 + 引用追踪）+ 孤儿清扫（`POST /maintenance/sweep` / `scripts/sweep_storage.py`）。
- **架构细节见 `docs/arch.md`**（Pipeline Detail / Database Schema / API Endpoints / Key Design Decisions）。

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
| Object Tracking | BoT-SORT + 在线 ReID (with_reid=true, model="auto"→yolo26n-cls.pt, 10fps, track_buffer=45, match_thresh=0.5) |
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
│   ├── face_routes.py    # Face data + thumbnail endpoints
│   ├── plate_routes.py   # Plate data + thumbnail endpoints
│   ├── export_routes.py  # Export: clip / frames / track / thumbnails (7 endpoints)
│   └── maintenance_routes.py  # 存储清扫: POST /maintenance/sweep + GET /maintenance/storage
├── core/                 # DB models, schemas, search, config
│   ├── db.py             # Async engine, init_db(), incremental migration
│   ├── models.py         # ORM: Video, Scene, Transcript, FrameEmbedding, Chunk
│   ├── schemas.py        # Pydantic DTOs + JSONB validation
│   ├── repository.py     # Data access layer + bulk_insert_frames/chunks
│   ├── search.py         # 6 async search functions: frame/chunk/text/track/plate/face
│   ├── interfaces.py     # 10 abstract plugin base classes
│   ├── config_loader.py  # YAML + .env loading with env var overrides
│   ├── prompt_loader.py  # Prompt template loader
│   ├── status_tracker.py # Pipeline progress persistence
│   ├── settings_service.py # API key management (settings.json backed)
│   ├── storage_manager.py # 存储管理: 路径解析/引用追踪/删除清盘/孤儿清扫
│   └── exceptions.py     # Custom exceptions
├── config/               # Configuration
│   ├── config.yaml       # Main config (server/db/storage/plugins/pipeline)
│   ├── config_schema.py  # Pydantic config validation
│   └── prompts.yaml      # Caption/Summarizer/Grounding prompt templates
├── pipeline/             # Pipeline DAG orchestrator + runners
│   ├── engine.py         # DAG executor: gate filter → EventDrivenScheduler
│   ├── operations.py     # Operation registry: ALL_OPERATIONS with gates/deps/labels
│   ├── runners/          # 15 operation runners (one per processing unit)
│   │   ├── duration.py, segmentation.py, transcription.py
│   │   ├── keyframe.py, alignment.py, caption.py, summary.py
│   │   ├── detection.py (YOLO11 + BoT-SORT), search_encode.py
│   │   ├── frame_encode.py, chunk_encode.py, text_encode.py
│   │   ├── track_encode.py, face.py, plate.py
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
│   ├── export_service.py # Export business logic (clip/frames/track/thumbnails)
├── utils/                # FFmpeg tools + metadata extraction
│   ├── video_util.py     # FFmpeg subprocess helpers (extract audio/keyframes/duration)
│   ├── metadata.py       # Video metadata extraction (pymediainfo/exiftool/ffprobe)
│   └── video_source.py   # Video source classification (rule engine: phone/camera/surveillance/...)
├── frontend/             # React + Vite + Tailwind dashboard
│   ├── public/
│   │   └── cerno.svg     # App logo
│   ├── src/
│   │   ├── Dashboard.tsx # Main workspace (~430 lines, orchestrates state + group state + detectionVideoId)
│   │   ├── components/   # 20 UI components
│   │   │   ├── Sidebar.tsx, Header.tsx, SlideOutPanel.tsx
│   │   │   ├── ParameterPanel.tsx, PipelineBar.tsx
│   │   │   ├── VideoSection.tsx, VideoPlayer.tsx
│   │   │   ├── VideoSummaryCard.tsx, VideoSearchCard.tsx
│   │   │   ├── HistoryPanelContent.tsx, SettingsPage.tsx, RightPanel.tsx
│   │   │   ├── DetectionOverlay.tsx, DetectionPanel.tsx, DetectionTimeline.tsx
│   │   │   ├── VideoInfoCard.tsx, ExportMenu.tsx, icons.tsx
│   │   ├── hooks/        # 8 custom hooks
│   │   │   ├── useDetectionData.ts, useHEVCCapability.ts, useParameterForm.ts
│   │   │   ├── useProxyStatus.ts, useSearch.ts, useStreamReady.ts, useVideoPolling.ts
│   │   ├── utils/helpers.ts  # Shared helpers (fmtDuration, fmtDate, formatSec)
│   │   ├── labels.ts        # YOLO COCO 类名英→中映射 + 颜色表
│   │   ├── services/api.ts
│   │   └── types/index.ts
│   ├── package.json
│   └── vite.config.ts
├── models/               # Local model weights (gitignored)
├── data/                 # Video storage & artifacts (gitignored)
├── config/               # YAML config, prompts, schema
├── scripts/              # 运维工具: sweep_storage.py 存储清扫 CLI (默认 dry-run, --apply 执行)
└── docs/                 # Design documents + search architecture docs
```

## Development Status

- **v0.21 — Storage Hygiene & Management**: 删除视频 = DB 级联 + 磁盘全回收（StorageManager 按 DB 引用追踪，reuse 共享文件只在最后引用删除时清理，空组同事务自动清理，处理中守卫 409 + `RUNNING_VIDEOS` 注册表闭合竞态）；批量 DELETE 替代 ORM 全量 load（删大视频性能修复）；`POST /maintenance/sweep`（dry-run/执行）+ `GET /maintenance/storage` + CLI `scripts/sweep_storage.py` 孤儿清扫（sweep 按 video_id 判定附属目录、mtime 保护上传竞态）；trackthumb 导出泄漏修复；人脸/检测/车牌缩略图缺失 404 兜底；前端删除二次确认 + processing 禁用 + 释放空间提示。
- **维护记录**: 清理废弃的前端 `DetectionContext`/`mockData`，进度阶段统一由 `/pipeline/operations` 按视频参数动态返回；补充 Python、前端缓存及本地环境文件的忽略规则。
- **v0.20 — Dual-layer ReID**: 在线 BoT-SORT ReID（`with_reid` + yolo26n-cls 特征, 遮挡/交叉保持身份）+ 全局 tracklet 缝合（detection 缓存 crop → mean pool → cosine ≥0.85 合并同一身份, segments 时序检查）。长视频友好（track_encode 零 seek）。
- **v0.19 — Multi-Video Group**: 批量上传 + VideoGroup 分组 + 组参数同步启动 + 前端历史堆叠/展开 + 组内切换 + 跨视频搜索 + 独立检测面板。
- **v0.18 — Universal Image Search + 中文化**: `POST /search/image` 通用图搜（独立 `search_image_only` 路径，帧不聚类精确到秒）+ 前端标签中文化 labels.ts。
- **Planned**: Grounding (Florence-2), OCR
