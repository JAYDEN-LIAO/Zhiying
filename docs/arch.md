# Cerno Architecture

> Version: 0.21 | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector
> Frontend: React 19 + Vite 6 + Tailwind CSS 4

## System Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     Client (CLI/Browser / React Frontend)                        │
└──────────────────┬────────────────────────────┬──────────────────┬───────────────┘
                   │ POST /videos/upload (single)     │ POST /search/semantic │ GET /videos/
                   │ + POST /videos/upload/batch (v0.19) │ GET /videos/{id}/meta │
                   │ + PUT /videos/{id}/params     │                        │
                   ▼                            ▼                        ▼
┌─────────────────────────────┐  ┌─────────────────────────────┐  ┌──────────────────┐
│     FastAPI (main.py)       │  │   SearchEngine              │  │  React Dashboard │
│                             │  │   ┌─ frame (1fps 精确)     │  │  ┌── video player │
│  ┌─ api/video_routes.py ──┐ │  │   ├─ chunk (滑动窗口)      │  │  ├── pipeline UI  │
│  │ upload/register/params  │ │  │   ├─ text (caption 语义)    │  │  ├── search panel │
│  │ stream (hevc_ok 路由)   │ │  │   ├─ label (JSONB 精确)     │  │  ├── history list │
│  │ proxy-status/thumbnail  │ │  │   └─ track (crop 跨模态)    │  │  ├── det panel    │
│  │ delete/metadata        │ │  │   └─ plate (Levenshtein)   │  │  └── export btn   │
│  └─────────────────────────┘ │  └──────────┬──────────────────┘  └──────────────────┘
│  ┌─ api/export_routes.py ──┐ │             │
│  │ clip / frames / track   │ │  ┌──────────▼──────────────────┐
│  │ thumbnails (GET+POST)   │ │  │   Embedder (local GPU)      │
│  └─────────────────────────┘ │  │   encode_text("query")      │
│  ┌─ api/detection_routes.py │  │   encode_image(frame)       │
│  │ detection/data + thumb   │  └──────────────────────────────┘
│  └───────────┬──────────────┘
│  ┌─ FormatService (v0.13)  ─┐
│  │ probe → remux → proxy    │
│  │ (按需, 异步, 不阻塞上传) │
│  └──────────────────────────┘
│  ┌─ StorageManager (v0.21)─┐
│  │ delete → 批量删DB+清盘   │
│  │ sweep → 孤儿清扫        │
│  └──────────────────────────┘
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
│  EventDrivenScheduler (v0.10)│
│  Each op awaits upstream     │
│  ┌─ duration                │
│  │  → detect ──→ search_queue ──→ search_encode (队列消费) │
│  │  → seg + transcribe      │
│  │    → keyframes + align   │
│  │      → caption           │
│  │      → frame_encode      │
│  │      → text_encode       │
│  │    → track_encode        │
│  │    → face + plate        │
│  │  → summary               │
│  └─ Persist → DB            │
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
│  track_embeddings (crop)    │
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
  ├─ detection_enabled → YOLO11 + BoT-SORT object detection (dual-gated: config + per-video)
  └─ grounding_enabled → Florence-2 grounding (always grayed, plugin not implemented)

L3: Function Switches (3)
  ├─ search_index_enabled → 4-path encoding for semantic search (frame+chunk+text+track)
  ├─ summary_enabled      → global structured summary
  └─ track_stitch_enabled → 全局 tracklet 缝合（合并被遮挡/缩放/切换拆分的同一身份 track）

L4: Advanced Params (7)
  ├─ language, sample_fps, segment_threshold
  ├─ caption_with_context, summary_detail
  ├─ encode_profile: "fast" | "balanced" | "precise" | null (全局默认)
  └─ summary_mode: "native_video" (默认, 本地Qwen3-VL-8B + 纯Python聚合) | "vlm_llm" (VLM+LLM, API驱动)

Validation: PipelineParams model_validator in core/schemas.py
  ● vision OFF → ocr/caption/detection forced OFF
  ● caption OFF → summary forced OFF
  ● vision+audio both OFF → reject
  ● search+summary both OFF → reject

