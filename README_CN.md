# Cerno — 通用视频分析引擎

一个通用的视频分析引擎，支持语义搜索和结构化摘要生成。专为单 GPU（8–32 GB 显存）环境设计。

## 快速开始

```bash
# 1. 启动数据库
docker-compose up -d db

# 2. 设置 API Key
set DASHSCOPE_API_KEY=sk-xxx   # Qwen-VL 画面描述
set DEEPSEEK_API_KEY=sk-xxx    # 摘要生成

# 3. 启动后端服务
uvicorn main:app --reload

# 4. (新窗口) 启动前端开发服务器
cd frontend && npm install && npm run dev

# 5. 上传视频
curl -X POST -F "file=@demo.mp4" http://localhost:8000/api/v1/videos/upload

# 6. 查看摘要
curl http://localhost:8000/api/v1/videos/{video_id}

# 7. 语义搜索
curl -X POST -H "Content-Type: application/json" \
  -d '{"query":"一个男人从黑色轿车里走出来"}' \
  http://localhost:8000/api/v1/search/semantic
```

> **API Key 说明**：将密钥写入项目根目录的 `.env` 文件中（已被 gitignore）。  
> 详见 `core/config_loader.py`。

## 核心功能

| 功能 | 端点 | 状态 |
|---|---|---|
| 视频上传与处理 | `POST /api/v1/videos/upload` | ✅ |
| 视频详情与摘要 | `GET /api/v1/videos/{id}` | ✅ |
| 处理进度查询 | `GET /api/v1/videos/{id}/status` | ✅ |
| 视频流式播放 | `GET /api/v1/videos/{id}/stream` | ✅ |
| 场景缩略图 | `GET /api/v1/videos/{id}/thumbnail/{scene_index}` | ✅ |
| 视频列表 | `GET /api/v1/videos/` | ✅ |
| 删除视频 | `DELETE /api/v1/videos/{id}` | ✅ |
| 语义搜索（四路召回） | `POST /api/v1/search/semantic` | ✅ |
| 全文检索 | `GET /api/v1/search/text?q=...` | ✅ |
| 混合检索（向量+文本） | `POST /api/v1/search/hybrid` | ✅ |
| 前端工作台 | React 19 + Vite + Tailwind CSS 4 | ✅ |

## 架构概览

```
上传 → Pipeline → 数据库 → 搜索 → 前端
       ├─ 质检 + 镜头分割 (TransNetV2)
       ├─ 关键帧抽取 @1fps (FFmpeg pipe → 内存)
       ├─ VLM 画面描述（API）
       ├─ 向量编码 — 三条链路：
       │    ├─ 帧级：encode_image（1fps，逐帧精确编码）
       │    ├─ 窗口级：encode_video（滑动窗口，过程语义）
       │    └─ 文本级：encode_text(caption)（语义匹配）
       └─ LLM 摘要生成（API）
```

- **五阶段 Pipeline**，由 `PipelineEngine` 编排，含三条帧/窗口/文本编码链路
- **9 个抽象插件接口**，工厂模式动态加载
- **PostgreSQL + pgvector**，5 张表：videos、scenes、transcripts、frame_embeddings、chunks
- **四路并行搜索**：帧级（1fps 精确定位）+ 窗口级（过程语义）+ 文本级（caption 语义）+ 标签级（JSONB 精确匹配）
- **配置驱动**：切换模型或 API 提供商只需改 `config.yaml`
- **React 前端**：视频播放器、六段 Pipeline 进度条、语义搜索面板（缩略图 + 精度标识）

## 技术栈

| 组件 | 技术选型 |
|---|---|
| 后端框架 | FastAPI (Python 3.12) |
| 前端框架 | React 19 + TypeScript |
| 构建工具 | Vite 6 |
| CSS | Tailwind CSS 4 |
| 数据库 | PostgreSQL 17 + pgvector 0.8 |
| 向量编码 | Qwen3-VL-Embedding-2B（本地 GPU） |
| 画面描述 | Qwen-VL-Max（DashScope API） |
| 摘要生成 | DeepSeek Chat（API） |
| 镜头分割 | TransNetV2 / 固定间隔（基于时长） |
| 语音转录 | faster-whisper（插件就绪，按需开启） |
| 视频处理 | FFmpeg（asyncio 子进程） |

