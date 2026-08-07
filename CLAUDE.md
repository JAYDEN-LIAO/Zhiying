# Zhiying Project Context for AI Agents

## One-Line Summary

Zhiying 是 **视频分析引擎**（v0.24.0）：上传视频（单个/批量分组）→ 声明式操作 DAG（15 ops）→ 4 条编码路径（frame/chunk/text/track）+ YOLO11/BoT-SORT 检测跟踪（双层 ReID）+ 人脸/车牌识别 → 7 路语义搜索 + 图搜 → FastAPI + PostgreSQL/pgvector 对外服务。4 级参数系统 + 系统设置（API 密钥/服务商端点/存储路径/管道性能 + 参数预设）控制管道；全局 GPU 锁串行推理 + 并发管道限流；存储卫生（删除即清盘 + 孤儿清扫）保证磁盘不泄漏。**已接入云智(Yunzhi)平台**：前端 Bridge 文件选择（`register-external` 共享路径就地引用）+ 异步任务接口（`/internal/yunzhi/jobs` 202+进度/完成/失败回调）。`deploy/` 提供 Windows 裸机一键安装（从零部署）；requirements 已做多架构区分（Windows/Linux x86 装 onnxruntime-gpu，ARM64 如 DGX Spark/GB10 无该 wheel 自动装 CPU 版，人脸/车牌走 CPU）。**已部署到生产服务器 10.0.0.176（systemd `zhiying.service`，8011）**，运维参考见 `docs/server.md`（gitignored，含凭证）。架构细节见 `docs/arch.md`。

## Quick File Map

