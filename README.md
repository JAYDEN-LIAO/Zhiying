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

**Windows 桌面端**：环境就绪（`deploy/setup_windows.ps1` 装机——自动装模型/Docker/依赖/生成 config.yaml/构建桌面前端 dist）后，双击 `智影桌面端.exe`（构建方法见 `desktop/README.md`）或 `python desktop/app.py`——启动器自动检查就绪 → 起 Docker 库 → 起本地后端 → 打开 pywebview 桌面窗口加载桌面前端（`ZHIYING_FRONTEND=desktop` 挂载 frontend-desktop/dist，与服务器前端 `frontend/` 完全隔离）。**日常更新用根目录 `update.bat` 一键自动更新**（git pull 走 7897 代理 → pip 装 desktop 依赖 → npm install/build → 重打 exe，全流程跑一遍）。

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
| 桌面端启动器 + 桌面前端（v0.34 重构） | `desktop/` pywebview 壳（**frameless 自定义窗口外框** + 窗口控制/系统监控 js_api）+ `build_exe.ps1 -Deploy` 一键构建部署纯产品启动器 exe + `frontend-desktop/` 独立前端（**浅蓝管理后台主题 + 4 页模型：文件库/视频解析/任务中心/系统设置 + 工作台 SplitPane 分栏 + 系统监控**，`ZHIYING_FRONTEND=desktop` 挂载）+ 根目录 `update.bat` 一键自动更新 | ✅ |
| 文件库 + 多版本解析 (v0.34) | `videos.file_id/version_no` 版本链（一次解析=一个版本行）+ `video_groups.number/owner` 案例编号/负责人 + `/groups /files /videos/{id}/versions /videos/{id}/reanalyze` 端点 + 案例素材 `/groups/{id}/assets` | ✅ |
| 任务中心 (v0.34) | `GET /tasks` scope 过滤 + `/tasks/{id}/log` + `/tasks/{id}/retry`；**耗时** `processing_started_at`（排队不计入）；**日志生命周期** 上传/参数/重解析/管道/重试全链写入 `task_logs`；**导出报告** `GET /tasks/{id}/report`（Markdown）+ `POST /tasks/export-batch`（zip） | ✅ |
| 桌面端页面组件裂解 (v0.34) | TaskCenter 裂解 TaskHeader/TaskBody；SettingsPage 4 子页收敛 2（系统设置=系统+参数预设，模型参数=模型参数+API密钥）+ 各页裂解子组件；卡片空隙靠透明根容器 + `app-main-flat` 透出渐变 | ✅ |
| 案例库批量解析（精确勾选） | `POST /api/v1/videos/analyze-batch`（仅 pending 精确启动、**不走组同步**、可选整批参数）+ 文件列表勾选列（仅待处理可勾）+ 一键/批量解析（参数面板整批应用）；后端 `upload_videos_batch` 复用已有分组修复 | ✅ |
| 文件/素材重命名 + 后缀展示字段 | `PUT /api/v1/files/{file_id}`（更新全部版本行）+ `PUT /api/v1/groups/{id}/assets/{asset_id}`；`file_ext` 真实扩展名作**展示字段**（编辑框只含主名，重命名不影响后缀） | ✅ |
| 案例编辑 + 编号自动填充 | 案例列表删除红色可见 + 编辑按钮（名称/编号/负责人，`PUT /groups/{id}`）+ 新建编号自动填充 `A-YYYY-MMDD-NN`（同天递增，可手动改） | ✅ |
| 搜索卡案例-文件范围 + 跨视频切主视频 | 下拉改案例-文件结构（当前视频/案例/文件多选，未处理隐藏）；无视频可交互；跨视频结果点击**切主视频**（播放器/时间轴/检测/摘要同步）+ seek 可靠定位 + 搜索卡单实例跨空态保留结果 | ✅ |
| 桌面端交互 + 暗色主题 (v0.34候选) | 标题栏「最近更新」下拉（SplashApi git log）+ 太阳/月亮主题切换（暗色=中性炭灰+靛蓝强调，`html.dark` 调色板重映射）；案例库闪电全状态（完成=实心+「重新配置参数解析」→ reparse 建新版本）+ 编辑按钮移入操作格；TaskCenter 导出报告/日志图标；参数面板 4:3 三段网格；设置页响应式两列卡片网格 | ✅ |

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
├── update.bat           # 桌面端一键自动更新（Windows：git pull 走 7897 代理 + pip 依赖 + npm install/build + 重打 exe）
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
├── desktop/              # 桌面端启动器 (Windows, pywebview 壳: 检查模型→起 db→起 uvicorn→开毛玻璃启动窗→就绪进前端→优雅关闭; desktop.bat 入口; build_exe.ps1 -Deploy 一键构建部署 exe)
├── frontend-desktop/     # 桌面独立前端（v0.34 重构：浅蓝管理后台主题 + frameless 自定义窗口标题栏 + 4 页模型 文件库/视频解析/任务中心/系统设置 + AppContext 导航 + 工作台 SplitPane 分栏 + 系统监控；TaskCenter/SettingsPage 组件裂解 + 设置 4 子页收敛 2；标题栏「最近更新」+ 太阳/月亮暗色主题、案例库闪电全状态、设置页两列网格；与服务器 frontend/ 完全隔离; desktop.bat 加载其 dist）
├── frontend-shared/      # 双前端共享后端对接层 (api/types/labels/helpers 一份实现, 两端 services/api.ts 等是再导出指针; 后端接口/字段变更只改这里)
├── scripts/              # 运维工具: sweep_storage.py 存储清扫 CLI (默认 dry-run, --apply 执行) + bump_version.py 一键版本提升 + mock_yunzhi_platform.py (mock 平台回调服务器)
└── docs/                 # Design documents + search architecture docs
```

## Development Status

- **v0.34 候选（未发版，后端）— 模型适配 embedding_profile**: 向量编码模型档位化——`8b`=Qwen3-VL-Embedding-8B/4096 维（默认）、`2b`=Qwen3-VL-Embedding-2B/2048 维（低显存平替）；新增 `core/embedding_profile.py`（`EmbedVector()` 懒读全局维度建表）+ `config_loader._apply_embedding_profile` 联动「模型路径 + 向量维度」；`core/db.py` 迁移参数化；改 config `embedding_profile` + 重启后端即换档，⚠️ 维度不同需重建向量库；人脸 512（ArcFace）与档位无关不受影响。
- **v0.34 候选（未发版，桌面端 + 后端）— 侧栏徽章系统 + 任务中心交互 + 后端排队检测修复**:
  - **侧栏徽章**：案例库🩶灰=仅上传未提交（pending 且未入队 且 未版本化）；视频解析🔵蓝「1」=有视频处理中（未选中视频时点进视频解析**自动定位处理中视频**）；任务中心 🟡黄=排队中 / 🟢绿=新完成（进任务中心清零 + 首次进入整行淡绿高亮）/ 🔴红=处理失败（实时计数）
  - **待处理剥离**：任务中心只显示**已提交任务**（排队/处理中/已完成/失败），仅上传未提交的文件不进任务中心列表与徽章（由案例库灰徽章承载）
  - **任务中心交互**：整行点击跳转视频（hover 淡灰 `#dbe2ea`）；失败行重试改**图标按钮**（`IconRetry`，busy 旋转）；筛选 Tab 改顶部**下拉**（全部/已完成/处理中/排队中/失败，置于「导出」左侧）；刷新 1.5s
  - **后端排队检测修复（根因）**：`pipeline_queue.enqueue` 形参未传 `video_id` 时**自动从 payload 取**（根治排队行 `pipeline_tasks.video_id` 全 NULL → queued 检测失效、黄徽章永不亮）；`TaskItem.queued` 字段（`list_tasks` 批量查排队集合防 N+1，侧栏黄徽章数据源）
  - **上传 FK 包装**：`upload_video`/`upload_videos_batch` 传 `group_id` 先校验案例存在 + `create_video` `IntegrityError` 兜底 → 友好 400「案例不存在或已被删除」
  - **重命名修复**：`rename_file` 改行 id→file_id 解析（版本化文件重命名 404「文件不存在」根治，与 delete_file 一致）
  - **按钮/图标一致性**：工具栏按钮图标统一 16px；ParameterPanel 主按钮统一 `g-btn-primary`（去渐变 teal）；行内操作统一无框幽灵（灰→hover 蓝，删除红）；文件操作顺序 解析→预览→重命名→删除
