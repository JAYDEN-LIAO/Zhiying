# Zhiying 生产部署布局（10.0.0.176）

> 版本：0.24.0 | 部署分支：`feature/yunzhi`（部署专用，不合并 main）
> 日期：2026-08-05
> 前置阅读：`docs/arch.md`、`docs/yunzhi-integration-plan.md`、`docs/yunzhi-integration-adaptation.md`
> **本文件是 B1 服务器基线执行时的唯一布局与安全依据。** 所有 `zhiying` 即项目名（中文「智影」）。

## 0. 首要原则：对服务器零影响、零伤害

> 部署的**最高准则**，优先于一切效率/便利。所有决策据此评估。

1. **只做"新增"，不做"修改 / 删除 / 重启"现有任何东西**——平台 docker 栈、vLLM（qwen-25/hunyuan-mt）、clip/ocr/rerank/glm-ocr、平台 postgres、平台文件库、GPU0，一律不碰。
2. **所有新资源以 `zhiying` 命名，自成一体，可完整回滚**——回滚 = 停掉 zhiying 相关项，现有服务一根汗毛不动。
3. **绝不遮蔽系统级命令**——新 ffmpeg 装独立前缀，只在自己 `start.sh` 的 PATH 里生效，绝不覆盖 `/usr/bin/ffmpeg`、`/usr/local/bin`。
4. **绝不污染共享环境**——base conda env 是 clip 等服务的共享运行时（PATH 指向它），zhiying 必须用**独立 env**，不往 base 装任何东西。
5. **共享资源（nginx / GPU1 / docker / firewalld / 根分区）上的每一步**：先验证、可回滚、**逐项停下等确认**后才动。
6. **只读平台文件库**——`source_owned=false` 就地引用，删除视频也绝不 unlink 平台源文件。

## 1. 服务器既有规范（实测，2026-08-05 只读侦查）

对现有 5 个服务（clip / qwen / hunyuan / rerank / glm-ocr）逐一检查，服务器摆放惯例：

| 类别 | 服务器惯例 |
|---|---|
| 代码 | `/home/services/{服务名}/`，`.py` 代码直接放服务目录 |
| 启动 | 目录内 `start.sh`（设 PATH/缓存环境变量/CUDA_VISIBLE_DEVICES → cd → `nohup ... > logs/server.log 2>&1 & wait`）+ systemd `Type=simple` + `ExecStart=/bin/bash .../start.sh` + `WorkingDirectory` |
| 依赖 | `/opt/miniconda3/envs/{服务名}` 独立 conda env |
| 模型 | 集中 `/home/model-weights/`（HF_HOME / TRANSFORMERS_CACHE 指向它） |
| 日志 | `/home/services/{服务名}/logs/server.log` |
| 大数据 | `/home/data/yunzhi-platform/`（file-library / postgres / redis / logs / generated…，**代码与数据分离**） |
| GPU | systemd 内 `CUDA_VISIBLE_DEVICES` 固定单卡 |

## 2. 复用清单（实测，2026-08-05 只读核实）

### 2.1 服务器可直接复用的资源

| 资源 | 实测 | 用途 |
|---|---|---|
| CUDA 12.8 toolkit | `/usr/local/cuda-12.8`，nvcc V12.8.61 | ffmpeg CUDA 编译、torch（无需另装 CUDA） |
| 编译工具链 | gcc 12.3 / make 4.4 / cmake 3.27 / pkg-config 1.9 全有 | ffmpeg 编译（若做） |
| base conda python | Python **3.13.13** + torch 2.8.0+cu128（cuda 可用） | 证明 3.13 在服务器可用；**只作参照，不作为运行时**（base 被 clip 共享，不可污染） |
| conda 源 | tuna 清华镜像（`~/.condarc`） | 依赖安装加速 |
| node / npm | node v20.19.5 + npm | 前端构建 |
| docker + compose | Docker 26.1 + Compose v2.27 | pgvector 容器 |
| 系统 ffmpeg | 6.1.1 + **libx264 软编** ✓（无 nvenc/cuvid） | **Phase 1 CPU 兜底**：解码 cv2 回退、代理 libx264 软编，管道全功能可用 |
| scp / sftp | ✓ | 代码/模型传输（服务器无 rsync） |
| git | 2.43.0 | 拉取代码 |
| 内存/CPU | 503GiB 内存 / 80 核 | 充裕 |
| 端口 | 8000、宿主 5432 均空闲 | zhiying 专属 |
| postgres:16 镜像 | docker 已有 | **不直接复用**（与平台隔离），pgvector 用独立容器 |

