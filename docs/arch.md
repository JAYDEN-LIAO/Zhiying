# Cerno Architecture

> Version: 0.1 | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector
> Frontend: React 19 + Vite + Tailwind CSS

## System Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     Client (CLI/Browser / React Frontend)                        │
└──────────────────┬────────────────────────────┬──────────────────┬───────────────┘
                   │ POST /videos/upload        │ POST /search/semantic │ GET /videos/
                   ▼                            ▼                        ▼
┌─────────────────────────────┐  ┌─────────────────────────────┐  ┌──────────────────┐
│     FastAPI (main.py)       │  │   SearchEngine              │  │  React Dashboard │
│                             │  │   ┌─ vector cosine search  │  │  ┌── video player │
│  ┌─ api/routes.py ────────┐ │  │   ├─ fulltext tsvector     │  │  ├── pipeline UI  │
│  │ upload_video()         │ │  │   ├─ label JSONB @>        │  │  ├── search panel │
│  │ register_video()       │ │  │   └─ RRF fusion            │  │  └── history list │
│  │ get_video()            │ │  └──────────┬──────────────────┘  └──────────────────┘
│  │ list_videos()          │ │             │
│  │ delete_video()         │ │  ┌──────────▼──────────────────┐
│  │ stream_video()         │ │  │   Embedder (local GPU)      │
│  │ search_semantic()      │ │  │   encode_text("query")      │
│  │ search_text()          │ │  │   encode_image(frame)       │
│  │ search_hybrid()        │ │  │        → 2048-dim vector    │
│  └───────────┬───────────┘ │  └──────────────────────────────┘
└──────────────┬─────────────┘
               │
               ▼
┌─────────────────────────────┐
│  VideoService               │
│  process_video(video_id)    │
│    → PipelineEngine.run()   │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  PipelineEngine             │
│  5-stage async workflow     │
│                             │
│  Phase 1: QC + Segmentation│
│  Keyframe Extraction        │
│  Phase 3: Transcript Align  │
│  Phase 4: Caption + Embed   │
│  Phase 5: Summarize         │
│  Persist: Write to DB       │
└─────────────────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  PostgreSQL + pgvector      │
│                             │
│  videos (metadata, summary) │
│  scenes (embedding, caption)│
│  transcripts (full text)    │
└─────────────────────────────┘
```

## Pipeline Detail

```
Phase 1 (QC + Split)
  ├─ QC (FFmpeg blackdetect/silencedetect) → qc_result
  │   写入 ctx.qc_result, ctx.duration
  ├─ Audio Extraction (可选, FFmpeg) → audio_path
  ├─ Transcribe (faster-whisper, 可选) → words[]
  └─ Segment (time-based 或 TransNetV2) → scenes[]
      每个 scene: {scene_index, start_sec, end_sec, keyframe?}

  ↓

Keyframe Extraction (Phase 1→4 间)
  └─ FFmpeg pipe → memory (numpy ndarray, 无磁盘 I/O)
      对每个 scene 的中点时间戳抽取一帧
      存入 scene.keyframe (H, W, C) uint8

  ↓

Phase 3 (Alignment, 可选)
  └─ Align words[] 到 scenes 按时间戳
      → scene.aligned_transcript

  ↓

Phase 4 (Understanding)
  ├─ Caption (Qwen-VL API / 本地 Qwen-VL) → scene.caption
  │   记忆窗口: 传入 prev_caption 作为上下文
  └─ Embed (Qwen3-VL-Embedding, 本地 GPU) → scene.embedding
      编码图像 → 2048-dim 向量

  ↓

Phase 5 (Summarization)
  └─ LLM (DeepSeek API) → 结构化 JSON summary
      {one_liner, scenes_summary, tags, main_topics, main_entities}

  ↓

Persist
  ├─ bulk_insert_scenes → scenes 表
  ├─ insert transcript → transcripts 表
  └─ update video → videos 表 (duration, qc_result, summary)
