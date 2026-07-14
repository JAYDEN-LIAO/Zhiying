# Cerno Architecture

> Version: 0.5 | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector
> Frontend: React 19 + Vite 6 + Tailwind CSS 4

## System Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     Client (CLI/Browser / React Frontend)                        │
└──────────────────┬────────────────────────────┬──────────────────┬───────────────┘
                   │ POST /videos/upload        │ POST /search/semantic │ GET /videos/
                   ▼                            ▼                        ▼
┌─────────────────────────────┐  ┌─────────────────────────────┐  ┌──────────────────┐
│     FastAPI (main.py)       │  │   SearchEngine              │  │  React Dashboard │
│                             │  │   ┌─ frame (1fps 精确)     │  │  ┌── video player │
│  ┌─ api/routes.py ────────┐ │  │   ├─ chunk (滑动窗口)      │  │  ├── pipeline UI  │
│  │ upload_video()         │ │  │   ├─ text (caption 语义)    │  │  ├── search panel │
│  │ register_video()       │ │  │   ├─ label (JSONB 精确)     │  │  └── history list │
│  │ get_video()            │ │  │   └─ 按 scene 合并 + 去重   │  └──────────────────┘
│  │ list_videos()          │ │  └──────────┬──────────────────┘
│  │ delete_video()         │ │             │
│  │ stream_video()         │ │  ┌──────────▼──────────────────┐
│  │ get_thumbnail()        │ │  │   Embedder (local GPU)      │
│  │ get_video_status()     │ │  │   encode_text("query")      │
│  │ search_text()          │ │  │   encode_image(frame)       │
│  │ search_hybrid()        │ │  │   encode_video(clip)        │
│  │ search_semantic()      │ │  │        → 2048-dim vector    │
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
│  Keyframe Extraction (1fps) │
│  Phase 3: Transcript Align  │
│  Phase 4: Caption + Embed   │
│  Phase 5: Summarize         │
│  Persist: Write to DB       │
│  Encode Frames: 帧/chunk/文本│
│       三条编码链路持久化      │
└─────────────────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  PostgreSQL + pgvector      │
│                             │
│  videos (metadata, summary) │
│  scenes (embedding, caption)│
│  transcripts (full text)    │
│  frame_embeddings (1fps)    │
│  chunks (滑动窗口)           │
└─────────────────────────────┘
```

## Pipeline Detail

```
Phase 1 (QC + Split)
  ├─ QC (FFmpeg blackdetect/silencedetect) → qc_result
  │   写入 ctx.qc_result, ctx.duration
  │   状态: "质检完成: 检测到 X 段黑屏、Y 段静音"
  ├─ Audio Extraction (可选, FFmpeg) → audio_path
  ├─ Transcribe (faster-whisper, 可选) → words[]
  │   状态: "正在转录音频..."
  └─ Segment (TransNetV2 / time-based) → scenes[]
      每个 scene: {scene_index, start_sec, end_sec, keyframe?}
      状态: "镜头分割完成: 共 N 个场景"

  ↓

Keyframe Extraction (Phase 1→4 间)
  ├─ FFmpeg pipe → memory (numpy ndarray, 无磁盘 I/O)
  │   按 1fps 逐帧抽取，全部存入 scene 帧池
  │   状态: "正在抽取第 X/Y 个场景的关键帧"
  ├─ 中点帧 → scene.keyframe（缩略图用）
  ├─ 均匀选 3-7 帧 → scene._caption_frames（VLM caption 用）
  └─ 三条消费链路复用同一批帧：
      ① 帧级路 → encode_image → frame_embeddings 表
      ② Chunk 路 → encode_video(clip) → chunks 表
      ③ VLM 路 → caption 生成

  ↓

Phase 3 (Alignment, 可选)
  └─ Align words[] 到 scenes 按时间戳
      → scene.aligned_transcript
      状态: "对齐完成: X/Y 个场景已分配转录文本"

  ↓

Phase 4 (Understanding)
  ├─ Caption (Qwen-VL API / 本地 Qwen-VL) → scene.caption
  │   记忆窗口: 传入 prev_caption 作为上下文
  │   状态: "正在描述第 X/Y 个场景"
  └─ Embed (Qwen3-VL-Embedding, 本地 GPU) → scene.embedding
      编码图像 → 2048-dim 向量

  ↓