```
run.py                     — 本地开发启动入口（按 config.yaml server 段绑端口，reload 模式）
main.py                    — FastAPI app, lifespan, exception handlers, shared embedder + shared detector (app.state, detector 模型懒加载); 静态托管 frontend/dist（部署免 nginx）
api/routes.py              — Transitional re-export (endpoints split into sub-routers)
api/video_routes.py        — Video CRUD + upload (probe同步+异步remux/proxy) + stream (hevc_ok智能路由) + proxy-status + thumbnail
api/search_routes.py       — Semantic search + pipeline/operations endpoints
api/settings_routes.py     — 系统设置端点：GET/PUT /settings（密钥/服务商/存储/管道性能）+ /settings/pipeline + 参数预设 CRUD
api/router.py              — Assembles sub-routers under /api/v1 prefix
api/yunzhi_routes.py       — 云智平台异步任务接口（POST /internal/yunzhi/jobs，根路径挂载非 /api/v1，202+幂等）
api/deps.py                — FastAPI dependency injection (get_db)
api/schemas.py             — Shared API DTOs (APIResponse, search/status models, ProxyStatusResponse, PipelineSettings/Presets, v0.22)
api/detection_routes.py    — Detection data API: GET /detection/tracks (摘要) + /detection/detections (时间窗, v0.22 替代旧 /detection/data) + thumbnail
api/export_routes.py       — Export endpoints: clip/frames/track/thumbnails (7 endpoints, GET+POST)
api/face_routes.py          — Face data API (GET face/data + face/thumbnail)
api/plate_routes.py         — Plate data API (GET plate/data + plate/thumbnail)
api/maintenance_routes.py  — 存储清扫端点 (POST /maintenance/sweep dry-run/执行, GET /maintenance/storage)
core/models.py             — ORM: Video (+8 format fields + group_id FK), VideoGroup, Scene, Transcript, FrameEmbedding, Chunk, FrameDetection, Track, TrackEmbedding, FaceIdentity, FaceDetection, PlateDetection (12 tables)
core/schemas.py            — Pydantic v2 DTOs + JSONB validation models + FormatInfo/ProxyStatus
core/interfaces.py         — 10 abstract base classes (ABCs) + Scene/VideoContext dataclasses
core/search.py             — 6 search functions: frame/chunk/text/track/plate/face (async def)
core/repository.py         — Data access layer + bulk_insert_frames/chunks
core/storage_manager.py    — 存储管理: 路径解析/引用追踪/删除清盘(remove_video_artifacts)/孤儿清扫(sweep)
core/db.py                 — Async engine, init_db(), incremental migration (extensions: pgvector, pg_trgm, fuzzystrmatch)
core/config_loader.py      — Loads config.yaml + .env + data/settings.json overrides; PIPELINE_NUMERIC_SPEC/clamp_param 参数钳制; _auto_fallback_captioner 自动降级
core/presets_service.py    — 参数预设服务 (data/presets.json): create/apply/rename/delete 命名参数快照
core/gpu_lock.py           — 全局 GPU 推理锁: 串行化 embedder + YOLO 前向，防并发驱动故障
core/cancellation.py       — 管道取消登记: 删除「处理中」视频后优雅中止（persist 前检查 is_cancelled，防写已删行 FK 异常）
core/settings_service.py   — 设置服务: data/settings.json 读写 {api_keys, providers, storage, pipeline}; API_KEY_DEFS/API_PROVIDER_DEFS; 脱敏显示
core/prompt_loader.py      — Prompt template loader (config/prompts.yaml)
core/status_tracker.py     — Pipeline progress + dynamic operation-based weight calculation
core/exceptions.py         — Custom exceptions
core/version.py            — 版本号单一事实来源 (__version__; /health 输出; 与 git tag v<__version__> 强绑定)
pipeline/engine.py         — DAG executor: EventDrivenScheduler (event-driven, ~200 lines), reads remuxed_path
pipeline/operations.py     — Operation registry: ALL_OPERATIONS with gates/deps/labels (v0.14 gate fixes)
pipeline/runners/          — 15 operation runners (one per processing unit):
  runners/base.py            — OperationRunner ABC + PipelineContext + Operation dataclass
  runners/duration.py        — ffprobe duration detection
  runners/segmentation.py    — TransNetV2 (≤30min) / time-based (>30min) 自适应
  runners/transcription.py   — Audio extraction + faster-whisper transcription
  runners/keyframe.py        — 1fps frame pool extraction + thumbnails (cv2 + asyncio.to_thread)
  runners/alignment.py       — Transcript word-to-scene alignment
  runners/caption.py         — Dual-mode: native_video / vlm_llm (gated by summary_enabled)
  runners/summary.py         — Dual-mode: Python aggregator / DeepSeek API LLM
  runners/frame_encode.py    — 1fps batch image encoding (embedder @336×224) → frame_embeddings
  runners/chunk_encode.py    — Sliding window video encoding → chunks (config-gated)
  runners/text_encode.py     — Text semantic encoding (gated: 有文本源才跑)
  runners/detection.py       — YOLO11 + BoT-SORT (10fps/128batch/640px), 生产者-消费者并发, 与 search_encode 共享 NVDEC 流, 每 2s 缓存 track crop 供 track_encode (batch 128 而非 1024: 受 gpu_lock 串行, 长批会饿死 embedder)
  runners/track_encode.py    — Track crop embedding + 全局 tracklet 缝合 (读检测缓存多帧 640×384 → mean pool → cosine 合并)
  runners/face.py            — SCRFD face detection + ArcFace R50 embedding + identity clustering
  runners/plate.py           — HyperLPR3 license plate detection + text recognition
  runners/search_encode.py   — 纯搜索路径：队列消费 detection 共享流帧 1fps + 批量编码，不依赖 segmentation/keyframes
pipeline/search_engine.py  — 7-path parallel recall (frame/chunk/text/label/track/plate + image) + scene-merge dedup, search_image_only() for no-cluster per-frame image search
plugins/factory.py         — Dynamic plugin loader (CATEGORY_MAP, _MODULE_OVERRIDES, _CLASS_OVERRIDES)
plugins/detector/yolo.py   — YOLO11s detector (batch GPU inference 受 core/gpu_lock 串行; batch_size/imgsz 可配, asyncio.to_thread)
plugins/face/insightface_face.py  — InsightFace SCRFD + ArcFace R50 recognizer
plugins/plate/hyperlpr_plate.py  — HyperLPR3 license plate detector + recognizer (primary)
plugins/plate/paddle_plate.py    — PaddleOCR license plate detector (alternative)
plugins/embedder/qwen_vl_embedder.py — Qwen3-VL-Embedding (336×224 encode, 内存路径, 零磁盘I/O; 量化 8bit/4bit via bitsandbytes; 受 gpu_lock 串行; 相对模型路径解析到项目根)
services/video_service.py  — Pipeline 调用与后台调度 (max_concurrent_videos 信号量限流; RUNNING_VIDEOS 注册表)
services/yunzhi_job_service.py — 云智任务执行: 建视频(source_owned=false)→管道→进度/完成/失败回调(httpx async with 内) + 默认参数映射
services/format_service.py — 格式兼容: probe(ffprobe) / remux(容器标准化, -c copy) / proxy(按需h264_nvenc)
services/export_service.py — 导出业务逻辑 (clip/frames/track/thumbnails zip)
utils/video_util.py        — FFmpeg 工具函数 + stream_frames() (NVDEC MJPEG pipe / cv2 fallback)
utils/metadata.py          — 视频元数据提取 (pymediainfo → exiftool → ffprobe 三级)
utils/video_source.py      — 视频来源分析: 规则引擎分类 phone/camera/surveillance/... + 监控品牌（文件头魔数嗅探 IMKH→海康威视, magic_bytes>filename>metadata）
config/config.yaml         — Main config: server/db/storage/plugins/pipeline (detection_fps:10, batch:128)
config/config_schema.py    — Pydantic config validation
config/prompts.yaml        — Caption/Summarizer/Grounding prompt templates
frontend/src/Dashboard.tsx — Main workspace (orchestrator, ~430 lines, hevcOk探测+proxy轮询+streamReady+group state+detectionVideoId+header dropdown)
frontend/src/components/    — Split components (20 files):
                              icons, Sidebar, Header, SlideOutPanel,
                              ParameterPanel, PipelineBar, VideoSection, VideoPlayer,
                              VideoSummaryCard, VideoSearchCard, HistoryPanelContent, SettingsPage,
                              DetectionOverlay, DetectionPanel, DetectionTimeline,
                              VideoInfoCard, ExportMenu, RightPanel
                              SettingsPage 4 分区: 系统(存储/NVDEC/chunk/并发上限) + 模型参数(编码三档/YOLO/量化) + 参数预设 + API 密钥
frontend/src/labels.ts        — COCO 类名英→中映射 + 统一颜色表 (zh/zhLabel/colorOf)
frontend/src/utils/helpers.ts — Shared helpers (fmtDuration, fmtDate, formatSec)
frontend/src/services/api.ts — API wrapper + polling helper (getVideoStreamUrl hevc_ok, getProxyStatus)
frontend/src/platform/        — 云智 Bridge SDK: yunzhi-bridge.ts/client.ts/YunzhiProvider/mock (VITE_YUNZHI_MOCK 切换真实/模拟)
frontend/src/types/index.ts — TypeScript types (mirrors backend schemas + ProxyStatus)
frontend/src/services/api.ts — Pipeline stages from `/pipeline/operations` (backend computes enabled operations)
scripts/sweep_storage.py   — 存储卫生清扫 CLI (默认 dry-run 只报告, --apply 执行, --json 机器可读)
scripts/mock_yunzhi_platform.py — 本地 mock 云智平台回调服务器 (监听 /progress /complete /fail, 联调验证用)
scripts/bump_version.py    — 一键版本提升 (交互式: 改号→输入提交信息→确认 commit/tag/push, git add .)
bump                       — 仓库根可执行启动器 → scripts/bump_version.py (任意开发机 git pull 后 `./bump minor`)
deploy/                    — Windows 裸机一键安装套件: setup_windows.ps1（装 Python/FFmpeg/CUDA torch/WSL2/Docker/依赖/模型 + 自校验, 旧 start_windows.ps1 与 write_windows_config.py 已删）/ download_models.py（含 reid 组件 yolo26n-cls.pt）/ deploy.md / deploy_feedback.md（部署踩坑记录）。配置已统一：无需 config.windows.yaml / ZHIYING_CONFIG，后端直接 uvicorn main:app
```

