# Zhiying — Universal Video Analytics Engine

通用视频分析引擎：上传视频 → 声明式 DAG 管道（16 ops）→ 4 条编码路径 + YOLO11/BoT-SORT 检测跟踪 + 人脸/车牌/OCR 识别 → 8 路语义搜索 + 图搜。面向单 GPU（8–32GB）设计，已接入云智(Yunzhi)平台异步任务，生产部署于 10.0.0.176。

## Quick Start

```bash
# 1. Start database
docker compose up -d db

# 2. Set API keys (vlm_llm 摘要模式需要)
set DASHSCOPE_API_KEY=sk-xxx   # Qwen-VL API (vlm_llm captioning)
set DEEPSEEK_API_KEY=sk-xxx    # LLM summarizer (vlm_llm mode)

# 3. Start backend server
python run.py   # 按 config.yaml server 段绑定端口（默认 8011），reload
# 健康检查：http://localhost:8011/health → {"status":"ok","service":"zhiying","version":"<版本>","database":"ok"}

# 4. (New tab) Start frontend dev server
cd frontend && npm install && npm run dev

# 5. Upload a video
curl -X POST -F "file=@demo.mp4" http://localhost:8011/api/v1/videos/upload

# 6. 查看摘要 / 语义搜索
curl http://localhost:8011/api/v1/videos/{video_id}
curl -X POST -H "Content-Type: application/json" -d '{"query":"a man in black"}' \
  http://localhost:8011/api/v1/search/semantic
```