### 2.2 必须新增的（不可复用）

| 项 | 说明 |
|---|---|
| conda env `zhiying` + requirements 依赖 | pip 缓存为空（`/root/.cache/pip` 0 字节），torch ~2.5G 需重新下载；装到 `/opt/miniconda3/envs/zhiying` |
| pgvector 容器 | 拉取 `pgvector/pgvector:pg17`（~450MB），数据卷 `/home/data/zhiying/pgdata` |
| 模型 ~17G | 服务器无任何缓存（modelscope/HF 缓存空）→ **服务器端 modelscope 直接下载** 或 scp 上传（见 §3.3） |
| 前端 node_modules + dist | `npm ci && npm run build` |
| nginx conf + systemd unit + start.sh | 全部新增 |
| （可选）CUDA ffmpeg | 独立前缀，见 §6.1 |

## 3. Zhiying 部署布局

### 3.1 目录树

```
/home/services/zhiying/              ← 代码（git clone / scp feature/yunzhi）
├── main.py / api/ / core/ / pipeline/ / plugins/ / frontend/ ...   ← 代码本体
├── start.sh                         ← 仿既有 start.sh（独立 ffmpeg PATH + env zhiying + 起 uvicorn）
├── logs/                            ← server.log（nohup 重定向）
├── cache/                           ← 杂项缓存（可选）
├── data/
│   └── settings.json / presets.json ← zhiying 运行时配置（代码硬依赖 data/ 相对路径，保留在服务目录）
├── models/ → /home/model-weights/zhiying   ← 符号链接（物理位置在规范区）
├── ffmpeg/                          ← （可选）独立前缀 CUDA ffmpeg，见 §6.1
└── frontend/dist/                   ← 前端构建产物（nginx root 指这里）

/opt/miniconda3/envs/zhiying/        ← 依赖环境（conda create -n zhiying python=3.13）

/home/model-weights/zhiying/         ← 模型集中区（软链 `models/` 指向这里）
├── Qwen/Qwen3-VL-Embedding-8B       ← 16G（embedder，8bit 量化加载）
├── yolo26s.pt                       ← YOLO11s 检测（20M）
├── yolo26n-cls.pt                   ← BoT-SORT ReID 外观模型（5.6M，必须真实存在，防 GitHub 下载）
└── ...（face/plate/segmenter 见 3.3）

/home/data/zhiying/                  ← 视频产出数据（仿 /home/data/yunzhi-platform 数据分离）
├── videos/                          ← storage.video_dir
├── artifacts/                       ← storage.artifact_dir（缩略图/crop/keyframe/remux/proxy）
└── pgdata/                          ← pgvector:pg17 数据卷

~/.insightface/models/buffalo_l      ← SCRFD+ArcFace（库强制缓存）
~/.hyperlpr3/<version>/onnx          ← HyperLPR3（库强制缓存）

nginx：新 server block（托管 dist + 反代 /api→127.0.0.1:8000，CSP frame-ancestors 待 B2）
systemd：zhiying.service（仿 qwen-25.service，CUDA_VISIBLE_DEVICES=1）
```

### 3.2 关键组件

| 组件 | 方案 |
|---|---|
| 后端 | `uvicorn main:app`，端口 **8000**（宿主空闲），`/health` 输出 `"service":"zhiying"` |
| 数据库 | docker `pgvector/pgvector:pg17`，宿主端口 **5432**（空闲），数据卷 `/home/data/zhiying/pgdata`；`init_db()` 自动建表 |
| 前端 | `npm ci && npm run build`；`VITE_YUNZHI_MOCK=false` + `VITE_YUNZHI_HOST_ORIGIN`（B2 平台给精确 Origin 后重 build） |
| GPU | `CUDA_VISIBLE_DEVICES=1`（GPU1；vLLM hunyuan-mt 同卡，剩 ~25.6G，只用空闲部分） |
| captioner | 降级 `qwen_api`（DashScope），需 `.env` 配 `DASHSCOPE_API_KEY`；embedder 8bit 量化 |
| ffmpeg | **Phase 1 复用系统 ffmpeg（CPU 兜底，零影响）**；Phase 2 可选编译 CUDA 版到独立前缀（见 §6.1） |

### 3.3 模型来源（推荐服务器端下载，零上传依赖）

