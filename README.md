# Zhiying · 智影 — Universal Video Analytics Engine

**English** | Zhiying is a GPU-powered video analytics & semantic search engine: upload videos, run a declarative 16-op DAG pipeline (YOLO11 detection + BoT-SORT multi-object tracking with two-stage ReID, face recognition, license plate recognition, OCR, video captioning & summarization), then search everything — 8-way semantic retrieval (frames / chunks / captions / labels / tracks / plates / OCR text / events), image-to-video search, and a watchlist (subject) library with face / appearance split-track matching. Built on FastAPI + PostgreSQL/pgvector, designed for a single consumer GPU (8–32 GB).

**中文** | 智影是一个 GPU 视频分析与语义搜索引擎：上传视频后执行声明式 DAG 管道（16 ops）——YOLO11 目标检测 + BoT-SORT 多目标跟踪（双层 ReID）、人脸识别、车牌识别、画面 OCR、视频描述与摘要——然后对全库进行 8 路语义搜索（画面/片段/文本/标签/物体轨迹/车牌/画面文字/事件）+ 以图搜视频 + 图片素材库（人脸/外观分轨检索）。后端 FastAPI + PostgreSQL/pgvector，面向单张消费级 GPU（8–32GB）设计。

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL_17-4169E1?logo=postgresql&logoColor=white">
  <img alt="pgvector" src="https://img.shields.io/badge/pgvector-semantic_search-4169E1">
  <img alt="PyTorch" src="https://img.shields.io/badge/PyTorch-CUDA-EE4C2C?logo=pytorch&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React_19-61DAFB?logo=react&logoColor=black">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-0078D6?logo=windows11&logoColor=white">
  <img alt="Linux" src="https://img.shields.io/badge/Linux-FCC624?logo=linux&logoColor=black">
</p>

<!-- TODO: 产品截图（工作台 / 搜索结果 / 素材库） -->

## ✨ 核心能力 | Core Features

- **视频结构化管道**：声明式 DAG（16 ops）异步执行——时长探测 → 场景切分 → 关键帧 → 检测/跟踪 → 人脸/车牌/OCR → 描述/摘要 → 多路向量编码，全局任务队列持久化、断电重启自动恢复
- **检测与跟踪**：YOLO11 + BoT-SORT（在线 with_reid + 全局 tracklet 缝合双层 ReID），轨迹级向量入库，支持"物体定位"检索
- **人脸识别**：SCRFD 检测 + ArcFace 512 维聚类（护栏式双阈值），人脸出现段时间轴、按段跳播、当前段高亮
- **车牌 / OCR**：HyperLPR3 车牌识别（模糊搜索）；RapidOCR PP-OCRv3 画面文字提取（DirectML 独立子进程，第 8 路精确检索）
- **8 路语义搜索 + 图搜**：query 一次编码、7 路并行召回合并去重；Qwen3-VL-Embedding 支持以图搜视频
- **智能参数系统**：9 场景自动分类推荐解析参数；4 级参数层次（场景/模块/开关/高级）+ 参数预设随仓库共享
- **图片素材库**：关注目标（人/其他）底库管理；person 走 ArcFace / other 走 Qwen3-VL 分轨检索；检测结果/图搜结果一键沉淀入库
- **多格式与硬件适配**：remux(-c copy) + 按需 NVENC H.264 proxy；NVDEC 单流解码共享；全局 GPU 锁防驱动故障；模型档位 8B(4096 维)/2B(2048 维) 按显存自动适配
- **Windows 桌面端 + 安装器**：pywebview 壳 + 5 页管理后台；Inno Setup 一体化安装（环境 + 内嵌 PostgreSQL + 模型，装完即用），首启断点续传兜底
- **Web 前端**：React 19 + Vite + Tailwind 4，轻量解析工作台（案例库网格 + 解析详情 + 搜索面板）

## 🚀 Quick Start

