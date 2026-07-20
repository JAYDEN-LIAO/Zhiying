# Cerno Architecture

> Version: 0.8 | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector
> Frontend: React 19 + Vite 6 + Tailwind CSS 4

## System Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     Client (CLI/Browser / React Frontend)                        │
└──────────────────┬────────────────────────────┬──────────────────┬───────────────┘
                   │ POST /videos/upload        │ POST /search/semantic │ GET /videos/
                   │ + PUT /videos/{id}/params  │                       │
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
│  │ search_semantic()      │ │  │   encode_image(frame)       │
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
│  Operation DAG executor      │
│                             │
│  Batch 0: [duration]        │
│  Batch 1: [seg, transcribe]│
│  Batch 2: [keyframes, align]│
│  Batch 3: [detect, caption, frame_e]│
│  Batch 4: [summary, text_e] │
│  Persist: Write to DB       │
│  3-path encoding runs in     │
│  parallel with other ops     │
└─────────────────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  PostgreSQL + pgvector      │
│                             │
│  videos (metadata, summary) │
│  scenes (text_embedding, caption)│
│  transcripts (full text)    │
│  frame_embeddings (1fps)    │
│  chunks (滑动窗口)           │
└─────────────────────────────┘
```

## Parameter System (v0.8)

```
4-level hierarchy controlling pipeline execution:

L1: Scene Type (1 of 5)
  ├─ general       → all modules balanced open
  ├─ meeting       → audio+ocr forced ON, transcript core
  ├─ surveillance  → audio OFF, summary OFF, detection ON
  ├─ text_recognition → ocr ON, caption OFF, audio OFF
  └─ custom        → user-modified preset, auto-saved to localStorage

L2: Perception Modules (6 switches, 1 grayed)
  ├─ vision_enabled   → frame processing master switch
  ├─ audio_enabled    → transcription (grayed when plugin disabled)
  ├─ ocr_enabled      → text from frames (grayed when plugin disabled)
  ├─ caption_enabled  → VLM scene description
  ├─ detection_enabled → YOLO11 + ByteTrack object detection (dual-gated: config + per-video)
  └─ grounding_enabled → Florence-2 grounding (always grayed, plugin not implemented)

L3: Function Switches (2)
  ├─ search_index_enabled → 3-path encoding for semantic search
  └─ summary_enabled      → global structured summary

L4: Advanced Params (6)
  ├─ language, sample_fps, segment_threshold
  ├─ caption_with_context, summary_detail
  └─ summary_mode: "native_video" (默认, 本地Qwen2.5-VL + 纯Python聚合) | "vlm_llm" (VLM+LLM, API驱动)

Validation: PipelineParams model_validator in core/schemas.py
  ● vision OFF → ocr/caption/detection forced OFF
  ● caption OFF → summary forced OFF
  ● vision+audio both OFF → reject
  ● search+summary both OFF → reject

Incremental: Only L3 switches can be toggled on completed videos
  → summary_mode change requires new video record (POST /videos/reuse)
  → runs run_incremental() → skips completed phases
```

## Pipeline Detail

```
Phase 1 (DAG: duration → segmentation, transcription)
  ├─ duration (ffprobe) → ctx.duration
  ├─ Audio Extraction (optional, FFmpeg) → audio_path
  ├─ Transcribe (faster-whisper, optional) → words[]
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
  ├─ vlm_llm 模式: 均匀选 3-7 帧 → scene.caption_frames（API captioner 用）
  │   native_video 模式: 跳过（模型直接读视频，不需要代表帧）
  └─ 三条消费链路复用同一批帧（chunk 路由 config pipeline.chunk_encoding 控制）：
      ① 帧级路 → encode_image → frame_embeddings 表
      ② Chunk 路 → encode_video(clip) → chunks 表（默认关闭）
      ③ 文本路 → encode_text(caption+ocr+transcript) → scenes.text_embedding
      ④ VLM 路 → caption 生成

  ↓

