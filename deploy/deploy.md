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
| `setup_windows.ps1` | **Windows 一键安装器**（开发机入口 = 根目录 `install1.bat` 双击交互；客户端 = Inno 安装器静默调用非交互）：选 **2B/8B** + 输代理 → Python/FFmpeg → .venv + CUDA torch + 依赖 → **内嵌 PostgreSQL**(`vendor/pg`，免 Docker/WSL2；组装完删 `vendor/pg-zips` 源 zip) → 模型(按档位) → 生成 config.yaml → init_db 建表 → **WebView2 Runtime 自动更新**（<151 过旧会 pywebview 静默白屏，下载 Evergreen 更新到最新，失败仅告警） → 校验完成（前端构建交给 `install2.bat`）。**非交互参数**（Inno 安装器用）：`-EmbeddingProfile/-Proxy/-Quiet/-ProgressLog/-DoneMarker/-OutputLog`——进度行 `PROGRESS\t<pct>\t<slug>` 供安装器轮询，退出码写 DoneMarker；**镜像策略**：pip 走清华镜像、CUDA torch 官方源走代理（失败自动回退阿里云 `pytorch-wheels` find-links 直连） |
| `setup_linux.sh` | **Linux 开发机一键安装器**（开发态，规格同 Windows）：apt / venv / CUDA torch / requirements+onnxruntime / 模型 / Docker db / config.yaml / Node+前端 dist |
| `build_backend_pyc.py` | 后端源码编译为 `.pyc` 字节码包 → `build/backend_pyc/`（封装模式：客户端盘上无明文源码；**用 `py_compile` 生成包根 legacy `<模块>.pyc`**——compileall 的 `__pycache__/*.cpython-XX.pyc` 在无源时 Python 不可导入，会致封装后端 `No module named 'core.db'` → exe 白屏；`build_exe.ps1` 打 exe 前调用） |
| `download_models.py` | 模型下载/校验（embedding 按 `--embedding-profile 8b/2b` 选档，yolo/reid/face/plate/segmenter，断点续传、`--verify-only`；**safetensors 下载后 `safe_open` 校验头部**——续传拼接产坏则删除重下） |
| `stop_runtime.ps1` | 卸载前停桌面壳 + 内嵌 PostgreSQL（Inno `[UninstallRun]` 调用；容忍全部错误，宁 immediate 强停不带锁删除） |
| `iss-lang/` | Inno Setup 中文语言包（`zhiying.iss` `[Languages]` 引用，构建必需随仓库走） |
| `deploy_feedback.md` | 部署实测问题与修复历史（踩坑记录，含本次所有修复的说明） |

> 旧 `write_windows_config.py`（生成 config/config.windows.yaml）与 `start_windows.ps1`（后端启动脚本）已删除——
> 配置已统一、启动直接用 `uvicorn main:app`，不再需要独立部署配置或启动脚本。

---

## 2. 环境要求

| 依赖 | 说明 |
|---|---|
| **Windows 10/11** | **无需 Docker / WSL2**——数据库用内嵌便携 PostgreSQL（`vendor/pg`，安装器自动组装） |
| **NVIDIA GPU + 驱动** | 脚本检测 `nvidia-smi` + CUDA 版本，按驱动选 cu124/cu126/cu130 装 PyTorch；缺失则报错中止（不自动装驱动） |
| **FFmpeg** | 缺失自动 winget 装 Gyan.FFmpeg（需含 h264_nvenc/h264_cuvid CUDA 编解码） |
| **embedding 档位** | 安装时交互选 **2B / 8B**——决定装哪个模型 + 向量维度（2B=2048 / 8B=4096）+ config `embedding_profile`；一台机器一个模型 |
| **磁盘 25GB+** | torch ~2.6GB + 模型（embedding 8B 16GB / 2B ~4GB）+ 其余 |
| **代理（可选）** | 安装时交互输入；GitHub / PyTorch / 模型源被墙需走代理，国内源直连 |
| **WebView2 Runtime** | 桌面端 exe（pywebview）必需。过旧（<151，pywebview 6.2.1 需 ICoreWebView2Environment10）会**静默白屏**（实测 runtime 100 报 COM E_NOINTERFACE）——`install1` 自动检测并下载 Evergreen 安装器更新到最新，失败仅告警不中断（服务器后端不依赖） |
| **OCR DirectML（v0.34）** | OCR 用 RapidOCR(PP-OCRv3 ONNX) + onnxruntime-DirectML。DML 版 onnxruntime **不在 requirements 直装**，由 `install1`(setup_windows.ps1) / `install2` 幂等装到 **`vendor/ort_dml`**（隔离子进程用，不污染人脸/车牌依赖的全局 onnxruntime-gpu/CUDA）。`rapidocr-onnxruntime` 在 requirements 常规安装 |

---

## 3. 快速开始

