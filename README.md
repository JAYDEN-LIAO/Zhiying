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
python run.py   # 按 config.yaml server 段绑定端口（默认 8011），reload 模式
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

> **Note on API Keys**: Place keys in a `.env` file at project root (gitignored)，或在前端设置页填写。  
> **摘要默认 `vlm_llm`（API 模式）**，需要 DashScope（画面描述）+ DeepSeek（摘要）key。`native_video`（本地视频原生理解）已置灰退役。

**Windows 桌面端**：环境就绪（`deploy/setup_windows.ps1` 装机——自动装模型/Docker/依赖/生成 config.yaml/构建桌面前端 dist）后，双击 `智影桌面端.exe`（构建方法见 `desktop/README.md`）或 `python desktop/app.py`——启动器自动检查就绪 → 起 Docker 库 → 起本地后端 → 打开 pywebview 桌面窗口加载桌面前端（`ZHIYING_FRONTEND=desktop` 挂载 frontend-desktop/dist，与服务器前端 `frontend/` 完全隔离）。

## Windows 部署

**从零部署**：全新 Windows + NVIDIA GPU 机器上，双击 `deploy/setup_windows.ps1` 自动安装一切（Python / FFmpeg / CUDA torch / WSL2 / Docker / 依赖 / 全部模型 / config.yaml / 前端 dist），装完自校验并打印启动指令；环境就绪后双击 `智影桌面端.exe` 即可拉起桌面进程（构建方法见 `desktop/README.md`）。

**Linux 开发机部署**：换新开发机时 `git clone` 后跑 `bash deploy/setup_linux.sh`（交互输代理 / `--proxy ... --non-interactive` 全自动），一键装齐环境/依赖/模型/前端，形态与本机一致，用于开发改代码测试。

- 一键安装器、环境要求、模型清单（embedding/yolo/**reid**/face/plate/segmenter）、代理必填与国内镜像、Linux/Windows 差异，详见 **[`deploy/deploy.md`](deploy/deploy.md)**。
- 部署实测踩坑记录（BOM 编码 / Blackwell cu130 / pip 大文件 curl 兜底 / 代理策略等）见 **[`deploy/deploy_feedback.md`](deploy/deploy_feedback.md)**。
- **配置模板化（v0.25.1 起）**：`config/config.yaml` **机器相关、gitignored、不入库**，新机复制 `config/config.yaml.example` 自改（embedder 相对路径解析 + captioner 本地模型缺失自动降级 `qwen_api`），无需 `config.windows.yaml` / `ZHIYING_CONFIG`。
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
| Face Recognition | SCRFD + ArcFace R50 (512d) identity clustering（v0.29: 护栏式双阈值聚类 + 多帧采样 + 最典型脸锚点） | ✅ |
| License Plate Recognition | HyperLPR3 (ONNX Runtime) detection + text recognition | ✅ |
| Face Image Search | `POST /api/v1/search/face` (upload image → ArcFace 512d; v0.29 双锚检索 + 返回 appearances 时间段) | ✅ |
| 搜索数据隔离 | search/face + search/image 严格按 video_ids 过滤（v0.29 修复 form 参数泄漏全库 bug） | ✅ |
| 五种搜索样式统一 | 语义/图搜/物体/车牌/人脸统一 sr-item 卡片（标签右上角 + 主体1行 + 导出展开式） | ✅ |
| Universal Image Search | `POST /api/v1/search/image` (upload any image → Qwen3-VL-Embedding 4096-dim → frame_embeddings) | ✅ |
| Plate Text Search（模糊模式） | `POST /api/v1/search/semantic`（plate path: Levenshtein + ILIKE + 字符归一化；前端「牌」模式按钮 → 一个字列出所有相关车牌） | ✅ |
| Track Thumbnail Download | `GET /api/v1/videos/{id}/export/track/{tid}/thumbnail` | ✅ |
| Track Video Export (zip) | `GET/POST /api/v1/videos/{id}/export/track/{tid}` | ✅ |
| Video Clip Export | `GET/POST /api/v1/videos/{id}/export/clip` | ✅ |
| Scene Thumbnails Export (zip) | `GET/POST /api/v1/videos/{id}/export/thumbnails` | ✅ |
| System Settings (API 服务 + 存储路径 + 管道性能) | `GET/PUT /api/v1/settings`（API 密钥/服务商端点/存储路径 + 管道性能：编码三档模板/检测参数/量化/并发上限，保存即运行时生效，量化需重启）+ `GET /api/v1/settings/pipeline` | ✅ |
| Pipeline Presets (参数预设) | `GET/POST/PUT/DELETE /api/v1/settings/presets` + `POST /{id}/apply`（data/presets.json 多套命名参数快照，一键套用） | ✅ |
| Windows 从零部署 | `deploy/setup_windows.ps1` 裸机一键安装器（Python/FFmpeg/CUDA torch/WSL2/Docker/依赖/模型）+ 自校验 | ✅ |
| 全局 GPU 锁 + 任务队列 | `core/gpu_lock.py` 串行化 embedder/YOLO 前向（防驱动故障）；`core/pipeline_queue.py` PipelineQueue worker 池限流并发管道（批量上传排队防 OOM，v0.32） | ✅ |
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
| 云智平台集成 (v0.24) | `POST /api/v1/videos/register-external`（平台共享文件就地引用，`source_owned=false` 删视频不删源文件）+ `POST /internal/yunzhi/jobs`（立即 202，进度/完成/失败回调，幂等）+ 前端 Bridge SDK | ✅ |
| 平台文件 id 自动跳转 (v0.26) | `GET /api/v1/videos/external/{file_id}` — 平台文件库资源 ID 存入 `videos.external_file_id`（register-external + jobs 透传）；Bridge connect() 后凭 `context.resource.id` 自动打开对应视频历史详情（非文件入口/无匹配 → 默认工作台） | ✅ |
| 桌面端启动器 + 桌面前端 | `desktop/` pywebview 壳（检查模型→起 db→起 uvicorn→开窗→日志→优雅关停）+ `build_exe.ps1 -Deploy` 一键构建部署纯产品启动器 exe + `frontend-desktop/` 独立前端（`ZHIYING_FRONTEND=desktop` 挂载）| ✅ |

