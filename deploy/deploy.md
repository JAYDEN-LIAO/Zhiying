# Zhiying 部署指南（deploy/）

> 目标：让 Zhiying 在**全新机器**上跑起来。两条部署路径：
> - **桌面路径（Windows 桌面机）**：裸机 → `setup_windows.ps1` 一键安装 → 双击 `智影桌面端.exe` 拉起桌面进程（纯产品启动器）。见 §3.1。
> - **开发机路径（Windows / Linux）**：git clone 后跑部署脚本 → 环境/包/模型/前端全装齐，形态与本机一致，用于开发改代码测试。见 §3.2。
>
> 脚本自动安装一切——Python / FFmpeg / Docker / CUDA torch / 全部 Python 依赖 / 全部模型 / 前端 dist，装完自校验，并打印启动指令。`config/config.yaml` 由脚本从 example 自动生成。
>
> 原则：**开发机上能用的功能，部署机必须能用；所有推理尽量 GPU，禁止静默退化成 CPU。**
>
> 平台间唯一硬差异是 onnxruntime（x86/Windows→GPU 版，ARM64→CPU 版），由 `requirements.txt` 环境标记自动处理。

---

## 1. deploy/ 目录

| 文件 | 作用 |
|---|---|
| `setup_windows.ps1` | **Windows 裸机一键安装器**：探测环境 → 复用兼容项、补装缺失项 → 装系统/依赖/模型 → **生成 config.yaml + 构建前端 dist** → 自校验 → 打印启动指令 |
| `setup_linux.sh` | **Linux 开发机一键安装器**（规格同 Windows）：apt 系统依赖 / venv / CUDA torch / requirements+onnxruntime / 模型 / Docker db / config.yaml / Node+前端 dist，同款代理交互+复用+幂等 |
| `download_models.py` | 模型下载/校验（embedding/yolo/reid/face/plate/segmenter，断点续传、`--verify-only`） |
| `deploy_feedback.md` | 部署实测问题与修复历史（踩坑记录，含本次所有修复的说明） |

> 旧 `write_windows_config.py`（生成 config/config.windows.yaml）与 `start_windows.ps1`（后端启动脚本）已删除——
> 配置已统一、启动直接用 `uvicorn main:app`，不再需要独立部署配置或启动脚本。

---

## 2. 环境要求

| 依赖 | 说明 |
|---|---|
| **Windows 10/11** | Home 版需 WSL2（脚本自动装，装完需重启一次） |
| **NVIDIA GPU + 驱动** | 脚本检测 `nvidia-smi` + CUDA 版本；缺失则报错中止（不自动装驱动） |
| **代理（必填）** | 脚本启动时强制输入代理地址并测试。GitHub/PyTorch 官方源被墙，必须走代理；国内源直连 |

---

## 3. 快速开始

