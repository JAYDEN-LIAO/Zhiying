# Zhiying — Universal Video Analytics Engine

A general-purpose video analytics engine for semantic search and structured summarization. Designed for single-GPU setups (8–32 GB VRAM).

## Quick Start

```bash
# 1. Start database
docker compose up -d db

# 2. Set API keys (only needed for vlm_llm summary mode)
set DASHSCOPE_API_KEY=sk-xxx   # Qwen-VL API (vlm_llm captioning)
set DEEPSEEK_API_KEY=sk-xxx    # LLM summarizer (vlm_llm mode)

# 3. Start backend server
uvicorn main:app --reload
# 健康检查：http://localhost:8011/health  →  {"status":"ok","service":"zhiying","version":"<当前版本>","database":"ok"}

# 4. (New tab) Start frontend dev server
cd frontend && npm install && npm run dev

# 5. Upload a video via curl
curl -X POST -F "file=@demo.mp4" http://localhost:8011/api/v1/videos/upload

# 6. Get summary
curl http://localhost:8011/api/v1/videos/{video_id}

# 7. Semantic search
curl -X POST -H "Content-Type: application/json" \
  -d '{"query":"a man in black"}' \
  http://localhost:8011/api/v1/search/semantic
```

> **Note on API Keys**: Place keys in a `.env` file at project root (gitignored).  
> Keys are only required when using the `vlm_llm` summary mode; the default `native_video` mode runs entirely on local GPU.

## Windows 部署

**从零部署**：全新 Windows + NVIDIA GPU 机器上，双击 `deploy/setup_windows.ps1` 自动安装一切（Python / FFmpeg / CUDA torch / WSL2 / Docker / 依赖 / 全部模型），装完自校验并打印启动指令。

- 一键安装器、环境要求、模型清单（embedding/yolo/**reid**/face/plate/segmenter）、代理必填与国内镜像、坑位审计与 Linux/Windows 差异，详见 **[`deploy/deploy.md`](deploy/deploy.md)**。
- 部署实测踩坑记录（BOM 编码 / Blackwell cu130 / pip 大文件 curl 兜底 / 代理策略等）见 **[`deploy/deploy_feedback.md`](deploy/deploy_feedback.md)**。
- 配置已统一：单份 `config/config.yaml` 通用所有机器（embedder 相对路径解析 + captioner 本地模型缺失自动降级 `qwen_api`），无需 `config.windows.yaml` / `ZHIYING_CONFIG`。
- **多架构支持**：`requirements.txt` 用环境标记区分平台——Windows/Linux x86 装 `onnxruntime-gpu`（人脸/车牌 GPU），**ARM64 Linux**（DGX Spark/GB10 等，无 `onnxruntime-gpu` wheel）自动装 `onnxruntime` CPU 版，人脸/车牌走 CPU。

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
| Universal Image Search | `POST /api/v1/search/image` (upload any image → Qwen3-VL-Embedding 4096-dim → frame_embeddings) | ✅ |
| Plate Text Search | `POST /api/v1/search/semantic` (plate path, Levenshtein + ILIKE) | ✅ |
| Track Thumbnail Download | `GET /api/v1/videos/{id}/export/track/{tid}/thumbnail` | ✅ |
| Track Video Export (zip) | `GET/POST /api/v1/videos/{id}/export/track/{tid}` | ✅ |
| Video Clip Export | `GET/POST /api/v1/videos/{id}/export/clip` | ✅ |
| Scene Thumbnails Export (zip) | `GET/POST /api/v1/videos/{id}/export/thumbnails` | ✅ |
| System Settings (API 服务 + 存储路径 + 管道性能) | `GET/PUT /api/v1/settings`（API 密钥/服务商端点/存储路径 + 管道性能：编码三档模板/检测参数/量化/并发上限，保存即运行时生效，量化需重启）+ `GET /api/v1/settings/pipeline` | ✅ |
| Pipeline Presets (参数预设) | `GET/POST/PUT/DELETE /api/v1/settings/presets` + `POST /{id}/apply`（data/presets.json 多套命名参数快照，一键套用） | ✅ |
| Windows 从零部署 | `deploy/setup_windows.ps1` 裸机一键安装器（Python/FFmpeg/CUDA torch/WSL2/Docker/依赖/模型）+ 自校验 | ✅ |
| 全局 GPU 锁 + 并发限制 | `core/gpu_lock.py` 串行化 embedder/YOLO 前向（防驱动故障）；`max_concurrent_videos` 信号量限流低显存并发 | ✅ |
| Frontend Dashboard | React 19 + Vite + Tailwind CSS 4 (unified objects view + face toggle) | ✅ |
| Track Crop Embedding (track search) | `POST /api/v1/search/semantic` (track path) | ✅ |
| Frontend Labels Chinese Localization | 统一 labels.ts 映射中心，zh()/zhLabel()/colorOf() 函数 | ✅ |
| Incremental Processing | summary/search re-run on completed videos | ✅ |
| Video Source Analysis | Rule engine: phone/camera/screen_recording/surveillance/non_camera_source + 监控品牌识别（文件头魔数嗅探 IMKH→海康威视）| ✅ |
| Global ReID Tracklet Stitching | 合并被遮挡/缩放/镜头切换拆分的同一身份 track（在线 ReID + 全局缝合双层） | ✅ |
| Metadata Caching | Extracted metadata cached to DB (fast path <1ms on repeat requests) | ✅ |
| Storage Hygiene (v0.21) | 删除视频 = DB 级联 + 磁盘文件全回收（引用计数, reuse 共享安全, 空组自动清理）| ✅ |
| Delete-while-processing + Pipeline Cancel (v0.22) | 处理中视频**允许删除**：删除端点登记 `core.cancellation`，后台管道 persist 前检查 `is_cancelled` 优雅中止（防写已删行 FK 异常） | ✅ |
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
         │    ├─ 删除: 404 守卫; 处理中可删 (cancellation 登记, 管道优雅中止)
         │    └─ sweep: 磁盘 vs DB 对账 (附属目录按 video_id, mtime 保护上传竞态)
         └─ Shared GPU models (embedder + detector 预加载到 app.state; captioner 按需加载):
              ├─ Qwen3-VL-Embedding-8B (embedder, FP16, ~16GB, preloaded; 可选 8bit/4bit 量化)
              ├─ Qwen3-VL-8B-Instruct (captioner, BF16, ~16GB, on-demand)
              ├─ YOLO11s (detector, ~2GB, 模型懒加载共享单实例)
              └─ SCRFD + ArcFace R50 (face recognizer, ONNX, preloaded)
         GPU 前向串行: 所有 embedder/YOLO 推理持 core/gpu_lock 全局锁
         （24GB 机器并发前向触发驱动故障; detection 攒批 128 保证 embedder 不被饿死）