Phase 3 (Alignment, 可选)
  └─ Align words[] 到 scenes 按时间戳
      → scene.aligned_transcript
      状态: "对齐完成: X/Y 个场景已分配转录文本"

  ↓

**Phase 4: Understanding (双模式)**
  ├─ native_video (默认): Qwen2.5-VL-7B 本地 GPU 直接观看视频片段
  │    → 输出结构化 JSON {description, keywords, objects, actions, scene_type, lighting}
  │    → scene.caption ← description (搜索用), scene.structured_caption ← 完整 JSON
  │    状态: "正在描述第 X/Y 个场景"
  ├─ vlm_llm (备选): Qwen-VL-Max API 看图说话
  │    → 传入 3-7 帧 caption_frames → 自然语言描述
  │    → scene.caption ← 纯文本, scene.structured_caption ← None
  │    状态: "正在描述第 X/Y 个场景"
  └─ Embed (Qwen3-VL-Embedding, 本地 GPU) → 编码在 Encode Frames 阶段完成
      (scene.embedding 已废弃，帧级编码统一在 _encode_frames 中处理)
      (embedder 在 lifespan 启动时预加载到 app.state.embedder，全局共享)

  ↓

Phase 5: Summarization (双模式)
  ├─ native_video (默认): 纯 Python 聚合器
  │    → 遍历 scenes.structured_caption, Counter 频率统计 + 去重
  │    → 自动生成 one_liner / tags / main_topics / main_entities
  │    → VideoSummary 结构化 summary JSON → videos.summary
  │    状态: "正在聚合 N 个场景的结构化数据..."
  └─ vlm_llm (备选): LLM 拼凑 (DeepSeek API)
       → 所有 scene.caption 拼成剧本 → summarizer API → 结构化 JSON
       状态: "正在生成摘要（N 个场景）..."

  ↓

Persist
  ├─ bulk_insert_scenes → scenes 表
  ├─ insert transcript → transcripts 表
  └─ update video → videos 表 (duration, summary, status_detail)

  ↓

Encode Frames（与 caption/summary 同批并行，Persist 前执行）
  ├─ a. 帧级路 (runners/frame_encode.py): 逐帧 encode_image → bulk_insert_frames → frame_embeddings 表
  │   状态: "逐帧向量编码中"
  ├─ b. Chunk 路 (runners/chunk_encode.py, config pipeline.chunk_encoding 控制，默认关闭):
  │     -c copy 流复制 → 480p 5fps 预处理 → encode_video → chunks 表
  │     自适应窗口: ≤5s 不切, 5-60s 窗口=时长/2, >60s 窗口=30s/步长=15s
  └─ c. 文本语义路 (runners/text_encode.py): encode_text(caption+ocr+transcript) → ctx.text_embedding
       → Persist 时由 bulk_insert_scenes 统一入库（不在 runner 内单写 DB）
```

## Module Dependency

```
main.py
  ├─ core/db.py              (engine, AsyncSessionLocal, init_db)
  ├─ core/config_loader.py   (YAML + .env 加载)
  └─ api/router.py
        ├─ api/video_routes.py  (视频管理: upload/register/params/stream/thumbnail)
        ├─ api/search_routes.py (语义搜索 + pipeline/operations)
        ├─ api/settings_routes.py (系统设置: API key 管理)
        ├─ api/schemas.py       (共享 API DTO)
        ├─ api/deps.py          (FastAPI 依赖: get_db)
              ├─ core/models.py      (ORM: Video, Scene, Transcript, FrameEmbedding, Chunk)
              ├─ core/schemas.py     (Pydantic DTOs)
              ├─ core/repository.py  (DB 数据访问层 + 批量写入)
              ├─ core/search.py      (3 种检索函数: frame/chunk/text，混合/全文/模糊已移除)
              ├─ services/video_service.py
              │     └─ pipeline/engine.py (DAG executor)
              │           ├─ pipeline/operations.py (ALL_OPERATIONS)
              │           ├─ pipeline/runners/*.py (10 operation runners)
              │           ├─ utils/video_util.py          (keyframe extraction)
              │           └─ plugins/factory.py
              │                 ├─ plugins/captioner/qwen_api_captioner.py
              │                 ├─ plugins/captioner/qwen25_vl_captioner.py
              │                 ├─ plugins/embedder/qwen_vl_embedder.py
              │                 ├─ plugins/summarizer/vllm_summarizer.py
              │                 ├─ plugins/segmenter/time_based.py
              │                 ├─ plugins/segmenter/transnet_v2.py
              │                 ├─ plugins/transcriber/faster_whisper.py
              │                 └─ plugins/*/ (detector, ocr, grounding — stubs)
              └─ pipeline/search_engine.py
                    ├─ core/search.py
                    └─ plugins/embedder/qwen_vl_embedder.py