- **v0.34 候选（未发版，桌面壳/前端）— 启动加载页改造**: 移除独立「启动日志」控制窗（`LogApi`/`LOG_HTML` 删除，`get_logs` 迁入主窗 `SplashApi`，日志仍落盘 `data/logs`）；`SPLASH_HTML` 重写为**毛玻璃启动页**（前端同款渐变背景 + 毛玻璃卡片 + 标题「视频智能快速检索平台」，**模型加载段按后端日志 tqdm `Loading weights: X%` 实时推进 10%→90%**，亮暗主题自适应，就绪显示版本后进主界面）；前端 `index.html` 加 `#boot` 毛玻璃过渡遮罩（无进度条，React 挂载后淡出，防白屏/避免「进度回退」误解）。
- **v0.34 候选（未发版，桌面前端/壳）— 桌面交互 + 暗色主题 + 布局**:
  - **标题栏**：新增「最近更新」（i 按钮下拉 → SplashApi `get_recent_commits` 项目根 `git log` 最近 8 条）+ **太阳/月亮主题切换**（暗色 = 中性炭灰环境 + 靛蓝强调色；`html.dark` 类驱动 CSS 变量调色板重映射，`index.html` 内联防闪烁）
  - **案例库/任务中心**：闪电按钮全状态显示（已完成 = 实心 `IconBoltSolid` + hover「重新配置参数解析」→ 打开工作台 **reparse 模式**建新版本）；编辑按钮移入操作格（编辑/解析/预览/删除 4 按钮整齐）+ 铅笔换 edit-3 风格；任务中心导出报告/日志换图标（`IconReport`/`IconLog`）
  - **参数面板**：4:3 顶向下三段 + 段内网格铺满（场景类型满宽 → 感知模块 2×2 开关 + 目标类别/人脸/车牌 → 功能开关 2×开关 + 摘要模式）；物体检测/文字识别调换位置
  - **工作台**：恒渲染 `DetectionPanel`（无视频也显示「物体检测」标题空态，与摘要/搜索一致）；播放器/时间轴/空态加小圆角；搜索卡人脸/车牌灰态 tooltip 说明原因
  - **设置页**：去 `max-w-900px` 死区 → 响应式两列卡片网格（`xl:grid-cols-2`，窄窗回落单列），编码卡 `col-span-2` 独占整行保住三档模板表格宽度
