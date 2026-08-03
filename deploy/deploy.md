# Cerno Windows 部署指南（deploy/）

> 目标：把 Cerno 后端以 **「本机 Python venv + Docker PostgreSQL/pgvector + 本机模型」** 的方式跑在
> 一台干净的 Windows + NVIDIA GPU 机器上。不含 Electron，不做 CUDA 容器。
> 原则：**开发机上能用的功能，部署机必须能用；所有推理尽量 GPU，禁止静默退化成 CPU。**

---

## 1. 目录与脚本

| 文件 | 作用 |
|---|---|
| `setup_windows.ps1` | 一次性安装向导：环境检查 → venv → CUDA torch → 依赖 → Docker db → 生成部署配置 → 模型 → API key |
| `start_windows.ps1` | 日常启动：模型校验 → 确保 db 健康 → 设 `CERNO_CONFIG`/`POSTGRES_URI` → 起 uvicorn → 轮询 `/health` |
| `download_models.py` | 模型下载/校验（断点续传、跳过已有、失败重试、`--verify-only`） |
| `write_windows_config.py` | 从 `config/config.yaml` 生成 `config/config.windows.yaml`（**不改原配置**） |
| `deploy.md` | 本文档 |

生成物：
- `config/config.windows.yaml` — 部署专用配置（绝对路径 + API 摘要模式 + 面板置灰功能关闭）
- `.venv/` — Python 3.12/3.13 虚拟环境（自动探测，`-PythonVersion` 可覆盖）
- `models/` — yolo + embedding
- `data/settings.json` — API key（前端设置页同源写入）
- `data/backend.log` — 后端日志

---

## 2. 环境要求（全部必装，`setup_windows.ps1` 逐一硬校验，缺失即中断）

| 依赖 | 校验方式 | 缺失后果 |
|---|---|---|
| **NVIDIA GPU + 驱动** | `nvidia-smi` 可执行，且列得出 GPU | 无法做 embedding/检测/人脸/车牌推理 |
| **驱动 ≥ 550 / CUDA 12.x** | `nvidia-smi` 的 "CUDA Version" | torch 按驱动自动选源，过旧无法用 GPU |
| **FFmpeg（CUDA 版）** | `ffmpeg -encoders` 含 `h264_nvenc`；`-decoders` 含 `h264_cuvid` | NVDEC 硬解/NVENC 转码**静默回退 CPU**（性能骤降） |
| **Python 3.12 / 3.13** | `py -0p` 可探测（setup 自动选用，`-PythonVersion` 可覆盖） | — |
| **Docker Desktop** | `docker info`（守护进程在运行） | 无法起数据库 |

安装命令（PowerShell）：
```powershell
winget install Python.Python.3.13   # 或 3.12（勾选 py launcher）
winget install Docker.DockerDesktop        # 记得启动并等待引擎就绪
winget install Gyan.FFmpeg                 # 完整版（含 CUDA/NVENC/NVDEC）
# NVIDIA 驱动：GeForce Experience 或 winget install Nvidia.GeForceExperience
```

---

## 3. 两种安装模式

| 模式 | 装 | 不装 |
|---|---|---|
| `full`（全功能） | Embedding-8B、YOLO、InsightFace、HyperLPR3、场景分割 | 本地视觉摘要大模型、语音转写、OCR、Grounding |
| `searchless` | YOLO、InsightFace、HyperLPR3、场景分割 | 上面全部 + Embedding |