```

- **声明式 DAG 引擎** — 15 个操作注册在 `pipeline/operations.py`（gate 条件 + 依赖边），EventDrivenScheduler 事件驱动执行；搜索/摘要路径解耦，与 detection 共享单 NVDEC 流（生产者-消费者并发）。
- **插件化** — 10 个插件 ABC + 工厂动态加载（config.yaml 换后端零代码改动）；4 条编码路径（frame/chunk/text/track）+ 7 路检索 + 人脸/车牌 + 4 级参数系统。
- **存储卫生 (v0.21)** — 删除即清盘（DB 级联 + 引用追踪）+ 孤儿清扫（`POST /maintenance/sweep` / `scripts/sweep_storage.py`）。
- **设置与参数系统 (v0.22)** — 系统设置页四区（存储/模型参数/参数预设/API 密钥），`data/settings.json` 覆盖 config.yaml 运行时生效；参数预设 `data/presets.json` 命名快照一键套用；4 级参数系统逐视频控制管道。
- **从零部署 (v0.22)** — `deploy/setup_windows.ps1` 一键安装（系统级/依赖级/模型级 + 自校验）；单份配置自动降级 captioner（本地 8B 缺失 → qwen_api）。
- **架构细节见 `docs/arch.md`**（Pipeline Detail / Database Schema / API Endpoints / Key Design Decisions）。

## Tech Stack

| Component | Technology |
|---|---|
| Backend Framework | FastAPI (Python 3.13) |
| Frontend Framework | React 19 + TypeScript |
| Build Tool | Vite 6 |
| CSS | Tailwind CSS 4 |
| Database | PostgreSQL 17 + pgvector 0.8 |
| Vector Embedding | Qwen3-VL-Embedding-8B (local GPU, 可选 8bit/4bit 量化) |
| Object Detection | YOLO11s (local GPU, 共享单实例 + 全局 GPU 锁串行) |
| Object Tracking | BoT-SORT + 在线 ReID (with_reid=true, 本地 `models/yolo26n-cls.pt` 外观模型, 10fps, track_buffer=45, match_thresh=0.5) |
| Captioning | Qwen3-VL-8B (local GPU, default) / Qwen-VL-Max (API, vlm_llm mode) |
| Summarization | Pure Python aggregator (default) / DeepSeek Chat (API, vlm_llm mode) |
| Scene Segmentation | TransNetV2 / Time-based (fixed interval) |
| Audio Transcription | faster-whisper (plugin ready, opt-in) |
| Video Processing | FFmpeg (asyncio subprocess) |
| Metadata Extraction | pymediainfo + exiftool (optional) |

## 版本号与发布

- **版本唯一事实来源**：`core/version.py` 的 `__version__`（SemVer pre-1.0：MINOR=新功能，PATCH=热修）；`/health` 返回 `version` 字段，服务器部署后 `curl /health` 即可核对运行版本。
- **发版**：`./bump minor`（新功能）/ `./bump patch`（修 bug）/ `./bump 0.24.0`（指定版本）。一条命令联动改 `core/version.py` + `frontend/package.json` + `package-lock.json`（含两处根版本），随后交互式让你输入提交信息、确认 `git add .` 提交、打 tag、推送——机器不擅自动手，但也不用复制粘贴命令。
- **tag 强绑定**：git tag 必须命名为 `v<__version__>`，与 `core/version.py` 完全一致；回滚 = 服务器 `git checkout v<旧tag>` + 重启。
- `./bump` 是随仓库分发的 bash 启动器，任何开发机 `git pull` 后即可用（Windows 开发机用 `python scripts/bump_version.py`）。

## Project Structure

```
zhiying/
├── bump                 # 版本号一键提升启动器 (→ scripts/bump_version.py)
├── main.py               # FastAPI entry point
├── api/                  # Route definitions
│   ├── router.py         # Route assembly (sub-routers under /api/v1)
│   ├── routes.py         # Transitional re-export
│   ├── deps.py           # FastAPI dependencies (DB session)
│   ├── schemas.py        # Shared API DTOs
│   ├── video_routes.py   # Video CRUD + upload + stream + thumbnail + metadata
│   ├── search_routes.py  # Semantic search + pipeline/operations
│   ├── settings_routes.py# 系统设置: /settings (密钥/服务商/存储/管道) + /settings/pipeline + /settings/presets
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
│   ├── config_loader.py  # YAML + .env + settings.json 覆盖; 参数钳制 + captioner 自动降级
│   ├── prompt_loader.py  # Prompt template loader
│   ├── status_tracker.py # Pipeline progress persistence
│   ├── settings_service.py # 设置管理: API密钥/服务商端点与模型/存储路径/管道性能 (settings.json backed)
│   ├── presets_service.py # 参数预设: 命名快照 create/apply/rename/delete (presets.json)
│   ├── gpu_lock.py       # 全局 GPU 推理锁 (embedder/YOLO 前向串行)
│   ├── cancellation.py   # 管道取消登记 (删除处理中视频后优雅中止, persist 前检查)
│   ├── storage_manager.py # 存储管理: 路径解析/引用追踪/删除清盘/孤儿清扫
│   ├── exceptions.py     # Custom exceptions
│   └── version.py        # 版本号单一事实来源 (__version__, /health 输出)
├── config/               # Configuration
│   ├── config.yaml       # Main config (server/db/storage/plugins/pipeline + encode_profiles/quantization/max_concurrent_videos)
│   ├── botsort.yaml      # BoT-SORT + ReID tracker 参数 (with_reid, 本地 yolo26n-cls.pt)
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
│   ├── detector/         # YOLO11s + BoT-SORT (全局 GPU 锁 + 可配 batch/imgsz)
│   ├── face/             # InsightFace SCRFD + ArcFace R50
│   ├── plate/            # HyperLPR3 (primary) / PaddleOCR (alternative)
│   ├── ocr/              # (stub) PaddleOCR
│   └── grounding/        # (stub) Florence-2
├── services/             # Business logic layer
│   ├── video_service.py  # Video processing orchestration (max_concurrent_videos 信号量限流)
│   ├── format_service.py # Multi-format support (probe/remux/proxy, lazy on-demand)
│   ├── export_service.py # Export business logic (clip/frames/track/thumbnails)
├── utils/                # FFmpeg tools + metadata extraction
│   ├── video_util.py     # FFmpeg subprocess helpers (extract audio/keyframes/duration)
│   ├── metadata.py       # Video metadata extraction (pymediainfo/exiftool/ffprobe)
│   └── video_source.py   # Video source classification (rule engine: phone/camera/surveillance/...)
├── frontend/             # React + Vite + Tailwind dashboard
│   ├── public/
│   │   └── zhiying.svg     # App logo
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
├── models/               # Local model weights (gitignored; yolo26s.pt, yolo26n-cls.pt 等在仓库内)
├── data/                 # Video storage & artifacts + settings.json/presets.json (gitignored)
├── config/               # YAML config, prompts, schema
├── deploy/               # Windows 从零部署套件: setup_windows.ps1 一键安装器 / download_models.py / deploy.md / deploy_feedback.md
├── scripts/              # 运维工具: sweep_storage.py 存储清扫 CLI (默认 dry-run, --apply 执行) + bump_version.py 一键版本提升
└── docs/                 # Design documents + search architecture docs
```

## Development Status

- **v0.22 — 部署系统 + 系统设置与参数系统 + Detection 渲染重构**:
  - **Windows 从零部署**: `deploy/setup_windows.ps1` 重写为裸机一键安装器（系统级 Python/FFmpeg/WSL2/Docker + 依赖级 CUDA torch 按 GPU 选源/onnxruntime-gpu + 模型级 embedding/yolo/**reid**/face/plate/segmenter + 自校验）；删除旧 `start_windows.ps1` / `write_windows_config.py`；`deploy_feedback.md` 记录部署踩坑（UTF-8 BOM、Blackwell cu130、pip 大文件 curl 兜底、代理策略、onnxruntime-gpu 桩等）。
  - **配置统一 + 自动降级**: 单份 `config/config.yaml` 通用所有机器——embedder 相对模型路径解析到项目根；captioner 本地 8B 模型缺失 → 自动降级 `qwen_api`（DashScope）+ `effective_summary_mode` 兜底；无需 `config.windows.yaml` / `ZHIYING_CONFIG`。BoT-SORT ReID 改用本地 `models/yolo26n-cls.pt`（实测 `auto` 仍从 GitHub 下载）。
  - **系统设置完善**: `GET/PUT /settings` 扩展 `pipeline` 段（编码三档模板 + 检测帧率/批大小/分辨率/阈值 + NVDEC/chunk 开关 + embedder 量化 + 并发上限），数值按 `PIPELINE_NUMERIC_SPEC` 钳制，保存即运行时生效（量化需重启）；前端设置页 4 分区。
  - **参数预设**: `data/presets.json` 多套命名管道参数快照，`/settings/presets` CRUD + apply 一键套用。
  - **全局 GPU 锁 + 共享单实例**: `core/gpu_lock.py` 串行化 embedder/YOLO 前向（24GB 机并发前向触发驱动硬故障）；detector 共享 `app.state` 单实例（懒加载 ~2GB）；detection 攒批 1024→128（长批持锁饿死 embedder）；`max_concurrent_videos` 信号量限流并发管道。
  - **Detection 渲染重构**: `/detection/data` 拆为 `/detection/tracks` + `/detection/detections`（按需时间窗）；前端 DetectionPanel 虚拟滚动 + DetectionTimeline Canvas 化；`frame_detections` 复合索引。
  - **删除处理中 + 管道取消**: 删除端点放开 PROCESSING 守卫（处理中视频可删），`core/cancellation.py` 登记后管道 persist 前 `is_cancelled` 检查优雅中止（防写已删行 FK 异常）；前端删除按钮不再禁用 processing、去掉"释放空间"弹窗。
  - **多架构 requirements**: `onnxruntime-gpu` 仅 Windows/x86 Linux 有 wheel；ARM64（DGX Spark/GB10）无 → 环境标记自动装 `onnxruntime` CPU 版（人脸/车牌走 CPU）；numpy 钉 `<2.4`（paddlex 3.7 要求）。
- **v0.21 — Storage Hygiene & Management**: 删除视频 = DB 级联 + 磁盘全回收（StorageManager 按 DB 引用追踪，reuse 共享文件只在最后引用删除时清理，空组同事务自动清理，处理中守卫 409 + `RUNNING_VIDEOS` 注册表闭合竞态）；批量 DELETE 替代 ORM 全量 load（删大视频性能修复）；`POST /maintenance/sweep`（dry-run/执行）+ `GET /maintenance/storage` + CLI `scripts/sweep_storage.py` 孤儿清扫（sweep 按 video_id 判定附属目录、mtime 保护上传竞态）；trackthumb 导出泄漏修复；人脸/检测/车牌缩略图缺失 404 兜底；前端删除二次确认 + processing 禁用 + 释放空间提示。
- **维护记录**: 清理废弃的前端 `DetectionContext`/`mockData`，进度阶段统一由 `/pipeline/operations` 按视频参数动态返回；补充 Python、前端缓存及本地环境文件的忽略规则。
- **v0.20 — Dual-layer ReID**: 在线 BoT-SORT ReID（`with_reid` + 检测骨干特征直通, 遮挡/交叉保持身份）+ 全局 tracklet 缝合（detection 缓存 crop → mean pool → cosine ≥0.85 合并同一身份, segments 时序检查）。长视频友好（track_encode 零 seek）。
- **v0.19 — Multi-Video Group**: 批量上传 + VideoGroup 分组 + 组参数同步启动 + 前端历史堆叠/展开 + 组内切换 + 跨视频搜索 + 独立检测面板。
- **v0.18 — Universal Image Search + 中文化**: `POST /search/image` 通用图搜（独立 `search_image_only` 路径，帧不聚类精确到秒）+ 前端标签中文化 labels.ts。
- **Planned**: Grounding (Florence-2), OCR