## Data Flow

```
上传 → 参数 → 管道 → 搜索:
  POST /videos/upload (或 /upload/batch 批量, 建 VideoGroup)
    → 存盘 → 同步 probe(<100ms) → 建记录(pending) → 异步 remux/proxy
  PUT /videos/{id}/params → 校验 PipelineParams → 更新记录
    → 后台 PipelineEngine.run() (pending) / run_incremental() (completed, 仅 summary/search_index)
    → 组内 pending 兄弟同步启动 (v0.19)
  DELETE /videos/{id} (v0.21 存储卫生; v0.22 放开处理中删除)
    → 404 守卫
    → 处理中 (PROCESSING/RUNNING_VIDEOS) → mark_cancelled 登记（后台管道 persist 前检查 is_cancelled 中止，防 FK 异常）
    → 批量 DELETE videos 行 (DB ON DELETE CASCADE 级联 10 张子表)
    → 同事务空组清理 → commit → StorageManager 引用判定清盘 → 返回 freed_bytes
  孤儿清扫: POST /maintenance/sweep (dry_run 默认) / scripts/sweep_storage.py --apply

云智平台接入 (v0.24):
  POST /api/v1/videos/register-external → 平台共享文件就地引用 (source_owned=false, 删视频绝不 unlink 源文件; probe + 异步 remux 与上传同流程)
  POST /internal/yunzhi/jobs → 立即 202 {accepted, bizTaskId} → 后台建视频+跑管道 → 进度/完成/失败回调 (callback.progressUrl/completeUrl/failUrl, 幂等 eventId/Idempotency-Key)
    → 平台文件库与 Zhiying 共享同一套绝对路径 (宿主同视角)

系统设置/参数预设 (v0.22, 运行时生效):
  GET/PUT /settings 读写 data/settings.json {api_keys, providers, storage, pipeline}
    → pipeline 段覆盖 config.yaml（编码三档模板/检测参数/量化/并发上限, clamp_param 钳制）
    → load_config() 每次 _apply_settings_overrides 合并, 保存清 lru_cache → 无需重启（quantization 除外）
  GET/POST /settings/presets + PUT/DELETE /{id} + POST /{id}/apply → data/presets.json 命名快照
  并发: pipeline.max_concurrent_videos >0 → VideoService 信号量限流同时处理的管道数
  GPU: 所有 embedder/YOLO 前向持 core/gpu_lock 串行（防并发驱动故障）; detector 共享 app.state 单实例

PipelineEngine.run() — 声明式 DAG (EventDrivenScheduler, 15 ops):
  duration
    ├─ search_encode ← detection 共享单 NVDEC 流 (队列消费) → frame_embeddings
    ├─ detection (生产者-消费者) → track_encode (读缓存 crop, mean pool) → face/plate
    └─ segmentation → keyframes → caption → summary → frame/text/chunk_encode
  → _persist() → mark_completed()
  新增感知模块: 新 runner + operations.py 一个 Operation 条目 → engine.py 零改动

流路由 GET /videos/{id}/stream?hevc_ok=: H.264 直出 / HEVC+hevc_ok→remuxed / 非 HEVC 浏览器→proxy(按需)
搜索 7 路 (frame/chunk/text/label/track/plate + 图搜): 详见 docs/arch.md Search Architecture
```