> API key 放项目根 `.env`（gitignored）或前端设置页。**摘要默认 `vlm_llm`（API）**：DashScope（画面描述）+ DeepSeek（摘要）；`native_video` 本地模式已置灰退役。
> **Windows 桌面端**：全新机双击 `install1.bat` 一键部署（选 2B/8B + 代理 → Python/FFmpeg/CUDA torch/依赖/**内嵌 PostgreSQL**(vendor/pg)/模型/config/建表 + WebView2 Runtime 自动更新）→ 双击 `智影桌面端.exe`（构建见 `desktop/README.md`）。日常更新 `install2.bat`（git pull 走 7897 代理 → 依赖 → 前端 build → 重打 exe）。

## Windows / Linux 部署

- **从零部署（Windows 桌面机）**：双击根目录 `install1.bat` 交互式一键安装（选**2B/8B** embedding 档位 + 代理 → 自动装全部环境/依赖/**内嵌 PostgreSQL**(免 Docker/WSL2)/模型(按档位)/config.yaml/建表 + **WebView2 Runtime 自动更新**）；装完双击 `智影桌面端.exe` 拉起桌面进程。
- **Linux 开发机**：`bash deploy/setup_linux.sh [--proxy ... --non-interactive]` 一键装齐环境/依赖/模型/前端，形态与本机一致。
- 细节见 **[`deploy/deploy.md`](deploy/deploy.md)**；部署踩坑见 **`deploy/deploy_feedback.md`**。
- **配置模板化**：`config/config.yaml` **机器相关、gitignored**，新机复制 `config/config.yaml.example` 自改（embedding_profile 档位、database.uri、路径）；`embedding_profile` 8b=4096 维 / 2b=2048 维（2b 档自动套用轻量编码/量化默认）。
- **多架构**：requirements 环境标记区分——x86/Windows 装 `onnxruntime-gpu`；ARM64（DGX Spark/GB10）自动装 `onnxruntime` CPU 版（人脸/车牌走 CPU）。

## Core Features

| Feature | Endpoint | Status |
|---|---|---|
| 上传 / 批量上传(分组) / 参数与管道触发 | `POST /videos/upload` + `/upload/batch` + `PUT /videos/{id}/params` | ✅ |
| 视频详情 / 状态 / 播放(stream, HEVC 智能路由) / 场景缩略图 | `GET /videos/{id}` · `/status` · `/stream?hevc_ok=` · `/thumbnail/{scene}` | ✅ |
| 多格式支持 | remux(-c copy) + 惰性 H.264 proxy(NVENC) + smart routing | ✅ |
| 语义搜索（frame/chunk/text/label/track/plate 6 路） | `POST /search/semantic` | ✅ |
| 人脸识别（SCRFD + ArcFace 512d 聚类, 双锚检索） | `GET /videos/{id}/face/data` · `POST /search/face` | ✅ |
| 车牌识别（HyperLPR3） | `GET /videos/{id}/plate/data` + 模糊搜索 | ✅ |
| OCR 画面文字提取（RapidOCR PP-OCRv3 + DirectML, 独立子进程） | `GET /videos/{id}/ocr/data` · 第 8 路 `search_types=["ocr"]` 精确串检索 | ✅ |
| 通用图搜（Qwen3-VL-Embedding → frame_embeddings） | `POST /search/image` | ✅ |
| 搜索数据隔离 / 五种搜索样式统一 | 严格按 video_ids 过滤 + uniform sr-item 卡片 | ✅ |
| 导出（clip/frames/track 视频/thumbnails zip） | `GET/POST /videos/{id}/export/...` | ✅ |
| 系统设置 + 参数预设（运行时生效, 预设随 git 迁移） | `GET/PUT /settings` + `/settings/presets` | ✅ |
| 文件库/多版本/任务中心 | `/files` `/groups` `/videos/{id}/versions` `/reanalyze` `/tasks` + 导出报告 | ✅ |
| 批量解析 / 文件与素材重命名 | `POST /videos/analyze-batch` · `PUT /files/{id}` · `PUT /groups/{id}/assets/{id}` | ✅ |
| 存储卫生 | 删除即清盘 + 孤儿清扫（`POST /maintenance/sweep` + 产物统计 CLI `scripts/sweep_storage.py`） | ✅ |
| 云智平台集成 | `register-external` 就地引用 + `/internal/yunzhi/jobs`（202 异步+回调+幂等）+ 平台文件 id 跳转 | ✅ |
| 桌面端启动器 + 独立桌面前端 | `desktop/` pywebview 壳 + `frontend-desktop/` 4 页管理后台（文件库/视频解析/任务中心/系统设置） | ✅ |
| 设置档位感知（2b 自动轻量默认 + 档位徽标） | `GET /settings/pipeline` 返回 embedding_profile；设置页按 2b/8b 展示推荐 | ✅ |
| 前端（服务器 + 桌面）| React 19 + Vite + Tailwind 4（对接层 `frontend-shared/` 一份实现） | ✅ |

## Architecture Overview

```
Upload → Probe → Pipeline (DAG) → DB → Search → Frontend
         ├─ Duration detection (ffprobe)
         ├─ [搜索路径] Search Encode @1fps — 与 detection 共享 NVDEC 流（队列消费）
         ├─ [摘要路径] Scene Segmentation (TransNetV2/时长固定段, max_scenes 上限)
         │    ├─ Keyframe @1fps → caption(vlm_llm API) → summary(vlm_llm API)
         │    └─ Frame/Text/Chunk embedding (4 编码路径, 分辨率 3 档预设)
         ├─ Object Detection — YOLO11s + BoT-SORT (可选，双门控) → 逐帧检测 → 跨帧追踪
         ├─ Face (SCRFD+ArcFace 512d 聚类) / Plate (HyperLPR3)（可选，三门控）
         ├─ OCR — 自抽高清帧 + RapidOCR(PP-OCRv3 ONNX, DirectML 独立子进程)（可选，双门控）→ ocr_detections 精确文字检索
         ├─ Global ReID Stitch（crop mean pool → cosine 合并同一身份 tracklet）
         ├─ Source Analysis（规则引擎：phone/camera/surveillance + 文件头魔数嗅探品牌）
         └─ Shared GPU models（embedder/detector 预载 app.state；GPU 前向串行锁防驱动故障）
搜索: 7 路并行召回 + 人脸图搜 + 通用图搜（含 OCR 精确文字）→ 合并去重 → 统一 confidence
```
- **声明式 DAG** — 16 操作注册在 `pipeline/operations.py`（gate + 依赖边），EventDrivenScheduler 事件驱动；搜索/摘要/OCR 路径解耦，与 detection 共享单 NVDEC 流。
- **插件化** — 10 插件 ABC + 工厂动态加载；4 条编码路径 + 7 路检索 + 人脸/车牌 + 4 级参数系统。
- **设置与参数运行时生效** — settings.json 覆盖 config.yaml（量化需重启）；参数预设 `config/presets.json` 命名快照一键套用（随 git 迁移）。
- **双前端共存** — `frontend/`（服务器）+ `frontend-desktop/`（桌面）UI 完全隔离共用后端，`ZHIYING_FRONTEND` 切挂载；对接层 `frontend-shared/` 一份实现。
- 架构细节见 `docs/arch.md`（Pipeline/Schema/API/Search/Design Decisions）。

## Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI (Python 3.13) + SQLAlchemy async + PostgreSQL 17 + pgvector |
| Frontend | React 19 + TypeScript + Vite 6 + Tailwind CSS 4（双前端） |
| Vector Embedding | Qwen3-VL-Embedding-8B/2B (本地 GPU, 可选 bitsandbytes 量化) |
| Detection/Tracking | YOLO11s + BoT-SORT with_reid（双层 ReID） |
| Caption/Summary | Qwen-VL-Max (DashScope) + DeepSeek（vlm_llm 模式, 默认） |
| Scene/Transcript | TransNetV2 / 时长分段 · faster-whisper（opt-in） |
| Face/Plate | InsightFace SCRFD + ArcFace R50 · HyperLPR3 (ONNX Runtime) |
| OCR | RapidOCR PP-OCRv3 ONNX + DirectML 子进程（DML 隔离，零影响人脸/车牌 CUDA） |
| Video Processing | FFmpeg (asyncio subprocess, NVDEC MJPEG pipe) |
| Desktop Shell | pywebview + 内嵌便携 PostgreSQL（免 Docker/WSL2), 后端字节码封装 |

## 版本号与发布

- **版本唯一事实来源**：`core/version.py` `__version__`；`/health` 返回 version；发版 `./bump minor|patch|版本`（联动 core/version.py + frontend/package.json + 锁文件，交互确认 commit/tag/push）；tag 必须 `v<__version__>`。
- **⚠️ 后端 + 服务器前端（`frontend/` + `frontend-shared/`）任何改动都必须 `./bump` 发版——即使不立刻部署**；仅纯文档/注释/桌面前端（`frontend-desktop/`）不需 bump。
- **部署**：服务器 `bash deploy.sh v<tag>`（fetch→config 迁移→checkout→requirements 变化才 pip→前端 build→restart→90s 健康检查）。回滚向前滚（config.yaml 已 gitignore，老 tag checkout 冲突）。

## Project Structure

```
zhiying/
├── bump / install1.bat / install2.bat   # 发版启动器 / 新机一键部署 / 桌面端一键更新
├── run.py / main.py / backend_launcher.py
├── api/            # 路由: video/search/settings/tasks/groups/detection/face/plate/ocr/export/maintenance/yunzhi
├── core/           # models(15表)/schemas/repository/search/db/config_loader/settings_service/presets_service
│                   #   storage_manager/gpu_lock/cancellation/embedding_profile/paths/version/prompt_loader
├── pipeline/       # engine(DAG 执行器) / operations(16 op) / runners/(16 runner) / search_engine
├── plugins/        # factory + detector/face/plate/ocr/embedder/captioner/summarizer/segmenter/transcriber/(grounding 占位)
├── services/       # video_service / yunzhi_job_service / format_service / export_service / report_service
├── utils/          # video_util / metadata / video_source
├── config/         # config.yaml(gitignored) + config.yaml.example + presets.json(随 git 共享) + prompts.yaml
├── frontend/       # 服务器前端（Dashboard 主工作台 + 云智 Bridge）
├── frontend-desktop/# 桌面前端（4 页管理后台, 独立）
├── frontend-shared/ # 双前端共享对接层（api/types/labels/helpers, 一份实现）
├── desktop/        # 桌面端 pywebview 壳 + build_exe.ps1(打纯壳 exe)
├── deploy/         # setup_windows.ps1 / setup_linux.sh / build_backend_pyc.py / download_models.py / deploy*.md
├── scripts/        # sweep_storage.py / bump_version.py / mock_yunzhi_platform.py
└── docs/           # arch.md(权威架构) / archive/(历史归档, 含 ocr 改造) / server.md(gitignored)
```

## Development Status

**当前状态（v0.34 候选，未发版）**：
- 桌面端重构（浅蓝 4 页管理后台 + frameless 窗口 + SplitPane 工作台 + 系统监控）+ 页面组件裂解 + 暗色主题 + 侧栏徽章 + 标题栏最近更新
- 文件库 / 多版本解析 / 任务中心（版本行=一次解析、日志生命周期、耗时、导出报告、批量解析、文件与素材重命名、后缀展示）
- 搜索卡案例-文件范围 + 跨视频切主视频 + 单实例保留结果
- 一键安装器 + 内嵌 PostgreSQL + 后端字节码封装 + 部署/构建健壮性（WebView2 Runtime 更新 / pyc legacy / safetensors 校验 / 幂等停 pg / start_db 幂等 / check_models 按档位）
- 设置档位感知（2b 自动套用轻量编码/量化默认 + 设置页档位徽标）+ 参数预设随 git 迁移（config/presets.json）
- OCR 定版：**RapidOCR(PP-OCRv3 ONNX) + DirectML 独立子进程**（替代 PaddleOCR/EasyOCR，中文精度第一梯队，DML 隔离零影响人脸/车牌 CUDA）+ 文本去重/顺序整理（固定文字只读一遍、同句全局合并、模糊合并、阅读序）+ 移除 easyocr 依赖 + requirements/install 补齐
- 桌面壳打磨：启动页 512 高清图标 + × 终止启动 + 全弹窗关闭按钮统一无框无底 + 任务日志一键复制 + 标题栏 logo 无框透明

**里程碑摘要**：v0.33 摘要链路根治（max_scenes/并发降级/预算截断）· v0.32 全局任务队列 · v0.31 人脸搜索+搜索范围+跨视频穿透 · v0.29 人脸链路重构+搜索隔离 · v0.28 云智嵌入 UI · v0.27 车牌模糊搜索 · v0.26 平台文件 id 跳转 · v0.24 云智接入+生产部署 · 更早见 git log。

**Planned**：Grounding(Florence-2)。