Incremental: Only L3 switches (summary_enabled / search_index_enabled) can be toggled on completed videos
  → track_stitch_enabled change requires new video record（需重跑检测路径）
  → summary_mode change requires new video record (POST /videos/reuse)
  → runs run_incremental() → skips completed phases
```

## Pipeline Detail

```
DAG 阶段流 (EventDrivenScheduler, 15 ops, 每 op 一个 asyncio 任务等待上游事件):
  duration
    ├─ search_encode (仅 summary_enabled=False) — 与 detection 共享单 NVDEC 流, 64 帧一批消费 → frame_embeddings
    ├─ detection (10fps, 生产者-消费者) → track_encode → face / plate
    └─ segmentation → keyframes (1fps, NVDEC MJPEG pipe / cv2) → asyncio.Queue(512) 并发编码
         → caption (双模式) → summary (双模式)
  → _persist() → mark_completed()

Keyframe 消费 4 链路:
  ① frame_encode → frame_embeddings 表 (1fps 帧向量)
  ② chunk_encode → chunks 表 (滑动窗口, 默认关闭; 窗口 ≤5s 不切 / 5-60s 半时长 / >60s 30s/步15s)
  ③ text_encode → scenes.text_embedding (caption+ocr+transcript 语义)
  ④ caption → scene.caption

Caption 双模式: native_video (Qwen3-VL-8B 本地 GPU 原生视频理解 → 结构化 JSON) / vlm_llm (Qwen-VL-Max API 看图)
Summary 双模式: native_video (纯 Python 聚合器, 无 API 成本) / vlm_llm (DeepSeek API)
Track 语义路 (track_encode): 读 detection 缓存 640×384 crop (每 2s, 零 FFmpeg seek)
  → 挑 20%/50%/80% 3 帧 → mean pool → cosine ≥0.85 + 同类 + 时序不重叠 全局缝合 (L3 开关)
  → track_embeddings 表