### 3.1 Windows 桌面机（desktop 路径，裸机）

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\setup_windows.ps1                    # 交互式（输入代理，看注意事项）
# 或全自动（需先开代理）：
.\deploy\setup_windows.ps1 -Proxy http://127.0.0.1:7897 -NonInteractive
```

脚本会（11 步）：
1. 请求管理员权限（UAC）
2. 打印注意事项 + 强制输入代理地址并测试
3. 探测 Python / FFmpeg / Docker / WSL2 / GPU，**复用兼容项、补装缺失项**
4. 装 Python（缺失时 winget）→ venv → **生成 `config/config.yaml`（cp example）** → CUDA torch（按 GPU/驱动选源，Blackwell 自动 cu130）→ 匹配 torchvision → requirements → onnxruntime-gpu → accelerate/lap
5. 下载全部模型（embedding / yolo / reid / face / plate / segmenter）
6. 数据库：WSL2 已装则直接配置 Docker + 拉 pgvector；WSL2 缺失则**放最后装 WSL2 + Docker Desktop** 并提示**重启**
7. **装 Node + 构建前端 dist**（frontend-desktop + frontend）
8. 自校验（模型齐全 + CUDA kernel 实测）→ 打印启动指令

**WSL2 缺失时的两段式**（Home 裸机常见）：
- 第一段：装完除 WSL2/Docker 外的一切 + 校验通过 → 脚本提示重启
- 重启后再双击一次脚本 → 检测到 WSL2 就绪 → 补拉 pgvector 镜像 → 完成（可选，不重跑也行，见 §4 启动指令）

**装完即用（桌面路径）**：环境就绪后，双击 `智影桌面端.exe`（构建方法见 `desktop/README.md`）或 `python desktop\app.py`，即可拉起桌面进程运行项目。exe = 纯产品启动器（pywebview 窗口壳），管理 db/后端/窗口生命周期。

**总下载量约 25GB+**（torch ~2.6GB + embedding 16GB + 其余模型），请预留磁盘空间。

### 3.2 Linux 开发机（deploy 路径，git clone 后裸机）

```bash
bash deploy/setup_linux.sh                                  # 交互式（输入代理）
# 或全自动（需先开代理）：
bash deploy/setup_linux.sh --proxy http://127.0.0.1:7897 --non-interactive
```

脚本会（10 步，规格与 Windows 版一致）：
1. 注意事项 + 代理输入实测
2. 探测 GPU / python3 / ffmpeg / docker / node
3. apt 装系统依赖（python3-venv / ffmpeg / exiftool / curl / git，docker 缺失时装 docker.io）
4. 建 `.venv` + **生成 `config/config.yaml`**
5. CUDA torch/torchvision（按 GPU/驱动选源 + 真实 CUDA kernel 验证；aarch64/GB10 失败给 conda 提示）
6. requirements（Aliyun 直连）+ onnxruntime-gpu（x86）/ CPU（aarch64）+ 虚拟桩 + accelerate/lap + pywebview（可选）
7. 下载全部模型（国内源直连 / GitHub 走代理，超时整组重试）
8. `docker compose up -d db` 等 healthy
9. Node（缺失时装 v22）+ 构建 frontend-desktop / frontend dist
10. 自校验 → 打印启动指令

装完形态与本机参考机一致：`.venv` / `models/` / `config/config.yaml` / 双前端 `dist`，即可开始开发改代码测试。

**总下载量约 25GB+**，请预留磁盘空间。

---

## 4. 安装完成后启动服务（由你手动执行）

```powershell
# 【0】桌面端（Windows 桌面机，装完即用，推荐）——前端 dist 已由安装器构建好
# 双击 智影桌面端.exe（构建方法见 desktop/README.md；exe + _internal 放项目根）
# 或开发态等价：python desktop\app.py
# 启动器自动：检查就绪 → docker compose up -d db → 起后端（ZHIYING_FRONTEND=desktop）→ 打开 WebView2 产品窗

# 【1】数据库（PostgreSQL + pgvector）—— 先启动 Docker Desktop
docker compose up -d db
docker ps | findstr zhiying_postgres        # 等到 healthy

# 【2】后端 —— 在项目根执行（开发用 run.py 带 reload；生产用 uvicorn）
.\.venv\Scripts\python run.py
# 或 .\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8011
# 健康检查：http://127.0.0.1:8011/health  →  {"status":"ok","service":"zhiying","version":"<当前版本>","database":"ok"}

# 【3】前端（开发态，可选；生产由后端静态托管 dist）
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
# 访问 http://localhost:5173