- **首选**：服务器 `deploy/download_models.py` 从 **modelscope** 直接下载 embedder + yolo + reid（服务器出网可达 modelscope，无需经本地传输 17G）
- 备选：本机 `models/` 经 **scp** 上传（服务器无 rsync）
- face（buffalo_l）/ plate（HyperLPR3 onnx）/ segmenter（TransNetV2）由各库首次运行自动缓存到 `~/.insightface`、`~/.hyperlpr3`、pip 包内
- **不传** `Qwen3-VL-8B-Instruct`（17G，captioner 已降级 API）

## 4. 符合度评估

| 项 | zhiying 摆放 | 对照规范 | 结论 |
|---|---|---|---|
| 代码目录 | `/home/services/zhiying/` | `/home/services/{name}` | ✅ 完全符合 |
| 依赖环境 | conda env `zhiying` | `/opt/miniconda3/envs/{name}` | ✅ 完全符合 |
| 启动方式 | `start.sh` + systemd + `logs/` | 同左 | ✅ 完全符合 |
| 日志 | `services/zhiying/logs/` | 同左 | ✅ 完全符合 |
| 模型 | `/home/model-weights/zhiying`（`models/` 软链过去） | 模型集中 `/home/model-weights` | ⚠️ 软链对齐：物理位置符合规范，config 相对路径零改动 |
| 视频/工件产出 | `/home/data/zhiying/` | 大数据在 `/home/data/yunzhi-platform` | ⚠️ 配置对齐：改 config 两行，符合"代码/数据分离" |
| insightface/hyperlpr3 | `~/.insightface`、`~/.hyperlpr3` | 库自身管理缓存 | ⚠️ 无法对齐（库强制路径，全平台同类先例） |
| 数据库 | `/home/data/zhiying/pgdata` | 平台 postgres 在 `/home/data/.../postgres` | ✅ 符合 |
| 前端产物 | `services/zhiying/frontend/dist` | 现有服务无前端 | ➖ 无先例，自包含即可 |

## 5. 偏离点与理由

> 共同原则：**物理布局尽量合规（模型、数据落在规范区），只在"代码入口"上做最小折中（软链、改配置），绝不为了表面一致去动业务代码、背回归风险。**

### ① 模型：项目内 `models/` 软链（非绝对路径）
- **规范**：现有服务用绝对路径/环境变量直接指 `/home/model-weights`，代码里不出现模型目录
- **zhiying**：物理放 `/home/model-weights/zhiying`（合规），项目根保留软链 `models/ → /home/model-weights/zhiying`
- **为什么偏离**：zhiying 代码里模型路径是写死的相对路径 `models/...`（`config/config.yaml`，约定"相对模型路径自动解析到项目根"）。改成绝对路径 = 动 config + 可能动 `config_loader.py` + 各开发机配置不一致 + 全量回归。软链让**磁盘物理布局 100% 合规**，只多一个一眼能懂的指针，零代码改动

### ② 视频/工件产出：放 `/home/data/zhiying`（服务目录不放数据）
- **规范**：现有 5 个服务目录里没有任何业务数据（只有 logs/ + cache/ 模型缓存）；平台大数据在 `/home/data/yunzhi-platform`
- **zhiying**：`/home/data/zhiying/{videos, artifacts, pgdata}`
- **为什么偏离**：zhiying 引入现有服务没有的新类别（GB 级持续膨胀的视频数据）。无现成先例，参照平台「代码与数据分离」哲学——视频放服务目录会把"代码目录"变成"数据仓库"，破坏分离语义，运维对账困惑。代价只是 `config.yaml` 里两个绝对路径

### ③ insightface / hyperlpr3 缓存：`~/.insightface`、`~/.hyperlpr3`
- **规范**：模型尽量集中 `/home/model-weights`
- **为什么偏离**：**库写死缓存路径**，不接受指定目录。与现有 `glm-ocr`（Ollama → `~/.ollama`）同类，属依赖行为，**不算违背**，可接受。部署时顺带验证是否支持自定义缓存环境变量，能收则收进规范区

## 6. 启动与服务（仿服务器惯例，零遮蔽）

### 6.1 ffmpeg 策略（分阶段，绝不遮蔽系统版）