```bash
# 1. 数据库（可选预起；python run.py 会自动自举：复用已有实例 → 内嵌 PostgreSQL → docker 回退）
docker compose up -d db

# 2. 配置 API key（摘要/描述用，放根目录 .env，gitignored）
set DASHSCOPE_API_KEY=sk-xxx

# 3. 启动后端（默认 8011）
python run.py

# 4. 启动 Web 前端开发服务器
cd frontend-web && npm install && npm run dev

# 5. 上传一个视频试试
curl -X POST -F "file=@demo.mp4" http://localhost:8011/api/v1/videos/upload
```

> 模型与依赖见 `deploy/`（Windows 一键环境脚本 `setup_windows.ps1`）；架构细节见 [`docs/arch.md`](docs/arch.md)。

## 🏗️ Architecture

```
Upload → Probe → Pipeline (DAG, 16 ops) → DB → Search → Frontend
  ├─ duration → segmentation → keyframes → caption/summary (VLM API)
  │                                    └→ frame/text/chunk embedding (4 编码路径)
  ├─ duration → detection (YOLO11, 共享 NVDEC) → track_encode (BoT-SORT + ReID)
  │                                    ├→ face (SCRFD + ArcFace 512d)
  │                                    └→ plate (HyperLPR3)
  ├─ duration → ocr (RapidOCR, DirectML 独立子进程) → ocr_detections
  └─ Shared GPU models（共享单实例 + 全局 GPU 串行锁）

Search: query → 1 次文本编码 → 7 路并行召回（frame/chunk/text/label/track/plate/ocr）
        + 人脸图搜（ArcFace 双锚）+ 通用图搜（Qwen3-VL）→ 合并去重 → 统一 confidence
```

## 🧰 Tech Stack

| Component | Technology |
|---|---|
| Backend | FastAPI (Python 3.13) + SQLAlchemy async + PostgreSQL 17 + pgvector |
| Frontend | React 19 + TypeScript + Vite 6 + Tailwind CSS 4 |
| Video Embedding | Qwen3-VL-Embedding 8B/2B（本地 GPU，可选 bitsandbytes 量化） |
| Detection/Tracking | YOLO11 + BoT-SORT（双层 ReID） |
| Face/Plate | InsightFace SCRFD + ArcFace R50 · HyperLPR3 |
| Caption/Summary | Qwen-VL-Max + DeepSeek（VLM API 模式） |
| OCR | RapidOCR PP-OCRv3 ONNX + DirectML 子进程 |
| Video I/O | FFmpeg（asyncio subprocess，NVDEC/NVENC） |
| Desktop | pywebview + 内嵌便携 PostgreSQL + Inno Setup 6 |

## 📁 Project Structure

```
zhiying/
├── api/             # FastAPI 路由（video/search/settings/tasks/groups/subjects/...）
├── core/            # models(19 表)/repository/search_engine/db/config/gpu_lock/pipeline_queue
├── pipeline/        # DAG engine + operations(16) + runners(20) + search_engine
├── plugins/         # detector/face/plate/ocr/embedder/captioner/summarizer/segmenter（config 驱动可换后端）
├── services/        # video_service / format_service / export_service / smart_suggest / ...
├── frontend-web/    # 新 Web 前端（轻量解析工作台）
├── frontend-desktop/# 桌面前端（5 页管理后台）
├── frontend-shared/ # 多端共享对接层（api/types/labels，一份实现）
├── desktop/         # pywebview 壳 + 构建/打包脚本 + 首启模型引导
├── deploy/          # Windows/Linux 环境脚本 + 模型下载 + backend_pyc 构建
└── docs/arch.md     # 权威架构文档
```

## 📌 Status

核心链路（上传 → 解析 → 检索 → 导出）全部可用，已在生产环境稳定运行。已知边界：Chunk 编码默认关 · Grounding（Florence-2 占位）· 素材库告警红点（前端空壳预留）。

> 变更历史查 git log；权威架构与设计决策详见 [`docs/arch.md`](docs/arch.md)。