### 3.0 Windows 安装器交付（客户端骨架包，Inno Setup 6.2.1）

面向最终用户的交付形态：**单个安装 exe**（不含模型、不含明文后端源码）。

```powershell
# 构建（项目根；前置：Inno Setup 6.2.1 + 已跑过 install1 的 .venv）
powershell -ExecutionPolicy Bypass -File desktop/build_installer.ps1
# 可选：-EmbeddingProfile 2b（2B 机器专用包）、-Version 1.0
# 产物：Bin\智影视频智能检索平台 Ver <版本>.exe（gitignored；交付上 SVN TestVersion）
```

流程与约定：
- `zhiying.iss`（仿 云侠.iss 骨架）：向导 = 选目录 → **档位页**（8B/2B 在线下载 | **自备模型导入**：路径校验 `models\Qwen` 锚 + robocopy 前置复制，不依赖环境安装成败）→ **代理页**（预填 `http://127.0.0.1:` 只补端口）→ 安装
- 安装期隐藏跑 `setup_windows.ps1`（非交互参数，见 §1）；**单进度条**（解压复用 Inno 原生条，环境安装由自建条接管）= setup 离散真实标记 + 安装器侧蠕动平滑（pip 接管道非 TTY 无进度条可解析）；等待循环每轮 ProcessMessages 泵消息防窗口假死，**90 分钟超时兜底**
- **骨架包不含 25GB 模型**：首启桌面壳 check_models 缺失 → `State.MODEL_BOOT` → `desktop/model_bootstrap.py` 后台跑 `download_models.py`（断点续传，档位写回 config.yaml），下载面板可改档位/代理/重试
- **交付面清理**：装完删安装耗材（`requirements.txt` / `deploy\setup_windows.ps1` / `desktop\db.py` / `manifest.json`）；卸载 = `stop_runtime.ps1` 停壳停 pg → `[UninstallDelete]` 清 `.venv`/`vendor`（保留 `data/` 用户数据与 `models/` 自备模型）

### 3.1 Windows 桌面机（desktop 路径，全新机）

全新 Windows（可能只有 git、连 python 都没有）：**U盘 / git clone 把源码放好** → **双击根目录 `install1.bat`**（或 `deploy\setup_windows.ps1`）。

**交互安装（命令行窗口）**：
1. 选 embedding 档位：**1 = 8B（Qwen3-VL-Embedding-8B，4096 维，需 ~16GB 显存）/ 2 = 2B（Qwen3-VL-Embedding-2B，2048 维，低显存平替）** —— 一台机器一个模型，向量维度随选择定死（`embedding_profile`）
2. 输代理地址（GitHub / PyTorch / 模型下载用；能直连可留空）

**自动托管（6 步）**：
1. **Python**（缺失时 winget 装 3.13）+ **FFmpeg**（Gyan 完整版，含 CUDA 编解码 h264_nvenc/h264_cuvid；**curl 走代理 + 断点续传下载**并加入 PATH，不再依赖 winget/github 直连）
2. **`.venv`** + **CUDA 版 PyTorch + torchvision**（同一 cuXXX 源，避免 torchvision 从 PyPI 拉到 CPU 版）+ requirements 依赖（**预置 onnxruntime 虚拟桩**，防 hyperlpr3/insightface 传递依赖拉回 CPU 版互相踩）+ **GPU 验证**
3. **内嵌 PostgreSQL**：下载 EDB PG17 便携 zip + andreiramani 预编译 pgvector（PG17）→ 组装 `vendor/pg`（**无 Docker / 无 WSL2 / 无重启**；本地 `vendor/pg-zips/` 有 zip 则优先使用，不联网）
4. **模型**（按档位下 embedding + yolo/reid/face/plate/segmenter；**embedding 走 modelscope 直连 + 断点续传**，github 组件走代理）
5. **生成 `config/config.yaml`**（`embedding_profile` 由选择写死 + `database.uri` 指向内嵌 pg 端口 5432）
6. **起 `vendor/pg` + `init_db` 建表** → 校验 → 完成

**下载健壮性（v0.34候选部署）**：
- 所有下载（FFmpeg / PG zip / 模型）均有**超时兜底 + 断点续传 + 实时进度**；pip 用 `--progress-bar raw` 显示大文件进度，不再静默。
- **代理策略**：`github.com` / `download.pytorch.org` / `enterprisedb.com` **走代理**（直连不通或极慢）；**`modelscope.cn` 强制直连**（国内 CDN，绕国际代理反而更慢更易断）。
- 网络波动时模型下载**断线自动续传**（`.incomplete` 保留），不白丢进度；任何错误落盘 `vendor/install.log` 并红字显示，不会无声闪退。
- **WebView2 Runtime 自动更新**（环境段）：检测版本（注册表 pv + 兜底扫 `EdgeWebView\Application` 目录），<151 下载 Evergreen 安装器 `/silent /install` 更新到最新——过旧 pywebview 会**静默白屏**（pywebview 6.2.1 需 ICoreWebView2Environment10，实测 runtime 100 报 COM E_NOINTERFACE）；失败仅告警不中断（服务器后端不依赖）。
- **构建健壮性**（`build_exe.ps1`）：部署前 **pg_ctl 幂等停内嵌 postgres**（常驻 daemon 从旧 `_internal` 加载 MSVC 运行库锁 DLL → `_internal` 删不掉；ErrorActionPreference 降 Continue 防 stderr 炸脚本 + 轮询 / immediate 强停 / 硬杀三级兜底）。