## 项目结构

```
cerno/
├── main.py               # FastAPI 入口
├── api/                  # 路由定义
│   ├── router.py         # 路由总装（从 routes.py 导出）
│   ├── routes.py         # 所有 API 端点（视频管理/搜索/上传）
│   ├── deps.py           # FastAPI 依赖注入（DB session）
│   ├── video_routes.py   # （骨架）未来视频路由拆分
│   ├── search_routes.py  # （骨架）未来搜索路由拆分
│   ├── export_routes.py  # （骨架）计划中的导出端点
│   └── maintenance_routes.py  # （骨架）计划中的健康/重建索引端点
├── core/                 # 数据库模型、数据校验、搜索、配置
│   ├── db.py             # 异步引擎、init_db()、触发器、增量迁移
│   ├── models.py         # ORM: Video、Scene、Transcript、FrameEmbedding、Chunk
│   ├── schemas.py        # Pydantic DTO + JSONB 校验
│   ├── repository.py     # 数据访问层 + bulk_insert_frames/chunks
│   ├── search.py         # 7 种检索函数：vector/fulltext/hybrid/fuzzy/frame/chunk/text
│   ├── interfaces.py     # 9 个抽象插件接口
│   ├── config_loader.py  # YAML + .env 加载，环境变量覆写
│   ├── prompt_loader.py  # Prompt 模板加载器
│   ├── status_tracker.py # Pipeline 进度持久化
│   └── exceptions.py     # 自定义异常
├── config/               # 配置
│   ├── config.yaml       # 主配置（server/db/storage/plugins/pipeline）
│   ├── config_schema.py  # Pydantic 配置校验
│   └── prompts.yaml      # Caption/Summarizer/Grounding 提示词模板
├── pipeline/             # Pipeline 编排器 + 各阶段
│   ├── engine.py         # 五阶段 PipelineEngine + 三条编码链路
│   ├── phase1_qc.py      # 质检 + 分割
│   ├── phase3_alignment.py
│   ├── phase4_caption.py # 画面描述 + 向量编码
│   ├── phase5_summary.py # LLM 摘要生成
│   └── search_engine.py  # 四路并行召回 + 按 scene 合并去重
├── plugins/              # 插件实现 + 工厂
│   ├── factory.py        # 动态插件加载器
│   ├── captioner/        # Qwen API 画面描述 + 本地 VL 画面描述
│   ├── embedder/         # Qwen3-VL-Embedding（本地 GPU）
│   ├── summarizer/       # DeepSeek API
│   ├── segmenter/        # TransNetV2 / 固定间隔
│   ├── transcriber/      # faster-whisper
│   ├── qc/               # FFmpeg 质检
│   ├── detector/         # （骨架）YOLO
│   ├── ocr/              # （骨架）PaddleOCR
│   └── grounding/        # （骨架）Florence-2
├── services/             # 业务逻辑层
│   ├── video_service.py  # 视频处理编排
│   └── export_service.py # （骨架）导出逻辑
├── utils/                # FFmpeg 工具、视频工具
├── frontend/             # React + Vite + Tailwind 工作台
│   ├── src/
│   │   ├── Dashboard.tsx # 主工作台（所有组件内联在同一文件）
│   │   ├── services/api.ts
│   │   ├── types/index.ts
│   │   ├── mockData.ts   # Pipeline 阶段定义
│   │   └── components/   # 子组件（AnalysisPanel、HistoryList 等）
│   ├── package.json
│   └── vite.config.ts
├── models/               # 本地模型权重（gitignored）
├── data/                 # 视频存储 & 处理产物（gitignored）
├── tests/                # 测试套件（30+ 测试文件）
└── docs/                 # 设计文档 + 搜索架构文档
```

## 开发状态

- **v0.5 — 功能完整**：视频摘要、四路语义搜索、帧/窗口/文本编码已在 4060 8GB 上验证通过
- **P0 完成**：Pipeline 核心、搜索引擎（7 种检索函数）、11 个 API 端点、前端工作台
- **规划中**：物体检测（YOLO）、OCR（PaddleOCR）、Grounding（Florence-2）、导出 API（clip/JSON/Markdown）