## Key Conventions

- **异步规则**: 所有插件接口 async; 同步模型推理 / cv2 等 C 调用 MUST 用 `asyncio.to_thread()`（关键帧 cv2 循环是范本）。
- **Config-driven**: 插件后端由 `config.yaml` `plugins.{name}.backend` 选择，`null`=禁用; API key 只在 `.env`/环境变量（`core/config_loader.py` `_ENV_OVERRIDES`）。
- **设置运行时生效**: 前端设置页 `GET/PUT /settings` 读写 `data/settings.json`（`{api_keys, providers{base_url,model}, storage{video_dir,artifact_dir}, pipeline{encode_profiles 三档模板 + 检测参数 + 开关 + 量化 + 并发上限}}`）；`core/config_loader._apply_settings_overrides` 每次 `load_config()` 覆盖进配置（数值按 `PIPELINE_NUMERIC_SPEC`/`clamp_param` 钳制），保存时清 `lru_cache` → **无需重启**（唯一例外：**quantization 启动时加载，改后需重启**）。上传路由/FormatService/VideoService 均用新鲜 `load_config()`（勿用启动时 `app.state.config` 快照）。
- **参数预设**: `data/presets.json` 多套命名管道参数快照（`GET/POST/PUT/DELETE /settings/presets` + `POST /settings/presets/{id}/apply`），不含存储路径与 API 密钥（机器相关）；套用即写 settings.json 覆盖区运行时生效。
- **全局 GPU 锁**: 所有 GPU 前向（embedder 4 个 encode_* 与 YOLO detect，含模型加载/tracker 初始化/批量推理）必须持 `core/gpu_lock.gpu_lock`（`async with gpu_lock`）串行——24GB 机器上 YOLO 卷积与 8bit matmul 并发会触发 GPU 驱动硬故障（蓝屏/卡死）。锁只串行 GPU 计算，不串行 NVDEC 解码/DB。detection 攒批因此用 **128**（1024 长批持锁 ~20s 会饿死 embedder）。
- **共享单实例**: embedder 与 detector 都在启动时预载到 `app.state`（detector 模型懒加载，首次 detect 才载 ~2GB，避免每视频重载），业务逻辑经 `shared_detector` 注入 PipelineEngine，禁用 `load_plugin("detector"/"embedder")` 重复实例化；captioner 按需加载。
- **并发管道限制**: `pipeline.max_concurrent_videos`（0=不限）→ VideoService 用 `asyncio.Semaphore` 限流同时处理的管道数（组批量上传会并发启动多管道，激活峰值按并发叠加，低显存机建议 1）。
- **配置统一 + 自动降级**: 一份 `config/config.yaml` 通用所有机器——embedder 相对模型路径自动解析到项目根；captioner 配 `qwen3_vl` 但本地 8B 模型缺失 → `load_config()` 自动降级 `qwen_api`（DashScope，打 WARNING），摘要模式由 `runners/base.py effective_summary_mode()` 兜底 `native_video→vlm_llm`。无需 `config.windows.yaml` / `ZHIYING_CONFIG`（后者仅保留为自定义配置覆盖入口）。
- **向量维度**: 4096（人脸 512）; 无 pgvector HNSW（超 2000 上限，demo 规模全扫描 <1ms）。
- **共享 embedder**: 启动时预载到 `app.state.embedder`，业务逻辑禁用 `load_plugin("embedder")`; captioner 按需加载。
- **增量迁移**: `init_db()` 用 `ADD COLUMN IF NOT EXISTS` 演进 schema。
- **4 级参数系统**: L1 场景 → L2 感知模块 → L3 功能开关 → L4 高级参数; detection 双门控（config backend + per-video），face/plate 三门控（+face_enabled/plate_enabled）。
- **DAG 扩展**: 新感知模块 = 新 runner + `operations.py` 一个 Operation 条目，engine.py 零改动。
- **摘要双模式**: native_video（本地 GPU + Python 聚合器, 默认）/ vlm_llm（API）; 切换封装在 runner 内部; `summary_mode` 变更需新建记录（不可增量）。
- **多格式两层**: remux（容器标准化, -c copy）+ proxy（NVENC h264, 按需懒生成）; 管道优先读 remuxed; proxy 永不主动生成。
- **NVDEC**: MJPEG pipe（~100KB/帧）默认启用，自动 fallback cv2。
- **ReID 双层**: 在线 BoT-SORT with_reid（`config/botsort.yaml` `model: "models/yolo26n-cls.pt"` 本地外观模型——实测 ultralytics 8.4.115 的 `auto` 仍会从 GitHub 下载，故本地预置避免运行时下载）+ 全局 tracklet 缝合（crop mean pool → cosine ≥0.85 + 同类 + 时序不重叠）; 缝合完成后修改需新建记录。
- **编码预设**: fast/balanced/precise 三档控制分辨率 + batch（336×224 / 504×336 / 672×448），三档模板与默认档可在设置页覆盖；embedder 支持 `quantization` none/8bit/4bit（bitsandbytes, 需重启生效）。
- **版本号与发布**: 版本唯一事实来源 `core/version.py` `__version__`；`/health` 返回 `version` 字段（服务器部署后核对运行版本）。发版用 `./bump minor|patch|0.24.0`（联动改 core/version.py + frontend/package.json + package-lock.json 两处，交互式确认提交信息/commit/tag/push，`git add .`）；git tag 必须 `v<__version__>` 与 version.py 完全一致，回滚 = 服务器 `git checkout` 旧 tag + 重启。
- **存储卫生**: 删除必须走 `repository.delete_video`（StorageManager 清盘, 勿直接 `session.delete`）; 新增落盘路径必须登记进 `core/storage_manager.py`; 孤儿清扫手动（maintenance 端点/CLI, dry-run 默认）。判定: 视频文件按 DB 三列引用集合, 附属目录按 `video_id ∈ videos 表` —— 绝不用 scenes.keyframe_path（persist 窗口期会误删）。删除守卫: 404 守卫; **处理中视频允许删除**（v0.22 `core/cancellation` 登记, 管道 persist 前检查 `is_cancelled` 中止, 防写已删行 FK 异常; 已删除集合在管道结束后 `unmark_cancelled` 移除）。