```

## Module Dependency

```
main.py
  ├─ core/db.py              (engine, AsyncSessionLocal, init_db)
  ├─ core/config_loader.py   (YAML + .env 加载)
  └─ api/router.py
        └─ api/routes.py     (所有 API 端点)
              ├─ api/deps.py         (FastAPI 依赖: get_db)
              ├─ core/models.py      (ORM: Video, Scene, Transcript)
              ├─ core/schemas.py     (Pydantic DTOs)
              ├─ core/repository.py  (DB 数据访问层)
              ├─ core/search.py      (pgvector + GIN 全文检索 SQL)
              ├─ services/video_service.py
              │     └─ pipeline/engine.py
              │           ├─ pipeline/phase1_qc.py
              │           ├─ pipeline/phase3_alignment.py
              │           ├─ pipeline/phase4_caption.py
              │           ├─ pipeline/phase5_summary.py
              │           ├─ utils/video_util.py          (keyframe extraction)
              │           └─ plugins/factory.py
              │                 ├─ plugins/captioner/qwen_api_captioner.py
              │                 ├─ plugins/captioner/qwen_vl_captioner.py
              │                 ├─ plugins/embedder/qwen_vl_embedder.py
              │                 ├─ plugins/summarizer/vllm_summarizer.py
              │                 ├─ plugins/segmenter/time_based.py
              │                 ├─ plugins/segmenter/transnet_v2.py
              │                 ├─ plugins/qc/basic_qc.py
              │                 └─ plugins/*/ (detector, ocr, grounding, transcriber — stubs)
              └─ pipeline/search_engine.py
                    ├─ core/search.py
                    └─ plugins/embedder/qwen_vl_embedder.py

core/
  ├─ interfaces.py         ← 9 个插件 ABC
  ├─ models.py             ← ORM: Video, Scene, Transcript
  ├─ schemas.py            ← Pydantic v2 DTOs + JSONB 校验模型
  ├─ repository.py         ← DB 数据访问层
  ├─ search.py             ← pgvector + GIN 全文检索 + 混合检索 SQL
  ├─ db.py                 ← 异步引擎/Session 工厂/表初始化
  ├─ config_loader.py      ← YAML + .env 加载
  ├─ config_schema.py      ← Pydantic 配置校验
  ├─ prompt_loader.py      ← Prompt 模板加载
  ├─ status_tracker.py     ← Pipeline 进度持久化
  └─ exceptions.py         ← 自定义异常

frontend/
  ├─ src/
  │   ├─ App.tsx           ← 入口: 渲染 Dashboard
  │   ├─ Dashboard.tsx     ← 主工作台: 视频播放器/Pipeline 卡片/搜索/历史
  │   ├─ main.tsx          ← React DOM 挂载
  │   ├─ index.css         ← 全局样式 + Tailwind
  │   ├─ services/api.ts   ← API 调用封装 + 轮询工具函数
  │   ├─ types/index.ts    ← TypeScript 类型定义 (镜像 backend schemas)
  │   └─ mockData.ts       ← Pipeline 阶段定义 + 进度计算逻辑
  ├─ package.json          ← React 19, Vite 6, Tailwind 4
  ├─ vite.config.ts        ← Vite 配置 + /api 代理到 localhost:8000
  └─ tsconfig.json
```

## Plugin System

```
plugins/factory.py:
  load_plugin(config, "captioner")
    → import plugins.captioner.qwen_api_captioner
    → instantiate QwenAPICaptioner(base_url, api_key, ...)
    → return instance (or None if disabled)

  backend → 模块名/类名 映射表:
    _MODULE_OVERRIDES:  (category, backend) → .py 文件名
    _CLASS_OVERRIDES:   (category, backend) → 实现类名

config.yaml controls which backends to load:

  captioner:  qwen_api         → calls Qwen-VL-Max API (DashScope)
  embedder:   qwen3_vl_embedding → runs local GPU model (Qwen3-VL-Embedding-2B)
  summarizer: vllm             → calls DeepSeek API via OpenAI-compatible endpoint
  segmenter:  time_based       → fixed-interval (no DL deps)
  qc:         native_qc        → FFmpeg-based (asyncio subprocess)
  transcriber: null             → disabled (placeholder)
  detector:   null              → disabled (placeholder)
  ocr:        null              → disabled (placeholder)
  grounding:  null              → disabled (placeholder)
```

## Search Architecture

```
Semantic Search: POST /api/v1/search/semantic
  User Query "a man in black"
    ↓
  SearchEngine (lazy init, cached in app.state._searcher)
    ├─ Embedder.encode_text() → 2048-dim vector
    ├─ _vector_search()   → pgvector cosine_distance (scenes.embedding)
    ├─ _fulltext_search() → ts_rank (scenes.search_vector, GIN-indexed)
    ├─ _label_search()    → JSONB @> entities.label (if entities exist)
    └─ RRF fusion (k=60) → ranked results (similarity ≥ min_similarity)

Text Search: GET /api/v1/search/text?q=...
  └─ core.search.full_text_search() — 直接 GIN tsvector 检索

Hybrid Search: POST /api/v1/search/hybrid
  └─ core.search.hybrid_search() — SQL 内加权融合 vector_score + text_score
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/v1/videos | 注册视频任务 (JSON body) |
| POST | /api/v1/videos/upload | 上传视频文件 (multipart) + 触发后台 Pipeline |
| GET | /api/v1/videos/ | 视频列表 (按创建时间降序) |
| GET | /api/v1/videos/{id} | 视频详情 + 关联 scenes + transcript |
| GET | /api/v1/videos/{id}/status | 轻量进度查询 |
| GET | /api/v1/videos/{id}/stream | 视频流式播放 (支持 Range) |
| DELETE | /api/v1/videos/{id} | 删除视频 (CASCADE scenes/transcript) |
| GET | /api/v1/search/text?q= | 全文检索 |
| POST | /api/v1/search/semantic | 语义搜索 (服务端自动编码 query→vector) |
| POST | /api/v1/search/hybrid | 混合检索 (vector + text 加权融合) |

## Frontend Architecture

```
React 19 + Vite 6 + Tailwind CSS 4
  │
  ├── App.tsx          ← 根组件
  ├── Dashboard.tsx    ← 主工作台布局 (三栏式)
  │   ├── LeftSidebar    ← 功能导航 + 上传触发
  │   ├── Main Content   ← 视频播放器 + Pipeline Stage Cards (滑动窗口)
  │   └── Right Sidebar  ← VideoSummaryCard + VideoSearchCard
  ├── HistoryPanel     ← 视频历史列表 (侧滑面板)
  ├── StageCard        ← Pipeline 阶段卡片 (完成/进行中/等待中)
  ├── VideoSummaryCard ← 视频摘要展示
  └── VideoSearchCard  ← 语义搜索面板

数据流:
  Dashboard mount → GET /api/v1/videos/ 拉取列表
  选择视频 → GET /api/v1/videos/{id} 每 3s 轮询 (处理中时)
  上传触发 → POST multipart → 自动选中新视频
  搜索 → POST /api/v1/search/semantic → 结果列表

Vite 开发代理:
  /api → http://localhost:8000 (dev)
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
| **React + Vite + Tailwind** | Fast dev experience, minimal config, glass-panel UI |
| **Unified API envelope** | All responses wrapped in `{code, message, data}` |

## Current Status

| Module | Status | Note |
|---|---|---|
| Pipeline Core | ✅ | Phase 1→Keyframe→3→4→5→Persist verified E2E |
| Semantic Search | ✅ | 234ms latency (cached embedder) |
| Fulltext Search | ✅ | tsvector via DB trigger |
| API Routes | ✅ | 10 endpoints: CRUD, stream, 3 search modes |
| Frontend Dashboard | ✅ | React 19 + Vite + Tailwind, video player, pipeline UI, search |
| Config Schema | ✅ | Pydantic v2 validation for config.yaml |
| DB Layer | ✅ | Async engine, pgvector, init_db(), triggers |
| Object Detection | 📋 | YOLO plugin shell only |
| OCR | 📋 | PaddleOCR shell only |
| Grounding | 📋 | Florence-2 shell only |
| Audio Transcription | 📋 | faster-whisper shell only |
| Export APIs | 📋 | Clip, JSON, Markdown, Merge |
| Health / Reindex | 📋 | maintenance_routes.py shell |