- **Phase 1（默认，零影响）**：**直接复用系统 ffmpeg 6.1.1**——解码 NVDEC 缺失自动回退 cv2，代理编码用 libx264 软编。管道全功能可用，只是慢一些。**零编译、零系统改动。**
- **Phase 2（可选性能优化）**：编译带 CUDA 的 ffmpeg（`--enable-cuda-nvcc --enable-nvenc --enable-cuvid`），安装到**独立前缀** `/home/services/zhiying/ffmpeg/`，**只在 zhiying 的 `start.sh` PATH 前置该目录**——系统 `/usr/bin/ffmpeg` 与其它服务完全不受影响。
- **前置**：编译需 nasm/yasm（2 个小包，可经 dnf 装到系统，或下载独立二进制到 /home）；根分区只剩 6.9G，**构建目录必须放 /home**。

### 6.2 `start.sh`（放 `/home/services/zhiying/start.sh`）

```bash
#!/bin/bash
# Phase 2 编译了 CUDA ffmpeg 后，此 PATH 前置让它生效；未编译则回退系统 ffmpeg
export PATH=/home/services/zhiying/ffmpeg/bin:/opt/miniconda3/bin:/usr/local/cuda-12.8/bin:$PATH
export CUDA_VISIBLE_DEVICES=1
export HF_HOME=/home/model-weights
export TRANSFORMERS_CACHE=/home/model-weights
cd /home/services/zhiying

nohup /opt/miniconda3/envs/zhiying/bin/python -m uvicorn main:app \
  --host 0.0.0.0 --port 8000 --workers 1 \
  > /home/services/zhiying/logs/server.log 2>&1 &
wait
```

### 6.3 systemd unit `zhiying.service`（仿 `qwen-25.service`）

```ini
[Unit]
Description=Zhiying Video Analytics Engine
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/services/zhiying
ExecStart=/bin/bash /home/services/zhiying/start.sh
Restart=always
RestartSec=10
Environment=PATH=/opt/miniconda3/bin:/usr/local/cuda-12.8/bin:/opt/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=HOME=/root

[Install]
WantedBy=default.target
```

### 6.4 数据库（pgvector 容器，宿主 5432）

```bash
docker run -d --name zhiying-pg \
  -e POSTGRES_USER=zhiying -e POSTGRES_PASSWORD=zhiying -e POSTGRES_DB=zhiying \
  -p 5432:5432 \
  -v /home/data/zhiying/pgdata:/var/lib/postgresql/data \
  pgvector/pgvector:pg17
```

> 账号/库名与 `config/config.yaml` 的 `db.uri`（`postgresql+asyncpg://zhiying:zhiying@localhost:5432/zhiying`）对齐。**与平台 postgres（15432/25432）完全隔离。**

### 6.5 nginx server block（草案，B2 确定入口 URL 后定稿）

```nginx
server {
    listen 80;
    server_name zhiying.<域名>;   # ← B2 平台登记后确定

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    location / {
        root /home/services/zhiying/frontend/dist;
        try_files $uri $uri/ /index.html;
    }
}
```

> CSP `frame-ancestors`（平台 iframe 嵌入）待 B2 平台提供精确 Origin 后补充。**作为独立 conf 文件新增，绝不动现有 80→3100 block；`nginx -t` 通过才 reload。**

## 7. 关键配置改动清单（B1 执行时）

| # | 位置 | 改动 |
|---|---|---|
| 1 | `config/config.yaml` | `storage.video_dir` → `/home/data/zhiying/videos`；`storage.artifact_dir` → `/home/data/zhiying/artifacts` |
| 2 | `/home/services/zhiying/.env` | `DASHSCOPE_API_KEY=<key>`（captioner 降级 qwen_api 必需） |
| 3 | 软链 | `ln -s /home/model-weights/zhiying /home/services/zhiying/models` |
| 4 | `config/botsort.yaml` | `model: "models/yolo26n-cls.pt"` **必须真实存在**（防 ultralytics 回退 GitHub 下载） |
| 5 | 前端 build env | `VITE_YUNZHI_MOCK=false` + `VITE_YUNZHI_HOST_ORIGIN=<平台精确 Origin>`（B2 提供后） |
| 6 | ffmpeg | Phase 1 复用系统 ffmpeg（零改动）；Phase 2 编译到 `/home/services/zhiying/ffmpeg`（独立前缀，构建在 /home） |

## 8. B1 执行顺序（两阶段：零风险优先，共享点逐项确认）

### Phase A — 零风险（不碰任何现有服务，可一口气推进）

