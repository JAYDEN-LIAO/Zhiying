# Zhiying Project Context for AI Agents

## Overview

智影 (Zhiying) 是**视频分析引擎**：上传视频（单个/批量分组/多版本解析）→ 声明式 DAG 管道（16 ops）→ 4 条编码路径 + YOLO11/BoT-SORT 检测跟踪（双层 ReID）+ 人脸/车牌/OCR 识别 → 8 路语义搜索 + 图搜 → FastAPI + PostgreSQL/pgvector 对外服务。当前状态 **v0.34 候选**（未发版，累积中）。

关键锚点：
- **生产部署**：10.0.0.176（systemd `zhiying.service`，8011）；发版 `./bump` → 服务器 `bash deploy.sh v<tag>`；运维参考 gitignored `docs/server.md`
- **配置模板化**：`config/config.yaml` 机器相关、**gitignored**（模板 `config/config.yaml.example`）；运行时覆盖走 `data/settings.json`（设置页，保存即生效，quantization 除外）+ 共享参数预设 `config/presets.json`（**入仓库随 git 走**，部署/换机复用）
- **双前端**：服务器 `frontend/`（云智嵌入 UI）+ 桌面独立 `frontend-desktop/`（浅蓝 4 页管理后台：文件库/视频解析/任务中心/系统设置，pywebview 壳）；对接层 `frontend-shared/`（api/types/labels/helpers）一份实现、双端再导出复用；后端按 `ZHIYING_FRONTEND` 切挂载
- **模型档位**：`embedding_profile` 8b=4096 维（默认）/ 2b=2048 维（低显存平替）；人脸固定 512（ArcFace）。2b 档自动套用轻量编码/量化默认（`_2B_ENCODE_DEFAULTS`）
- **摘要默认 vlm_llm（API）**；native_video 本地模式已置灰退役（代码保留兼容历史）
- **云智平台**：`register-external` 就地引用来源文件 + `/internal/yunzhi/jobs`（202 异步任务、进度/完成/失败回调、幂等）+ 平台文件 id 自动跳转
- Windows 桌面端从零部署 `install1.bat`（选 2B/8B + 代理，内嵌 PostgreSQL，WebView2 Runtime 自动更新）；日常更新 `install2.bat`（git pull → 依赖 → 前端 build → 重打 exe）
- 架构与接口细节见 `docs/arch.md`

## Quick File Map