# 【4】API key（摘要 vlm_llm 模式需要，可选但推荐）
# 前端 → 设置页 → 系统设置，填 DashScope + DeepSeek key（保存即生效，无需重启）
```

---

## 5. 配置统一（无需 config.windows.yaml / ZHIYING_CONFIG）

一份 `config/config.yaml` 通用所有机器。**config.yaml 已 gitignore 不入库**，两个安装脚本都会在缺失时**自动从 `config/config.yaml.example` 复制生成**（桌面启动器/后端的第一道检查就是它）。
- **路径**：模型/存储相对路径自动解析到项目根（embedder 已对齐 detector，摆脱 cwd 依赖）
- **captioner 自动降级**：配置 `qwen3_vl` 但本地 8B 模型缺失 → 自动切 `qwen_api`（DashScope），启动打醒目 WARNING
- **摘要模式自动转换**：captioner 为 `qwen_api` 时，`native_video` 自动视为 `vlm_llm`（`effective_summary_mode`）。**摘要默认 vlm_llm，native_video 已置灰退役**（前端不再可选；后端保留兼容历史记录，旧视频仍正常处理）；本地 captioner 8B **不再下载**（`download_models.py` 本就不含该项）
- 开发机有本地 8B 模型 → 保持本地推理；部署机无 → 走 API。**同一份配置，无需环境变量**

> `ZHIYING_CONFIG` 环境变量仍保留为"自定义配置文件"的通用覆盖入口（机制无害），但默认部署不需要它。

---

## 6. 故障排查

| 症状 | 原因 / 处理 |
|---|---|
| `torch.cuda.is_available()` True 但推理报 `no kernel image for sm_120` | **Blackwell (RTX 50xx) 装成了 cu126**。安装器按 GPU 自动选 cu130；手动装务必 `--index-url .../cu130` |
| torchvision 报 `torchvision::nms ... CUDA backend` | torchvision 是 CPU 版（PyPI 默认拉）。需装**与 torch 同 CUDA 源**的版本（安装器已处理） |
| 人脸/车牌速度极慢 | onnxruntime 是 CPU 版。确认 `.venv` 里是 `onnxruntime-gpu` 且探针含 `CUDAExecutionProvider` |
| ARM64 上 `pip install onnxruntime-gpu` 失败（找不到匹配版本） | 正常——PyPI 无 aarch64 版 onnxruntime-gpu（仅 x86_64/win_amd64）。`requirements.txt` 环境标记会自动改装 `onnxruntime` CPU 版；ARM64 机器人脸/车牌走 CPU 是预期行为 |
| 模型下载卡死 | pip/直连大文件不稳定 → 安装器用 curl 下载 + 本地安装；GitHub 源必须走代理 |
| `pip check` 警告 `onnxruntime not installed` | 预期现象——部署用 `onnxruntime-gpu`，安装器已建虚拟 `onnxruntime` 桩，pip check 全绿 |
| paddlex 报 numpy 版本冲突 | requirements 已钉 `numpy<2.4`（paddlex 3.7 要求） |
| 抽帧/转码 CPU 占用高 | ffmpeg 无 CUDA（缺 `h264_nvenc`/`h264_cuvid`）→ 安装器自动装 Gyan 完整版 |
| 摘要跑 vlm_llm 但报 key 错 | 设置页填 DashScope/DeepSeek key，或写 `data/settings.json` |
| 代理测试失败（github 000） | 确认代理软件已启动、端口正确、**有可用节点**（端口在监听但路由不通=节点没生效） |
| aarch64（GB10/DGX Spark）torch 装不上 CUDA | `setup_linux.sh` 会提示走 conda：`conda install pytorch torchvision pytorch-cuda -c pytorch -c nvidia`（参考机 GB10 就是 anaconda 环境） |
| Linux 前端构建报 node 版本过旧 | `setup_linux.sh` 自动走 NodeSource 装 v22；失败则手动装 node≥20 后重跑 |
| `config/config.yaml` 缺失 | 安装脚本会从 example 自动生成；缺失时桌面启动器会提示先跑安装脚本 |

---

## 7. 维护与扩展

- **Linux 开发机安装**：`bash deploy/setup_linux.sh`（或 `--proxy http://127.0.0.1:7897 --non-interactive` 全自动）；Windows 用 `setup_windows.ps1`
- **模型下载**：`python deploy/download_models.py --component <x> --model-root models`（断点续传、`--verify-only` 校验）
- **多架构依赖**：`onnxruntime-gpu` 仅 Windows/x86 Linux 有 wheel；ARM64（DGX Spark/GB10）由 requirements 环境标记自动装 `onnxruntime` CPU 版。新增带平台差异的依赖时用 PEP 508 环境标记区分（如 `; sys_platform == "win32" or platform_machine == "x86_64"`）
- **新增会产生磁盘文件的功能** → 落盘路径模式必须登记进 `core/storage_manager.py`
- **新增感知模块** → `pipeline/runners/` 新 runner + `pipeline/operations.py` 一个 Operation，engine 零改动
- **版本号与发布** → 版本唯一事实来源 `core/version.py`；`/health` 返回 `version` 字段（部署/回滚后核对运行版本）；发版用 `./bump minor|patch|0.24.0`（联动改后端 + 前端 + 锁文件，交互式确认提交信息/commit/tag/push）；git tag 必须 `v<版本>` 与 version.py 一致，回滚 = `git checkout` 旧 tag + 重启
- **完整踩坑记录** → 见 `deploy_feedback.md`

## 8. Linux / Windows 环境差异（摘要）

| 维度 | Linux 开发机 | Windows 部署机 | 影响 |
|---|---|---|---|
| torch 安装 | `pip install torch`=CUDA 版 | 默认 CPU 版 | 安装器按 GPU 选源 + 实测 kernel |
| onnxruntime | x86 默认 CPU；**ARM64 无 GPU wheel** | 默认 CPU → 安装器换 onnxruntime-gpu | requirements 环境标记按平台选（win32/x86_64→GPU, aarch64/arm64→CPU） |
| Docker | Linux 原生 | Docker Desktop (WSL2) | 仅用 `db` 服务 + named volume |
| 路径/编码/事件循环 | — | 反斜杠/GBK/Proactor | 代码用 pathlib；安装器处理 BOM/编码 |
| 文件删除 | 允许删打开中的文件 | **打开中的不可删** | 处理中视频可删（v0.22 `core.cancellation` 登记，管道优雅中止）；Windows 打开中文件删除失败 → 清盘逐项 try/except 非致命，残留由孤儿清扫兜底 |

---

*部署问题的完整修复历史见 `deploy_feedback.md`。*
