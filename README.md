# Zhiying — Universal Video Analytics Engine

通用视频分析引擎：上传视频 → 声明式 DAG 管道（16 ops）→ 4 条编码路径 + YOLO11/BoT-SORT 检测跟踪 + 人脸/车牌/OCR 识别 → 8 路语义搜索 + 图搜。面向单 GPU（8–32GB）设计，已接入云智平台，生产部署于 10.0.0.176。

## Quick Start

```bash
docker compose up -d db                        # 启动数据库
set DASHSCOPE_API_KEY=sk-xxx                   # 设置 API key（vlm_llm 摘要模式）
python run.py                                  # 启动后端（默认 8011）
cd frontend && npm install && npm run dev       # 启动前端开发服务器
curl -X POST -F "file=@demo.mp4" http://localhost:8011/api/v1/videos/upload  # 上传视频
```

> API key 放项目根 `.env`（gitignored）。**Windows 桌面端**：双击 `install1.bat` 一键部署（选 2B/8B + 代理，内嵌 PostgreSQL，WebView2 Runtime 自动更新）；`install2.bat` 日常更新。

## Core Features

| Feature | Endpoint | Status |
|---|---|---|
| 上传/批量上传/参数与管道触发 | `POST /videos/upload` + `/upload/batch` + `PUT /videos/{id}/params` | ✅ |
| **智能参数系统** | `POST /videos/suggest-params` 自动持久化场景推荐 + `PATCH /videos/{id}/toggles` 抽屉轻量持久化 + 抽屉「参数设置」小面板 + 批量解析弹窗（按各视频/统一参数 二选一） | ✅ |
| 视频详情/状态/播放(stream)/场景缩略图 | `GET /videos/{id}` · `/status` · `/stream?hevc_ok=` · `/thumbnail/{scene}` | ✅ |
| 多格式支持 | remux(-c copy) + 惰性 H.264 proxy(NVENC) + smart routing | ✅ |
| 语义搜索（frame/chunk/text/label/track/plate/ocr 7 路） | `POST /search/semantic` | ✅ |
| 人脸识别（SCRFD + ArcFace 512d 聚类, 双锚检索） | `GET /videos/{id}/face/data` · `POST /search/face` | ✅ |
| 车牌识别（HyperLPR3） | `GET /videos/{id}/plate/data` + 模糊搜索 | ✅ |
| OCR 画面文字提取（RapidOCR PP-OCRv3 + DirectML, 独立子进程） | `GET /videos/{id}/ocr/data` · `POST /search/semantic` (search_types=["ocr"]) | ✅ |
| 通用图搜（Qwen3-VL-Embedding → frame_embeddings） | `POST /search/image` | ✅ |
| 导出（clip/frames/track/thumbnails zip） | `GET/POST /videos/{id}/export/...` | ✅ |
| 系统设置+参数预设（运行时生效, 预设随 git 迁移） | `GET/PUT /settings` + `/settings/presets` | ✅ |
| 文件库/多版本/任务中心/批量解析/重命名 | `/files` `/groups` `/tasks` `/analyze-batch` | ✅ |
| 存储卫生 | 删除即清盘 + 孤儿清扫（`POST /maintenance/sweep`） | ✅ |
| 云智平台集成 | `register-external` + `/internal/yunzhi/jobs`（202 异步+回调+幂等） | ✅ |
| 桌面端启动器+独立桌面前端 | pywebview 壳 + 4 页管理后台（文件库/视频解析/任务中心/系统设置） | ✅ |
| 桌面前端 v0.35 增强 | 全局搜索重构（4 类型+句式化 chip/中文 token/人脸·通用图搜分轨）+ 案例库正文拖拽上传 + 侧栏顺序优化 | ✅ |
| 前端（服务器+桌面）| React 19 + Vite + Tailwind 4（对接层 `frontend-shared/` 一份实现） | ✅ |

## Architecture Overview

```
Upload → Probe → Pipeline (DAG) → DB → Search → Frontend
         ├─ Duration detection (ffprobe)
         ├─ [搜索路径] Search Encode @1fps — 与 detection 共享 NVDEC 流
         ├─ [摘要路径] Scene Segmentation (TransNetV2/时长固定段)
         │    ├─ Keyframe @1fps → caption(vlm_llm API) → summary(vlm_llm API)
         │    └─ Frame/Text/Chunk embedding (4 编码路径, 分辨率 3 档预设)
         ├─ Object Detection — YOLO11s + BoT-SORT (双层 ReID) → 逐帧检测 → 跨帧追踪
         ├─ Face (SCRFD+ArcFace 512d 聚类) / Plate (HyperLPR3)
         ├─ OCR — 自抽高清帧 + RapidOCR(PP-OCRv3 ONNX, DirectML 独立子进程) → ocr_detections
         └─ Shared GPU models（embedder/detector 预载 app.state；GPU 前向串行锁）
搜索: 7 路并行召回 + 人脸图搜 + 通用图搜 → 合并去重 → 统一 confidence
```

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