## Architecture Overview

```
Upload → Probe → Pipeline (DAG) → DB → Search → Frontend
         ├─ Duration detection (ffprobe)
         ├─ [搜索路径]  Search Encode @1fps — 与 detection 共享 NVDEC 流 (队列消费)
         ├─ [摘要路径]  Scene Segmentation (TransNetV2) + Audio Transcription (faster-whisper)
         │    ├─ Keyframe Extraction @1fps (NVDEC MJPEG pipe / cv2 stream)
         │    ├─ Captioning — vlm_llm API（默认；native_video 本地模式已置灰退役）:
         │    │    └─ vlm_llm: Qwen-VL-Max API 看图说话
         │    └─ Summarization — vlm_llm API（DeepSeek）默认；native_video 聚合器代码保留仅兼容历史
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
         └─ Shared GPU models (embedder + detector 预加载到 app.state; captioner 走 API):
              ├─ Qwen3-VL-Embedding-8B (embedder, FP16, ~16GB, preloaded; 可选 8bit/4bit 量化)
              ├─ Qwen-VL-Max (captioner, DashScope API; 本地 captioner 8B 不再下载, native_video 已退役)
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
- **双前端共存** — `frontend/`（服务器, v0.28 云智嵌入 UI）+ `frontend-desktop/`（桌面独立前端）UI 完全隔离；共用同一后端，`main.py` 按 `ZHIYING_FRONTEND` 切挂载（默认服务器, 桌面启动器传 desktop）。**对接层 `frontend-shared/` 一份实现**（api/types/labels/helpers, 双端再导出复用）——后端接口/字段变更只改一处。
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
| Captioning | Qwen-VL-Max (DashScope API, vlm_llm 默认; native_video 本地 8B 已退役) |
| Summarization | DeepSeek Chat (API, vlm_llm 默认) / Pure Python aggregator (native_video, 仅兼容历史) |
| Scene Segmentation | TransNetV2 / Time-based (fixed interval) |
| Audio Transcription | faster-whisper (plugin ready, opt-in) |
| Video Processing | FFmpeg (asyncio subprocess) |
| Metadata Extraction | pymediainfo + exiftool (optional) |

## 版本号与发布

- **版本唯一事实来源**：`core/version.py` 的 `__version__`（SemVer pre-1.0：MINOR=新功能，PATCH=热修）；`/health` 返回 `version` 字段，服务器部署后 `curl /health` 即可核对运行版本。
- **发版**：`./bump minor`（新功能）/ `./bump patch`（修 bug）/ `./bump 0.24.0`（指定版本）。一条命令联动改 `core/version.py` + `frontend/package.json` + `package-lock.json`（含两处根版本），随后交互式让你输入提交信息、确认 `git add .` 提交、打 tag、推送——机器不擅自动手，但也不用复制粘贴命令。
- **tag 强绑定**：git tag 必须命名为 `v<__version__>`，与 `core/version.py` 完全一致；部署/回滚 = 服务器 `bash deploy.sh v<版本>`（fetch→checkout→构建→重启→健康检查；回滚=部署旧 tag，config 已 gitignore 需注意向前滚原则）。
- `./bump` 是随仓库分发的 bash 启动器，任何开发机 `git pull` 后即可用（Windows 开发机用 `python scripts/bump_version.py`）。

## Project Structure

```
zhiying/
├── bump                 # 版本号一键提升启动器 (→ scripts/bump_version.py)
├── run.py                # 本地开发启动入口（按 config.yaml server 段绑端口，reload）
├── main.py               # FastAPI entry point (+ 静态托管 frontend/dist, 部署免 nginx)
├── api/                  # Route definitions
│   ├── router.py         # Route assembly (sub-routers under /api/v1)
│   ├── yunzhi_routes.py  # 云智平台异步任务接口 (POST /internal/yunzhi/jobs, 根路径挂载)
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
│   ├── video_service.py  # Video processing orchestration（并发由 core/pipeline_queue.py 队列 worker 池限流）
│   ├── yunzhi_job_service.py # 云智任务执行 (202+进度/完成/失败回调, 幂等)
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
│   │   ├── components/   # 19 UI components
│   │   │   ├── Header.tsx, SlideOutPanel.tsx
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
│   │   ├── platform/       # 云智 Bridge SDK (yunzhi-bridge.ts/client.ts/YunzhiProvider/mock)
│   │   ├── services/api.ts
│   │   └── types/index.ts
│   ├── package.json
│   └── vite.config.ts
├── models/               # Local model weights (gitignored; yolo26s.pt, yolo26n-cls.pt 等在仓库内)
├── data/                 # Video storage & artifacts + settings.json/presets.json (gitignored)
├── config/               # YAML config, prompts, schema
├── deploy/               # 部署套件: setup_windows.ps1 (Windows 裸机一键安装) + setup_linux.sh (Linux 开发机一键安装) + download_models.py / deploy.md / deploy_feedback.md
├── desktop/              # 桌面端启动器 (Windows, pywebview 壳: 检查模型→起 db→起 uvicorn→开窗→日志面板→优雅关闭; desktop.bat 入口; build_exe.ps1 -Deploy 一键构建部署 exe)
├── frontend-desktop/     # 桌面独立前端 (v0.27 独立工作台 + native_video 置灰 + 无云智 Bridge, 与服务器 frontend/ 完全隔离; desktop.bat 加载其 dist)
├── frontend-shared/      # 双前端共享后端对接层 (api/types/labels/helpers 一份实现, 两端 services/api.ts 等是再导出指针; 后端接口/字段变更只改这里)
├── scripts/              # 运维工具: sweep_storage.py 存储清扫 CLI (默认 dry-run, --apply 执行) + bump_version.py 一键版本提升 + mock_yunzhi_platform.py (mock 平台回调服务器)
└── docs/                 # Design documents + search architecture docs
```

## Development Status

- **v0.33 — 摘要链路根治重构（本次发版）**: 场景数上限 `pipeline.max_scenes`（默认 6：长视频固定段数 / TransNetV2 结果按累计时长合并）；caption 并发限流 + 单场景失败降级重试 + 配置穿透（with_context/max_new_tokens 从 params 子层读，默认关 with_context）；text_encode 攒批 encode_texts_batch；summary 剧本输入预算截断（max_input_chars）；incremental 纯搜索→开摘要不再静默失败（完整跑摘要流水线 + 更新 scenes）；keyframe 抽帧统一 resize 到编码预设分辨率（取消原分辨率帧驻留，内存大幅下降）；frame_encode/search_encode/keyframe/detection 统一 resolve_encode_profile 解析；summary_mode 默认值全量 native_video→vlm_llm。
- **v0.32 — 全局任务队列（已发版）**: `core/pipeline_queue.py` FIFO 任务队列 + worker 池（N=`max_concurrent_videos`，0/未设=1 串行）+ `pipeline_tasks` 表 DB 持久化。所有管道触发点（yunzhi jobs/上传 params/组同步/增量）统一入队，批量上传排队处理防 GPU OOM；重启恢复（yunzhi 续跑防重复建视频 / pipeline 标失败）+ "排队中"低进度回调 + 幂等跨重启。接口保持异步（jobs 202 不变）。
- **桌面端 EXE + 双部署路径（未发版，桌面前端/部署侧，随后端版本走）**: `desktop/build_exe.ps1 -Deploy` 一条命令构建并部署纯产品启动器 exe（PyInstaller onedir，桌面壳不含后端/模型；壳修复：pywebviewready JS 轮询 + CREATE_NO_WINDOW 防弹终端 + spec SPECPATH/collect_submodules）+ `deploy/setup_linux.sh` Linux 开发机一键安装 + `setup_windows.ps1` 补 config.yaml 生成与前端 dist 构建 + **bump 命令全机接入 PATH**。详见 `deploy/deploy.md` / `desktop/README.md`。
- **v0.31 — 人脸搜索交互完善 + 搜索范围模型 + 跨视频检索穿透 + 通用置信度**: 人脸搜索交互重构（搜索人脸结果点击定位检测栏"人脸"视图 + 身份展开按 track 聚合出现时间段 + 单次不展开 + 人脸行下载按钮 + 选中视频框金色高亮 + 时间轴联动 + 丝滑定位）；搜索范围模型重构（当前/全组/全部/自定义跨视频多选，下拉常驻；无视频默认工作台直接全库搜索；人脸/车牌门控按"范围内任一视频具备即可用"）；跨视频检索穿透定位（结果点击不再重置搜索卡，根治 `video?.id` 派生 currentVideoId 的 旧→null→新 双触发；seekTarget loadedmetadata+轮询 跨视频可靠 seek；播放/时间轴/检测栏穿透）；通用置信度 confidence（`search_engine.py` 结果返回 `confidence=相似度×路径权重`，跨路径统一排行）。
- **v0.29 — 人脸识别链路重构 + 搜索隔离 + 前端搜索样式统一**: 人脸聚类改护栏式双阈值（同track 0.30/跨track 0.58，替代单一 0.60 拆碎/0.40 并错）；多帧采样提脸 + 最典型脸作检索锚；detection 全分辨率帧升级；修复 search/face + search/image 的 video_ids 泄漏全库 bug（form 参数改 Form 声明）；五种搜索（语义/图搜/物体/车牌/人脸）统一 sr-item 卡片样式（标签右上角 + 主体1行 + 导出展开式）；人脸并入物体检测下拉栏。
- **v0.28 — 云智嵌入 UI 重构**: 移除侧边栏（避免与 yunzhi 平台重复）→ 导航上移 header；参数/历史抽屉改右侧滑出；设置页点面板先跳回工作台；搜索框车牌/人脸按钮按检测门控置灰。
- **v0.27 — 搜索修正 + 车牌模糊搜索模式**: 统一 track 编号；搜索范围 fail-closed；车牌归一化 + 编辑距离 + 「牌」模式（单字列出所有相关车牌）。
- **v0.26 — 平台文件 id → 视频自动跳转**: `videos.external_file_id` + `GET /videos/external/{file_id}`，Bridge connect() 后凭 `context.resource.id` 打开对应视频。
- **v0.24 — 云智平台接入 + 生产部署**: Bridge 文件选择（register-external, source_owned=false）+ `/internal/yunzhi/jobs` 异步任务（202+回调, 幂等）+ 生产部署 10.0.0.176:8011（systemd, git+tag 部署）。
- **v0.22 — 部署系统 + 设置/参数 + Detection 重构**: Windows 裸机一键安装器；单份 config 自动降级；系统设置页 + 参数预设；全局 GPU 锁 + 共享单实例；Detection 渲染重构（tracks/detections 端点）；删除处理中 + 管道取消；多架构 requirements（ARM64 自动 CPU）。
- **更早版本**（v0.21 存储卫生 / v0.20 双层 ReID / v0.19 多视频分组 / v0.18 图搜+中文化）: 细节见 git 历史。
- **Planned**: Grounding (Florence-2), OCR
