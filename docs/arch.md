# Zhiying Architecture

> Version: 0.24 | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector
> Frontend: React 19 + Vite 6 + Tailwind CSS 4
> v0.22: Windows 从零部署 + 系统设置/参数预设 + 全局 GPU 锁 + Detection 渲染重构 + 删除处理中/管道取消 + ARM64 多架构
> v0.24: 云智(Yunzhi)平台接入（register-external + /internal/yunzhi/jobs 异步任务）+ 生产部署（systemd, 8011, pgvector:pg17, 静态托管前端）
> v0.26: 平台文件 id → 视频自动跳转（videos.external_file_id + GET /videos/external/{file_id} + 前端 connect() 后自动打开对应视频）
> v0.27: 搜索修正（统一 track 编号 + 范围 fail-closed + 车牌搜索修正）+ 车牌模糊搜索模式（字符归一化 + 前端「牌」模式按钮）

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
│  │ tracks/detections+thumb │  └──────────────────────────────┘
│  └───────────┬──────────────┘
│  ┌─ FormatService (v0.13)  ─┐
│  │ probe → remux → proxy    │
│  │ (按需, 异步, 不阻塞上传) │
│  └──────────────────────────┘
│  ┌─ StorageManager (v0.21)─┐
│  │ delete → 批量删DB+清盘   │
│  │   └ 处理中: cancellation│
│  │     登记 → 管道优雅中止  │
│  │ sweep → 孤儿清扫        │
│  └──────────────────────────┘
│  ┌─ SettingsService (v0.22) ┐
│  │ settings.json 运行时覆盖 │
│  │ presets.json 参数预设    │
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

L4: Advanced Params (7)
  ├─ language, sample_fps, segment_threshold
  ├─ caption_with_context, summary_detail
  ├─ encode_profile: "fast" | "balanced" | "precise" | null (全局默认)
  └─ summary_mode: "vlm_llm" (默认, API驱动) | "native_video" (已置灰退役: 前端不再可选; 后端代码保留兼容历史记录——effective_summary_mode() 在 captioner 为 qwen_api 时自动映射为 vlm_llm, 旧视频仍正常处理; captioner 8B 不再下载)

Validation: PipelineParams model_validator in core/schemas.py
  ● vision OFF → ocr/caption/detection forced OFF
  ● caption OFF → summary forced OFF
  ● vision+audio both OFF → reject
  ● search+summary both OFF → reject

Incremental: Only L3 switches (summary_enabled / search_index_enabled) can be toggled on completed videos
  → summary_mode change requires new video record (POST /videos/reuse)
  → runs run_incremental() → skips completed phases
```

## Settings & Presets (v0.22)

```
系统设置 — 全局运行时生效（settings.json 覆盖 config.yaml）:
  GET/PUT /settings 读写 data/settings.json:
    api_keys   {dashscope, deepseek}            → 注入 env → _ENV_OVERRIDES 流入插件（脱敏显示末4位）
    providers  {dashscope/base_url+model, deepseek/...} → 覆盖 captioner/summarizer 配置
    storage    {video_dir, artifact_dir}         → 覆盖 storage 配置
    pipeline   (见下)                            → 覆盖 pipeline + plugins.detector + embedder.quantization

  pipeline 段:
    encode_profiles       三档模板 {fast/balanced/precise: {encode_width, encode_height, encode_batch_size}}
    default_encode_profile 默认档 fast/balanced/precise
    detection_fps / detector_batch_size / confidence_threshold / iou_threshold   → plugins.detector
    yolo_imgsz             → plugins.detector.imgsz (320-640, 32倍数)
    use_nvdec / chunk_encoding   布尔开关
    quantization          embedder 量化 none/8bit/4bit（⚠️ 启动时加载，改后需重启）
    max_concurrent_videos 并发管道上限 (0=不限) → VideoService asyncio.Semaphore

  core/config_loader: PIPELINE_NUMERIC_SPEC + ENCODE_PROFILE_NUMERIC_SPEC + clamp_param()
    → 保存/应用时范围钳制 + 步进取整；空字符串 = 删除覆盖（回退 config.yaml）
  load_config() 每次 _apply_settings_overrides 合并 → 保存清 lru_cache → 运行时生效
  （唯一例外 quantization：启动加载，改后需重启后端）

