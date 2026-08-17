# Zhiying Project Context for AI Agents

## One-Line Summary

Zhiying 是 **视频分析引擎**（v0.33.0）：上传视频（单个/批量分组）→ 声明式操作 DAG（15 ops）→ 4 条编码路径（frame/chunk/text/track）+ YOLO11/BoT-SORT 检测跟踪（双层 ReID）+ 人脸/车牌识别 → 7 路语义搜索 + 图搜 → FastAPI + PostgreSQL/pgvector 对外服务。4 级参数系统 + 系统设置（API 密钥/服务商端点/存储路径/管道性能 + 参数预设）控制管道；全局 GPU 锁串行推理 + 并发管道限流；存储卫生（删除即清盘 + 孤儿清扫）保证磁盘不泄漏。**已接入云智(Yunzhi)平台**：前端 Bridge 文件选择（`register-external` 共享路径就地引用）+ 异步任务接口（`/internal/yunzhi/jobs` 202+进度/完成/失败回调）+ 平台文件 id 自动跳转（v0.26 `external_file_id` + `GET /videos/external/{file_id}`，前端凭 `context.resource.id` 直达对应视频详情）。`deploy/` 提供 Windows 裸机一键安装（从零部署）；**双前端共存**：服务器前端 `frontend/`（v0.28 云智嵌入 UI）+ 桌面独立前端 `frontend-desktop/`（桌面启动器 `desktop/desktop.bat` 加载，pywebview 壳管理本地后端生命周期，后端按 `ZHIYING_FRONTEND` 切换挂载）；**桌面端 v0.34 重构**（浅蓝管理后台 4 页模型文件库/视频解析/任务中心/系统设置 + frameless 自定义窗口外框 + SplitPane 工作台 + 系统监控，`update.bat` 一键更新）；requirements 已做多架构区分（Windows/Linux x86 装 onnxruntime-gpu，ARM64 如 DGX Spark/GB10 无该 wheel 自动装 CPU 版，人脸/车牌走 CPU）。**摘要默认 vlm_llm（API 模式）**：native_video 本地视频原生理解已置灰退役（双前端一致），本地 captioner 8B 不再下载。**v0.33 摘要链路根治重构**：场景数上限 `pipeline.max_scenes`（默认 6，长视频固定段数 / TransNetV2 结果合并）；caption 并发+失败降级+配置穿透（with_context/max_new_tokens 从 params 读）；text_encode 批量；摘要输入预算截断；增量补摘要不再静默失败；keyframe 抽帧统一 resize 到编码预设分辨率（取消原分辨率帧驻留）。**已部署到生产服务器 10.0.0.176（systemd `zhiying.service`，8011，部署走 git+tag：`./bump` 发版 → 服务器 `bash deploy.sh v<tag>`，config/config.yaml 已模板化不入库）**，运维参考见 `docs/server.md`（gitignored，含凭证）。架构细节见 `docs/arch.md`。

## Quick File Map

