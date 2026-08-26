# Zhiying — Universal Video Analytics Engine

通用视频分析引擎：上传视频 → 声明式 DAG 管道（16 ops）→ 4 条编码路径 + YOLO11/BoT-SORT 检测跟踪 + 人脸/车牌/OCR 识别 → 8 路语义搜索 + 图搜 + 图片素材库（人脸/通用图搜分轨检索）。面向单 GPU（8–32GB）设计，已接入云智平台，生产部署于 10.0.0.176。

## Quick Start

```bash
docker compose up -d db                        # 可选：预起数据库（python run.py 会自动自举）
set DASHSCOPE_API_KEY=sk-xxx                   # 设置 API key（vlm_llm 摘要模式）
python run.py                                  # 启动后端（默认 8011；DB 自举：端口已通→复用 / 内嵌 vendor/pg / docker 回退）
cd frontend && npm install && npm run dev       # 启动前端开发服务器
curl -X POST -F "file=@demo.mp4" http://localhost:8011/api/v1/videos/upload  # 上传视频
```

> API key 放项目根 `.env`（gitignored）。**Windows 桌面端**：双击 `install1.bat` 一键部署（选 2B/8B + 代理，内嵌 PostgreSQL，WebView2 Runtime 自动更新）；`install2.bat` 日常更新。

## Core Features

| Feature | Endpoint | Status |
|---|---|---|
| 上传/批量上传/参数与管道触发 | `POST /videos/upload` + `/upload/batch` + `PUT /videos/{id}/params` | ✅ |
| **智能参数系统** | `POST /videos/suggest-params` 自动持久化场景推荐 + `PATCH /videos/{id}/toggles` 抽屉轻量持久化 + 抽屉「参数设置」小面板 + 批量解析弹窗（按各视频/统一参数 二选一） | ✅ |
| 视频详情/状态/播放(stream)/场景缩略图 | `GET /videos/{id}` · `/status` · `/stream` · `/thumbnail/{scene}` · `/metadata` · `/proxy-status` | ✅ |
| 多格式支持 | remux(-c copy) + 惰性 H.264 proxy(NVENC) + smart routing | ✅ |
| 语义搜索（frame/chunk/text/label/track/plate/ocr 7 路） | `POST /search/semantic` | ✅ |
| **搜索结果智能筛选推荐** | `POST /search/suggest-filter` 事件/动作类→画面定位、单物体类→物体定位，手动选择优先 | ✅ |
| 人脸识别（SCRFD + ArcFace 512d 聚类, 双锚检索；检测栏按主 person track 显示出现段 + 自动跳播 + 当前段高亮） | `GET /videos/{id}/face/data` · `POST /search/face` | ✅ |
| 车牌识别（HyperLPR3） | `GET /videos/{id}/plate/data` + 模糊搜索 | ✅ |
| OCR 画面文字提取（RapidOCR PP-OCRv3 + DirectML, 独立子进程） | `GET /videos/{id}/ocr/data` · `POST /search/semantic` (search_types=["ocr"]) | ✅ |
| 通用图搜（Qwen3-VL-Embedding → frame_embeddings） | `POST /search/image` | ✅ |
| 导出（clip/frames/track/thumbnails zip） | `GET/POST /videos/{id}/export/...` | ✅ |
| 系统设置+参数预设（运行时生效, 预设随 git 迁移） | `GET/PUT /settings` + `/settings/presets` | ✅ |
| 文件库/多版本/任务中心/批量解析/重命名/任务删除(仅失败,隐藏) | `/files` `/groups` `/tasks` `/analyze-batch` · `DELETE /tasks/{id}` | ✅ |
| 案例素材管理（图片拖拽上传/预览/删除） | `GET/POST /groups/{id}/assets` · `/assets/{id}/file` · `DELETE /assets/{id}` | ✅ |
| 任务报告导出（Markdown 聚合产物统计） | `GET /tasks/{id}/report` · `POST /tasks/export-batch` | ✅ |
| 存储卫生 | 删除即清盘 + 孤儿清扫（`POST /maintenance/sweep`）+ 存储用量（`GET /maintenance/storage`） | ✅ |
| 云智平台集成 | `register-external` + `/internal/yunzhi/jobs`（202 异步+回调+幂等） | ✅ |
| 桌面端启动器+独立桌面前端 | pywebview 壳 + 5 页管理后台（文件库/视频解析/素材库/任务中心/系统设置） | ✅ |
| **图片素材库**（v0.6） | 关注目标（人/其他）底库照片管理 + 人脸/通用图搜分轨检索 + 检测/图搜沉淀 + 案例库转存 | ✅ |
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
- **⚠️ 后端 + 服务器前端（`frontend/` + `frontend-shared/`）任何改动都必须 `./bump`**；仅纯文档/注释/桌面前端（`frontend-desktop/`）不需 bump
- **部署**：服务器 `bash deploy.sh v<tag>`（fetch→config 迁移→checkout→requirements 变化才 pip→前端 build→restart→90s 健康检查）