判定依据：**参数面板里置灰 / 未实现 / 不可配置的功能一律不装**。
- 语音转写（faster-whisper）：面板音频开关默认置灰 → 不装（`transcriber.backend` 保持 `null`）。
- OCR / Grounding：插件未实现，恒置灰 → 不装。
- 画面描述 / 摘要：面板可用，但走 **API**（DashScope + DeepSeek），无本地大模型。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\setup_windows.ps1                              # 交互式
.\deploy\setup_windows.ps1 -Mode full -NonInteractive   # 非交互全功能
.\deploy\setup_windows.ps1 -Mode searchless              # 无向量检索
.\deploy\start_windows.ps1                               # 启动
```

---

## 4. 安装流程（setup_windows.ps1 内部步骤）

1. **前置检查**：GPU(nvidia-smi) / ffmpeg CUDA / Docker / Python / 驱动版本 —— 缺一即中断。
2. **venv**：自动探测 Python（3.13→3.12→3.11），`py -<ver> -m venv .venv`（已存在则跳过）。
3. **依赖（关键顺序）**：
   - 安装 CUDA 版 PyTorch：**按驱动 CUDA 版本自动选源**（≥12.6→cu126 / ≥12.4→cu124 / ≥12.1→cu121），必须用 PyTorch 官方源（pip 默认给 Windows 装 CPU 版）；**torch 已可用则跳过**；
   - `pip install -r requirements.txt`；
   - `pip uninstall -y onnxruntime && pip install onnxruntime-gpu` ← **否则人脸/车牌静默跑 CPU**；
   - 实测 `torch.cuda.is_available() == True`，否则中断。
4. **数据目录**：`data/videos`、`data/artifacts`、`models`。
5. **数据库**：`docker compose up -d db`，**轮询 `docker inspect cerno_postgres` 直到 `healthy`**（最多 3 分钟）。
6. **部署配置**：`write_windows_config.py --mode <mode>` → `config/config.windows.yaml`。
7. **API key（可选）**：DashScope + DeepSeek，写入 `data/settings.json`（与前端设置页同一存储，可之后补）。
8. **模型**：`download_models.py` 下载/校验（embedding + yolo + face + plate + segmenter）。

---

## 5. 模型清单与存放位置

| 组件 | 模型 | 位置 | 说明 |
|---|---|---|---|
| embedding (仅 full) | Qwen3-VL-Embedding-8B (~16GB) | `models/Qwen/...` | ModelScope 下载，断点续传 |
| yolo | yolo26s.pt (~20MB) | `models/` | BoT-SORT `with_reid` + `model: auto` = **检测骨干特征直通，无需额外 ReID 模型**（已核实 ultralytics 8.4.104 行为） |
| face | InsightFace `buffalo_l` | `~/.insightface/models/buffalo_l` | SCRFD + ArcFace R50，库自带下载 |
| plate | HyperLPR3 ONNX 包 | `~/.hyperlpr3/<ver>/onnx` | 库自带下载（`http://hyperlpr.tunm.top/raw/...`） |
| segmenter | TransNetV2 权重 | 随 `transnetv2-pytorch` pip 包分发 | 纯 Python wheel，无下载 |
| 本地 caption 大模型 | — | 不装 | 走 DashScope API |
| 语音转写模型 | — | 不装 | 面板置灰 |

---

## 6. API 服务与存储路径（摘要 vlm_llm 模式）

前端 **「设置页 → 系统设置」** 可配置三项，保存即运行时生效（无需重启）：

- **API 密钥**：DashScope（画面描述）`DASHSCOPE_API_KEY` + DeepSeek（摘要生成）`DEEPSEEK_API_KEY`
- **服务商**（端点 Base URL + 模型名）：DashScope 默认 `https://dashscope.aliyuncs.com/compatible-mode/v1` + `qwen-vl-max`；DeepSeek 默认 `https://api.deepseek.com/v1` + `deepseek-chat`
- **存储路径**：`video_dir` / `artifact_dir`（默认沿用 config 值 `data/videos` / `data/artifacts`）

安装时也可通过交互输入写 `data/settings.json`（部署脚本 `update_keys` 兼容）。

`data/settings.json` 结构：`{ "api_keys": {...}, "providers": {"dashscope": {base_url, model}, "deepseek": {base_url, model}}, "storage": {video_dir, artifact_dir} }`

关键机制：每次 `load_config()` 时 `core/config_loader._apply_settings_overrides` 将
settings.json 覆盖进配置（key→env、providers→captioner/summarizer 的 base_url/model_name、
storage→storage 路径）；`PUT /settings` 保存后**同步 env + 清 config 缓存**，**无需重启**。
上传路由 / FormatService / VideoService 均读取新鲜 `load_config()`，因此改存储路径后
**新上传立即落到新目录**，转码/导出亦跟随。
插件侧（`QwenAPICaptioner` / `VLLMSummarizer`）对占位 key 有 env 兜底。