```
run.py                     — 本地开发启动入口（按 config.yaml server 段绑端口，reload 模式）
deploy.sh                  — 服务器一键部署（仓库根；`bash deploy.sh v<tag>`：fetch→config 迁移→checkout→build→restart→健康检查）
main.py                    — FastAPI app, lifespan, exception handlers, shared embedder + shared detector (app.state, detector 模型懒加载); 静态托管前端（默认 frontend/dist 服务器前端, `ZHIYING_FRONTEND=desktop` 时挂 frontend-desktop/dist 桌面前端）
api/video_routes.py        — Video CRUD + upload (probe同步+异步remux/proxy; 传 group_id 校验案例存在 + create_video IntegrityError 兜底友好400 v0.34候选) + stream (hevc_ok智能路由) + proxy-status + thumbnail + external-id lookup (v0.26) + 批量解析 analyze-batch (v0.34候选) + 文件重命名 PUT /files/{id} (v0.34候选; 行 id→file_id 解析修复版本化重命名)
api/search_routes.py       — Semantic search + pipeline/operations endpoints
api/settings_routes.py     — 系统设置端点：GET/PUT /settings（密钥/服务商/存储/管道性能）+ /settings/pipeline + 参数预设 CRUD
api/router.py              — Assembles sub-routers under /api/v1 prefix
api/yunzhi_routes.py       — 云智平台异步任务接口（POST /internal/yunzhi/jobs，根路径挂载非 /api/v1，202+幂等）
api/deps.py                — FastAPI dependency injection (get_db)
api/schemas.py             — Shared API DTOs (APIResponse, search/status models, ProxyStatusResponse, PipelineSettings/Presets, v0.22)
api/detection_routes.py    — Detection data API: GET /detection/tracks (摘要) + /detection/detections (时间窗, v0.22 替代旧 /detection/data) + thumbnail
api/export_routes.py       — Export endpoints: clip/frames/track/thumbnails (7 endpoints, GET+POST)
api/face_routes.py          — Face data API (GET face/data + face/thumbnail; v0.29 track_to_identity 身份↔track 映射; v0.31 每身份返回 appearances 按 track 聚合时间段)
api/plate_routes.py         — Plate data API (GET plate/data + plate/thumbnail)
api/maintenance_routes.py  — 存储清扫端点 (POST /maintenance/sweep dry-run/执行, GET /maintenance/storage)
api/tasks_routes.py        — 任务中心 API: GET /tasks (scope 过滤) + /tasks/{id}/log + /tasks/{id}/retry + 导出报告 (GET /tasks/{id}/report md + POST /tasks/export-batch zip, v0.34) + TaskItem.queued 排队中字段 (list_tasks 批量查排队集合防 N+1, v0.34候选)
api/groups_routes.py       — 案例/文件库 API: /groups CRUD + /files + /groups/{id}/assets 案例素材 + 素材重命名 PUT /groups/{id}/assets/{asset_id} (v0.34)
core/models.py             — ORM: Video (+8 format fields + group_id/file_id/version_no + processing_started_at), VideoGroup (+number/owner), Scene, Transcript, FrameEmbedding, Chunk, FrameDetection, Track, TrackEmbedding, FaceIdentity, FaceDetection, PlateDetection, PipelineTask, TaskLog, CaseAsset (15 tables)
core/schemas.py            — Pydantic v2 DTOs + JSONB validation models + FormatInfo/ProxyStatus + FileItem/CaseAssetItem.file_ext 真实扩展名（后缀展示字段）
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
  runners/segmentation.py    — TransNetV2 (≤30min) / 长视频固定段数 (>30min, duration/max_scenes 均匀切)；TransNetV2 结果超 max_scenes 时按累计时长合并
  runners/transcription.py   — Audio extraction + faster-whisper transcription
  runners/keyframe.py        — 1fps frame pool extraction（抽帧统一 resize 到编码预设分辨率, 取消原分辨率帧驻留）+ thumbnails (asyncio.to_thread)
  runners/alignment.py       — Transcript word-to-scene alignment
  runners/caption.py         — Caption（vlm_llm API 默认；native_video 本地模式已置灰退役，代码保留仅兼容历史）; v0.33: 并发限流 + 单场景失败降级重试 + 配置穿透（with_context/max_new_tokens/concurrency 从 params 子层读）
  runners/summary.py         — Dual-mode: Python aggregator / DeepSeek API LLM; v0.33: 剧本输入预算截断 (max_input_chars, 优先截台词→文字→画面)
  runners/frame_encode.py    — 1fps batch image encoding（统一 resolve_encode_profile 解析预设）→ frame_embeddings
  runners/chunk_encode.py    — Sliding window video encoding → chunks (config-gated)
  runners/text_encode.py     — Text semantic encoding (gated: 有文本源才跑); v0.33: 攒批 encode_texts_batch
  runners/detection.py       — YOLO11 + BoT-SORT (10fps/128batch/640px), 生产者-消费者并发, 与 search_encode 共享 NVDEC 流, 每 2s 缓存 track crop 供 track_encode (batch 128 而非 1024: 受 gpu_lock 串行, 长批会饿死 embedder); **best 帧按"置信度×面积"加权选取 + `_upgrade_best_frames` 全分辨率帧升级（person/vehicle 类）供 face/plate 用**
  runners/track_encode.py    — Track crop embedding + 全局 tracklet 缝合 (读检测缓存多帧 640×384 → mean pool → cosine 合并)
  runners/face.py            — SCRFD face detection + ArcFace R50 embedding + 身份聚类（v0.29 重构: 多帧采样提脸 + 护栏式双阈值聚类[同track 0.30/跨track 0.58] + 最典型脸作检索锚）
  runners/plate.py           — HyperLPR3 license plate detection + text recognition
  runners/search_encode.py   — 纯搜索路径：队列消费 detection 共享流帧 1fps + 批量编码，不依赖 segmentation/keyframes
pipeline/search_engine.py  — 7-path parallel recall (frame/chunk/text/label/track/plate + image) + scene-merge dedup, search_image_only() for no-cluster per-frame image search
plugins/factory.py         — Dynamic plugin loader (CATEGORY_MAP, _MODULE_OVERRIDES, _CLASS_OVERRIDES)
plugins/detector/yolo.py   — YOLO11s detector (batch GPU inference 受 core/gpu_lock 串行; batch_size/imgsz 可配, asyncio.to_thread)
plugins/face/insightface_face.py  — InsightFace SCRFD + ArcFace R50 recognizer (_to_bgr 任意通道归一化防 RGBA 崩溃; rec_thresh 死参数已删)
plugins/plate/hyperlpr_plate.py  — HyperLPR3 license plate detector + recognizer (primary)
plugins/plate/paddle_plate.py    — PaddleOCR license plate detector (alternative)
plugins/embedder/qwen_vl_embedder.py — Qwen3-VL-Embedding (336×224 encode, 内存路径, 零磁盘I/O; 量化 8bit/4bit via bitsandbytes; 受 gpu_lock 串行; 相对模型路径解析到项目根)
services/video_service.py  — Pipeline 调用与后台调度 (RUNNING_VIDEOS 注册表; 并发由全局 PipelineQueue worker 池限流, v0.32 起无信号量)
services/yunzhi_job_service.py — 云智任务执行: 建视频(source_owned=false)→管道→进度/完成/失败回调(httpx async with 内) + 默认参数映射
services/format_service.py — 格式兼容: probe(ffprobe) / remux(容器标准化, -c copy) / proxy(按需h264_nvenc)
services/export_service.py — 导出业务逻辑 (clip/frames/track/thumbnails zip)
services/report_service.py — 任务导出报告: build_report_md() 聚合版本行信息/产物统计/日志 → Markdown (v0.34)
utils/video_util.py        — FFmpeg 工具函数 + stream_frames() (NVDEC MJPEG pipe / cv2 fallback)
utils/metadata.py          — 视频元数据提取 (pymediainfo → exiftool → ffprobe 三级)
utils/video_source.py      — 视频来源分析: 规则引擎分类 phone/camera/surveillance/... + 监控品牌（文件头魔数嗅探 IMKH→海康威视, magic_bytes>filename>metadata）
config/config.yaml         — 机器相关主配置（gitignored、不入库，v0.25.1 起；模板见 config/config.yaml.example）：server/db/storage/plugins/pipeline (detection_fps:10, batch:128)
config/config_schema.py    — Pydantic config validation
config/prompts.yaml        — Caption/Summarizer/Grounding prompt templates
frontend/src/Dashboard.tsx — Main workspace (orchestrator, ~430 lines, hevcOk探测+proxy轮询+streamReady+group state+detectionVideoId+header dropdown + yunzhi 入口自动跳转 v0.26)
frontend/src/components/    — Split components (19 files):
                              icons, Header, SlideOutPanel,
                              ParameterPanel, PipelineBar, VideoSection, VideoPlayer,
                              VideoSummaryCard, VideoSearchCard, HistoryPanelContent, SettingsPage,
                              DetectionOverlay, DetectionPanel, DetectionTimeline,
                              VideoInfoCard, ExportMenu, RightPanel
                              SettingsPage 4 分区: 系统(存储/NVDEC/chunk/并发上限) + 模型参数(编码三档/YOLO/量化) + 参数预设 + API 密钥
frontend/src/labels.ts        — 再导出指针 → frontend-shared/labels（COCO 类名/颜色, 一份实现）
frontend/src/utils/helpers.ts — 再导出指针 → frontend-shared/helpers (fmtDuration/fmtDate/formatSec)
frontend/src/services/api.ts — 再导出指针 → frontend-shared/api（API wrapper + 轮询辅助; 后端接口变更只改 frontend-shared）
frontend/src/platform/        — 云智 Bridge SDK: yunzhi-bridge.ts/client.ts/YunzhiProvider/mock (VITE_YUNZHI_MOCK 切换真实/模拟; 仅服务器前端)
frontend/src/types/index.ts — 再导出指针 → frontend-shared/types (mirrors backend schemas + ProxyStatus)
frontend-desktop/             — 桌面独立前端（v0.34 重构 + v0.34候选：浅蓝管理后台主题 + frameless 自定义窗口标题栏[手动拖拽: 最大化先还原再跟随] + 4 页模型 文件库/视频解析/任务中心/系统设置 + AppContext 导航 + 工作台 SplitPane 分栏 + 系统监控; 案例库批量解析[勾选+一键/批量解析] + 案例编辑/编号自动填充 + 文件与图片重命名[内联编辑] + 后缀展示字段; 搜索卡案例-文件范围 + 跨视频切主视频 + 单实例保留结果; TaskCenter/SettingsPage 组件裂解 + 设置 4 子页收敛 2; 标题栏「最近更新(i 下拉: SplashApi git log) + 太阳/月亮主题切换」（暗色=中性炭灰环境+靛蓝强调色，`html.dark` 类 + CSS 变量调色板重映射 + index.html 内联防闪烁）；案例库闪电全状态显示（已完成=实心 IconBoltSolid + 「重新配置参数解析」→ reparse 建新版本）+ 编辑按钮移入操作格 4 按钮 + 铅笔换 edit-3；TaskCenter 导出报告/日志图标按钮；参数面板 4:3 顶向下三段+段内网格 + 物体检测/文字识别调换；设置页响应式两列卡片网格（去 max-w-900 死区）+ 编码卡独占整行；**侧栏徽章系统**（案例库🩶灰=仅上传未提交 / 视频解析🔵蓝「1」=有视频处理中、未选中视频点进自动定位 / 任务中心 🟡黄=排队中·🟢绿=新完成[进任务中心清零+整行淡绿高亮]·🔴红=失败实时计数）；**任务中心待处理剥离**（只显示已提交任务）+ 整行点击跳转 + hover 淡灰 + 失败行重试图标 + 顶部筛选下拉(全部/已完成/处理中/排队中/失败) + 1.5s 刷新；工具栏按钮图标 16px 统一 + ParameterPanel 主按钮 g-btn-primary 统一 + 行内幽灵按钮一致；与服务器 frontend/ UI 完全隔离; 构建 cd frontend-desktop && npm run build; 加载经 ZHIYING_FRONTEND=desktop）
scripts/sweep_storage.py   — 存储卫生清扫 CLI (默认 dry-run 只报告, --apply 执行, --json 机器可读)
frontend-shared/           — 双前端共享后端对接层（api/types/labels/helpers 一份实现; frontend/ 与 frontend-desktop/ 各留 1 行再导出指针; 后端接口/字段变更只改这里）
scripts/mock_yunzhi_platform.py — 本地 mock 云智平台回调服务器 (监听 /progress /complete /fail, 联调验证用)
scripts/bump_version.py    — 一键版本提升 (交互式: 改号→输入提交信息→确认 commit/tag/push, git add .)
bump                       — 仓库根可执行启动器 → scripts/bump_version.py (任意开发机 git pull 后 `./bump minor`)
update.bat                 — 桌面端一键自动更新（Windows 双击/`.\update.bat`：git pull 走 7897 代理 → pip 装 desktop 依赖 → npm install/build → build_exe.ps1 -Deploy 重打 exe，全流程跑一遍不判断）
deploy/                    — 部署套件: setup_windows.ps1（Windows 裸机一键安装：Python/FFmpeg/CUDA torch/WSL2/Docker/依赖/模型 + 生成 config.yaml + 构建前端 dist + 自校验；旧 start_windows.ps1 与 write_windows_config.py 已删）/ setup_linux.sh（Linux 开发机一键安装，规格同 Windows：代理交互/环境复用/幂等）/ download_models.py（含 reid 组件 yolo26n-cls.pt）/ deploy.md / deploy_feedback.md（部署踩坑记录）。配置已统一：无需 config.windows.yaml / ZHIYING_CONFIG，后端直接 uvicorn main:app
desktop/                   — 桌面端启动器（pywebview 壳, Windows 桌面机）: app.py/state/checks/db/backend/logs/webview_panel + desktop.bat（dev 入口）+ build_exe.ps1/build_exe.spec（`build_exe.ps1 -Deploy` 一条命令构建并部署纯产品启动器 exe：exe+_internal 放项目根双击即用，仅桌面壳不含后端/模型；壳子进程统一 CREATE_NO_WINDOW 防弹终端，spec 用 SPECPATH/collect_submodules 全后端打包）。**v0.34：主窗 `frameless=True, shadow=True` 自定义窗口外框；`webview_panel.py` SplashApi 扩展窗口控制（minimize/toggle_maximize/quit）+ `get_system_stats`（psutil CPU/内存/网络 + nvidia-smi GPU，`desktop/requirements.txt` 含 psutil）+ `get_recent_commits`（TitleBar「最近更新」下拉：项目根 `git log`，`CREATE_NO_WINDOW` 防闪框）+ `get_logs`（启动实时日志增量，迁自已删除的控制窗 LogApi）；主窗 `SPLASH_HTML` 为**毛玻璃启动页**（前端同款渐变 + 毛玻璃卡片 + 标题 + 阶段进度条，**模型加载段按日志 tqdm `Loading weights: X%` 实时推进 10%→90%**，亮暗自适应）；独立「启动日志」控制窗已移除（LogApi/LOG_HTML 删除，日志仍落盘 data/logs）；前端 `index.html` 加 `#boot` 毛玻璃过渡遮罩（无进度条，React 挂载后淡出防白屏）；标题栏手动拖拽（onMouseDown → SplashApi.move 跟随，替代原生 drag-region）+ 窗口按钮经 js_api 桥接；is_maximized 读真实 WindowState（window.native=BrowserView 实例）、关闭走主题化确认弹窗；backend_child 父进程句柄看门狗（免疫 PID 复用）+ 启动前清孤儿；build_exe -Deploy 内容拷贝防嵌套 + 部署自检**。起后端时传 `ZHIYING_FRONTEND=desktop` → 后端挂载桌面前端 frontend-desktop/dist；摘要默认 vlm_llm（native_video 置灰退役）；库用根 docker-compose.yaml 的 db 服务
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