```
run.py / deploy.sh         本地开发启动（config.yaml server 段绑端口）；服务器一键部署 `bash deploy.sh v<tag>`
main.py                    FastAPI app, lifespan, shared embedder/detector（app.state, detector 懒加载）; 静态托管前端（ZHIYING_FRONTEND 切 frontend/ 或 frontend-desktop/ dist）
api/                       路由（/api/v1 前缀；yunzhi_routes 根路径挂载）
  video_routes.py          Video CRUD + upload/upload/batch + register-external + stream(hevc 智能路由) + thumbnail + external-id 跳转 + reanalyze 版本化 + analyze-batch 批量解析 + 文件重命名
  search_routes.py         语义搜索（含 OCR 第 8 路）+ pipeline/operations
  ocr_routes.py            GET /videos/{id}/ocr/data 画面文字清单
  settings_routes.py       GET/PUT /settings + /settings/pipeline + /settings/presets（参数预设 CRUD/apply）
  tasks_routes.py          任务中心：/tasks + {id}/log + {id}/retry + {id}/report(md) + export-batch(zip) + TaskItem.queued
  groups_routes.py         案例/文件库：/groups CRUD + /files + /groups/{id}/assets 素材 + 素材重命名
  detection/face/plate/export/maintenance_routes.py  检测/人脸/车牌数据+缩略图; 导出 clip/frames/track/thumbnails; 存储清扫 sweep/storage
core/                      models.py（15 表 ORM）· schemas.py（DTO）· repository.py（数据访问 + append_task_log）· search.py（7 路检索：frame/chunk/text/track/plate/ocr/face）· db.py（init_db 增量迁移 + pgvector）
                           config_loader.py（config + .env + settings 覆盖 + 参数钳制 + captioner 自动降级 + embedding_profile 联动）· settings_service.py + presets_service.py（设置/参数预设）
                           storage_manager.py（删除清盘/孤儿清扫）· gpu_lock.py（全局 GPU 串行锁）· cancellation.py（删除处理中视频后管道优雅中止）· embedding_profile.py· paths.py· version.py（版本唯一来源）
pipeline/                  engine.py（EventDrivenScheduler DAG 执行器）· operations.py（16 op 注册表）· search_engine.py（8 路并行召回 + 去重）
  runners/                 16 个操作 runner：duration/segmentation/transcription/keyframe/alignment/caption/summary/frame_encode/chunk_encode/text_encode/detection/track_encode/face/plate/search_encode/ocr
plugins/                   factory.py 动态加载；detector/yolo + face/insightface + plate/hyperlpr + ocr/rapidocr（PP-OCRv3 ONNX，DirectML 独立子进程，不占主 GPU/CUDA）+ embedder/qwen_vl_embedder（内存路径零磁盘 I/O，可按 bitsandbytes 量化）+ grounding 占位；easyocr.py 已移除（精度弱，OCR 定版 rapidocr）
services/                  video_service（管道调度，并发由 PipelineQueue 队列 worker 池限流）· yunzhi_job_service（云智任务执行+回调）· format_service（probe/remux/proxy 两层格式兼容）· export_service· report_service
utils/                     video_util（FFmpeg + stream_frames NVDEC MJPEG/cv2）· metadata（三级元数据）· video_source（来源规则引擎，文件头魔数嗅探监控品牌）
desktop/                   桌面端 pywebview 壳：app.py/state/checks/db/backend/logs/webview_panel + build_exe.ps1（-Deploy 打纯壳 exe）；SPLASH 毛玻璃启动页；SplashApi 窗口控制/系统监控/启动日志；backend_launcher 统一拉起后端（封装字节码/源码双模式 + 父进程看门狗）
frontend/                  服务器前端（React 19 + Vite + Tailwind 4，Dashboard 主工作台 + 19 组件 + 云智 Bridge SDK）
frontend-desktop/          桌面前端（App.tsx 壳 + AppContext 导航 + 4 页组件 + TitleBar/SplitPane/SystemMonitor；与 server 端 UI 完全隔离）
frontend-shared/           api/types/labels/helpers 一份实现（双端再导出指针；后端接口变更只改这里）
deploy/                    setup_windows.ps1（install1.bat 入口，从零部署）/ setup_linux.sh / build_backend_pyc.py（编译 .pyc 字节码包藏源码）/ download_models.py（按档位下载+校验）/ deploy.md / deploy_feedback.md
scripts/                   sweep_storage.py（存储清扫 CLI）· bump_version.py（一键版本提升）· mock_yunzhi_platform.py（本地 mock 云智回调）
install1.bat / install2.bat  新机一键部署 / 桌面端一键自动更新
backend_launcher.py       后端子进程统一启动器（父进程看门狗，免疫 PID 复用）
```

## Core Flow

```
上传 → 参数 → 管道 → 搜索:
  POST /videos/upload(/upload/batch 批量建组) → 存盘 → 同步 probe → 建记录(pending) → 异步 remux/proxy
  PUT /videos/{id}/params → 校验 → 入队 → PipelineEngine.run()(pending) / run_incremental()(completed, 仅 summary/search_index)
  DELETE /videos/{id} → 404 守卫 → 处理中可删(cancellation 登记, 管道 persist 前优雅中止) → 批量删行(DB 级联) → StorageManager 引用判定清盘
  PipelineEngine 事件驱动 DAG(16 ops): duration → detection(生产者-消费者, 共享 NVDEC 流) → track_encode → face/plate; segmentation → keyframes → caption → summary → frame/text/chunk_encode; ocr(自抽高清帧, RapidOCR+DirectML 独立子进程) → ocr_detections
  GET /videos/{id}/stream?hevc_ok=: H.264 直出 / HEVC+hevc_ok→remuxed / 非 HEVC→proxy(按需懒生成, 永不主动)
  搜索 7 路并行 + 图搜：frame/chunk/text/label/track/plate/ocr；详见 docs/arch.md

文件库 / 多版本 / 任务中心:
  一次解析 = 一个版本行(videos.file_id+version_no 版本链)；reanalyze 建新版本入队；analyze-batch 精确勾选批量解析
  任务生命周期日志统一走 repository.append_task_log（task_logs 表）；任务中心列表按 scope 过滤；耗时 = updated_at − processing_started_at

云智平台:
  POST /videos/register-external → 平台共享文件就地引用(source_owned=false, 删视频不删源文件)
  POST /internal/yunzhi/jobs → 立即 202 → 后台建视频跑管道 → 进度/完成/失败回调(幂等 eventId)

系统设置/参数预设（运行时生效）:
  GET/PUT /settings 读写 data/settings.json → 每次 load_config() 合并, 保存清缓存 → 无需重启(quantization 需重启)
  /settings/presets → config/presets.json 命名参数快照（入仓库, 随 git 迁移）
  并发: max_concurrent_videos → 全局 PipelineQueue worker 池（0=1 串行 FIFO）；所有 GPU 前向持 gpu_lock 串行
```