core/
  ├─ interfaces.py         ← 8 个插件 ABC
  ├─ models.py             ← ORM: Video, Scene, Transcript, FrameEmbedding, Chunk
  ├─ schemas.py            ← Pydantic v2 DTOs + JSONB 校验模型
  ├─ repository.py         ← DB 数据访问层 + bulk_insert_frames/chunks
  ├─ search.py             ← 3 种检索: frame/chunk/text（混合/全文/模糊已移除）
  ├─ db.py                 ← 异步引擎/Session 工厂/表初始化/触发器
  ├─ config_loader.py      ← YAML + .env 加载
  ├─ prompt_loader.py      ← Prompt 模板加载
  ├─ status_tracker.py     ← Pipeline 进度持久化 + 动态权重 + sub_progress 插值
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
  │   ├─ mockData.ts       ← Pipeline 阶段定义 + fetchPipelineStages API
  │   ├─ services/api.ts   ← API 调用封装 + 轮询工具函数
  │   ├─ types/index.ts    ← TypeScript 类型定义 (镜像 backend schemas)
  │   └─ components/       ← 子组件目录 (LeftSidebar/ParameterPanel/PipelineBar/VideoSearchCard 等)
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

  segmenter:   transnetv2    → TransNetV2 neural network scene detection
  captioner:   qwen25_vl     → local Qwen2.5-VL-7B video understanding (default)
               qwen_api      → Qwen-VL-Max DashScope API (vlm_llm mode)
  embedder:    qwen3_vl_embedding → local GPU model (Qwen3-VL-Embedding-2B), loaded at startup
  summarizer:  vllm          → DeepSeek API (vlm_llm mode only; native mode uses Python aggregator)
  transcriber: null          → disabled (faster-whisper plugin exists, opt-in)
  detector:    yolo          → YOLO11s object detection (default: enabled via config)
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
    ├─ 三路并行召回:
    │   ├─ _frame_search()  → frame_embeddings 表, 1fps 帧级精确秒定位
    │   ├─ _chunk_search()  → chunks 表, 滑动窗口多帧原生编码
    │   ├─ _text_search()   → scenes.text_embedding, caption+ocr+transcript 语义
    │   └─ _label_search()  → JSONB @> entities.label (YOLO 激活后, 预留)
    └─ 按 scene 合并 + 去重:
        ├─ 帧结果按时间聚类 (间隔 ≤ 4s)
        ├─ chunk/text 结果与帧簇重叠 → 丢弃 (帧精度更高)
        └─ 非重叠 chunk/text 保留, 同 scene 取最高分

  返回格式: {scene_id, video_id, scene_index, precise_start/end,
             precision_level (frame|chunk|text|label),
             match_paths, caption, similarity, thumbnail_url}

core/search.py 提供的 3 种检索函数 (废弃的全文/混合/模糊检索已移除):
  1. frame_vector_search      — 帧级精确搜索 (frame_embeddings)
  2. chunk_vector_search      — 窗口过程语义搜索 (chunks)
  3. text_vector_search       — 文本语义搜索 (scenes.text_embedding, 含 caption+ocr+transcript)