## Project Structure

```
zhiying/
├── bump / install1.bat / install2.bat   # 发版启动器 / 新机一键部署 / 桌面端一键更新
├── run.py / main.py / backend_launcher.py
├── api/            # 路由: video/search/settings/tasks/groups/detection/face/plate/ocr/export/maintenance/yunzhi/subjects
├── core/           # models(19表)/schemas/repository/search/db/config_loader/settings_service/presets_service
│                   #   storage_manager/gpu_lock/cancellation/embedding_profile/paths/version/pipeline_queue
├── pipeline/       # engine(DAG 执行器) / operations(16 op) / runners/(20 runner) / search_engine
├── plugins/        # factory + detector/face/plate/ocr/embedder/captioner/summarizer/segmenter/transcriber
├── services/       # video_service / yunzhi_job_service / format_service / export_service / report_service / smart_suggest
├── config/         # config.yaml(gitignored) + config.yaml.example + presets.json(随 git 共享) + prompts.yaml
├── frontend/       # 服务器前端（Dashboard 主工作台 + 云智 Bridge）
├── frontend-desktop/# 桌面前端（5 页管理后台, 独立）
├── frontend-shared/ # 双前端共享对接层（api/types/labels/helpers, 一份实现）
├── desktop/        # 桌面端 pywebview 壳 + build_exe.ps1(打纯壳 exe)
├── deploy/         # setup_windows.ps1 / setup_linux.sh / build_backend_pyc.py / download_models.py
├── scripts/        # sweep_storage.py / bump_version.py / mock_yunzhi_platform.py
└── docs/           # arch.md(权威架构) / archive/(历史归档)
```

## Development Status

**当前状态（v0.6）**：图片素材库 + 搜索统一 + 摘要/文字识别 UI 重构

- **图片素材库**（v0.6 核心）：`image_subjects` / `subject_photos` / `subject_photo_embedding` 三表 + 15 个 `/subjects` API + 桌面端第 5 页 `ImageLibrary`（左列表+右详情+裁剪+拖拽扩充）+ `SubjectPhotoPicker`（全局搜索/视频搜索卡统一选图来源）+ `AddSubjectDrawer`（检测/图搜一键沉淀）；检索分轨：person→ArcFace 512 / other→Qwen3-VL
- **搜索统一**：退役 `CaseAssetPicker`（案例图片选图），所有图搜/人脸搜入口统一走素材库 `SubjectPhotoPicker`；全局搜索关键词/人脸/图搜自动同步到视频搜索卡片
- **摘要/文字识别 UI**：`VideoSummaryCard` 标题随内容自动切换（视频摘要/文字识别），无 tab 按钮；去掉 `minor-card` 嵌套容器
- **caption-summary 联动**：开摘要自动开画面描述（后端校验 caption OFF → summary OFF）
- **视频搜索卡优化**：退役范围下拉，严格限定当前视频检索（与全局搜索划清边界）+ 结果类型筛选下拉（全部/画面定位/物体定位）+ 搜索框固定不随结果滚动 + 搜索结果时间范围自动暂停
- **视频搜索卡智能筛选推荐**：`POST /search/suggest-filter` 文本相似度预判——事件/动作/语义类（求婚、打架、两车相撞…）自动画面定位；单物体类（黑色车辆、戴口罩的人…）自动物体定位；手动选择优先，不打扰
- **全局搜索类型互斥**：人/车/车牌/文本 chip 选中互斥，切换自动清除前一个
- **智能参数系统**（v0.37）：持久化推荐 + 抽屉轻量面板 + AnalyzeSettingsPanel 三处共用 + 摘要默认全关
- **人脸出现段修复**（v0.6.1）：检测栏人脸出现段 = 该身份的主 person track 的 `[first_seen, last_seen]`（时间轴同源 `track_to_identity`），排除搭车长 track；点击人脸搜索结果/时间列表自动从头播放并逐段跳过，当前播放段黄色高亮（字样标黑）
- **任务中心删除**：`DELETE /tasks/{id}` 仅允许删除失败任务（清 `pipeline_tasks`/`task_logs`，`videos.task_hidden=true` 隐藏，不删视频/文件）；列表过滤 `task_hidden`，失败任务显示百分比
- **弹窗/抽屉 portal 修复**：桌面前端所有弹窗/抽屉统一 `createPortal(document.body)` + `onMouseDown` 遮罩关闭 + `DetectionOverlay` 用真实事件目标 containment 判定（杜绝穿透点击/遮挡关不掉）
- **案例素材管理**：`case_assets` 表 + 案例库拖拽上传图片素材（图片上传已退役，仅保留视频）
- **Planned**：Grounding(Florence-2)。