## Key Conventions

- **异步规则**: 所有接口 async；同步模型推理 / cv2（VideoCapture.read 等）MUST `asyncio.to_thread()`（关键帧 cv2 循环是范本）。
- **Config-driven**: 插件后端由 `config.yaml` `plugins.{name}.backend` 选，null=禁用；API key 只在 `.env`/环境变量。新增感知模块 = 新 runner + `operations.py` 一个 Operation，engine 零改动。
- **设置运行时生效**: 上传路由/FormatService/VideoService 均用新鲜 `load_config()`（勿用启动时 app.state.config 快照）；数值按 `PIPELINE_NUMERIC_SPEC`/`clamp_param` 钳制。
- **参数预设**: `config/presets.json` 命名快照（不含存储路径/API key），套用写 settings.json 覆盖区；入仓库随 git 走，旧 data/presets.json 首次读取自动搬迁。
- **全局 GPU 锁**: 所有 embedder encode_* / YOLO detect 前向必须 `async with gpu_lock`（并发前向会触发驱动硬故障蓝屏/卡死）；detection 攒批用 **128**（1024 长批持锁 ~20s 饿死 embedder）。锁只串行 GPU 计算，不串行 NVDEC/DB。
- **OCR DML 隔离（v0.34 定版）**: onnxruntime 与 onnxruntime-directml 共用 `import onnxruntime` 名、进程内只能一份——RapidOCR 必须走**独立子进程**（`plugins/ocr/rapidocr_worker.py`，启动时 `sys.path` 前置 `vendor/ort_dml` 加载 DML），**绝不**在主进程改全局 onnxruntime（否则静默剥夺人脸/车牌 CUDA）。`onnxruntime-directml` 由 install1/install2 装到 `vendor/ort_dml`（不在 requirements 直装）。OCR 文本去重在 `pipeline/runners/ocr.py:_dedup_tracklets`：全局合并 + 固定文字抑制（static_frames/static_move_eps）+ 模糊合并（difflib 子串/相似）+ 阅读序。
- **共享单实例**: embedder + detector 启动预载 app.state（detector 懒加载），业务经 `shared_detector` 注入，禁用 `load_plugin("detector"/"embedder")` 重复实例化；captioner 按需加载。
- **全局任务队列**: PipelineQueue FIFO + N worker（N=max_concurrent_videos）+ `pipeline_tasks` 表持久化；所有管道触发点统一入队；重启恢复（queued 重入队 / running yunzhi 续跑 / running pipeline 标失败）；enqueue 未传 video_id 时自动从 payload 取。
- **向量维度**: 随 embedding_profile（`EmbedVector()` 懒读全局维度，8b=4096 / 2b=2048）；所有向量列用它；人脸固定 `Vector(512)`。换档改 config + 重启，维度不同需重建向量库。**2b 档自动套用轻量编码/量化默认**（`_2B_ENCODE_DEFAULTS`）；`_ENCODING_OVERRIDDEN` 字段级让位用户设置页保存值。无 pgvector HNSW（4096 超 2000，demo 规模全扫描 <1ms）。
- **DB 连接**: 解析顺序 = 环境变量 `POSTGRES_URI` → config.yaml `database.uri` → 兜底 5432（服务器 2026-08 迁到 5433）。
- **配置模板化 + 自动降级**: config.yaml 机器相关 gitignored；captioner 配 `qwen3_vl` 但本地模型缺失 → 自动降级 `qwen_api`（DashScope）；摘要默认 vlm_llm。
- **4 级参数系统**: L1 场景 → L2 感知模块 → L3 功能开关 → L4 高级参数；detection 双门控（config backend + per-video），face/plate 三门控（+face_enabled/plate_enabled）。
- **摘要双模式**: vlm_llm（API，默认）/ native_video（本地 GPU + Python 聚合器，已置灰退役，代码保留兼容历史）；summary_mode 变更需新建记录（不可增量）。
- **双前端**：UI 层各自演进不共享，共用后端；对接层 `frontend-shared/` 一份实现，改后端接口只改一处；桌面端页面卡片空隙靠外层 `app-main-flat` 透明 + 根容器透明透出渐变。
- **多格式两层**: remux（容器标准化, -c copy）+ proxy（NVENC h264, 按需懒生成）；管道优先读 remuxed。
- **NVDEC**: MJPEG pipe 默认启用，自动 fallback cv2。
- **ReID 双层**: 在线 BoT-SORT with_reid（本地 `models/yolo26n-cls.pt` 外观模型防运行时下载）+ 全局 tracklet 缝合（crop mean pool → cosine ≥0.85 + 同类 + 时序不重叠）；缝合完成后修改需新建记录。
- **人脸聚类护栏式双阈值**: 同 track 内阈值 0.30 宽松合并（时间连续强先验），跨 track 0.58 保守合并（防并错）；检索锚点用**最典型单脸**（非质量分最高）；`FACE_SEARCH_MIN_SIM=0.45` 单一日治阈值；搜索用 `GREATEST(最典型脸, 均值)` 双锚。
- **搜索隔离**: search/face 与 search/image 的 `video_ids` 等必须 `Form(...)` 声明（曾误用 query → 全库泄漏）；搜索严格按 `video_ids` 过滤。
- **编码预设**: fast/balanced/precise 三档模板（分辨率+批量）可设置页覆盖；embedder 支撑 none/8bit/4bit 量化（bitsandbytes，需重启）。
- **版本号与发布**: 版本唯一来源 `core/version.py` `__version__`（`/health` 返回）；发版 `./bump`（改 version + frontend package.json，交互确认 commit/tag/push）；tag 必须 `v<__version__>`。**后端任何改动 + 服务器前端（`frontend/`+`frontend-shared/`）都必须 `./bump` 发版——即使不立刻部署**；只有纯文档/注释/桌面前端（`frontend-desktop/`）不需 bump。部署 `bash deploy.sh v<tag>`；回滚限制：config.yaml 已 gitignore，老 tag（≤v0.25.0）checkout 会冲突，正解向前滚。
- **存储卫生**: 删除必须走 `repository.delete_video`（StorageManager 清盘，勿直接 session.delete）；新增落盘路径必须登记进 `core/storage_manager.py`；孤儿清扫手动（sweep 端点/CLI，dry-run 默认）。判定：视频文件按 DB 三列引用集合、附属目录按 video_id——绝不用 scenes.keyframe_path（persist 窗口期会误删）。