参数预设 — 多套命名参数快照，一键套用 (data/presets.json):
  POST   /settings/presets            快照「当前生效」管道参数为新预设
  GET    /settings/presets            列出
  PUT    /settings/presets/{id}       重命名
  DELETE /settings/presets/{id}       删除
  POST   /settings/presets/{id}/apply 套用 → 写回 settings.json 覆盖区，运行时生效
  预设只含管道性能/模型参数（编码+检测+开关+量化+并发），不含存储路径与 API 密钥（机器相关）

配置统一 (v0.22, 部署): 单份 config/config.yaml 通用所有机器
  - embedder 相对模型路径自动解析到项目根（对齐 detector，摆脱 cwd 依赖）
  - captioner 配 qwen3_vl 但本地 8B 模型缺失 → _auto_fallback_captioner 自动降级 qwen_api (DashScope, WARNING)
  - 摘要模式默认 vlm_llm（API 驱动）; native_video 已置灰退役, 由 runners/base.py effective_summary_mode() 兜底兼容历史记录（captioner 为 qwen_api 时自动映射 vlm_llm, 旧视频仍正常处理; captioner 8B 不再下载）
  - 无需 config.windows.yaml / ZHIYING_CONFIG（后者仅保留为自定义配置覆盖入口）
```

## Pipeline Detail

```
DAG 阶段流 (EventDrivenScheduler, 15 ops, 每 op 一个 asyncio 任务等待上游事件):
  duration
    ├─ search_encode (仅 summary_enabled=False) — 与 detection 共享单 NVDEC 流, 64 帧一批消费 → frame_embeddings
    ├─ detection (10fps, 生产者-消费者, 攒批 128) → track_encode → face / plate
    └─ segmentation → keyframes (1fps, NVDEC MJPEG pipe / cv2) → asyncio.Queue(512) 并发编码
         → caption (双模式) → summary (双模式; 默认 vlm_llm, native_video 已置灰退役)
  → _persist() → mark_completed()

GPU 串行 (v0.22): 所有 embedder encode_* / YOLO detect 前向持 core/gpu_lock 全局锁
  → 并发前向（YOLO cuDNN 卷积 + bitsandbytes 8bit matmul）在 24GB 机器触发驱动硬故障
  → detection 攒批 128（约 2-4s 持锁），1024 长批持锁 ~20s 会饿死 embedder / 卡死共享流
并发管道 (v0.22): max_concurrent_videos >0 → VideoService 信号量限流，防组批量激活峰值叠加 OOM

Keyframe 消费 4 链路:
  ① frame_encode → frame_embeddings 表 (1fps 帧向量)
  ② chunk_encode → chunks 表 (滑动窗口, 默认关闭; 窗口 ≤5s 不切 / 5-60s 半时长 / >60s 30s/步15s)
  ③ text_encode → scenes.text_embedding (caption+ocr+transcript 语义)
  ④ caption → scene.caption

Caption 双模式: native_video (Qwen3-VL-8B 本地 GPU 原生视频理解 → 结构化 JSON; 已置灰退役, 8B 不再下载) / vlm_llm (Qwen-VL-Max API 看图, 默认)
Summary 双模式: native_video (纯 Python 聚合器, 无 API 成本; 已置灰退役) / vlm_llm (DeepSeek API, 默认)
Track 语义路 (track_encode): 读 detection 缓存 640×384 crop (每 2s, 零 FFmpeg seek)
  → 挑 20%/50%/80% 3 帧 → mean pool → cosine ≥0.85 + 同类 + 时序不重叠 全局缝合
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
       search.py (6 检索) · db.py (引擎/init_db) · config_loader.py (settings 覆盖/参数钳制/自动降级)
       settings_service.py (设置) · presets_service.py (参数预设) · gpu_lock.py (GPU 串行锁)
       cancellation.py (管道取消登记, 删除处理中视频后优雅中止)
       prompt_loader.py · status_tracker.py (进度) · interfaces.py (10 插件 ABC) · exceptions.py