Persist: bulk_insert_scenes + insert transcript + update videos (duration/summary/status_detail)
```

## Module Dependency

```
main.py
  ├─ core/db.py, core/config_loader.py
  └─ api/router.py (挂载 /api/v1)
        ├─ api/video_routes.py, search_routes.py, settings_routes.py
        ├─ api/detection_routes.py, export_routes.py, face_routes.py, plate_routes.py
        ├─ api/maintenance_routes.py (存储清扫)
        ├─ api/deps.py → core/models.py, core/schemas.py, core/repository.py
        │     ├─ services/video_service.py → pipeline/engine.py
        │     │     ├─ pipeline/operations.py + pipeline/runners/*.py (15 runners)
        │     │     ├─ utils/video_util.py, utils/metadata.py
        │     │     └─ plugins/factory.py → plugins/{captioner,embedder,summarizer,segmenter,
        │     │                              transcriber,detector,face,plate,ocr,grounding}/
        │     └─ pipeline/search_engine.py → core/search.py
        └─ services/export_service.py → utils/video_util.py

core/  models.py (12 表) · schemas.py (DTO) · repository.py (数据访问) · storage_manager.py (存储卫生)
       search.py (6 检索) · db.py (引擎/init_db) · config_loader.py · prompt_loader.py
       status_tracker.py (进度) · interfaces.py (10 插件 ABC) · exceptions.py
config/  config.yaml (server/db/storage/plugins/pipeline) · config_schema.py · prompts.yaml
frontend/  Dashboard.tsx + components/ (20) + hooks/ (8) + labels.ts + services/api.ts + types/ + mockData.ts
utils/  video_util.py (FFmpeg) · metadata.py (三级元数据) · video_source.py (来源规则引擎)
services/  video_service.py (管道调度) · format_service.py (remux/proxy) · export_service.py
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
  captioner:   qwen3_vl      → local Qwen3-VL-8B video understanding (default)
               qwen_api      → Qwen-VL-Max DashScope API (vlm_llm mode)
  embedder:    qwen3_vl_embedding_8b → local GPU model (Qwen3-VL-Embedding-8B), loaded at startup
  summarizer:  vllm          → DeepSeek API (vlm_llm mode only; native mode uses Python aggregator)
  transcriber: null          → disabled (faster-whisper plugin exists, opt-in)
  detector:    yolo          → YOLO11s object detection (default: enabled via config)
  face:        insightface   → InsightFace SCRFD + ArcFace R50 (512d)
  plate:       hyperlpr      → HyperLPR3 ONNX Runtime LPR (with PaddleOCR alternative)
  ocr:         null          → disabled (placeholder)
  grounding:   null          → disabled (placeholder)
```

## Search Architecture

```
Semantic Search: POST /api/v1/search/semantic — query → embedder.encode_text() (编码一次)
  → 6 路并行召回:
     frame (1fps 精确秒) / chunk (滑窗, 默认关) / text (caption+ocr+transcript 语义)
     label (JSONB @> entities) / track (crop 跨模态, 返回具体物体) / plate (Levenshtein + ILIKE)
  → Face 图搜: POST /search/face — 图片 → ArcFace 512d → face_identities cosine
  → 通用图搜: POST /search/image — 图片 → Qwen3-VL 2048-dim → frame_embeddings
     (专用 search_image_only 路径: 帧不聚类, 每帧独立精确到秒, 不补 scene 信息)
  → 合并去重: 帧簇(间隔≤4s)优先, chunk/text 与帧重叠丢弃, track 按 (video_id, track_id) 去重
  返回: {precision_level, precise_start/end, match_paths, thumbnail_url, track_id?, bbox?}

core/search.py 6 种检索函数:
  frame_vector_search · chunk_vector_search · text_vector_search
  track_vector_search · plate_text_search (Levenshtein) · face_identity_search (ArcFace cosine)
```

## Database Schema

```
video_groups (v0.19 多视频分组)
  ├─ id (UUID PK), name (nullable), created_at, updated_at
  └─ videos: list["Video"] (relationship)

videos
  ├─ id (UUID PK), status, progress, error_message
  ├─ file_path, file_name, file_size, duration
  ├─ content_type, language
  ├─ perception: audio/vision/ocr/grounding/caption/detection_enabled, detection_classes
  ├─ function: search_index_enabled, summary_enabled, summary_mode, track_stitch_enabled
  ├─ advanced: sample_fps, segment_threshold, caption_with_context, summary_detail
  ├─ summary (JSONB)
  ├─ metadata_json (JSONB)          — 缓存的完整技术元数据（首次提取后后续 <1ms）
  ├─ source_analysis (JSONB)        — 视频来源分析：类型/置信度/证据链/监控品牌
  ├─ ai_detect_result (JSONB)       — [残留] AI 生成检测结果（AICheck 服务已移除，此列保留但恒为 not_run）
  ├─ status_detail (管道实时操作描述)
  ├─ group_id (UUID FK → video_groups.id, nullable, v0.19) — NULL=单视频未分组
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
  ├─ segments (JSONB, [{start, end}, ...]) — ReID 合并后的多段时间片段
  └─ created_at

track_embeddings
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ track_id, class_name, embedding (Vector 2048)
  ├─ timestamp_sec, bbox (JSONB)
  └─ created_at

face_identities
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ identity_label (String, "人物 A/B/C..."), face_count
  ├─ face_embedding (Vector 512 — ArcFace R50 output)
  ├─ first_seen, last_seen, avg_quality
  ├─ best_face_timestamp, best_face_bbox (JSONB)
  └─ created_at

face_detections
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ identity_id (FK → face_identities.id, SET NULL)
  ├─ track_id, timestamp_sec
  ├─ bbox (JSONB), quality_score, face_embedding (Vector 512)
  └─ created_at

plate_detections
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ track_id, class_name, timestamp_sec
  ├─ plate_text, plate_type (blue/yellow/green/white)
  ├─ char_confidences (JSONB), bbox (JSONB), detection_confidence
  └─ created_at
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/v1/videos | 注册视频任务 (JSON body) |
| POST | /api/v1/videos/upload | 上传视频文件 (multipart, 不启动 Pipeline, group_id=NULL) |
| POST | /api/v1/videos/upload/batch | 批量上传视频文件 (multipart, 创建 VideoGroup, 并发处理) |
| PUT | /api/v1/videos/{id}/params | 设置参数 + 启动 Pipeline (pending/completed) |
| POST | /api/v1/videos/reuse | 基于已有视频创建新记录 (复用文件) |
| GET | /api/v1/videos/ | 视频列表 (按创建时间降序) |
| GET | /api/v1/videos/{id} | 视频详情 + 关联 scenes + transcript |
| GET | /api/v1/videos/{id}/status | 轻量进度查询 |
| GET | /api/v1/videos/{id}/stream | 视频流式播放 (支持 Range) |
| GET | /api/v1/videos/{id}/thumbnail/{scene_index} | 场景缩略图 |
| DELETE | /api/v1/videos/{id} | 删除视频 (CASCADE) |
| GET | /api/v1/videos/{id}/metadata | 视频元数据 + 来源分析 (支持 ?verbose=true, 自动缓存) |
| GET | /api/v1/settings | 获取系统设置 (API key 状态) |
| PUT | /api/v1/settings | 更新系统设置 (保存 API key) |
| GET | /api/v1/settings/pipeline | 获取 Pipeline 配置 (编码预设等全局默认值) |
| GET | /api/v1/pipeline/operations | 查询启用的操作列表 + 进度范围 |
| GET | /api/v1/videos/{id}/detection/data | 逐帧检测框 + 追踪轨迹 JSON |
| GET | /api/v1/videos/{id}/detection/thumbnail | track crop 缩略图 (bbox 裁剪) |
| GET | /api/v1/videos/{id}/face/data | 人脸识别数据 (身份/track_id/时间戳) |
| GET | /api/v1/videos/{id}/face/thumbnail | 人脸 crop 缩略图 |
| GET | /api/v1/videos/{id}/plate/data | 车牌识别数据 |
| GET | /api/v1/videos/{id}/plate/thumbnail | 车牌缩略图 |
| POST | /api/v1/search/semantic | 语义搜索 (六路并行：frame+chunk+text+label+track+plate) |
| POST | /api/v1/search/face | 人脸图片搜索 (multipart image → ArcFace 512d) |
| POST | /api/v1/search/image | 通用图搜 (multipart image → Qwen3-VL-Embedding 2048-dim → frame_embeddings) |
| POST | /api/v1/videos/{id}/export/clip | 导出视频片段 (JSON) |
| GET | /api/v1/videos/{id}/export/clip | 导出视频片段/单帧 (query params) |
| POST | /api/v1/videos/{id}/export/frames | 导出帧 zip (兼容) |
| POST | /api/v1/videos/{id}/export/track/{tid} | 导出 track 分段视频 zip (JSON) |
| GET | /api/v1/videos/{id}/export/track/{tid} | 导出 track 分段视频 zip (query params) |
| GET | /api/v1/videos/{id}/export/track/{tid}/thumbnail | 导出 track 物体全尺寸裁剪图 |
| POST | /api/v1/videos/{id}/export/thumbnails | 导出场景缩略图 zip (JSON) |
| GET | /api/v1/videos/{id}/export/thumbnails | 导出场景缩略图 zip (直接下载) |
| POST | /api/v1/maintenance/sweep | 存储孤儿清扫 (body {dry_run}, true=预览/默认, false=执行) |
| GET | /api/v1/maintenance/storage | 存储用量概览 (各目录大小 + 可回收量) |

## Frontend Architecture

```
React 19 + Vite 6 + Tailwind CSS 4
  │
  ├── App.tsx                ← 根组件
  ├── Dashboard.tsx          ← 主工作台 (~430 行, 状态编排 + group 状态 + detectionVideoId + header 下拉)
  ├── components/
  │   ├── Sidebar            ← 深色渐变导航栏: 页面切换 + 面板开关
  │   ├── ParameterPanel     ← 侧滑参数面板: 四级联动 (L1场景/L2感知/L3功能/L4高级)
  │   ├── PipelineBar        ← 动态阶段进度条 (根据开关渲染对应节点)
  │   ├── VideoSummaryCard   ← 视频摘要展示 + 缩略图导出按钮
  │   ├── VideoSearchCard    ← 语义/图搜/人脸搜索面板 (索引未开启时置灰) + 搜索范围选择器 (组感知)
  │   ├── HistoryPanelContent← 历史记录列表 (搜索+自动刷新+缩略图+参数摘要, 删除二次确认+processing禁用+释放空间提示) + 组卡片堆叠/展开
  │   ├── SettingsPage       ← 系统设置: 存储路径 + API 密钥管理
  │   ├── DetectionOverlay   ← Canvas bbox 渲染 (插值+拖尾+选中)
  │   ├── DetectionPanel     ← 物体列表 (分类筛选+缩略图 hover+导出按钮) + 独立视频选择器 (组感知)
  │   ├── DetectionTimeline  ← Track 时间轴 (播放头+色条+悬浮提示)
  │   ├── VideoInfoCard      ← 视频元数据 + 来源分析
  │   ├── ExportMenu         ← 导出菜单 (视频片段或节点)
  │   └── icons.tsx          ← 20+ SVG 图标
  ├── labels.ts              ← YOLO COCO 类名英→中映射 + 统一颜色表
  ├── utils/helpers.ts       ← fmtDuration, fmtDate, formatSec
  ├── services/api.ts        ← API 封装 + 轮询工具函数 + 下载辅助 + uploadBatch()
  ├── types/index.ts         ← TypeScript 类型定义 (镜像 backend schemas, +VideoGroup)
  └── mockData.ts            ← Pipeline 阶段定义 + computePipelineStages()

数据流:
  Dashboard mount → GET /api/v1/videos/ 拉取列表
  上传 → POST multipart → 参数面板自动展开 (不可点击外部关闭); 多文件走 uploadBatch → VideoGroup
  POST /videos/upload/batch → group 内第一个视频自动选中, history 组卡片堆叠
  配置参数 → PUT /videos/{id}/params → Pipeline 启动 (组内所有 pending 兄弟同步启动)
  选择视频 → GET /api/v1/videos/{id} 每 3s 轮询, 同步更新历史列表状态
  增切换 → Header 下拉切组内视频 / 历史卡片切视频 / 搜索结果跨视频跳转
  增量修改 → PUT /videos/{id}/params (仅 summary/search_index) → run_incremental()
  搜索 → POST /api/v1/search/semantic (支持 video_ids 范围过滤: 当前/组内/全部)
  信息 → GET /videos/{id}/metadata → VideoInfoCard 弹出卡片
  导出 → window.open(GET /videos/{id}/export/...) → 浏览器直接下载
  删除 → DELETE /videos/{id} (v0.21 二次确认, processing 禁用, 提示释放空间; 后端 DB 级联+磁盘清盘)

Vite 开发代理:
  /api → http://localhost:8000 (dev)
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Plugin + Factory** | config.yaml 换后端零代码改动 |
| **pgvector over 独立向量库** | 部署简单、事务一致 |
| **本地 GPU Embedder** | 每场景/帧 2048-dim 编码，API 延迟不可接受 |
| **双模式摘要** | native_video 本地 GPU + 纯 Python 聚合（零成本）/ vlm_llm API 备选 |
| **FFmpeg pipe → 内存** | 帧不落盘，减 I/O |
| **TransNetV2 分段** | 神经镜头边界检测优于固定间隔 |
| **1fps 帧池 + 4 编码路径** | 帧级精度主力 + chunk/text/track 互补 |
| **自适应 chunk 窗口** | ≤5s 跳过 / 5-60s 半时长 / >60s 30s 窗 |
| **共享 embedder (app.state)** | 避免每视频重载 ~4GB 模型 |
| **4 级参数 + 增量** | 场景设默认值，L3 开关可增量重跑 |
| **单 NVDEC 流共享 + 生产者-消费者** | detection 与 search_encode 共享解码流，帧提取与推理重叠，消灭双流解码竞争 |
| **NVDEC MJPEG pipe** | ~100KB/帧 替代 raw NV12 (3.1MB)，pipe I/O 减少 30× |
| **三档速度预设** | fast/balanced/precise 控制分辨率 + batch |
| **搜索/摘要路径解耦** | search_encode 独立于摘要，帧搜索不等 caption |
| **track 回退移除** | 直接读缓存 crop（零 seek），长视频 track_encode 257s→43s |
| **车牌 Levenshtein 检索** | 编辑距离 ≤2 + ILIKE，天然处理错位/增减 |
| **上传/参数解耦** | 上传建 pending，配置后才启动管道 |
| **两层格式兼容 + 懒代理** | remux (-c copy) 即时 + proxy (NVENC h264) 按需，HEVC 浏览器零处理 |
| **GET+POST 双导出** | POST 供编程调用，GET 供浏览器直接下载 |
| **三级元数据 + DB 缓存** | pymediainfo→exiftool→ffprobe；缓存后 <1ms |
| **多视频分组 (v0.19)** | 批量上传 + 组参数同步 + 跨视频搜索 |
| **全局 ReID 缝合 (v0.20)** | 在线 with_reid + 全局 cosine ≥0.85 合并（segments 时序检查, L3 开关）|
| **来源分析规则引擎** | EXIF + 文件名 + 文件头魔数（IMKH→海康），无 ML 依赖 <10ms |
| **人脸/车牌开关** | 三门控: config + detection_enabled + face/plate_enabled |
| **图搜双通道** | 人脸 ArcFace 512d / 通用 Qwen3-VL 2048-dim（帧不聚类精确到秒）|
| **存储卫生 (v0.21)** | 删除 = DB 级联 + 引用追踪清盘；孤儿清扫手动（dry-run 默认）防误删 |

## Current Status

| Module | Status | Note |
|---|---|---|
| Pipeline Core (DAG) | ✅ | EventDrivenScheduler (v0.10): operations.py declares 15 ops, search/summary decoupled, gates/deps, events-driven |
| Track Encoding (crop→embed) | ✅ | runners/track_encode.py: 读检测缓存多帧 640×384 crop（零 FFmpeg seek）→ mean pool → Qwen3-VL-Embedding 2048-dim。长视频友好（track_encode 不随 track 数 seek 爆炸） |
| Global ReID Tracklet Stitch | ✅ | track_encode Phase 2: cosine ≥0.85 + 同类 + 时序不重叠（segments 真实片段, MAX_OVERLAP_SEC=1.0 + HIGH_SIM_OVERRIDE=0.90 容忍双跟踪伪影）；L3 track_stitch_enabled 开关 |
| Face Recognition | ✅ | plugins/face/insightface_face.py — SCRFD + ArcFace R50 (512d), FaceRunner identity clustering |
| License Plate Recognition | ✅ | plugins/plate/hyperlpr_plate.py — HyperLPR3 detection + text recognition (paddle_plate.py alternative), PlateRunner |
| Face Image Search | ✅ | POST /api/v1/search/face — upload image → ArcFace 512d → face_identities cosine match |
| Plate Text Search | ✅ | core/search.py plate_text_search — Levenshtein edit distance + ILIKE substring |
| Semantic Search (7-path) | ✅ | frame + chunk + text + label + track + plate + image 并行召回, plate 独立 ILIKE |
| Universal Image Search | ✅ | POST /api/v1/search/image — Qwen3-VL-Embedding 2048-dim → frame_embeddings, 独立 search_image_only() 路径 (帧不聚类、不补 scene、每帧独立精确到秒) |
| Frontend Chinese Labels | ✅ | frontend/src/labels.ts — 统一 ZH_LABELS (80 COCO 类)+zh()/zhLabel()/colorOf(), 消除 3 份重复 CLASS_COLORS |
| Frame-level Encoding | ✅ | runners/frame_encode.py: batch encode 4 frames |
| Chunk-level Encoding | ⚠️ | config pipeline.chunk_encoding 控制，默认关闭 |
| Text Semantic Encoding | ✅ | runners/text_encode.py: ctx 写入 → Persist 统一入库 |
| Object Detection + Tracking | ✅ | YOLO11s + BoT-SORT, 10fps 独立帧率（与 search 共享 NVDEC 流）, dual-gate control |
| AI Generation Detection | ❌ 已移除 | services/ai_detect_service.py + utils/ai_detect/ 已删除, upload 不再触发 AICheck。残留: ai_detect_result DB 列 + schema + 前端展示（恒为 not_run） |
| Video Source Analysis | ✅ | utils/video_source.py: 规则引擎 classify_video_source(), phone/camera/screen_recording/surveillance/non_camera_source, 基于 EXIF + file naming + media structure + 文件头魔数嗅探（IMKH→海康威视, magic_bytes 内容级签名）, 首次 GET /metadata 触发, 结果缓存到 DB |
| Metadata Extraction + Cache | ✅ | utils/metadata.py: 三级提取 (pymediainfo→exiftool→ffprobe); 结果缓存到 Video.metadata_json 列, 后续请求 <1ms 返回; ?verbose=true 查看原始数据 |
| Clip Export | ✅ | services/export_service.py: 流复制 (-c copy) 极速导出 |
| Frames Export | ✅ | 指定时间戳帧序列 → zip 打包 |
| Track Segments Export | ✅ | 读 segments 字段按段导出 → zip |
| Track Thumbnail Download | ✅ | 全尺寸物体裁剪图下载 |
| Scene Thumbnails Export | ✅ | 全部/指定场景缩略图 → zip |
| Multi-Format Support | ✅ | 两层: remux (-c copy) + proxy (NVENC H.264, 按需) |
| Performance Optimizations | ✅ | embedder 可配置 3 档 (336-672), PIL resize 8线程并行, batch 512, NVDEC MJPEG pipe 默认启用, keyframes→frame_encode 生产者-消费者并发, float32 |
| API Routes | ✅ | 30 endpoints: +batch upload +face/data +face/thumbnail +metadata cache +source_analysis +maintenance/sweep +maintenance/storage |
| Pipeline Progress System | ✅ | 动态权重按 progress_weight 比例分配 + sub_progress 操作内插值 |
| Parameter System (4-level) | ✅ | PipelineParams schemas, presets config, frontend cascade panel |
| Incremental Processing | ✅ | run_incremental() on completed videos for summary/search_index |
| Storage Hygiene (v0.21) | ✅ | core/storage_manager.py: 删除即清盘 (DB 级联 + 引用追踪) + 删除守卫 409 + 空组清理; POST /maintenance/sweep 清扫 + scripts/sweep_storage.py CLI; trackthumb 泄漏修复; 缩略图缺失 404 兜底 |
| Multi-Video Group (v0.19) | ✅ | POST /videos/upload/batch; VideoGroup ORM; 组参数同步; frontend 历史堆叠/展开/切换/跨视频搜索/独立检测面板 |
| Settings API + Keys | ✅ | core/settings_service.py, GET/PUT /api/v1/settings |
| Frontend Dashboard | ✅ | React 19 + Vite + Tailwind, 20 components + 8 hooks + labels.ts incl Detection/Timeline/Metadata/Export/ImageSearch |
| Config Schema | ✅ | Pydantic v2 validation for config.yaml |
| Prompt Templates | ✅ | config/prompts.yaml — caption/summarizer/grounding prompts |
| DB Layer | ✅ | Async engine, pgvector, init_db(), incremental migration, 12 tables (+video_groups) |
| TransNetV2 Segmenter | ✅ | Neural scene boundary detection |
| faster-whisper Transcriber | ✅ | Plugin exists, config-disabled by default |
| OCR | 📋 | PaddleOCR available as plate recognition alternative (plugins/plate/paddle_plate.py) |
| Grounding | 📋 | Florence-2 shell only |
| Health / Reindex | 🔶 | maintenance_routes.py — 存储清扫已实现, 健康检查待办 |