## Database (15 tables)

| Table | Purpose |
|---|---|
| `video_groups` | 批量上传自动分组；组内单个视频删除自动清空组 |
| `videos` | 主表：status/progress/summary/感知与功能开关/高级参数/语言/格式字段 + source_owned(平台文件) + group_id + external_file_id + file_id/version_no(版本链) + processing_started_at(任务耗时) |
| `scenes` | 搜索主粒度：text_embedding(=caption+ocr+transcript 语义), caption, ocr_text, aligned_transcript, entities(JSONB) |
| `transcripts` | 完整字幕 + words(字词时间戳) |
| `frame_embeddings` / `chunks` | 1fps 帧向量 / 滑动窗口向量（gated） |
| `frame_detections` / `tracks` / `track_embeddings` | YOLO 逐帧检测 / BoT-SORT 轨迹摘要 / 轨迹 crop 跨模态向量 |
| `face_identities` / `face_detections` | 聚类身份（512d，双锚）+ 逐帧人脸 |
| `plate_detections` | HyperLPR3 车牌识别 |
| `pipeline_tasks` | 全局任务队列持久化（重启恢复 + 幂等 + 回调存档） |
| `task_logs` | 任务生命周期日志（seq 递增） |

向量列（scenes.text_embedding / frame_embeddings.embedding / chunks.embedding / track_embeddings.embedding）用 `EmbedVector()` 随 embedding_profile 维度。