- **版本唯一事实来源**：`core/version.py` `__version__`；`/health` 返回 version
- **发版**：`./bump minor|patch|版本`（联动 core/version.py + frontend/package.json，交互确认 commit/tag/push）；tag 必须 `v<__version__>`
- **⚠️ 后端 + 服务器前端（`frontend/` + `frontend-shared/`）任何改动都必须 `./bump` 发版**；仅纯文档/注释/桌面前端（`frontend-desktop/`）不需 bump
- **部署**：服务器 `bash deploy.sh v<tag>`（fetch→config 迁移→checkout→requirements 变化才 pip→前端 build→restart→90s 健康检查）

## Project Structure

```
zhiying/
├── bump / install1.bat / install2.bat   # 发版启动器 / 新机一键部署 / 桌面端一键更新
├── run.py / main.py / backend_launcher.py
├── api/            # 路由: video/search/settings/tasks/groups/detection/face/plate/ocr/export/maintenance/yunzhi
├── core/           # models(15表)/schemas/repository/search/db/config_loader/settings_service/presets_service
│                   #   storage_manager/gpu_lock/cancellation/embedding_profile/paths/version
├── pipeline/       # engine(DAG 执行器) / operations(16 op) / runners/(16 runner) / search_engine
├── plugins/        # factory + detector/face/plate/ocr/embedder/captioner/summarizer/segmenter/transcriber
├── services/       # video_service / yunzhi_job_service / format_service / export_service / report_service
├── config/         # config.yaml(gitignored) + config.yaml.example + presets.json(随 git 共享) + prompts.yaml
├── frontend/       # 服务器前端（Dashboard 主工作台 + 云智 Bridge）
├── frontend-desktop/# 桌面前端（4 页管理后台, 独立）
├── frontend-shared/ # 双前端共享对接层（api/types/labels/helpers, 一份实现）
├── desktop/        # 桌面端 pywebview 壳 + build_exe.ps1(打纯壳 exe)
├── deploy/         # setup_windows.ps1 / setup_linux.sh / build_backend_pyc.py / download_models.py
├── scripts/        # sweep_storage.py / bump_version.py / mock_yunzhi_platform.py
└── docs/           # arch.md(权威架构) / archive/(历史归档)
```

## Development Status

**当前状态（v0.37 候选，未发版）—— 智能参数系统**：

### 智能参数系统（核心改动）

**持久化推荐结果**：上传完成弹智能参数推荐弹窗（`SmartSuggestDialog`）→ `POST /videos/suggest-params` 计算场景分类 → **自动落库**到 `videos.suggested_scene_key / label / confidence / suggested_params(JSONB)`。关掉弹窗也不丢，下次打开视频详情直接回填。

**抽屉「参数设置」小面板**（替代旧 ParameterPanel）：网格 6 开关（物体检测/人脸/车牌/OCR/搜索/智能摘要）+ 智能推荐按钮。**点击即保存**（PATCH `/videos/{id}/toggles`，仅持久化不入队管道）+ 智能推荐按钮一键重置（自动关摘要）。摘要默认关闭（LLM 摘要耗时长且非核心）。

**ContentType 9 场景枚举**（`core/models.py`）：与 `services/smart_suggest.py` SCENE_CLASSES 一一对应 —— traffic/vehicle_focus/surveillance_people/indoor/portrait_focus/document/street_mixed/outdoor_landscape/chat_screen。每个场景对应一组检测/人脸/车牌/OCR 开关预设（全部摘要关）。

**批量解析弹窗**（替代旧 ParameterPanel）：2 选项单选卡片 —— 「按各视频已有设置处理」或「统一参数处理」。统一参数区用同一套 `AnalyzeSettingsPanel`（内容类型 + 6 开关），per-video 模式置灰禁用。

**Workbench 视频解析弹窗**：`SingleAnalyzeDialog`（460px 紧凑弹窗）替代原 ParameterPanel 模态框 —— pending 直接启动 / completed/failed 建新版本。

### 其他

- 后端 v0.34：OCR 定版 RapidOCR(PP-OCRv3 ONNX) + DirectML 独立子进程（DML 隔离零影响人脸/车牌 CUDA）+ 文本去重/顺序整理
- 桌面端重构（浅蓝 4 页管理后台 + frameless 窗口 + SplitPane 工作台 + 系统监控）+ 暗色主题
- 文件库/多版本解析/任务中心（版本行=一次解析、日志生命周期、耗时、批量解析、文件与素材重命名）
- 一键安装器+内嵌 PostgreSQL+后端字节码封装+部署/构建健壮性
- 设置档位感知（2b 自动套用轻量编码/量化默认 + 设置页档位徽标）+ 参数预设随 git 迁移

**里程碑摘要**：v0.37 智能参数系统 · v0.34 OCR 定版 · v0.33 摘要链路根治 · v0.32 全局任务队列 · v0.31 人脸搜索+跨视频穿透 · v0.29 人脸链路重构 · v0.28 云智嵌入 UI · v0.24 云智接入+生产部署 · 更早见 git log。

**Planned**：Grounding(Florence-2)。