config/  config.yaml (server/db/storage/plugins/pipeline) · config_schema.py · prompts.yaml
frontend/  Dashboard.tsx + components/ (20) + hooks/ (8) + labels.ts + services/api.ts + types/
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
               qwen_api      → Qwen-VL-Max DashScope API (vlm_llm mode; 本地模型缺失自动降级)
  embedder:    qwen3_vl_embedding_8b → local GPU model (Qwen3-VL-Embedding-8B), loaded at startup
                                       可选 quantization none/8bit/4bit (bitsandbytes); 相对路径解析到项目根
  summarizer:  vllm          → DeepSeek API (vlm_llm mode only; native mode uses Python aggregator)
                               (截断自愈: finish_reason=length → max_tokens 翻倍重试 ≤3 次 + JSON 截断修复)
  transcriber: null          → disabled (faster-whisper plugin exists, opt-in)
  detector:    yolo          → YOLO11s object detection (默认启用; batch_size/imgsz 可配; 共享单实例懒加载)
  face:        insightface   → InsightFace SCRFD + ArcFace R50 (512d)
  plate:       hyperlpr      → HyperLPR3 ONNX Runtime LPR (with PaddleOCR alternative)
  ocr:         null          → disabled (placeholder)
  grounding:   null          → disabled (placeholder)

所有 embedder encode_* / YOLO detect 前向持 core/gpu_lock 全局锁串行（v0.22，防并发驱动故障）

人脸/车牌 ONNX 推理依赖 onnxruntime：x86/Windows 装 onnxruntime-gpu（GPU 探针含 CUDAExecutionProvider）；
ARM64（DGX Spark/GB10）无 onnxruntime-gpu wheel → requirements 环境标记自动装 onnxruntime CPU 版（人脸/车牌走 CPU）。


## Search Architecture