## Database Tables (12)

| Table | Key Columns | Purpose |
|---|---|---|
| `video_groups` | id(UUID PK), name, created_at, updated_at | 视频分组 — 批量上传时自动创建，组内单个视频删除自动清理空组 |
| `videos` | id, status, progress, status_detail, summary(JSONB), content_type, summary_mode (native_video/vlm_llm), perception switches (vision/audio/ocr/grounding/caption/detection_enabled/summary_enabled), function switches (search_index_enabled), advanced params (sample_fps, segment_threshold, caption_with_context, summary_detail, encode_profile), language, format fields (container_format, video_codec, audio_codec, has_audio, remuxed_path, proxy_path, proxy_status, proxy_progress), **source_owned**(平台共享文件=false, 删视频不删源文件), **group_id(UUID FK → video_groups.id)** | Video master |
| `scenes` | id, video_id(FK), scene_index, text_embedding(Vector4096), caption, ocr_text, aligned_transcript, entities(JSONB) | Core search grain (text_embedding = caption+ocr+transcript 语义) |
| `transcripts` | id, video_id(FK, UNIQUE), full_text, words(JSONB) | Speech transcripts |
| `frame_embeddings` | id, video_id(FK), timestamp_sec, embedding(Vector4096), is_keyframe | 1fps frame vectors |
| `chunks` | id, video_id(FK), chunk_index, start_sec, end_sec, embedding(Vector4096) | Sliding window vectors |
| `frame_detections` | id, video_id(FK), track_id, timestamp_sec, class_name, confidence, bbox(JSONB) | Per-frame YOLO detection results (10fps, indexed by timestamp) |
| `tracks` | id, video_id(FK), track_id, class_name, first_seen, last_seen, frame_count, segments(JSONB) | BoT-SORT cross-frame track summaries |
| `track_embeddings` | id, video_id(FK), track_id, class_name, embedding(Vector4096), timestamp_sec, bbox(JSONB) | Track crop cross-modal vectors, for track-path search |
| `face_identities` | id, video_id(FK), identity_label, face_embedding(Vector512), face_count, first_seen, last_seen, avg_quality, best_face_bbox(JSONB) | Clustered face identities (ArcFace R50 512d), "人物 A/B/C..." |
| `face_detections` | id, video_id(FK), identity_id(FK), track_id, timestamp_sec, bbox(JSONB), quality_score, face_embedding(Vector512) | Per-frame face detections, linked to YOLO person tracks |
| `plate_detections` | id, video_id(FK), track_id, class_name, timestamp_sec, plate_text, plate_type, char_confidences(JSONB), bbox(JSONB), detection_confidence | HyperLPR3 license plate recognition results (per-vehicle-track, pre-ReID merge) |