文件库 / 多版本 / 任务中心 (v0.34):
  POST /videos/upload → videos.file_id=uuid (首次) + version_no=1; POST /videos/{id}/reanalyze → 复制文件信息建新版本行 (file_id 同, version_no 递增) + 入队
  GET /files → 每 file_id 一行 (根行信息 + 当前版本状态); GET /videos/{id}/versions → 同 file_id 全部版本行
  PUT /params / reanalyze / retry → append_task_log 写 task_logs ("任务已创建/参数已提交/重新解析新版本/任务重试")
  PipelineEngine._set_processing → videos.processing_started_at=now; mark_completed/failed → updated_at → 任务中心「耗时」= updated_at − processing_started_at
  GET /tasks (scope) → 版本行列表; GET /tasks/{id}/log → task_logs; GET /tasks/{id}/report → Markdown; POST /tasks/export-batch → zip
  POST /videos/analyze-batch (v0.34候选) → 批量解析：精确启动指定 pending 视频（仅 pending、不走组同步、可选整批参数整批应用），前端文件列表勾选列 + 一键/批量解析（弹参数面板）
  PUT /files/{file_id} / PUT /groups/{id}/assets/{asset_id} (v0.34候选) → 文件/素材重命名（无后缀自动补磁盘真实扩展名）；FileItem/CaseAssetItem.file_ext 真实扩展名作展示字段（前端编辑框只含主名，重命名不影响后缀）

