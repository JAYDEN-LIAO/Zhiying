# Cerno — 通用视频分析引擎

一个通用的视频分析引擎，支持语义搜索和结构化摘要生成。专为单 GPU（8–32 GB 显存）环境设计。

## 快速开始

```bash
# 1. 启动数据库
docker-compose up -d db

# 2. 设置 API Key
set DASHSCOPE_API_KEY=sk-xxx   # Qwen-VL 画面描述
set DEEPSEEK_API_KEY=sk-xxx    # 摘要生成

# 3. 启动服务
uvicorn main:app --reload

# 4. 上传视频
curl -X POST -F "file=@demo.mp4" http://localhost:8000/api/v1/videos/upload

# 5. 查看摘要
curl http://localhost:8000/api/v1/videos/{video_id}

# 6. 语义搜索
curl -X POST -H "Content-Type: application/json" \
  -d '{"query":"一个男人从黑色轿车里走出来"}' \
  http://localhost:8000/api/v1/search/semantic
```

> **API Key 说明**：将密钥写入项目根目录的 `.env` 文件中（已被 gitignore）。  
> 详见 `config.yaml` 和 `core/config_loader.py`。

## 核心功能

| 功能 | 端点 | 状态 |
|---|---|---|
| 视频上传与处理 | `POST /api/v1/videos/upload` | ✅ |
| 视频详情与摘要 | `GET /api/v1/videos/{id}` | ✅ |
| 处理进度查询 | `GET /api/v1/videos/{id}/status` | ✅ |
| 语义搜索 | `POST /api/v1/search/semantic` | ✅ |
| 全文检索 | `GET /api/v1/search/text?q=...` | ✅ |
| 混合检索（向量+文本） | `POST /api/v1/search/hybrid` | ✅ |

## 架构概览

```
上传 → Pipeline → 数据库 → 搜索
       ├─ 质检 + 镜头分割
       ├─ VLM 画面描述（API）
       ├─ 向量编码（本地 GPU，2048 维）
       └─ LLM 摘要生成（API）
```

- **五阶段 Pipeline**，由 `PipelineEngine` 编排
- **9 个抽象插件接口**，工厂模式动态加载
- **PostgreSQL + pgvector** 向量存储与相似度搜索
- **配置驱动**：切换模型或 API 提供商只需改 `config.yaml`

## 技术栈

| 组件 | 技术选型 |
|---|---|
| 框架 | FastAPI (Python 3.12) |
| 数据库 | PostgreSQL 17 + pgvector 0.8 |
| 向量编码 | Qwen3-VL-Embedding-2B（本地 GPU） |
| 画面描述 | Qwen-VL-Max（DashScope API） |
| 摘要生成 | DeepSeek Chat（API） |
| 镜头分割 | 固定间隔（基于时长） |
| 视频处理 | FFmpeg（asyncio 子进程） |

## 项目结构

```
cerno/
├── main.py               # FastAPI 入口
├── api/                  # 路由定义
├── core/                 # 数据库模型、数据校验、搜索、配置
├── pipeline/             # Pipeline 编排器 + 各阶段
├── plugins/              # 插件实现 + 工厂
├── services/             # 业务逻辑层
├── utils/                # FFmpeg 工具
├── config/               # YAML 配置、提示词模板
└── docs/                 # 设计文档
```

## 开发状态

- **Demo 就绪**：视频摘要与语义搜索已在 4060 8GB 上验证通过
- **P0 完成**：Pipeline 核心、搜索引擎、API 路由
- **规划中**：物体检测（YOLO）、OCR、动态 Grounding、音频转录、导出 API