## Current Implementation Status

| Area | Status | Key files |
|---|---|---|
| Pipeline DAG (15 ops, EventDrivenScheduler) | ✅ | engine.py, operations.py |
| 4-path encoding (frame/chunk/text/track) | ✅ | runners/frame_encode, chunk_encode, text_encode, track_encode |
| Detection + Tracking (双层 ReID) | ✅ | plugins/detector/yolo.py, runners/detection.py |
| Detection 大规模渲染重构 (v0.22) | ✅ | /detection/tracks + /detection/detections 替代旧 /detection/data; 前端虚拟滚动 + Canvas 时间轴 |
| 7-path search + 图搜 (face/universal) | ✅ | search_engine.py, core/search.py |
| Face / Plate 识别 | ✅ | plugins/face/insightface_face.py, plugins/plate/hyperlpr_plate.py |
| 双模式摘要 (native_video/vlm_llm) | ✅ | runners/caption.py, summary.py |
| 多格式兼容 (remux + lazy proxy) | ✅ | services/format_service.py |
| 存储卫生 (v0.21) | ✅ | core/storage_manager.py, api/maintenance_routes.py, scripts/sweep_storage.py |
| 4级参数 + 增量处理 | ✅ | core/schemas.py, engine.py run_incremental() |
| 系统设置（API 密钥/服务商/存储/管道性能） | ✅ | core/settings_service.py, api/settings_routes.py — GET/PUT /settings（含 pipeline 段：编码三档模板/检测参数/量化/并发上限，settings.json backed，运行时生效） |
| 参数预设 (v0.22) | ✅ | core/presets_service.py — GET/POST/PUT/DELETE /settings/presets + apply（data/presets.json 命名快照） |
| 全局 GPU 锁 + 共享单实例 | ✅ | core/gpu_lock.py, main.py app.state.detector — embedder/YOLO 前向串行防驱动故障; 并发管道 max_concurrent_videos 限流 |
| 前端 Dashboard (20 组件 + 8 hooks) | ✅ | Dashboard.tsx, components/ (SettingsPage 4 分区) |
| 元数据 / 来源分析 / 导出 | ✅ | utils/metadata.py, video_source.py, export_service.py |
| Windows 从零部署 (v0.22) | ✅ | deploy/setup_windows.ps1 裸机一键安装器 + download_models.py (含 reid) + deploy_feedback.md; 配置统一自动降级 |
| 删除处理中 + 管道取消 (v0.22) | ✅ | core/cancellation.py — 处理中视频允许删除，删除端点登记后管道 persist 前优雅中止（防写已删行 FK 异常） |
| 多架构 requirements (v0.22) | ✅ | 环境标记: onnxruntime-gpu (win32/x86_64/AMD64) / onnxruntime (aarch64/arm64, 无 GPU wheel 自动 CPU) |
| 云智平台接入 (v0.24) | ✅ | api/yunzhi_routes.py + services/yunzhi_job_service.py (202+进度/完成/失败回调, 幂等) + register-external (source_owned) + 前端 Bridge (frontend/src/platform/) |
| 生产部署 (v0.24) | ✅ | systemd `zhiying.service` @ 10.0.0.176:8011, pgvector:pg17 容器, 后端静态托管前端 dist, 详见 `docs/server.md`（gitignored 含凭证）|
| OCR / Grounding | ⬜ Shell | plugins/ocr/, plugins/grounding/ |
| Health / Reindex | 🔶 部分 | /health 已上, reindex 待办 |