## Status

**已完成**：DAG(16 ops) / 4-path 编码 / 双层 ReID 检测跟踪 / 8 路搜索+图搜 / 人脸+车牌+OCR / **OCR 定版 RapidOCR+DirectML 子进程**（含去重/固定文字抑制/模糊合并/阅读序）/ 双模式摘要(vlm_llm 默认) / 多格式 remux+proxy / 存储卫生 / 4 级参数+增量 / 系统设置+参数预设 / 全局 GPU 锁+共享实例 / 任务队列 / 文件库+多版本+任务中心 / 批量解析+重命名 / 云智嵌入 UI / 桌面端重构 + pywebview 壳 + 生产部署 / 档位感知设置 / 预设随 git 迁移。

**待办**：Grounding(Florence-2)。

## Agent Instructions

> Read this section last. It tells you how to behave in this project.

1. **Don't modify `.env`** — contains API keys, gitignored.
2. **Don't delete empty `__init__.py` / 空占位** — plugins/grounding/ 是故意占位（plugins/ocr/ 已实现，paddleocr.py 勿删）；`api/maintenance_routes.py` 等是活跃路由，NOT stubs。
3. **Config-driven + operation registration**: 新感知模块 = `pipeline/runners/` 新 runner + `pipeline/operations.py` 一个 Operation；新插件后端注册到 `plugins/factory.py`（CATEGORY_MAP / _MODULE_OVERRIDES / _CLASS_OVERRIDES）。业务逻辑不硬编码模型引用。
4. **Sync vs Async**: 插件接口全 async；同步模型推理必须 `asyncio.to_thread()`。
5. **Search paths**: `config_loader.py` / `prompt_loader.py` 用 `Path(__file__).resolve().parent.parent` 定位项目根，保持惯例。
6. **Vector dimension**: 向量列用 `EmbedVector()`（维度随 embedding_profile）；人脸 `Vector(512)`。
7. **新依赖**: 加 `requirements.txt` AND `Dockerfile`。
8. **Search result format**: 结果含 `precision_level` / `precise_start/end` / `match_paths` / `thumbnail_url`；帧簇优先，text 与帧重叠丢弃；图搜独立 `search_image_only()`（帧不聚类, precise_end=None）。
9. **Frontend（双前端）**: 服务器 `frontend/` + 桌面 `frontend-desktop/` UI 各自演进；对接层 `frontend-shared/` 一份实现，两端 services/api.ts 等是 1 行再导出指针。改后端接口/字段 → 只改 `frontend-shared/`。
10. **Detection gate**: 可选感知模块遵循双门控（config backend + per-video toggle）。
11. **Canvas overlay**: DetectionOverlay 用 `pointerEvents:"none"` canvas + 原生 addEventListener 挂父容器，点击穿透到视频控件。
12. **Video format**: 两层 remux + proxy（惰性）；Probe 同步(<100ms)，remux/proxy 异步；流走 `FormatService.get_stream_target(id, hevc_ok)`。
13. **cv2/sync C calls MUST use asyncio.to_thread()** — 防阻塞事件循环（keyframe cv2 循环是范本）。
14. **Storage hygiene**: 删除必须 `repository.delete_video`；新落盘路径登记进 `core/storage_manager.py`。
15. **commit / tag / push / 服务器部署必须事前征得用户明确同意**: 本地随便做；git 写操作与部署都先问用户。同一时刻只允许一个 agent 跑部署闭环。
16. **改前端先确认哪端**: 本项目有两个前端——服务器 `frontend/`（会上服务器、需 bump）与桌面前端 `frontend-desktop/`（独立自由）。用户说「前端/界面/UI」未明确时先反问确认。`frontend-shared/` 双端共用（视为服务器侧改动）。

## Python Environment

Python 3.13 · FastAPI + SQLAlchemy async + asyncpg + pgvector · transformers/torch(CUDA)/modelscope/qwen-vl-utils · bitsandbytes(量化) · onnxruntime-gpu(x86/Windows; ARM64 自动降级 onnxruntime CPU) · openai/httpx/Pillow · pytest/pytest-asyncio