云智平台接入 (v0.24):
  POST /api/v1/videos/register-external → 平台共享文件就地引用 (source_owned=false, 删视频绝不 unlink 源文件; probe + 异步 remux 与上传同流程; 可选带 external_file_id)
  GET /videos/external/{file_id} + videos.external_file_id (v0.26): 平台文件 id 唯一标识 → 前端 Bridge connect() 后凭 context.resource.id 自动打开对应视频详情（非文件入口/无匹配 → 默认工作台）
  POST /internal/yunzhi/jobs → 立即 202 {accepted, bizTaskId} → 后台建视频+跑管道 → 进度/完成/失败回调 (callback.progressUrl/completeUrl/failUrl, 幂等 eventId/Idempotency-Key)
    → 平台文件库与 Zhiying 共享同一套绝对路径 (宿主同视角)

系统设置/参数预设 (v0.22, 运行时生效):
  GET/PUT /settings 读写 data/settings.json {api_keys, providers, storage, pipeline}
    → pipeline 段覆盖 config.yaml（编码三档模板/检测参数/量化/并发上限, clamp_param 钳制）
    → load_config() 每次 _apply_settings_overrides 合并, 保存清 lru_cache → 无需重启（quantization 除外）
  GET/POST /settings/presets + PUT/DELETE /{id} + POST /{id}/apply → data/presets.json 命名快照
  并发: pipeline.max_concurrent_videos → 全局 PipelineQueue worker 池（0/未设=1 串行 FIFO 排队，防批量并发 OOM）
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
- **全局任务队列（v0.32）**: `core/pipeline_queue.py` PipelineQueue — FIFO + N worker（N=max_concurrent_videos，0/未设=1 串行）+ `pipeline_tasks` 表 DB 持久化。所有管道触发点（yunzhi jobs / 上传 params / 组同步 / 增量）统一入队，接口保持异步（jobs 202）。重启恢复：queued 重入队 / running yunzhi 续跑（防重复建视频）/ running pipeline 标失败；yunzhi payload_json 存回调 URL+token，恢复后照常发 complete/fail；入队即发"排队中"低进度回调。worker 数随设置运行时调整（configure）。**v0.34候选 enqueue 形参未传 video_id 时自动从 payload 取**（根治排队行 pipeline_tasks.video_id 全 NULL → TaskItem.queued 排队检测/侧栏黄徽章失效）。
- **任务中心（v0.34）**: `api/tasks_routes.py` + `services/report_service.py`。一次解析 = 一个版本行（videos 行），任务中心列表按 scope 过滤（all/active/history）；「耗时」= `updated_at − processing_started_at`（管道开跑才计时，排队不计入，重试重置）；**日志生命周期**：所有写入统一走 `core/repository.append_task_log`（task_logs 表，seq 递增）——覆盖 create_video（"任务已创建"）、PUT params（"参数已提交，任务入队"）、reanalyze（"重新解析新版本"）、engine（管道开始/完成/失败）、retry（"任务重试"）；导出报告 = `GET /tasks/{id}/report`（Markdown 下载，中文文件名 URL 编码）+ `POST /tasks/export-batch`（zip 打包，Python 3.13 zipfile 自动 UTF-8 中文名），产物表统计单表异常降级不阻塞整份报告。**v0.34候选 交互**：TaskItem.queued 排队中字段（list_tasks 批量查排队集合）；前端 TaskHeader 顶部下拉筛选（全部/已完成/处理中/排队中/失败）+ 整行点击跳转 + hover 淡灰 + 失败行重试图标（IconRetry busy 旋转）+ 1.5s 轮询 + 新完成行首次进入淡绿高亮；**待处理剥离**——仅上传未提交的任务不进任务中心列表（由案例库灰徽章承载）。
- **批量解析 / 重命名 / 后缀展示（v0.34候选）**: `POST /videos/analyze-batch` 批量解析 = 精确勾选启动（仅 pending、**不走组同步**、可选整批 `params` 整批应用）；前端文件列表勾选列（仅待处理可勾）+ 一键/批量解析（弹参数面板）；文件/素材重命名 = `PUT /files/{file_id}`（更新该文件全部版本行 file_name，含遗留 NULL file_id）+ `PUT /groups/{id}/assets/{asset_id}`（仅改显示名），**新名无后缀自动补磁盘真实扩展名**；`FileItem/CaseAssetItem.file_ext` 真实扩展名作**展示字段**——前端名称单元格主名+灰后缀展示、编辑框只含主名、重命名不影响后缀。
- **配置模板化 + 自动降级**: `config/config.yaml` **机器相关、gitignored、不入库**（v0.25.1 起；模板 `config/config.yaml.example`，新机复制后自改路径/密钥）——embedder 相对模型路径自动解析到项目根；captioner 配 `qwen3_vl` 但本地 8B 模型缺失 → `load_config()` 自动降级 `qwen_api`（DashScope，打 WARNING），摘要模式由 `runners/base.py effective_summary_mode()` 兜底 `native_video→vlm_llm`。**摘要默认 vlm_llm**（native_video 已置灰退役，前端不再可选；模板 captioner 默认 `qwen_api`，本地 captioner 8B 不再下载）。无需 `config.windows.yaml` / `ZHIYING_CONFIG`（后者仅保留为自定义配置覆盖入口）。
- **向量维度（v0.34候选 模型适配）**: 随 `embedding_profile` 档位——`8b`=4096（默认）/ `2b`=2048（低显存平替）；`core/embedding_profile.py` 的 `EmbedVector()` 懒读全局维度建表，`config_loader._apply_embedding_profile` 联动「模型路径+维度」；人脸固定 512（ArcFace，与档位无关）。换档改 `embedding_profile` + 重启后端，⚠️ 维度不同需重建向量库。无 pgvector HNSW（超 2000 上限，demo 规模全扫描 <1ms）。
- **DB 连接读 config（v0.27 起）**: `core/db.py` 连接地址解析顺序 = **环境变量 `POSTGRES_URI` → config.yaml 的 `database.uri` → 兜底 5432**（不再有"忽略 config 的硬编码"陷阱）。服务器 2026-08-08 因系统 postgres 抢 5432 迁到 **5433**（config.yaml `database.uri=5433`；start.sh 的 POSTGRES_URI=5433 冗余但无害）。新部署机在 config.yaml 配好 `database.uri` 即可。
- **共享 embedder**: 启动时预载到 `app.state.embedder`，业务逻辑禁用 `load_plugin("embedder")`; captioner 按需加载。
- **增量迁移**: `init_db()` 用 `ADD COLUMN IF NOT EXISTS` 演进 schema。
- **4 级参数系统**: L1 场景 → L2 感知模块 → L3 功能开关 → L4 高级参数; detection 双门控（config backend + per-video），face/plate 三门控（+face_enabled/plate_enabled）。
- **DAG 扩展**: 新感知模块 = 新 runner + `operations.py` 一个 Operation 条目，engine.py 零改动。
- **摘要双模式（native_video 已置灰退役）**: vlm_llm（API, 默认）/ native_video（本地 GPU + Python 聚合器, 前端置灰不可选, 后端代码保留仅兼容历史记录）; 切换封装在 runner 内部; `summary_mode` 变更需新建记录（不可增量）。
- **双前端共存 + 共享对接层**: `frontend/`（服务器, v0.28 云智嵌入 UI）+ `frontend-desktop/`（桌面独立前端）UI 层完全隔离, 共用同一后端; main.py 按 `ZHIYING_FRONTEND` 切挂载（默认服务器, 桌面启动器传 desktop）。**后端对接层 `frontend-shared/`（api/types/labels/helpers）一份实现, 双端各留再导出指针复用**——后端接口/字段变更只改共享目录一处, 两端自动同步, 无「改两遍」负担。UI 层各自演进不共享。**桌面端（v0.34）结构**：`AppContext` 持有跨页导航（page/selectedVideoId/settingsTab）+ 共享视频列表轮询 + 上传/删除/拖拽编排；4 页模型（FileLibrary 文件库 / Workbench 视频解析 / TaskCenter 任务中心 / SettingsPage 系统设置）；TitleBar 自绘标题栏（手动拖拽 SplashApi.move + 窗口控制经 js_api，is_maximized 读真实 WindowState）；SplitPane 可拖拽分栏（自智影 v2 demo 移植）；SystemMonitor 底部真机监控（等 `pywebviewready` 再轮询 `get_system_stats`）。**页面组件裂解（与后端任务中心/设置新架构对齐）**：TaskCenter 裂解为 TaskHeader（顶部卡：状态下拉筛选 全部/已完成/处理中/排队中/失败 + 导出 + 1.5s 刷新指示）+ TaskBody（正文卡：整行点击跳转 + hover 淡灰 + 失败行重试图标 + 日志弹窗，1.5s 轮询）；SettingsPage 4 子页收敛为 2（系统设置=系统+参数预设，模型参数=模型参数+API密钥），每页再裂解为子组件（系统设置 PresetSection/StorageSection/PipelineSection，模型参数 EncoderSection/DetectionSection/ApiKeysSection），样式类模块级复用、state 留主组件、子组件纯展示+回调；**卡片空隙**靠外层 `app-main-flat` 透明背景 + 页面根容器透明（不透明白底会挡死渐变，TaskCenter/FileLibrary/SettingsPage 根容器均透明）实现渐变透出。**发布**：根目录 `update.bat` 一键自动更新（Windows）。
- **多格式两层**: remux（容器标准化, -c copy）+ proxy（NVENC h264, 按需懒生成）; 管道优先读 remuxed; proxy 永不主动生成。
- **NVDEC**: MJPEG pipe（~100KB/帧）默认启用，自动 fallback cv2。
- **ReID 双层**: 在线 BoT-SORT with_reid（`config/botsort.yaml` `model: "models/yolo26n-cls.pt"` 本地外观模型——实测 ultralytics 8.4.115 的 `auto` 仍会从 GitHub 下载，故本地预置避免运行时下载）+ 全局 tracklet 缝合（crop mean pool → cosine ≥0.85 + 同类 + 时序不重叠）; 缝合完成后修改需新建记录。
- **人脸聚类护栏式双阈值（v0.29）**: 单一聚类阈值是"跷跷板"——0.60 拆碎同人（碎片化）、0.40 并错不同人（代表性 embedding 稀释成噪声 → 搜索搜不到）。正确策略在 `face.py`: **同 track 内（同一人时间连续，强先验）阈值 0.30 宽松合并；跨 track（不同时空）阈值 0.58 保守合并**。检索锚点用**最典型单脸**（与均值最接近的成员，非质量分最高——质量分高可能偏角度导致搜索漏检）；`core/search.py` `FACE_SEARCH_MIN_SIM=0.45` 为搜索命中阈值（单一来源，聚类/搜索共用，杜绝脱节）。身份存 `best_face_embedding`（最典型单脸主锚）+ `face_embedding`（均值兜底），搜索用 `GREATEST` 双锚取高。
- **搜索隔离（v0.29 bug 修复）**: `POST /search/face` 与 `/search/image` 的 `video_ids`/`search_types`/`top_k`/`min_similarity` 必须是 **`Form(...)` 声明**（前端 form-data 提交；曾误声明为普通参数 → FastAPI 从 query 取 → None → 全库数据泄漏）。语义搜索走 JSON body 一直正确。搜索必须严格按 `video_ids` 隔离，单视频搜索不得混入其它视频结果。
- **编码预设**: fast/balanced/precise 三档控制分辨率 + batch（336×224 / 504×336 / 672×448），三档模板与默认档可在设置页覆盖；embedder 支持 `quantization` none/8bit/4bit（bitsandbytes, 需重启生效）。
- **版本号与发布**: 版本唯一事实来源 `core/version.py` `__version__`；`/health` 返回 `version` 字段（服务器部署后核对运行版本）。发版用 `./bump minor|patch|0.24.0`（联动改 core/version.py + frontend/package.json + package-lock.json 两处，交互式确认提交信息/commit/tag/push，`git add .`）；git tag 必须 `v<__version__>` 与 version.py 完全一致。**⚠️ 后端任何改动（bug 修复/性能优化/管线重构/新功能上线）以及服务器前端改动（`frontend/` + `frontend-shared/`，会上服务器）都必须 `./bump` 发版打 tag——即使不立刻部署**（保持最新 tag = 当前可部署状态）；只有纯文档、注释、**桌面前端改动（`frontend-desktop/`，独立自由不发版，随后端版本走）**不需要 bump。**部署（v0.25.1 起）**: 服务器 `bash deploy.sh v<tag>`（fetch → config 迁移 → checkout → requirements 变化才 pip → 前端 build → restart → 90s 健康检查）。**回滚限制**: config.yaml 已 gitignore，回退到 config 仍入库的老 tag（≤v0.25.0）会 checkout 冲突，正解是向前滚（出 bug 发下个 patch）；必须回退老 tag 时先还原服务器 config 备份。
- **存储卫生**: 删除必须走 `repository.delete_video`（StorageManager 清盘, 勿直接 `session.delete`）; 新增落盘路径必须登记进 `core/storage_manager.py`; 孤儿清扫手动（maintenance 端点/CLI, dry-run 默认）。判定: 视频文件按 DB 三列引用集合, 附属目录按 `video_id ∈ videos 表` —— 绝不用 scenes.keyframe_path（persist 窗口期会误删）。删除守卫: 404 守卫; **处理中视频允许删除**（v0.22 `core/cancellation` 登记, 管道 persist 前检查 `is_cancelled` 中止, 防写已删行 FK 异常; 已删除集合在管道结束后 `unmark_cancelled` 移除）。

