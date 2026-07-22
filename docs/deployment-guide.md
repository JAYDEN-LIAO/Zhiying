# Cerno 部署移植手册

> 适用场景：将 Cerno v0.10 部署到新机器（无 GPU / 有 GPU 两种场景）
> 目标系统：Linux (Ubuntu 22.04+ / Debian 12+)，Python 3.12

---

## 目录

1. [前置检查](#1-前置检查)
2. [环境准备](#2-环境准备)
3. [数据库配置](#3-数据库配置)
4. [后端部署](#4-后端部署)
5. [前端部署](#5-前端部署)
6. [模型权重](#6-模型权重)
7. [配置与环境变量](#7-配置与环境变量)
8. [启动验证](#8-启动验证)
9. [Docker 部署](#9-docker-部署)
10. [常见问题](#10-常见问题)

---

## 1. 前置检查

### 1.1 硬件最低要求

| 组件 | 有 GPU（推荐） | 纯 CPU（降级） |
|---|---|---|
| GPU | NVIDIA GeForce RTX 4060 8GB+ | 不需要 |
| VRAM | ≥8 GB（caption+embedding 同时加载约 6-7 GB） | N/A |
| 系统 RAM | ≥16 GB | ≥32 GB |
| 磁盘 | ≥50 GB（含模型权重约 20 GB） | ≥30 GB |
| CUDA | 12.1+ (`nvidia-smi` 确认) + `nvcc` | N/A |

### 1.2 系统包依赖

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y \
    ffmpeg \
    gcc \
    libpq-dev \
    curl \
    libgl1-mesa-glx \
    libglib2.0-0 \
    postgresql-client

# 仅 GPU 场景
sudo apt install -y nvidia-driver-535  # 或对应版本
```

### 1.3 确认 Python

```bash
python3 --version   # 需要 >= 3.10，推荐 3.12
pip3 --version
```

---

## 2. 环境准备

### 2.1 获取代码

```bash
git clone <仓库地址> cerno
cd cerno
```

### 2.2 清理部署残留

参考 [cleanup-checklist.md](cleanup-checklist.md) 清理不必要的文件。

必做：
```bash
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
rm -rf frontend/node_modules
rm -rf data/videos data/artifacts   # 如不需要旧数据
```

### 2.3 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2.4 安装 Python 依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt

# ⚠️ requirements.txt 中缺失但实际需要的包：
pip install opencv-python-headless  # 不含 GUI 的 OpenCV，部署推荐
# 如果使用 TransNetV2 分割器：
pip install transnetv2
# 如果使用 faster-whisper 转录：
pip install faster-whisper
```

---

## 3. 数据库配置

### 3.1 启动 PostgreSQL（二选一）

**选项 A：Docker 容器（推荐）**

```bash
docker compose up -d db
```

或者单独启动：

```bash
docker run -d \
  --name cerno_postgres \
  -e POSTGRES_USER=cerno \
  -e POSTGRES_PASSWORD=cerno \
  -e POSTGRES_DB=cerno \
  -p 5432:5432 \
  pgvector/pgvector:pg17
```

**选项 B：裸机安装 PostgreSQL + pgvector**

```bash
# 安装 PostgreSQL 17
sudo apt install -y postgresql-17 postgresql-17-pgvector

# 创建数据库和用户
sudo -u postgres psql -c "CREATE USER cerno WITH PASSWORD 'cerno';"
sudo -u postgres psql -c "CREATE DATABASE cerno OWNER cerno;"
sudo -u postgres psql -d cerno -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo -u postgres psql -d cerno -c "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";"
sudo -u postgres psql -d cerno -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### 3.2 数据库自动建表

Cerno 使用 `init_db()` 自动建表+增量迁移，无需手动执行 SQL：

```bash
# 首次启动服务时自动执行
uvicorn main:app --host 0.0.0.0 --port 8000
```

启动日志中应看到：
```
[DB] Database tables initialized/verified
```

> 注意：如果表已存在，`init_db()` 不会重建，只会执行增量 ALTER TABLE 补充缺失列。

---

## 4. 后端部署

### 4.1 配置数据库连接

**方式 1：环境变量（推荐）**

```bash
export POSTGRES_URI="postgresql+asyncpg://cerno:cerno@localhost:5432/cerno"
```

**方式 2：修改 `config/config.yaml`**

```yaml
database:
  uri: "postgresql+asyncpg://cerno:cerno@localhost:5432/cerno"
```

> 环境变量优先于配置文件。

### 4.2 配置 API Keys

```bash
# 创建 .env 文件（从模板或手动）
cat > .env << 'EOF'
DASHSCOPE_API_KEY=sk-xxx   # Qwen-VL-Max API（vlm_llm caption 模式）
DEEPSEEK_API_KEY=sk-xxx    # DeepSeek API（vlm_llm summary 模式）
EOF
```

> 默认 `native_video` 模式不使用 API Key，仅本地 GPU 推理。
> 如需使用 `vlm_llm` 模式（API 驱动），则必须配置对应 Key。

### 4.3 启动服务

```bash
# 生产方式（推荐）
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1

# 开发方式（热重载）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

> ⚠️ 首次启动时会加载模型（Embedder + Captioner），耗时 10-30 秒。日志中出现 `Application startup complete` 即就绪。

---

## 5. 前端部署

### 5.1 方式一：使用预构建产物（推荐）

```bash
# 检查是否有预构建的 dist/
ls frontend/dist/

# 如果不存在，本地构建
cd frontend
npm install
npm run build
cd ..
```

### 5.2 方式二：开发服务器（仅开发场景）

```bash
cd frontend
npm install
npm run dev
# 默认在 localhost:5173 启动，/api 代理到 localhost:8000
```

### 5.3 配置后端地址

前端通过 Vite 代理 `/api` 到后端。如需更改后端地址，编辑 `frontend/vite.config.ts`：

```typescript
server: {
  proxy: {
    '/api': 'http://localhost:8000'  // 改为实际后端地址
  }
}
```

---

## 6. 模型权重

### 6.1 所需模型清单

| 模型 | 文件 | 大小 | 下载源 | 必需？ |
|---|---|---|---|---|
| YOLO11s | `models/yolo26s.pt` | ~20 MB | ultralytics 自动下载 | ✅ detection 模式必需 |
| Qwen2.5-VL-7B | `models/models/Qwen--Qwen2.5-VL-7B-Instruct/` | ~15 GB | ModelScope / HuggingFace | ✅ caption 模式必需 |
| Qwen3-VL-Embedding-2B | `models/models/Qwen--Qwen3-VL-Embedding-2B/` | ~4 GB | ModelScope / HuggingFace | ✅ 搜索索引必需 |
| TransNetV2 | pip 包 | ~200 MB | pip install transnetv2 | ✅ 分割器必需 |

### 6.2 模型获取方式

**方式 A：从原机器拷贝（最省时）**

```bash
# 在原机器上打包模型
tar czf models.tar.gz models/models/
# 传输到目标机器，解压到 models/ 下
tar xzf models.tar.gz -C models/
```

**方式 B：首次启动自动下载**

Cerno 内部使用 `modelscope` 和 `ultralytics` 自动下载模型到 `models/` 目录。首次启动时日志会显示下载进度。根据网络情况可能需要 30-120 分钟。

### 6.3 模型存储路径

```
cerno/
  models/
    yolo26s.pt                      # YOLO 检测模型
    models/                          # ModelScope 缓存目录
      Qwen--Qwen2.5-VL-7B-Instruct/
      Qwen--Qwen3-VL-Embedding-2B/
```

> `models/` 已在 `.gitignore` 中，不会被 git 追踪。
> 部署时需确保目标机器上有完整模型文件，或可自动下载。

---

## 7. 配置与环境变量

### 7.1 关键配置总览

| 配置项 | 默认值 | 环境变量覆盖 | 说明 |
|---|---|---|---|
| 数据库 URI | `postgresql+asyncpg://cerno:cerno@localhost:5432/cerno` | `POSTGRES_URI` | 数据库连接字符串 |
| DashScope API Key | 无（默认 null） | `DASHSCOPE_API_KEY` | vlm_llm caption 模式 |
| DeepSeek API Key | 无（默认 null） | `DEEPSEEK_API_KEY` | vlm_llm summary 模式 |
| 检测帧率 | 15 fps | `config.yaml plugins.detector.params.detection_fps` | — |
| Chunk 编码 | false | `config.yaml pipeline.chunk_encoding` | 默认关闭 |

### 7.2 配置优先级

```
环境变量 POSTGRES_URI > config.yaml database.uri
环境变量 DASHSCOPE_API_KEY > .env 文件 > config.yaml placeholder
```

### 7.3 端口说明

| 服务 | 默认端口 | 说明 |
|---|---|---|
| FastAPI 后端 | 8000 | 主 API 服务 |
| PostgreSQL | 5432 | 数据库 |
| Vite 前端开发 | 5173 | 仅开发模式 |

---

## 8. 启动验证

### 8.1 健康检查

```bash
# 后端是否响应
curl http://localhost:8000/api/v1/videos/

# 预期：{"code": 0, "message": "ok", "data": [...]}
```

### 8.2 完整流程验证

```bash
# 1. 上传视频
curl -X POST -F "file=@test.mp4" http://localhost:8000/api/v1/videos/upload

# 2. 配置参数并启动 Pipeline
curl -X PUT http://localhost:8000/api/v1/videos/<video_id>/params \
  -H "Content-Type: application/json" \
  -d '{"content_type": "general", "vision_enabled": true, "search_index_enabled": true}'

# 3. 等待处理完成（轮询状态）
curl http://localhost:8000/api/v1/videos/<video_id>/status

# 4. 搜索测试
curl -X POST http://localhost:8000/api/v1/search/semantic \
  -H "Content-Type: application/json" \
  -d '{"query": "测试", "search_types": ["frame", "text", "track"]}'
```

### 8.3 日志监控

```bash
# 启动时日志应包含：
# [Config] Config loaded
# [DB] Database tables initialized/verified
# [PluginFactory] Loading embedder: qwen3_vl_embedding
# [YoloDetector] Loading model: models/yolo26s.pt
# Application startup complete
```

---

## 9. Docker 部署

### 9.1 构建前准备

创建 `.dockerignore`：

```bash
cat > .dockerignore << 'EOF'
.git/
.gitignore
.venv/
__pycache__/
*.py[cod]
data/
frontend/node_modules/
docs/
tests/
.DS_Store
.env
EOF
```

### 9.2 构建镜像

```bash
# 模型文件需手动放到 models/ 目录下
docker compose build

# 或单独构建
docker build -t cerno-app .
```

### 9.3 启动服务

```bash
# 启动全部（数据库 + 应用）
docker compose up -d

# 仅启动应用（连接外部数据库）
docker compose up -d app
```

### 9.4 现有 Dockerfile 问题

| 问题 | 影响 | 建议 |
|---|---|---|
| 缺少 `.dockerignore` | build 会复制 20G+ 无用文件 | 按 9.1 创建 `.dockerignore` |
| 缺少 Node.js | 前端无法在容器内构建 | 预先 `cd frontend && npm run build` |
| `WORKDIR /home/cerno/project` | 路径与挂载点耦合 | 小问题，保持一致即可 |
| 使用 `--reload` 启动 | 生产环境不应使用 | Dockerfile 的 CMD 已用 `--host 0.0.0.0`，OK |
| 模型需手动放置 | 镜像内不含模型权重 | 通过 volume 挂载或 build 时 COPY |

---

## 10. 常见问题

### Q1：启动后模型加载失败

**现象**：日志中出现 `ModelNotFoundError` 或 HF 下载失败。

**解决**：
```bash
# 确认模型文件存在
ls -lh models/yolo26s.pt
ls models/models/Qwen--Qwen2.5-VL-7B-Instruct/snapshots/

# 如缺失：配置镜像源
export MODELSCOPE_CACHE=/path/to/cerno/models
```

### Q2：数据库连接被拒绝

**现象**：`could not connect to server: Connection refused`

**检查**：
```bash
# PostgreSQL 是否运行
pg_isready -h localhost -U cerno -d cerno

# 端口是否监听
ss -tlnp | grep 5432
```

### Q3：GPU 显存不足

**现象**：`CUDA out of memory`

**解决**：调整配置 `config/config.yaml`：

```yaml
captioner:
  params:
    max_new_tokens: 1024    # 减少生成长度
    min_pixels: 128000      # 降低输入分辨率
    max_pixels: 501760
```

### Q4：前端页面空白

**检查**：
```bash
# 确认 dist 存在
ls frontend/dist/index.html

# 或者用开发模式
cd frontend && npm run dev
```

### Q5：搜索无 track 结果

**可能原因**：
- 视频没有启用 `detection_enabled`（需要重新创建视频记录）
- 没有 track 与搜索词跨模态匹配
- `track_embeddings` 表为空（检查 Pipeline 日志中 `TrackEncodeRunner` 是否运行）

---

## 附录：依赖清单

### Python 运行时依赖（requirements.txt + 补充）

```
fastapi, uvicorn                  # Web 框架
sqlalchemy[asyncio], asyncpg      # 数据库 ORM + 驱动
pgvector                          # 向量扩展
pydantic, pydantic-settings       # 配置校验
pyyaml                            # YAML 配置
numpy                             # 数值计算
httpx, openai                     # HTTP 客户端 + API
Pillow                            # 图像处理
modelscope                        # 模型下载/加载
torch                              # 深度学习框架
transformers                      # Transformer 模型
bitsandbytes                      # 4-bit 量化
qwen-vl-utils                     # Qwen-VL 工具
python-multipart                  # 文件上传
ultralytics                       # YOLO11 检测
opencv-python-headless            # 视频处理（补充）
transnetv2                        # 场景分割（补充）
faster-whisper                    # 语音转录（补充，可选）
pytest, pytest-asyncio            # 测试
```

### Node.js 运行时依赖（前端）

```
react, react-dom                  # UI 框架
vite                              # 构建工具
tailwindcss                       # CSS 框架
typescript                        # 类型系统
```