```

## Database Schema

```
videos
  ├─ id (UUID PK), status, progress, error_message
  ├─ file_path, file_name, file_size, duration
  ├─ content_type, language
  ├─ perception: audio/vision/ocr/grounding/caption/summary_enabled
  ├─ function: search_index_enabled
  ├─ advanced: sample_fps, segment_threshold, caption_with_context, summary_detail
  ├─ summary (JSONB)
  ├─ status_detail (管道实时操作描述, 如"正在编码第 5/23 个场景的帧向量")
  └─ created_at, updated_at

scenes
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ scene_index, start_sec, end_sec, keyframe_path
  ├─ text_embedding (Vector 2048)    — caption+ocr+transcript 语义向量
  ├─ ocr_text, aligned_transcript, caption, prev_caption
  ├─ entities (JSONB)
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

frame_detections
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ track_id, timestamp_sec, class_name, confidence
  ├─ bbox (JSONB, {x1, y1, x2, y2} 归一化 0-1)
  └─ created_at

tracks
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ track_id, class_name, first_seen, last_seen, frame_count
  └─ created_at
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/v1/videos | 注册视频任务 (JSON body) |
| POST | /api/v1/videos/upload | 上传视频文件 (multipart, 不启动 Pipeline) |
| PUT | /api/v1/videos/{id}/params | 设置参数 + 启动 Pipeline (pending/completed) |
| POST | /api/v1/videos/reuse | 基于已有视频创建新记录 (复用文件) |
| GET | /api/v1/videos/ | 视频列表 (按创建时间降序) |
| GET | /api/v1/videos/{id} | 视频详情 + 关联 scenes + transcript |
| GET | /api/v1/videos/{id}/status | 轻量进度查询 |
| GET | /api/v1/videos/{id}/stream | 视频流式播放 (支持 Range) |
| GET | /api/v1/videos/{id}/thumbnail/{scene_index} | 场景缩略图 |
| DELETE | /api/v1/videos/{id} | 删除视频 (CASCADE scenes/transcript/frames/chunks) |
| GET | /api/v1/settings | 获取系统设置 (API key 状态) |
| PUT | /api/v1/settings | 更新系统设置 (保存 API key) |
| GET | /api/v1/pipeline/operations | 查询启用的操作列表 + 进度范围（前端 PipelineBar 用） |
| GET | /api/v1/videos/{id}/detection/data | 获取检测框 + 追踪轨迹 JSON（前端 Canvas overlay 用） |
| POST | /api/v1/search/semantic | 语义搜索 (四路并行召回：frame+chunk+text+label，按 scene 合并) |

## Frontend Architecture