## Database Tables (13)

| Table | Key Columns | Purpose |
|---|---|---|
| `video_groups` | id(UUID PK), name, created_at, updated_at | 视频分组 — 批量上传时自动创建，组内单个视频删除自动清理空组 |
| `videos` | id, status, progress, status_detail, summary(JSONB), content_type, summary_mode (native_video/vlm_llm), perception switches (vision/audio/ocr/grounding/caption/detection_enabled/summary_enabled), function switches (search_index_enabled), advanced params (sample_fps, segment_threshold, caption_with_context, summary_detail, encode_profile), language, format fields (container_format, video_codec, audio_codec, has_audio, remuxed_path, proxy_path, proxy_status, proxy_progress), **source_owned**(平台共享文件=false, 删视频不删源文件), **group_id(UUID FK → video_groups.id)**, **external_file_id**(平台文件库资源ID, 前端自动跳转用, v0.26), **file_id+version_no**(版本链: 同文件多版本行, v0.34), **processing_started_at**(管道开始处理时间, 任务中心「耗时」数据源, v0.34) | Video master |
| `scenes` | id, video_id(FK), scene_index, text_embedding(向量(随embedding_profile)), caption, ocr_text, aligned_transcript, entities(JSONB) | Core search grain (text_embedding = caption+ocr+transcript 语义) |
| `transcripts` | id, video_id(FK, UNIQUE), full_text, words(JSONB) | Speech transcripts |
| `frame_embeddings` | id, video_id(FK), timestamp_sec, embedding(向量(随embedding_profile)), is_keyframe | 1fps frame vectors |
| `chunks` | id, video_id(FK), chunk_index, start_sec, end_sec, embedding(向量(随embedding_profile)) | Sliding window vectors |
| `frame_detections` | id, video_id(FK), track_id, timestamp_sec, class_name, confidence, bbox(JSONB) | Per-frame YOLO detection results (10fps, indexed by timestamp) |
| `tracks` | id, video_id(FK), track_id, class_name, first_seen, last_seen, frame_count, segments(JSONB) | BoT-SORT cross-frame track summaries |
| `track_embeddings` | id, video_id(FK), track_id, class_name, embedding(向量(随embedding_profile)), timestamp_sec, bbox(JSONB) | Track crop cross-modal vectors, for track-path search |
| `face_identities` | id, video_id(FK), identity_label, face_embedding(Vector512 均值兜底), best_face_embedding(Vector512 最典型脸主锚 v0.29), best_track_id(v0.29 身份↔track 映射), face_count, first_seen, last_seen, avg_quality, best_face_bbox(JSONB) | Clustered face identities (ArcFace R50 512d), "人物 A/B/C..." |
| `face_detections` | id, video_id(FK), identity_id(FK), track_id, timestamp_sec, bbox(JSONB), quality_score, face_embedding(Vector512) | Per-frame face detections, linked to YOLO person tracks |
| `plate_detections` | id, video_id(FK), track_id, class_name, timestamp_sec, plate_text, plate_type, char_confidences(JSONB), bbox(JSONB), detection_confidence | HyperLPR3 license plate recognition results (per-vehicle-track, pre-ReID merge) |
| `pipeline_tasks` | id(UUID PK), type(yunzhi_job/pipeline/incremental), dedup_key, video_id, payload_json(Text), status(queued/running/completed/failed), error, created_at, updated_at | 全局任务队列持久化（v0.32）— 重启恢复 + 幂等查重 + 回调 URL/token 存档 |
| `task_logs` | id(SERIAL PK), task_id(UUID=版本行 videos.id), seq, level, message, created_at | 任务生命周期日志（v0.34）— 上传/参数/重解析/管道/重试各点写入，任务中心展示 |