**装完即用**：双击根目录 `install2.bat`（git pull + 依赖 + 前端 npm build + 重打 exe）做日常更新/构建，或 `python desktop\app.py` 直接跑桌面端。

> **总下载量约 25GB+**（torch ~2.6GB + embedding 8B 16GB / 2B ~4GB + 其余模型），请预留磁盘空间。

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
4. 建 `.venv` + **生成 `config/config.yaml` + bump 命令接入 PATH**（软链 `~/.local/bin/bump`）
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
# 【0】桌面端（Windows 桌面机，装完即用，推荐）
# 双击 智影桌面端.exe（构建方法见 desktop/README.md；exe + _internal 放项目根）
# 或开发态等价：python desktop\app.py
# 启动器自动：检查就绪 → 起内嵌 PostgreSQL（vendor/pg，首次自动 initdb+建库，已在运行则 pg_isready 探测直接复用）→
#             起后端（ZHIYING_FRONTEND=desktop）→ 打开 WebView2 产品窗

# 【1】数据库（内嵌 PostgreSQL，装完即由启动器自动托管，无需手动）
#     vendor/pg（便携 PG17 + pgvector）+ data/pgdata（数据目录）+ 端口 5432
#     开发机也可用 docker compose up -d db（db.py 自动回退检测）

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
- **embedding 档位**：顶层 `embedding_profile: 8b|2b` 决定「加载哪个 embedder 模型 + 向量表维度（4096/2048）」（`core/embedding_profile.py` `EmbedVector()` 建表时读档位维度）。安装器按交互选择写死；改档需重建向量库（维度不同）
- **路径**：模型/存储相对路径自动解析到项目根（封装模式由 `ZHIYING_PROJECT_ROOT` 注入 exe 所在目录）
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
| 桌面端 exe 打开白屏（无任何提示） | **WebView2 Runtime 过旧**（pywebview 6.2.1 需 ≥151，实测 runtime 100 报 COM E_NOINTERFACE）。`install1` 已自动更新到最新；仍白屏则手动重装 Evergreen（`go.microsoft.com/fwlink/p/?LinkId=2124703`） |
| `install2` 重打 exe 时 `_internal` / exe 删不掉（提示占用） | 内嵌 postgres 常驻 daemon 从旧 `_internal` 加载 MSVC 运行库锁 DLL。`build_exe.ps1` 部署前已幂等 `pg_ctl stop`（三级兜底）；残留可手动 `vendor\pg\bin\pg_ctl -D data\pgdata stop` |
| 封装后端 exe 白屏 + 日志报 `No module named 'core.db'` | `build_backend_pyc.py` 已改 `py_compile` 生成包根 legacy `.pyc`（compileall 的 `__pycache__` 形式无源时 Python 不可导入）；重跑 `build_backend_pyc.py` + `build_exe.ps1 -Deploy` |
| embedder 加载失败 `header too large` | 断点续传拼接产坏 `model.safetensors`。`download_models.py` 已加 `safe_open` 头部校验，损坏自动删除重下；可 `--verify-only` 校验 |
| 桌面启动器误报「模型未齐全」卡白屏（2B 机器） | `desktop/checks.py` 已读 `config.yaml` 的 `embedding_profile` 传给 `verify`（不再默认查 8B 目录）；确认 config 里 `embedding_profile: 2b` |

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
| 数据库 | Docker db（`docker compose up -d db`） | **内嵌便携 PostgreSQL**（`vendor/pg` + `data/pgdata`，桌面启动器自动 initdb/起停） | `desktop/db.py` 双模式：vendor/pg 存在走内嵌（封装交付），否则回退 docker（开发机） |
| 路径/编码/事件循环 | — | 反斜杠/GBK/Proactor | 代码用 pathlib；安装器处理 BOM/编码 |
| 文件删除 | 允许删打开中的文件 | **打开中的不可删** | 处理中视频可删（v0.22 `core.cancellation` 登记，管道优雅中止）；Windows 打开中文件删除失败 → 清盘逐项 try/except 非致命，残留由孤儿清扫兜底 |

---

*部署问题的完整修复历史见 `deploy_feedback.md`。*