- **v0.34 候选（未发版，本次大批改动）— 案例库批量解析 + 案例库交互 + 搜索卡重构 + 桌面壳**:
  - **批量解析**：`POST /videos/analyze-batch` 精确勾选启动（不走组同步，可选整批参数）；文件列表勾选列（仅待处理可勾）+ 一键/批量解析按钮（弹参数面板整批应用）；`upload_videos_batch` 复用已有分组 bug 修复
  - **案例库**：案例编辑（名称/编号/负责人）+ 删除红色可见 + 编号自动填充 `A-YYYY-MMDD-NN`；文件与图片重命名（内联编辑，后端 `PUT /files/{id}` + `PUT /groups/{id}/assets/{id}`）；文件操作改图标按钮（智能解析/预览合并/删除）+ 文件名铅笔右对齐；**后缀作展示字段**（`file_ext` 真实扩展名，编辑框只含主名、重命名不影响后缀）
  - **搜索卡**：下拉重构为**案例-文件**结构（当前视频/案例/文件多选，未处理直接隐藏、未索引置灰）；无视频也可交互（全部=空选）；跨视频结果点击**切主视频**（播放器/时间轴/检测/摘要同步）+ `pendingSeek` 可靠定位；搜索卡合并为**单实例**（空态↔有视频结果/范围保留）
  - **工作台/桌面壳**：三卡片待处理态统一（居中灰字）；搜索卡纵向滚动修复 + 横滚动条删除；`.g-btn` 全局 nowrap + 工具栏 flex-wrap 防窄窗口挤压；TitleBar 改**手动拖拽**（最大化先还原再跟随光标）+ `SplashApi.move`；标题改「视频智能快速检索平台」；人脸按钮图标修正