## Current Implementation Status
**已完成**：Pipeline DAG(15 ops) / 4-path 编码 / Detection+Tracking(双层 ReID) / 7-path 搜索+图搜 / 人脸+车牌识别 / 双模式摘要(vlm_llm 默认) / 多格式(remux+proxy) / 存储卫生 / 4级参数+增量 / 系统设置+参数预设 / 全局 GPU 锁+共享实例 / 任务队列(v0.32) / 文件库+多版本解析+任务中心(v0.34: 版本行=一次解析, 日志生命周期, 耗时, 导出报告) / 云智嵌入 UI / 桌面端启动器+前端(v0.34 重构+页面组件裂解) / 生产部署 / OCR 设计(docs/ocr.md)。关键实现文件见上方 Quick File Map。

**待办**：OCR 实现 / Grounding(Florence-2)。

版本演进细节（v0.22–v0.33）见 README「Development Status」。

## Agent Instructions

> Read this section last. It tells you how to behave in this project.

1. **Don't modify `.env`** — it contains API keys and is gitignored.
2. **Don't delete empty `__init__.py` files** — they're intentional package markers.
3. **Don't delete empty files** — 空 `__init__.py` / 插件目录（plugins/ocr/, plugins/grounding/）是故意的占位。`api/maintenance_routes.py` 现在是**活跃的存储清扫路由**；`api/video_routes.py`/`search_routes.py`/`export_routes.py` 也都是活跃路由，NOT stubs。
4. **Config-driven design + operation registration**: when adding a new perception module, write a runner class in `pipeline/runners/`, add one `Operation(...)` entry to `pipeline/operations.py` `ALL_OPERATIONS`. For new plugin backends, register in `plugins/factory.py` `CATEGORY_MAP` / `_MODULE_OVERRIDES` / `_CLASS_OVERRIDES`. No hardcoded model references in business logic.
5. **Sync vs Async**: all `core/interfaces.py` methods are `async def`. If your plugin runs synchronous model inference, wrap it with `asyncio.to_thread()`. Never call `model.predict()` directly in an async function.
6. **Search paths**: `config_loader.py` and `prompt_loader.py` use `Path(__file__).resolve().parent.parent` to locate the project root. Keep this convention.
7. **Vector dimension**: 随 `embedding_profile`（`core/embedding_profile.py` 的 `EmbedVector()` 懒读全局维度，8b=4096 / 2b=2048）；所有向量列（scenes.text_embedding、frame_embeddings.embedding、chunks.embedding、track_embeddings.embedding）用 `EmbedVector()`，维度由 `config_loader._apply_embedding_profile` 在建表前设置。Face embeddings 固定 `Vector(512)` (ArcFace R50)。No pgvector HNSW/IVFFlat index (4096 > 2000 limit, but full scan is fine for demo scale).
8. **Four encoding paths**: Frame (encode_image), Chunk (config-gated, default disabled, -c copy + encode_video), Text (encode_text). All three reuse the shared embedder.
9. **When adding new dependencies**: add to `requirements.txt` AND to `Dockerfile`.
10. **Search result format**: All results include `precision_level` (frame/chunk/text/label), `precise_start/end` (text 也有 scene 起止作为锚点), `match_paths`, and `thumbnail_url`. Merge 时帧簇优先，text 与非重叠帧的 text 按路径权重排序。图搜使用独立 `search_image_only()` 路径：帧不做时间聚类、不补充 scene 信息，`precise_end=None` 表示单帧精确匹配。
11. **Frontend（双前端）**: 服务器前端 `frontend/`（v0.28 云智嵌入 UI, 组件 19 个已删 Sidebar）+ 桌面独立前端 `frontend-desktop/`（v0.34 浅蓝管理后台 4 页模型：文件库/视频解析/任务中心/系统设置；AppContext 导航 + TitleBar/SplitPane/SystemMonitor）——UI 层各自演进不共享；**对接层 `frontend-shared/`（api/types/labels/helpers）一份实现，两端 `services/api.ts`/`types`/`labels`/`helpers` 是 1 行再导出指针**。改后端接口/字段 → 只改 `frontend-shared/` 一处。桌面端已无 Dashboard.tsx——改为 App.tsx 壳 + AppContext + 4 页组件（Workbench 承载原工作台状态）。
12. **Detection gate pattern**: New perception modules that are optional should follow the dual-gate pattern: config-level enable/disable (`plugins.{name}.backend: yolo` vs `null`) AND per-video toggle (`detection_enabled` in PipelineParams). Gate function checks both. This allows server-wide opt-out while letting users control per-video.
13. **Canvas overlay pattern**: The DetectionOverlay uses a `canvas` with `pointerEvents: "none"` for pure rendering, with click/mousemove handlers attached via native `addEventListener` to the parent container. This allows clicks to pass through to video controls while still enabling bbox interaction.
14. **Video format handling**: 两层 — remux（容器标准化, -c copy）+ proxy（NVENC H.264, 按需懒生成）。Probe 同步(<100ms)，remux/proxy 异步。流端点走 `FormatService.get_stream_target(id, hevc_ok)`，前端 `canPlayType()` 探测 HEVC。Proxy 永不主动生成。
15. **cv2/sync C calls MUST use asyncio.to_thread()**: All cv2 operations (VideoCapture.read, cvtColor, etc.) and other synchronous C calls that take >1ms MUST be wrapped in `asyncio.to_thread()`. This prevents event loop blocking and ensures other asyncio tasks can be scheduled. The keyframe runner's cv2 read loop is the canonical example.
16. **Embedder encode resolution**: 编码分辨率三档预设（fast 336×224 / balanced 504×336 / precise 672×448），`encode_images_batch` 支持 per-call `target_size` 覆盖；PIL resize 8 线程并行，embedder 与 stream decode 分辨率保持一致。
17. **Storage hygiene**: 删除视频必须走 `repository.delete_video`（内部由 StorageManager 按 DB 引用清盘，不要在路由里直接 `session.delete`）。新增会产生磁盘文件的功能，落盘路径模式必须登记进 `core/storage_manager.py`（视频文件按 DB 引用集合判定、附属目录按 video_id 判定），否则删除会残留。孤儿清扫用 `POST /maintenance/sweep`（dry-run 默认）或 `scripts/sweep_storage.py --apply`。
18. **commit / tag / push / 服务器部署必须事前征得用户明确同意**: 改代码、本地验证随便做；但任何 git 写操作（commit/tag/push）与服务器部署（`bash deploy.sh` / 重启 systemd）都先问用户，用户点头才执行。**同一时刻只允许一个 agent 跑部署闭环**，防并发 bump 打架。
19. **改前端必须先确认是哪个前端**: 本项目有**两个前端**——服务器前端 `frontend/`（v0.28 云智嵌入 UI，会上服务器、改动需 bump）与桌面前端 `frontend-desktop/`（v0.34 浅蓝管理后台 4 页模型，独立自由、改动不需 bump）。用户说「前端/界面/UI」时，若没明确指哪一端，**先反问确认再动手**，绝不猜着改错端。共享对接层 `frontend-shared/` 双端共用，改了影响两端（视为服务器侧改动）。

## Python Environment

- Python 3.13
- FastAPI, SQLAlchemy async, asyncpg, pgvector
- transformers, torch (CUDA 12.4), modelscope, qwen-vl-utils
- bitsandbytes (embedder 8bit/4bit 量化), onnxruntime-gpu (人脸/车牌 GPU 推理; 仅 x86/Windows — ARM64 无该 wheel, requirements 环境标记自动降级 onnxruntime CPU 版)
- openai, httpx, Pillow
- pytest, pytest-asyncio