```
A1 代码就位       scp/git 把 feature/yunzhi 送到 /home/services/zhiying
A2 依赖环境       conda create -n zhiying python=3.13 + pip install -r requirements.txt（tuna 源，/ 不占用）
A3 模型           服务器端 modelscope 下载（首选）或 scp 上传；~17G → /home/model-weights/zhiying
A4 数据库         拉取 pgvector:pg17 → docker run zhiying-pg（5432）→ init_db
A5 前端构建       npm ci && npm run build（VITE_YUNZHI_MOCK=true 先跑通）
A6 配置改动       按 §7 清单（数据路径/软链/.env/ReID）
```

### Phase B — 共享点（每步先验证、停下等确认）

```
B1 [确认]  ffmpeg 策略：先确认 Phase 1 系统 ffmpeg 可用 → 冒烟管道；性能不足再进 Phase 2 编译
B2 [确认]  nginx：新增独立 conf → `nginx -t` 校验 → 通过才 reload（绝不动 3100 block）
B3 [确认]  启动 zhiying.service：先 nvidia-smi 核实 GPU1 空闲显存 → 启动 → /health 冒烟
B4 [确认]  验证：register-external + 跑管道 + /internal/yunzhi/jobs 202/进度回调
```

> 详细步骤与平台登记（B2 平台侧 / B3 联调 / B4 端到端）见 `docs/yunzhi-integration-adaptation.md` §8。

## 9. 影响边界（谁不碰 / 共享点及防护）

### 🟢 完全不碰
- 现有 docker 容器（yunzhi 全栈 + yanshi 演示栈）、现有 systemd 服务（vLLM/clip/ocr/rerank/glm-ocr）
- 平台文件库（只读，`source_owned=false` 就地引用，绝不 unlink）
- 平台 postgres（15432/25432）、GPU0（vLLM qwen-25）、系统 `/usr/bin/ffmpeg`、base conda env
- 根分区 `/`：一切安装/构建/缓存/数据路径指 `/home`（根仅 6.9G）

### 🟡 新增独立（可完整回滚）
- `/home/services/zhiying`、`/home/data/zhiying`、`/home/model-weights/zhiying`
- conda env `zhiying`、docker 容器 `zhiying-pg`、systemd `zhiying.service`
- 回滚 = 停这几样，现有服务零影响

### 🔴 共享资源上的谨慎操作（5 点，均有防护）
| # | 共享点 | 风险 | 防护 |
|---|---|---|---|
| 1 | GPU1 显存（hunyuan-mt 用，剩 ~25.6G） | 超可用显存挤到 vLLM | 加载前 `nvidia-smi` 核实；embedder 8bit ~8G + YOLO 2G，只用空闲部分；超限立即中止 |
| 2 | nginx（80→3100 平台 web） | 配置错误/reload 失败弄挂平台入口 | 独立 conf 文件；`nginx -t` 通过才 reload |
| 3 | 系统 ffmpeg（平台可能调用） | 遮蔽系统版影响其它服务 | 独立前缀 `/home/services/zhiying/ffmpeg`，只在 zhiying start.sh PATH 生效 |
| 4 | firewalld（只开 3100/http/ssh） | 需给 8000 加规则 | 纯加法规则；是否开取决于 B2 平台后台调用方式，B1 可先不开 |
| 5 | 根分区 `/`（剩 6.9G） | 系统包/构建吃根分区 | 只装 KB 级小包（nasm/yasm）；构建全在 /home；实时 `df -h` 监控 |

## 10. 交接注意事项

1. **source_owned**：凡 `source_owned=false`（平台共享文件就地引用），删除视频绝不 unlink 平台源文件
2. **jobs 路由**：`/internal/yunzhi/jobs` 挂根路径（`main.py`），不经 `/api/v1` 前缀
3. **幂等**：jobs 幂等登记为进程内集合，单 worker 有效；多 worker 需迁 DB/共享存储
4. **回调客户端**：`run_yunzhi_job` 所有平台回调须在共享 `httpx.AsyncClient` 的 `async with` 块内发送
5. **命名**：项目名 Zhiying（智影）；部署目录/env/DB 一律 `zhiying`。本地开发路径（`~/projects/cerno`、本地 DB `cerno_postgres`）保留原名，不属产品命名
6. **零遮蔽**：CUDA ffmpeg 只进 zhiying 的 start.sh PATH；base conda env 只读不写
7. **根分区**：一切安装/缓存/下载/数据路径必须指 `/home`（conda pkgs、pip cache、HF cache 均设到 /home）
8. **逐项确认**：Phase B 每步（ffmpeg 策略/nginx/启动/验证）先停下汇报，用户确认后再执行