```
React 19 + Vite 6 + Tailwind CSS 4
  │
  ├── App.tsx                ← 根组件
  ├── Dashboard.tsx          ← 主工作台 (~380 行, 状态编排 + render)
  ├── components/
  │   ├── LeftSidebar        ← 深蓝导航栏: 页面切换 + 面板开关
  │   ├── ParameterPanel     ← 侧滑参数面板: 四级联动 (L1场景/L2感知/L3功能/L4高级)
  │   ├── PipelineBar        ← 动态阶段进度条 (根据开关渲染对应节点)
  │   ├── VideoSummaryCard   ← 视频摘要展示
  │   ├── VideoSearchCard    ← 语义搜索面板 (索引未开启时置灰)
  │   ├── HistoryPanelContent← 历史记录列表 (自动刷新 + 缩略图 + 参数摘要)
  │   ├── SettingsPage       ← 系统设置: 存储路径 + API 密钥管理 (真实连接后端)
  │   └── icons.tsx          ← 18 个 SVG 图标
  ├── utils/helpers.ts       ← fmtDuration, fmtDate, formatSec
  ├── services/api.ts        ← API 封装 + 轮询工具函数
  ├── types/index.ts         ← TypeScript 类型定义
  └── mockData.ts            ← Pipeline 阶段定义 + computePipelineStages()

数据流:
  Dashboard mount → GET /api/v1/videos/ 拉取列表
  上传 → POST multipart → 参数面板自动展开 (不可点击外部关闭)
  配置参数 → PUT /videos/{id}/params → Pipeline 启动
  选择视频 → GET /api/v1/videos/{id} 每 3s 轮询, 同步更新历史列表状态
  增量修改 → PUT /videos/{id}/params (仅 summary/search_index) → run_incremental()
  搜索 → POST /api/v1/search/semantic → 结果卡片 (切换视频时自动清空)

Vite 开发代理:
  /api → http://localhost:8000 (dev)
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Plugin + Factory** | Swap models via config.yaml, zero code changes |
| **pgvector over standalone vector DB** | Simpler deployment, transactional consistency |
| **Local GPU for Embedder** | 2048-dim encoding every scene/frame; API latency unacceptable |
| **Local GPU for Captioner (default)** | Qwen2.5-VL-7B 4-bit on 4060, native video understanding; API captioner available as vlm_llm fallback |
| **Pure Python summarizer (default)** | native_video mode: aggregated from structured captions, no LLM API costs or latency |
| **FFmpeg pipe → memory** | No frame files on disk, reduces I/O |
| **TransNetV2 segmentation** | Neural scene boundary detection, superior to fixed-interval |
| **1fps frame pool + 3 encoding paths** | Frame-level precision (主力) + text semantics + chunk (config-gated, 默认关闭) |
| **Adaptive chunk windows** | ≤5s scene: skip; 5-60s: half-duration window; >60s: 30s fixed window; stream copy + preprocessing |
| **Enabled modules only** | pipeline checks each plugin; null = skip gracefully |
| **React + Vite + Tailwind** | Fast dev experience, minimal config, fluid-blob background + card-surface panels |
| **Unified API envelope** | All responses wrapped in `{code, message, data}` |
| **Shared embedder in app.state** | Avoids reloading 4GB model per video |
| **4-level parameter hierarchy** | Scene type sets defaults for modules, which gate functions and advanced params |
| **Incremental pipeline** | L3 switches (summary/search) can re-run independently on completed videos |
| **Decoupled upload/params** | Upload creates pending video; pipeline starts only after user configures params |

## Current Status

| Module | Status | Note |
|---|---|---|
| Pipeline Core | ✅ | DAG-based: operations.py declares 10 ops with gates/deps → engine topo-sorts + parallel batches |
| Semantic Search (3-path) | ✅ | frame + chunk + text 并行召回, scene-merge dedup, label 预留 |
| Frame-level Encoding | ✅ | runners/frame_encode.py: batch encode 4 frames |
| Chunk-level Encoding | ⚠️ | config pipeline.chunk_encoding 控制，默认关闭 |
| Text Semantic Encoding | ✅ | runners/text_encode.py: ctx 写入 → Persist 统一入库 |
| API Routes | ✅ | 14 endpoints: CRUD, stream, thumbnail, status, params, reuse, settings, semantic search, pipeline/operations |
| Pipeline Progress System | ✅ | 动态权重按 progress_weight 比例分配 + sub_progress 操作内插值，丝滑推进 |
| Parameter System (4-level) | ✅ | PipelineParams schemas, presets config, frontend cascade panel |
| Incremental Processing | ✅ | run_incremental() on completed videos for summary/search_index |
| Settings API + Keys | ✅ | core/settings_service.py, GET/PUT /api/v1/settings |
| Frontend Dashboard | ✅ | React 19 + Vite + Tailwind, 8 extracted components, dynamic PipelineBar, auto-refresh history |
| Config Schema | ✅ | Pydantic v2 validation for config.yaml |
| Prompt Templates | ✅ | config/prompts.yaml — caption/summarizer/grounding prompts |
| DB Layer | ✅ | Async engine, pgvector, init_db(), incremental migration |
| TransNetV2 Segmenter | ✅ | Neural scene boundary detection |
| faster-whisper Transcriber | ✅ | Plugin exists, config-disabled by default |
| Object Detection + Tracking | ✅ | YOLO11s + ByteTrack, dual-gate control, frontend canvas overlay |
| OCR | 📋 | PaddleOCR shell only |
| Grounding | 📋 | Florence-2 shell only |
| Export APIs | 📋 | export_routes.py / export_service.py shells |
| Health / Reindex | 📋 | maintenance_routes.py shell |