Phase 5 (Summarization)
  └─ LLM (DeepSeek API) → 结构化 JSON summary
      {one_liner, scenes_summary, tags, main_topics, main_entities}
      状态: "正在生成摘要（N 个场景）..."

  ↓

Persist
  ├─ bulk_insert_scenes → scenes 表
  ├─ insert transcript → transcripts 表
  └─ update video → videos 表 (duration, qc_result, summary, status_detail)

  ↓

Encode Frames (Persist 后, 纯搜索用)
  ├─ a. 帧级路: 逐帧 encode_image → bulk_insert_frames → frame_embeddings 表
  │   状态: "正在编码第 X/Y 个场景的帧向量"
  ├─ b. Chunk 路: 滑动窗口创建 temp clip → encode_video → bulk_insert_chunks → chunks 表
  │     自适应窗口: ≤5s 不切, 5-60s 窗口=时长/2, >60s 窗口=30s/步长=15s
  └─ c. 文本语义路: encode_text(caption) → text_embedding → 更新 scenes 表
```

## Module Dependency

```
main.py
  ├─ core/db.py              (engine, AsyncSessionLocal, init_db)
  ├─ core/config_loader.py   (YAML + .env 加载)
  └─ api/router.py
        └─ api/routes.py     (所有 API 端点, 含视频管理/搜索/上传)
              ├─ api/deps.py         (FastAPI 依赖: get_db)
              ├─ core/models.py      (ORM: Video, Scene, Transcript, FrameEmbedding, Chunk)
              ├─ core/schemas.py     (Pydantic DTOs)
              ├─ core/repository.py  (DB 数据访问层 + 批量写入)
              ├─ core/search.py      (7 种检索函数: vector/fulltext/hybrid/fuzzy/frame/chunk/text)
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
              │                 ├─ plugins/transcriber/faster_whisper.py
              │                 ├─ plugins/qc/basic_qc.py
              │                 └─ plugins/*/ (detector, ocr, grounding — stubs)
              └─ pipeline/search_engine.py
                    ├─ core/search.py
                    └─ plugins/embedder/qwen_vl_embedder.py

core/
  ├─ interfaces.py         ← 9 个插件 ABC
  ├─ models.py             ← ORM: Video, Scene, Transcript, FrameEmbedding, Chunk
  ├─ schemas.py            ← Pydantic v2 DTOs + JSONB 校验模型
  ├─ repository.py         ← DB 数据访问层 + bulk_insert_frames/chunks
  ├─ search.py             ← 7 种检索: vector/fulltext/hybrid/fuzzy/frame/chunk/text
  ├─ db.py                 ← 异步引擎/Session 工厂/表初始化/触发器
  ├─ config_loader.py      ← YAML + .env 加载
  ├─ prompt_loader.py      ← Prompt 模板加载
  ├─ status_tracker.py     ← Pipeline 进度持久化
  └─ exceptions.py         ← 自定义异常

config/
  ├─ config.yaml           ← 主配置文件 (server/database/storage/plugins/pipeline)
  ├─ config_schema.py      ← Pydantic 配置校验
  └─ prompts.yaml          ← Caption/Summarizer/Grounding 提示词模板

frontend/
  ├─ src/
  │   ├─ App.tsx           ← 入口: 渲染 Dashboard
  │   ├─ Dashboard.tsx     ← 主工作台: 视频播放器/Pipeline 进度条/搜索面板/历史面板
  │   ├─ main.tsx          ← React DOM 挂载
  │   ├─ index.css         ← 全局样式 + Tailwind
  │   ├─ mockData.ts       ← Pipeline 阶段定义 + 进度计算逻辑
  │   ├─ services/api.ts   ← API 调用封装 + 轮询工具函数
  │   ├─ types/index.ts    ← TypeScript 类型定义 (镜像 backend schemas)
  │   └─ components/       ← 子组件目录 (AnalysisPanel/HistoryList/Layout/VideoPlayer)
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

  CATEGORY_MAP:       category → package path
  IMPL_CLASS_MAP:     category → expected class name
  _MODULE_OVERRIDES:  (category, backend) → .py filename
  _CLASS_OVERRIDES:   (category, backend) → implementation class name

config.yaml controls which backends to load:

  qc:          native_qc     → FFmpeg-based (asyncio subprocess)
  segmenter:   transnetv2    → TransNetV2 neural network scene detection
  captioner:   qwen_api      → calls Qwen-VL-Max API (DashScope)
  embedder:    qwen3_vl_embedding → runs local GPU model (Qwen3-VL-Embedding-2B)
  summarizer:  vllm          → calls DeepSeek API via OpenAI-compatible endpoint
  transcriber: null          → disabled (faster-whisper plugin exists, opt-in)
  detector:    null          → disabled (placeholder)
  ocr:         null          → disabled (placeholder)
  grounding:   null          → disabled (placeholder)
```

## Search Architecture

```
Semantic Search: POST /api/v1/search/semantic
  User Query "a man in black"
    ↓
  SearchEngine (lazy init, cached in app.state._searcher)
    ├─ Embedder.encode_text() → 2048-dim vector (shared, 只编码一次)
    ├─ 四路并行召回:
    │   ├─ _frame_search()  → frame_embeddings 表, 1fps 帧级精确秒定位
    │   ├─ _chunk_search()  → chunks 表, 滑动窗口多帧原生编码
    │   ├─ _text_search()   → scenes.text_embedding, caption 文本语义
    │   └─ _label_search()  → JSONB @> entities.label (YOLO 激活后)
    └─ 按 scene 合并 + 去重:
        ├─ 帧结果按时间聚类 (间隔 ≤ 4s)
        ├─ chunk/text 结果与帧簇重叠 → 丢弃 (帧精度更高)
        └─ 非重叠 chunk/text 保留, 同 scene 取最高分

  返回格式: {scene_id, video_id, scene_index, precise_start/end,
             precision_level (frame|chunk|text|label),
             match_paths, caption, similarity, thumbnail_url}

Text Search: GET /api/v1/search/text?q=...
  └─ core.search.full_text_search() — 直接 GIN tsvector 检索

Hybrid Search: POST /api/v1/search/hybrid
  └─ core.search.hybrid_search() — SQL 内加权融合 vector_score + text_score

core/search.py 提供的 7 种检索函数:
  1. vector_similarity_search  — pgvector cosine (scenes.embedding)
  2. full_text_search          — GIN tsvector (scenes.search_vector)
  3. hybrid_search             — 向量 + 全文加权融合
  4. fuzzy_transcript_search   — ILIKE 模糊匹配 (transcripts.full_text)
  5. frame_vector_search       — 帧级精确搜索 (frame_embeddings)
  6. chunk_vector_search       — 窗口过程语义搜索 (chunks)
  7. text_vector_search        — 文本语义搜索 (scenes.text_embedding)
```

## Database Schema

```
videos
  ├─ id (UUID PK), status, progress, error_message
  ├─ file_path, file_name, file_size, duration
  ├─ preset, content_type, language
  ├─ audio/vision/ocr/grounding/caption/summary_enabled (感知线路开关)
  ├─ qc_result (JSONB), summary (JSONB)
  ├─ status_detail (管道实时操作描述, 如"正在编码第 5/23 个场景的帧向量")
  └─ created_at, updated_at

scenes
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ scene_index, start_sec, end_sec, keyframe_path
  ├─ embedding (Vector 2048)         — 图像编码向量 (关键帧)
  ├─ text_embedding (Vector 2048)    — caption 文本语义向量
  ├─ ocr_text, aligned_transcript, caption, prev_caption
  ├─ entities (JSONB), search_vector (TSVECTOR, GIN 索引)
  └─ created_at

transcripts
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE, UNIQUE)
  ├─ full_text, words (JSONB, 字词级时间戳)
  ├─ language, duration_transcribed
  └─ created_at

frame_embeddings
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ scene_index, timestamp_sec
  ├─ embedding (Vector 2048), thumbnail_path, is_keyframe
  └─ created_at

chunks
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ scene_index, chunk_index, start_sec, end_sec
  ├─ embedding (Vector 2048), thumbnail_path
  └─ created_at
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
| GET | /api/v1/videos/{id}/thumbnail/{scene_index} | 场景缩略图 |
| DELETE | /api/v1/videos/{id} | 删除视频 (CASCADE scenes/transcript/frames/chunks) |
| GET | /api/v1/search/text?q= | 全文检索 (GIN tsvector) |
| POST | /api/v1/search/semantic | 语义搜索 (四路并行召回 + 按 scene 合并) |
| POST | /api/v1/search/hybrid | 混合检索 (vector + text 加权融合) |

## Frontend Architecture

```
React 19 + Vite 6 + Tailwind CSS 4
  │
  ├── App.tsx          ← 根组件
  ├── Dashboard.tsx    ← 主工作台 (多视图 + 面板布局, 所有主要组件内联)
  │   ├── LeftSidebar    ← 深蓝导航栏: 页面切换 (工作台/系统设置) + 面板开关 (参数/历史)
  │   ├── Main Content   ← Cerno 标志 + 视频播放器 + PipelineBar (两行紧凑卡片, 实时状态详情)
  │   ├── Right Sidebar  ← VideoSummaryCard + VideoSearchCard
  │   ├── ParameterPanel ← 侧滑参数面板: 处理预设/内容类型/语言/感知模块开关/高级参数
  │   └── SettingsPage   ← 全页系统设置: 存储路径/默认处理参数/API 密钥状态
  ├── VideoSummaryCard ← 视频摘要展示 (one_liner + scenes + tags/topics)
  ├── VideoSearchCard  ← 语义搜索面板 (四路召回结果 + 缩略图 + 精度标识)
  ├── PipelineBar      ← 紧凑两行布局: 渐变进度条 + 阶段圆形指示灯 + 实时状态文字
  └── components/      ← 子组件外壳 (AnalysisPanel/HistoryList/Layout/VideoPlayer)

数据流:
  Dashboard mount → GET /api/v1/videos/ 拉取列表
  选择视频 → GET /api/v1/videos/{id} 每 3s 轮询 (处理中时), 展示 status_detail 实时状态
  上传触发 → POST multipart → 自动选中新视频
  搜索 → POST /api/v1/search/semantic → 结果卡片 (点击跳转视频时间点)

Vite 开发代理:
  /api → http://localhost:8000 (dev)
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Plugin + Factory** | Swap models via config.yaml, zero code changes |
| **pgvector over standalone vector DB** | Simpler deployment, transactional consistency |
| **Local GPU for Embedder** | 2048-dim encoding every scene/frame; API latency unacceptable |
| **API for Captioner/Summarizer** | Better quality, zero GPU footprint on 4060 8GB |
| **FFmpeg pipe → memory** | No frame files on disk, reduces I/O |
| **TransNetV2 segmentation** | Neural scene boundary detection, superior to fixed-interval |
| **1fps frame pool + 3 encoding paths** | Frame-level precision + chunk-level process semantics + text semantics |
| **Adaptive chunk windows** | ≤5s scene: skip; 5-60s: half-duration window; >60s: 30s fixed window |
| **Enabled modules only** | pipeline checks each plugin; null = skip gracefully |
| **React + Vite + Tailwind** | Fast dev experience, minimal config, fluid-blob background + card-surface panels |
| **Unified API envelope** | All responses wrapped in `{code, message, data}` |
| **Shared embedder in app.state** | Avoids reloading 4GB model per video |

## Current Status

| Module | Status | Note |
|---|---|---|
| Pipeline Core | ✅ | Phase 1→Keyframe→3→4→5→Persist→Encode Frames verified E2E |
| Semantic Search (4-path) | ✅ | frame + chunk + text + label parallel recall, scene-merge dedup |
| Fulltext Search | ✅ | tsvector via DB trigger |
| Frame-level Encoding | ✅ | 1fps 逐帧 encode_image → frame_embeddings 表 |
| Chunk-level Encoding | ✅ | 自适应滑动窗口 encode_video → chunks 表 |
| Text Semantic Encoding | ✅ | encode_text(caption) → scenes.text_embedding |
| API Routes | ✅ | 11 endpoints: CRUD, stream, thumbnail, status, 3 search modes |
| Frontend Dashboard | ✅ | React 19 + Vite + Tailwind, video player, pipeline bar, search with thumbnails |
| Config Schema | ✅ | Pydantic v2 validation for config.yaml |
| Prompt Templates | ✅ | config/prompts.yaml — caption/summarizer/grounding prompts |
| DB Layer | ✅ | Async engine, pgvector, init_db(), triggers, incremental migration |
| TransNetV2 Segmenter | ✅ | Neural scene boundary detection |
| faster-whisper Transcriber | ✅ | Plugin exists, config-disabled by default |
| Object Detection | 📋 | YOLO plugin shell only |
| OCR | 📋 | PaddleOCR shell only |
| Grounding | 📋 | Florence-2 shell only |
| Export APIs | 📋 | export_routes.py / export_service.py shells |
| Health / Reindex | 📋 | maintenance_routes.py shell |