**摘要模式兜底**：`captioner.backend = qwen_api`（无本地模型）时，后端把 `native_video`
摘要模式自动视为 `vlm_llm`（`pipeline/runners/base.py: effective_summary_mode`），
避免缺模型时空图调用/管道失败。

---

## 7. 部署坑位审计（重点）

逐一核实过的「CPU 代替 GPU / 静默降级」风险及处置：

| # | 风险 | 现状 | 处置 |
|---|---|---|---|
| 1 | **pip 默认装 CPU 版 torch** | Windows `pip install torch` 给 CPU 版 | ✅ setup 按驱动 CUDA 自动选源 + 实测 `torch.cuda.is_available()`，已可用则跳过 |
| 2 | **onnxruntime 默认 CPU 版** → insightface/hyperlpr3 静默跑 CPU | requirements 里 `onnxruntime`（CPU） | ✅ setup 卸载后装 `onnxruntime-gpu` |
| 3 | **hyperlpr3 硬编码 CPU provider** | `MultiTaskDetectorORT` 写死 `['CPUExecutionProvider']`，光装 gpu 版也没用 | ✅ `plugins/plate/hyperlpr_plate.py` 打 CUDA 升级补丁（CUDA 不可用时安全 no-op，幂等） |
| 4 | **ffmpeg 缺 CUDA → NVDEC 静默回退 cv2 解码 / NVENC 静默回退 libx264 编码** | `video_util`/`format_service` 都有软回退 | ✅ setup 硬校验 `h264_nvenc` + `h264_cuvid`，缺失即中断 |
| 5 | **embedder / detector 设备写死 `cuda`** | CPU 环境会**显式报错**（非静默） | ✅ 依赖 setup 前置 GPU 校验 |
| 6 | **本地 caption 大模型缺失** | 部署不装它 | ✅ 摘要模式强制 vlm_llm |
| 7 | **API key 填了不生效** | settings.json 从未被插件读取 | ✅ 修复：settings.json → env → config + 清缓存 + 插件 env 兜底 |
| 8 | **searchless 模式语义搜索 500** | embedder 为 None 时搜索会炸 | ✅ `/search/semantic` 返回友好 400 |

其他确认无坑：
- `transnetv2-pytorch` 是 `py3-none-any` 纯 Python wheel，Windows 无需编译。
- `pymediainfo` 有 `win_amd64` wheel（自带 MediaInfo.dll）；缺失时 metadata 自动降级 ffprobe，非致命。
- `bitsandbytes` 有 `win_amd64` wheel；且仅被**本地 caption 插件（部署不用）**注释提及，装不上也可忽略。
- `modelscope` 走 HTTP 快照下载，不依赖 git。
- insightface 的 `get_default_providers()` 含 `CUDAExecutionProvider`，装 gpu 版后**自动用 GPU**。
- ffmpeg/ffprobe 全部经 PATH 调用，Windows 上 Gyan.FFmpeg 加入 PATH 即可。

---

## 8. Linux / Windows 环境差异（调查结论，暂不改代码）