## Agent Instructions

> Read this section last. It tells you how to behave in this project.

1. **Don't modify `.env`** — it contains API keys and is gitignored.
2. **Don't delete empty `__init__.py` files** — they're intentional package markers.
3. **Don't delete empty files** — 空 `__init__.py` / 插件目录（plugins/ocr/, plugins/grounding/）是故意的占位。`api/maintenance_routes.py` 现在是**活跃的存储清扫路由**；`api/video_routes.py`/`search_routes.py`/`export_routes.py` 也都是活跃路由，NOT stubs。
4. **Config-driven design + operation registration**: when adding a new perception module, write a runner class in `pipeline/runners/`, add one `Operation(...)` entry to `pipeline/operations.py` `ALL_OPERATIONS`. For new plugin backends, register in `plugins/factory.py` `CATEGORY_MAP` / `_MODULE_OVERRIDES` / `_CLASS_OVERRIDES`. No hardcoded model references in business logic.
5. **Sync vs Async**: all `core/interfaces.py` methods are `async def`. If your plugin runs synchronous model inference, wrap it with `asyncio.to_thread()`. Never call `model.predict()` directly in an async function.
6. **Search paths**: `config_loader.py` and `prompt_loader.py` use `Path(__file__).resolve().parent.parent` to locate the project root. Keep this convention.
7. **Vector dimension**: 4096. All vector columns (scenes.text_embedding, frame_embeddings.embedding, chunks.embedding, track_embeddings.embedding) use `Vector(4096)`. Face embeddings use `Vector(512)` (ArcFace R50). No pgvector HNSW/IVFFlat index (4096 > 2000 limit, but full scan is fine for demo scale).
8. **Four encoding paths**: Frame (encode_image), Chunk (config-gated, default disabled, -c copy + encode_video), Text (encode_text). All three reuse the shared embedder.
9. **When adding new dependencies**: add to `requirements.txt` AND to `Dockerfile`.
10. **Search result format**: All results include `precision_level` (frame/chunk/text/label), `precise_start/end` (text 也有 scene 起止作为锚点), `match_paths`, and `thumbnail_url`. Merge 时帧簇优先，text 与非重叠帧的 text 按路径权重排序。图搜使用独立 `search_image_only()` 路径：帧不做时间聚类、不补充 scene 信息，`precise_end=None` 表示单帧精确匹配。
11. **Frontend**: Dashboard.tsx 编排所有状态（含组状态 videoGroups/detectionVideoId），组件在 `components/`（20 个）、hooks 在 `hooks/`（8 个）、标签/颜色映射在 `labels.ts`、类型在 `types/index.ts` 镜像后端 schema。
12. **Detection gate pattern**: New perception modules that are optional should follow the dual-gate pattern: config-level enable/disable (`plugins.{name}.backend: yolo` vs `null`) AND per-video toggle (`detection_enabled` in PipelineParams). Gate function checks both. This allows server-wide opt-out while letting users control per-video.
13. **Canvas overlay pattern**: The DetectionOverlay uses a `canvas` with `pointerEvents: "none"` for pure rendering, with click/mousemove handlers attached via native `addEventListener` to the parent container. This allows clicks to pass through to video controls while still enabling bbox interaction.
14. **Video format handling**: 两层 — remux（容器标准化, -c copy）+ proxy（NVENC H.264, 按需懒生成）。Probe 同步(<100ms)，remux/proxy 异步。流端点走 `FormatService.get_stream_target(id, hevc_ok)`，前端 `canPlayType()` 探测 HEVC。Proxy 永不主动生成。
15. **cv2/sync C calls MUST use asyncio.to_thread()**: All cv2 operations (VideoCapture.read, cvtColor, etc.) and other synchronous C calls that take >1ms MUST be wrapped in `asyncio.to_thread()`. This prevents event loop blocking and ensures other asyncio tasks can be scheduled. The keyframe runner's cv2 read loop is the canonical example.
16. **Embedder encode resolution**: 编码分辨率三档预设（fast 336×224 / balanced 504×336 / precise 672×448），`encode_images_batch` 支持 per-call `target_size` 覆盖；PIL resize 8 线程并行，embedder 与 stream decode 分辨率保持一致。
17. **Storage hygiene**: 删除视频必须走 `repository.delete_video`（内部由 StorageManager 按 DB 引用清盘，不要在路由里直接 `session.delete`）。新增会产生磁盘文件的功能，落盘路径模式必须登记进 `core/storage_manager.py`（视频文件按 DB 引用集合判定、附属目录按 video_id 判定），否则删除会残留。孤儿清扫用 `POST /maintenance/sweep`（dry-run 默认）或 `scripts/sweep_storage.py --apply`。

## Python Environment

- Python 3.13
- FastAPI, SQLAlchemy async, asyncpg, pgvector
- transformers, torch (CUDA 12.4), modelscope, qwen-vl-utils
- bitsandbytes (embedder 8bit/4bit 量化), onnxruntime-gpu (人脸/车牌 GPU 推理; 仅 x86/Windows — ARM64 无该 wheel, requirements 环境标记自动降级 onnxruntime CPU 版)
- openai, httpx, Pillow
- pytest, pytest-asyncio