- **桌面端重构（未发版，桌面前端/部署侧）**: 浅蓝管理后台主题 + frameless 自定义窗口外框 + 4 页模型（文件库/视频解析/任务中心/系统设置，设置 4 子页拆入导航）+ AppContext + 工作台按智影 v2 demo 骨架（SplitPane 分栏）+ 系统监控（psutil）+ 根目录 `update.bat` 一键更新。
- **文件库 + 多版本解析 + 任务中心（未发版）**: 后端 `videos.file_id/version_no` 版本链 + `video_groups.number/owner` + `task_logs` 表 + `/groups /files /versions /reanalyze /tasks` 端点；前端案例库/视频解析/任务中心界面重构；任务中心日志生命周期（上传→完成全链）+ 耗时（`processing_started_at`）+ 导出报告（Markdown/zip）。
- **桌面端页面组件裂解（未发版）**: TaskCenter 裂解 TaskHeader/TaskBody（删删除按钮、失败任务导出报告左侧加重试、字段顺序 任务文件/版本/所属 + 耗时列）；SettingsPage 4 子页收敛 2（系统设置=系统+参数预设，模型参数=模型参数+API密钥）+ 每页裂解子组件；设置页根容器去白底 + `app-main-flat` 透渐变实现卡片空隙；设置保存按钮统一 `g-btn g-btn-primary`。
- **桌面端稳定性修复（未发版，桌面前端/壳）**: `build_exe.ps1` 部署加固（杀运行中壳+遗留后端 / `$src\*` 内容拷贝杜绝 `_internal\_internal` 嵌套 / 部署后自检 python313.dll 落地，不再静默产出半残 exe）；`backend_child` 看门狗改**持有父进程句柄**信号检测（`OpenProcess(SYNCHRONIZE)` + `WaitForSingleObject`，**免疫 PID 复用**，根治孤儿后端锁 `_internal` DLL）；启动前 `sweep_orphan_backends` 沿父链清遗留孤儿（兼容 `.venv\Scripts\python.exe` 重定向器三层）；窗口控制修复（`is_maximized` 读真实 WindowState、toggle 修标志、resize 同步图标）；关闭确认改**主题化弹窗**（去 pywebview 原生 MessageBox）；`.gitignore` 补 `/_internal/` 与 `/智影桌面端.exe` 构建产物。
- **v0.33（本次发版）— 摘要链路根治重构**: 场景数上限 `max_scenes`；caption 并发限流+失败降级+配置穿透；text_encode 批量；summary 输入预算截断；增量补摘要修复；keyframe 抽帧 resize；summary_mode 默认 vlm_llm。
- **v0.32 — 全局任务队列**: `pipeline_queue.py` FIFO + worker 池 + `pipeline_tasks` 表持久化；批量上传排队防 OOM；重启恢复 + 排队中回调 + 幂等。
- **桌面 EXE + 双部署路径（未发版）**: `build_exe.ps1 -Deploy` 一键打纯壳 exe + `setup_linux.sh`/`setup_windows.ps1` 补全 + bump 全机接入。详见 `deploy/deploy.md` / `desktop/README.md`。
- **v0.31 — 人脸搜索交互 + 搜索范围模型 + 跨视频穿透 + 置信度**: 结果定位检测栏人脸视图/身份展开时间段/选中金框高亮；搜索范围 current/group/all/custom；跨视频结果点击不重置搜索卡 + seekTarget 可靠定位；`confidence=相似度×路径权重`。
- **v0.29 — 人脸链路重构 + 搜索隔离**: 护栏式双阈值聚类（同track 0.30/跨track 0.58）+ 最典型脸锚点；search/face+image 改 Form 声明修泄漏；五种搜索样式统一。
- **v0.28 — 云智嵌入 UI**: 删侧边栏 / 导航上移 header / 参数历史右侧抽屉 / 搜索检测门控。
- **v0.27 — 搜索修正 + 车牌模糊搜索**: 统一 track 编号；范围 fail-closed；车牌归一化 + 「牌」模式。
- **v0.26 — 平台文件 id 自动跳转**: `videos.external_file_id` + `GET /videos/external/{file_id}`。
- **v0.24 — 云智接入 + 生产部署**: register-external + `/internal/yunzhi/jobs`（202+回调）+ 生产 10.0.0.176:8011。
- **v0.22 — 部署系统 + 设置/参数 + Detection 重构**: Windows 一键安装器；config 自动降级；系统设置+参数预设；GPU 锁+共享实例；删除处理中。
- **更早**（v0.18–0.21）: 见 git 历史。
- **Planned**: OCR（设计见 `docs/ocr.md`）/ Grounding (Florence-2)。