| 维度 | Linux 开发机 | Windows 部署机 | 影响 / 现状 |
|---|---|---|---|
| **torch 安装** | `pip install torch` = CUDA 版 | `pip install torch` = **CPU 版** | 按驱动 CUDA 自动选源（setup 已处理） |
| **onnxruntime** | 默认 CPU 版 | 默认 CPU 版 | 需 `onnxruntime-gpu`（setup 已处理） |
| **Docker** | Linux 原生 | Docker Desktop（Linux 虚拟机跑容器） | 仅用 `db` 服务 + named volume，行为一致；`app` 服务不用 |
| **路径分隔符** | `/` | `\`（Python 双兼容） | 代码用 `pathlib`/`os.path`；配置统一 forward-slash，Windows 兼容 |
| **模型缓存目录** | `~/.insightface`、`~/.hyperlpr3`、`~/.cache/huggingface` | `C:\Users\X\...` | `Path.home()` 自动解析；hyperlpr3 内部已按 `sys.platform` 处理 `HOMEPATH` |
| **ffmpeg 二进制** | `ffmpeg`（apt，可能无 CUDA） | `ffmpeg.exe`（Gyan 完整版，含 CUDA） | 代码全走 PATH；setup 校验 CUDA 能力 |
| **asyncio 事件循环** | Proactor 无关 | Windows 用 ProactorEventLoop | uvicorn 自动适配，subprocess 正常 |
| **exiftool** | 可能已装 | 默认无 | metadata 三级提取自动降级 ffprobe，非致命 |
| **文件删除/改名** | 允许打开中文件删除 | **打开中的文件不可删** | 删除视频时若正在播放/转码，`StorageManager` 清盘可能失败 → 需先停用再删（已由删除守卫 409 兜底处理中状态） |
| **控制台编码** | UTF-8 | GBK(cp936) | 中文日志在终端可能乱码；不影响 API/落盘 |
| **路径长度** | 无限制 | MAX_PATH=260 | 超长视频/导出路径可能受限；建议装项目到浅目录 |
| **新行符** | LF | CRLF | 脚本为 PS1（CRLF 原生）；`deploy/` 内文件建议保持 CRLF |

**结论**：差异主要集中在「安装期」（torch/onnxruntime/ffmpeg 的 CUDA 来源）和「运行时极少数文件系统语义」。
安装期差异已由 setup 硬校验覆盖；运行期差异均已确认非致命或有兜底。无需为跨平台改动业务代码。

---

## 9. 日常启动与验证

```powershell
.\deploy\start_windows.ps1                 # 校验模型 → 等 db → 起后端 → 轮询 /health
Invoke-RestMethod http://127.0.0.1:8000/health
# 期望：{"status":"ok","service":"cerno","database":"ok"}
# database=unreachable → 返回 503，说明后端起来了但 db 未就绪
```

启动脚本行为：
1. 按 `config/config.windows.yaml` 判定必需模型（embedding 视模式而定），缺则提示先跑 setup；
2. `docker compose up -d db` + 等待 `healthy`；
3. `POSTGRES_URI` 优先取环境变量 → 其次 `.env` → 最后默认本机 docker；
4. `CERNO_CONFIG` 指向 `config/config.windows.yaml`（不存在则退回默认配置并警告）；
5. 后台起 uvicorn，日志写 `data/backend.log`，前台轮询 `/health` 直到 200 后挂住（Ctrl+C 停止后端）。

---

## 10. 故障排查

| 症状 | 原因 / 处理 |
|---|---|
| `torch.cuda.is_available()` False | 驱动过旧 / 装了 CPU 版 torch。升级驱动，或 `pip uninstall torch` 后重跑 setup（自动按驱动选源） |
| `/health` 返回 503 `database:unreachable` | db 容器未就绪。`docker logs cerno_postgres` |
| 人脸/车牌速度极慢 | onnxruntime 还是 CPU 版。确认 `.venv` 里是 `onnxruntime-gpu`；hyperlpr 补丁日志应有 "ONNX CUDA patch applied" |
| 抽帧/转码 CPU 占用高 | ffmpeg 无 CUDA。`ffmpeg -encoders \| findstr nvenc`，重装 Gyan.FFmpeg |
| 模型下载中断 | 重跑 `setup_windows.ps1` 断点续传；或 `python deploy/download_models.py --component <x> --model-root models` |
| 前端设置页填 key 后立即生效 | 已支持（无需重启）；若提示未配置，确认 `data/settings.json` 有内容 |
| 摘要跑 vlm_llm 但报 key 错 | 确认 DashScope/DeepSeek key 已配置（设置页或 settings.json） |

---

## 11. 提交给后续开发的注意点

- 新增会产生磁盘文件的功能 → 落盘路径模式必须登记进 `core/storage_manager.py`（见 CLAUDE.md）。
- 新增感知模块 → `pipeline/runners/` 新 runner + `pipeline/operations.py` 一个 Operation，engine 零改动。
- 若未来启用语音转写：`config.yaml` 取消注释 faster-whisper，`transcriber.backend: faster_whisper`，并加回 `deploy/download_models.py` 的 transcriber 组件。