```
Semantic Search: POST /api/v1/search/semantic — query → embedder.encode_text() (编码一次)
  → 6 路并行召回:
     frame (1fps 精确秒) / chunk (滑窗, 默认关) / text (caption+ocr+transcript 语义)
     label (JSONB @> entities) / track (crop 跨模态, 返回具体物体) / plate (Levenshtein + ILIKE + 字符归一化)
  → Face 图搜: POST /search/face — 图片 → ArcFace 512d → face_identities cosine
  → 通用图搜: POST /search/image — 图片 → Qwen3-VL 4096-dim → frame_embeddings
     (专用 search_image_only 路径: 帧不聚类, 每帧独立精确到秒, 不补 scene 信息)
  → 合并去重: 帧簇(间隔≤4s)优先, chunk/text 与帧重叠丢弃, track/plate 各按 (video_id, track_id) 去重
  → 范围过滤: video_ids 为空列表 → 返回空（fail-closed, `if video_ids is not None`）；None=全库
  返回: {precision_level, precise_start/end, match_paths, thumbnail_url, track_id?, bbox?}

core/search.py 6 种检索函数:
  frame_vector_search · chunk_vector_search · text_vector_search
  track_vector_search · plate_text_search (Levenshtein + ILIKE + 归一化, 单字模糊) · face_identity_search (ArcFace cosine)
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
  ├─ function: search_index_enabled, summary_enabled, summary_mode
  ├─ advanced: sample_fps, segment_threshold, caption_with_context, summary_detail
  ├─ summary (JSONB)
  ├─ metadata_json (JSONB)          — 缓存的完整技术元数据（首次提取后后续 <1ms）
  ├─ source_analysis (JSONB)        — 视频来源分析：类型/置信度/证据链/监控品牌
  ├─ ai_detect_result (JSONB)       — [残留] AI 生成检测结果（AICheck 服务已移除，此列保留但恒为 not_run）
  ├─ status_detail (管道实时操作描述)
  ├─ source_owned (Boolean, 默认 true; 平台共享文件= false → 删除不 unlink 源文件, v0.24)
  ├─ group_id (UUID FK → video_groups.id, nullable, v0.19) — NULL=单视频未分组
  └─ created_at, updated_at

scenes
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ scene_index, start_sec, end_sec, keyframe_path
  ├─ text_embedding (Vector 4096)    — caption+ocr+transcript 语义向量
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
  ├─ embedding (Vector 4096), thumbnail_path, is_keyframe
  └─ created_at

chunks
  ├─ id (SERIAL PK), video_id (UUID FK → videos.id CASCADE)
  ├─ scene_index, chunk_index, start_sec, end_sec
  ├─ embedding (Vector 4096), thumbnail_path
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
  ├─ track_id, class_name, embedding (Vector 4096)
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
| POST | /api/v1/videos/register-external | 平台共享文件就地引用 (source_owned=false, 删视频不删源文件, v0.24) |
| GET | /api/v1/videos/external/{file_id} | 按云智平台文件库资源 ID 查找视频（Bridge context.resource.id → 自动跳转目标；无匹配 404，v0.26） |
| PUT | /api/v1/videos/{id}/params | 设置参数 + 启动 Pipeline (pending/completed) |
| POST | /api/v1/videos/reuse | 基于已有视频创建新记录 (复用文件) |
| GET | /api/v1/videos/ | 视频列表 (按创建时间降序) |
| GET | /api/v1/videos/{id} | 视频详情 + 关联 scenes + transcript |
| GET | /api/v1/videos/{id}/status | 轻量进度查询 |
| GET | /api/v1/videos/{id}/stream | 视频流式播放 (支持 Range) |
| GET | /api/v1/videos/{id}/thumbnail/{scene_index} | 场景缩略图 |
| DELETE | /api/v1/videos/{id} | 删除视频 (级联+清盘; 处理中可删, 管道优雅中止) |
| GET | /api/v1/videos/{id}/metadata | 视频元数据 + 来源分析 (支持 ?verbose=true, 自动缓存) |
| GET | /api/v1/settings | 获取系统设置 (API 密钥/服务商端点与模型/存储路径/管道性能) |
| PUT | /api/v1/settings | 更新系统设置 (密钥/服务商/存储/pipeline 段皆可，保存即运行时生效；量化需重启) |
| GET | /api/v1/settings/pipeline | 获取 Pipeline 配置 (编码预设/摘要模式默认/插件可用性) |
| GET | /api/v1/settings/presets | 列出参数预设 (v0.22) |
| POST | /api/v1/settings/presets | 创建参数预设 (快照当前生效管道参数) |
| PUT | /api/v1/settings/presets/{id} | 重命名参数预设 |
| DELETE | /api/v1/settings/presets/{id} | 删除参数预设 |
| POST | /api/v1/settings/presets/{id}/apply | 套用参数预设 (写回 settings.json 覆盖区, 运行时生效) |
| GET | /api/v1/pipeline/operations | 查询启用的操作列表 + 进度范围 |
| GET | /api/v1/videos/{id}/detection/tracks | 追踪轨迹摘要 (v0.22 替代旧 /detection/data) |
| GET | /api/v1/videos/{id}/detection/detections | 时间窗逐帧检测框 (v0.22, 按需区间加载) |
| GET | /api/v1/videos/{id}/detection/thumbnail | track crop 缩略图 (bbox 裁剪) |
| GET | /api/v1/videos/{id}/face/data | 人脸识别数据 (身份/track_id/时间戳) |
| GET | /api/v1/videos/{id}/face/thumbnail | 人脸 crop 缩略图 |
| GET | /api/v1/videos/{id}/plate/data | 车牌识别数据 |
| GET | /api/v1/videos/{id}/plate/thumbnail | 车牌缩略图 |
| POST | /api/v1/search/semantic | 语义搜索 (六路并行：frame+chunk+text+label+track+plate) |
| POST | /api/v1/search/face | 人脸图片搜索 (multipart image → ArcFace 512d) |
| POST | /api/v1/search/image | 通用图搜 (multipart image → Qwen3-VL-Embedding 4096-dim → frame_embeddings) |
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
| POST | /internal/yunzhi/jobs | 云智平台异步任务 (根路径挂载非 /api/v1, 立即202+幂等, 进度/完成/失败回调, v0.24) |

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
  │   ├── SettingsPage       ← 系统设置 4 分区 (v0.22): 系统(存储/NVDEC/chunk/并发上限) + 模型参数(编码三档模板/默认档/量化 + YOLO 帧率/批/分辨率/阈值) + 参数预设(快照/套用/重命名/删除) + API 密钥(端点/模型/密钥)
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
  └── services/api.ts        ← Pipeline 阶段通过 `/pipeline/operations` 动态获取

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
  /api → http://localhost:8011 (dev)
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Plugin + Factory** | config.yaml 换后端零代码改动 |
| **pgvector over 独立向量库** | 部署简单、事务一致 |
| **本地 GPU Embedder** | 每场景/帧 4096-dim 编码，API 延迟不可接受 |
| **双模式摘要** | 默认 vlm_llm（API 驱动）；native_video（本地 GPU + 纯 Python 聚合）已置灰退役——前端不再可选，后端保留兼容历史记录（旧视频仍正常处理），captioner 8B 不再下载 |
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
| **车牌模糊检索** | 字符归一化（全角→半角/去分隔符/大写） + 编辑距离≤2 + ILIKE 子串；相似度 `LEAST(dist,2)` 封顶（子串匹配不被 0.3 门槛误杀）；「牌」模式（search_types=["plate"], top_k=100）一个字列出所有相关 |
| **上传/参数解耦** | 上传建 pending，配置后才启动管道 |
| **两层格式兼容 + 懒代理** | remux (-c copy) 即时 + proxy (NVENC h264) 按需，HEVC 浏览器零处理 |
| **GET+POST 双导出** | POST 供编程调用，GET 供浏览器直接下载 |
| **三级元数据 + DB 缓存** | pymediainfo→exiftool→ffprobe；缓存后 <1ms |
| **多视频分组 (v0.19)** | 批量上传 + 组参数同步 + 跨视频搜索 |
| **全局 ReID 缝合 (v0.20)** | 在线 with_reid + 全局 cosine ≥0.85 合并（segments 时序检查）|
| **来源分析规则引擎** | EXIF + 文件名 + 文件头魔数（IMKH→海康），无 ML 依赖 <10ms |
| **人脸/车牌开关** | 三门控: config + detection_enabled + face/plate_enabled |
| **图搜双通道** | 人脸 ArcFace 512d / 通用 Qwen3-VL 4096-dim（帧不聚类精确到秒）|
| **存储卫生 (v0.21)** | 删除 = DB 级联 + 引用追踪清盘；孤儿清扫手动（dry-run 默认）防误删 |
| **删除处理中 + 管道取消 (v0.22)** | 放开 PROCESSING 守卫；删除端点 `core/cancellation.mark_cancelled` 登记已删 id，管道 persist 前 `is_cancelled` 检查即中止，防写已删行 FK 异常（单进程集合, 管道结束 unmark 防膨胀） |
| **全局 GPU 锁 (v0.22)** | 24GB 机 YOLO 卷积 + 8bit matmul 并发触发驱动硬故障 → 单进程全局锁串行所有 GPU 前向；detection 攒批 1024→128 防饿死 embedder |
| **共享单实例 (v0.22)** | embedder + detector 预载 app.state（detector 懒加载），业务逻辑经 shared_detector 注入，禁重复 load_plugin |
| **并发管道限制 (v0.22)** | max_concurrent_videos 信号量限流（激活峰值按并发叠加），低显存机防组批量并发 OOM |
| **参数预设 (v0.22)** | presets.json 命名快照一键套用，运行时生效；不含机器相关（存储路径/密钥） |
| **从零部署 + 配置统一 (v0.22)** | setup_windows.ps1 裸机一键安装；单份 config 自动降级 captioner（本地缺失→qwen_api），effective_summary_mode 兜底摘要模式 |
| **多架构 requirements (v0.22)** | `onnxruntime-gpu` 仅 x86/Windows 有 wheel → 环境标记：win32/x86_64/AMD64 装 GPU 版，aarch64/arm64（DGX Spark/GB10）自动装 `onnxruntime` CPU 版（人脸/车牌走 CPU）；numpy 钉 `<2.4`（paddlex 3.7） |
| **embedder 量化 (v0.22)** | none/8bit/4bit (bitsandbytes) 把 ~16GB 权重降到 ~8GB/~4GB；启动时加载，改后需重启 |
| **平台共享文件 source_owned (v0.24)** | register-external 就地引用平台文件（不复制、不传字节），`source_owned=false` 时删除视频绝不 unlink 源文件（所有权归平台） |
| **平台文件 id 自动跳转 (v0.26)** | 注册/任务时把平台文件库资源 ID 存入 `videos.external_file_id`；前端 Bridge connect() 后凭 `context.resource.id` 查 `GET /videos/external/{file_id}` 自动打开对应视频详情（一次性跳转；非文件入口/无匹配正常展示默认工作台） |
| **异步任务 jobs (v0.24)** | /internal/yunzhi/jobs 根路径挂载（不经 /api/v1），202 立即返回 + 幂等（进程内 eventId/Idempotency-Key），进度经 StatusTracker.on_progress → callback.progressUrl 推送 |

## Current Status

| Module | Status | Note |
|---|---|---|
| Pipeline Core (DAG) | ✅ | EventDrivenScheduler (v0.10): operations.py declares 15 ops, search/summary decoupled, gates/deps, events-driven |
| Track Encoding (crop→embed) | ✅ | runners/track_encode.py: 读检测缓存多帧 640×384 crop（零 FFmpeg seek）→ mean pool → Qwen3-VL-Embedding 4096-dim。长视频友好（track_encode 不随 track 数 seek 爆炸） |
| Global ReID Tracklet Stitch | ✅ | track_encode Phase 2: cosine ≥0.85 + 同类 + 时序不重叠（segments 真实片段, MAX_OVERLAP_SEC=1.0 + HIGH_SIM_OVERRIDE=0.90 容忍双跟踪伪影） |
| Face Recognition | ✅ | plugins/face/insightface_face.py — SCRFD + ArcFace R50 (512d), FaceRunner identity clustering |
| License Plate Recognition | ✅ | plugins/plate/hyperlpr_plate.py — HyperLPR3 detection + text recognition (paddle_plate.py alternative), PlateRunner |
| Face Image Search | ✅ | POST /api/v1/search/face — upload image → ArcFace 512d → face_identities cosine match |
| Plate Text Search（模糊） | ✅ | core/search.py plate_text_search — 归一化(全角/分隔符/大写) + Levenshtein≤2 + ILIKE 子串 + 相似度 LEAST 封顶；plate 按 (video_id, track_id) 独立去重；前端「牌」模式按钮 |
| Semantic Search (7-path) | ✅ | frame + chunk + text + label + track + plate + image 并行召回, plate 独立 ILIKE |
| Universal Image Search | ✅ | POST /api/v1/search/image — Qwen3-VL-Embedding 4096-dim → frame_embeddings, 独立 search_image_only() 路径 (帧不聚类、不补 scene、每帧独立精确到秒) |
| Frontend Chinese Labels | ✅ | frontend/src/labels.ts — 统一 ZH_LABELS (80 COCO 类)+zh()/zhLabel()/colorOf(), 消除 3 份重复 CLASS_COLORS |
| Frame-level Encoding | ✅ | runners/frame_encode.py: batch encode 4 frames |
| Chunk-level Encoding | ⚠️ | config pipeline.chunk_encoding 控制，默认关闭 |
| Text Semantic Encoding | ✅ | runners/text_encode.py: ctx 写入 → Persist 统一入库 |
| Summary（双模式摘要） | ✅ | 默认 vlm_llm（API 驱动）；native_video 已置灰退役（前端不可选，后端 effective_summary_mode 保留兼容，旧视频仍正常处理；captioner 8B 不再下载） |
| Object Detection + Tracking | ✅ | YOLO11s + BoT-SORT, 10fps 独立帧率（与 search 共享 NVDEC 流）, dual-gate control; 共享 app.state 单实例懒加载 + gpu_lock 串行, batch_size/imgsz 可配 |
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
| Storage Hygiene (v0.21) | ✅ | core/storage_manager.py: 删除即清盘 (DB 级联 + 引用追踪) + 空组清理; POST /maintenance/sweep 清扫 + scripts/sweep_storage.py CLI; trackthumb 泄漏修复; 缩略图缺失 404 兜底 |
| Delete-while-processing (v0.22) | ✅ | core/cancellation.py — 删除端点 mark_cancelled 登记, engine persist 前 is_cancelled 检查中止; 前端删除按钮放开 processing、去释放空间弹窗 |
| Multi-Video Group (v0.19) | ✅ | POST /videos/upload/batch; VideoGroup ORM; 组参数同步; frontend 历史堆叠/展开/切换/跨视频搜索/独立检测面板 |
| Settings API (Keys + Providers + Storage + Pipeline) | ✅ | core/settings_service.py, GET/PUT /api/v1/settings（密钥/端点/模型 + 存储路径 + pipeline 段: 编码三档/检测参数/量化/并发上限，settings.json backed，运行时生效，量化需重启） |
| Pipeline Presets (v0.22) | ✅ | core/presets_service.py + /settings/presets CRUD + apply（data/presets.json 命名快照，一键套用） |
| Global GPU Lock (v0.22) | ✅ | core/gpu_lock.py — embedder/YOLO 前向全局串行（防 24GB 机并发驱动故障）; detection 攒批 128 |
| 并发管道限制 (v0.22) | ✅ | pipeline.max_concurrent_videos → VideoService asyncio.Semaphore 限流同时处理的管道数 |
| Embedder Quantization (v0.22) | ✅ | plugins/embedder/qwen_vl_embedder.py — none/8bit/4bit via bitsandbytes; 相对模型路径解析到项目根 |
| Windows 从零部署 + 多架构 (v0.22) | ✅ | deploy/setup_windows.ps1 裸机一键安装器 + download_models.py (含 reid) + deploy_feedback.md; 单份 config 自动降级 captioner; requirements 环境标记支持 ARM64 (onnxruntime CPU) |
| Frontend Dashboard | ✅ | React 19 + Vite + Tailwind, 20 components + 8 hooks + labels.ts incl Detection/Timeline/Metadata/Export/ImageSearch |
| Config Schema | ✅ | Pydantic v2 validation for config.yaml |
| Prompt Templates | ✅ | config/prompts.yaml — caption/summarizer/grounding prompts |
| DB Layer | ✅ | Async engine, pgvector, init_db(), incremental migration, 12 tables (+video_groups) |
| TransNetV2 Segmenter | ✅ | Neural scene boundary detection |
| faster-whisper Transcriber | ✅ | Plugin exists, config-disabled by default |
| OCR | 📋 | PaddleOCR available as plate recognition alternative (plugins/plate/paddle_plate.py) |
| Grounding | 📋 | Florence-2 shell only |
| 云智平台接入 (v0.24) | ✅ | api/yunzhi_routes.py + services/yunzhi_job_service.py: POST /internal/yunzhi/jobs（根路径, 202+幂等, callback.progressUrl/completeUrl/failUrl, 结果写 workDirectory） |
| 平台共享文件 (v0.24) | ✅ | POST /videos/register-external（source_owned=false 就地引用, 删除不 unlink 源文件）; StatusTracker.on_progress / engine.progress_callback 透传 |
| 前端 Bridge (v0.24) | ✅ | frontend/src/platform/（yunzhi-bridge.ts/client.ts/YunzhiProvider/mock, VITE_YUNZHI_MOCK 切换真实/模拟） |
| 平台文件 id 自动跳转 (v0.26) | ✅ | videos.external_file_id + GET /videos/external/{file_id} + Dashboard connect() 后凭 context.resource.id 自动打开对应视频 |
| 生产部署 (v0.24) | ✅ | systemd `zhiying.service` @ 10.0.0.176:8011, pgvector:pg17 容器, 后端静态托管 frontend/dist 免 nginx; 运维见 docs/server.md |
| Health | ✅ | main.py GET /health → {"status":"ok","service":"zhiying","version":"<__version__>","database":"ok"}（含 DB 连通性 + 版本号） |
| Reindex | 🔶 | 待办 |

## 版本发布

- **唯一事实来源**：`core/version.py` `__version__`（SemVer pre-1.0：MINOR=新功能，PATCH=热修）；`/health` 返回 `version` 字段，部署/回滚后 `curl /health` 即可核对服务器实际运行版本。
- **发版**：`./bump minor|patch|0.24.0` —— 联动改 `core/version.py` + `frontend/package.json` + `package-lock.json`（含两处根版本，避免 npm ci 因版本不同步报错），随后交互式输入提交信息、确认 `git add .` commit / tag / push。机器不自动提交——每一步发布动作由你按 y 确认（不擅自动版本库）。
- **tag 强绑定**：git tag 必须 `v<__version__>`，与 version.py 完全一致；回滚 = 服务器 `git checkout v<旧tag>` + 重启。版本与 tag 不一致时 `/health` 无法对质。
- **多开发机**：`./bump` 是随仓库分发的 bash 启动器，任何开发机 `git pull` 后即可用（Windows 开发机用 `python scripts/bump_version.py`）。
