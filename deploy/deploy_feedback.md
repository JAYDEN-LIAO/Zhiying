# Zhiying 部署实测反馈（deploy_feedback.md）

> 本文件记录在 **Windows 11 Home + RTX 5090 Laptop 24GB 全新机器** 上实测部署时发现的
> 脚本问题、环境坑位与改进建议。随部署进展持续更新。
> 环境快照：Windows 11 26100 / PS 5.1 / Python 3.13 / Docker Desktop 29.6 / WSL2 / NVIDIA 591.91 (CUDA 13.1)
> 注：`deploy/start_windows.ps1` 与 `deploy/write_windows_config.py` 已删除（配置统一 + 后端直接
> `uvicorn main:app` 启动）。历史章节引用它们以记录当时的处理，其"修复/结论"仍适用。

---

## 1. 【脚本 Bug】UTF-8 无 BOM 的中文 `.ps1` 在 Windows PowerShell 5.1 下解析崩溃

- **症状**：`setup_windows.ps1` / `start_windows.ps1` 启动即报 `ParserError: UnexpectedToken`，
  一个步骤都没执行。错误散布在所有含中文的行上。
- **根因**：两个 `.ps1` 是 **UTF-8 无 BOM**。Windows PowerShell **5.1 读取无 BOM 文件一律按 ANSI/GBK 解码**，
  中文多字节序列被拆坏 → 破坏相邻字符串字面量 → 解析失败。
- **修复**：给 `setup_windows.ps1`、`start_windows.ps1` 前置 **UTF-8 BOM（EF BB BF）**，内容逐字节不变。
  验证：`[System.Management.Automation.Language.Parser]::ParseFile(...)` 通过。
- **影响面**：本机只有 PS 5.1（无 pwsh 7）时**必现**。PowerShell 7 默认按 UTF-8 读取，不触发。
- **建议**：
  - 提交时保留 BOM（`git` 不剥 BOM）；或
  - 部署脚本改为纯 ASCII 输出（英文消息），彻底规避编码问题；或
  - 在 `deploy.md` 环境要求里注明「脚本需在 UTF-8 BOM 下提交，PS 5.1 用户注意」。

## 2. 【脚本 Bug】全新环境的 torch / onnxruntime 探针被 `$ErrorActionPreference="Stop"` 误杀

- **症状**：步骤 `[3/9] 检查现有 PyTorch GPU 支持` 直接抛 `NativeCommandError` 中止，
  根本走不到「安装 torch」。全新 venv 上**必现**。
- **根因**：脚本顶部 `$ErrorActionPreference = "Stop"`。全新 venv 未装 torch → `import torch` 失败把
  Traceback 写 stderr → PS 5.1 将原生命令的 stderr 升级为**终止性错误**，`2>$null` 压不住。
  onnxruntime 探针同理（`import onnxruntime` 失败时）。
- **修复**：两个探针（torch、onnxruntime）套 `try/catch`，探不到返回 `$null`，自然落入安装分支。
- **建议**：脚本内对「可能失败的探测性原生命令」统一用 try/catch 或临时
  `$ErrorActionPreference="Continue"` 包裹，不要依赖裸 `2>$null`。

## 3. 【环境/网络】中国大陆网络下代理是刚需，且 Python 与系统代理的差异容易踩坑

实测（梯子关闭时）：
- `github.com` 直连不可达（000）；经代理 `127.0.0.1:7897` 正常（200/302）。
- `download.pytorch.org` 直连 **仅 ~33KB/s**（2.6GB 要 20+ 小时，等于不可用）；经代理正常。
- `modelscope.cn`、`pytorch.org` 直连可达（200）。

关键坑位：
- **Python 进程不读 Windows「系统代理」**（注册表 ProxyEnable）。pip / modelscope / urllib 只认
  `HTTP_PROXY` / `HTTPS_PROXY` **环境变量**。所以「系统代理开着」≠「Python 下载走代理」。
- **winget / Docker Desktop** 走 WinINET（读系统代理）。两者行为不一致，需分别处理。
- `insightface buffalo_l` 模型在 **GitHub**（deepinsight/insightface releases）→ 必须走代理；
  而脚本里 python 下载不读系统代理 → 需显式设 `HTTP(S)_PROXY` 或用 `curl -x` 预下载。
- yolo26s.pt（Ultralytics assets，GitHub）同样必须代理；本次已预下载到 `models/yolo26s.pt` 规避。
- Docker Hub 拉 `pgvector/pgvector:pg17` 建议开系统代理（Docker Desktop 读它）。

**建议**：`deploy.md` 增加「中国大陆网络环境」小节：
- 列出哪些环节必须代理（torch 源 / GitHub 模型）、哪些直连即可（ModelScope / 国内源）；
- 明确「Python 认环境变量、winget/Docker 认系统代理」的差异；
- 提供 `curl -x` 预下载模型的兜底路径，避免 `download_models.py` 在 GitHub 上整体中断。

## 4. 【环境要求】Windows 11 Home 上 Docker Desktop 必须先装 WSL2

- 本机 **WSL 未安装**，Docker Desktop 引擎无法启动（Home 版无 Hyper-V，只能 WSL2 后端）。
- 需 `wsl --install`（管理员 + **重启**），VirtualMachinePlatform 功能生效后才能跑 Docker。
- **建议**：`deploy.md` 环境要求表补充 WSL2 一项（Home 版必装、需重启），并给出一键命令。

## 5. 【其他观察】

- `winget install Gyan.FFmpeg` 输出成功但当前 shell PATH 不刷新 → 部署脚本若在**同一会话**内校验
  ffmpeg 会误报缺失；重开终端即可。本机 PATH 已含 `...\ffmpeg-8.1.2-full_build\bin`（CUDA 全功能）。
- `download_models.py` 的 yolo 下载失败会让 `setup_windows.ps1` 的模型步骤**整体中断**
  （虽然前面已完成的步骤可续跑）。建议：模型组件逐个失败不阻塞、或先 `--verify-only` 列出缺失清单。
- `setup_windows.ps1 -SkipModels` + 独立窗口并行下载大模型（embedding 16GB）是可行的并行路径；
  建议文档补充该用法。

## 6. 【网络补充】Docker Hub 直连不可达；docker / pip / npm 三套国内镜像方案

- **Docker Hub 直连超时**：`docker pull pgvector/pgvector:pg17` 报
  `...connecting to registry-1.docker.io:443: connectex: A connection attempt failed...`
  （Docker Desktop 无代理时直连不通）。
  **免代理解法**：`~/.docker/daemon.json` 加 `"registry-mirrors": ["https://docker.m.daocloud.io"]`
  （直连可达，registry 返回 401 属正常未认证响应），**重启 Docker Desktop 后生效**。
  ⚠️ **实测 daocloud 镜像拉大镜像（pgvector ~400MB）极慢/停滞（15+ 分钟拉不完）**，不可靠。
  **可靠方案**：给 Docker Desktop 配置**手动代理**——`%APPDATA%\Docker\settings-store.json` 加
  `"ProxyHttpMode": "manual"` + `"OverrideProxyHTTP"/"OverrideProxyHTTPS": "http://127.0.0.1:7897"`，
  重启 Docker Desktop 后拉取满速。✅ 本次采用此方案成功拉取 pgvector（627MB）。
  其它可用镜像：`hub-mirror.c.163.com`（实测不可达）、`docker.mirrors.ustc.edu.cn`（可能需认证）。
- **pip 国内镜像**：`pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/`
  → requirements 除 torch 外的所有包免代理安装；torch 由 setup 的 `--index-url` 单独指定（命令行优先于 config），不受影响。✅ 已配置（用户级 pip.ini）。
- **npm 国内镜像**：`npm install --registry=https://registry.npmmirror.com` → 前端依赖免代理。✅ 本次重跑成功（Vite dev server 正常）。注意 npm 11 的 allow-scripts 会拦 esbuild 的 postinstall，但 esbuild 二进制来自平台包（`@esbuild/win32-x64`），不受影响。

## 7. 【教训】并行大下载会抢带宽；下载期间的干扰要避免

- **大文件下载（embedding 16GB）期间不要同时跑 npm install / docker pull 等占带宽任务**，
  会互相拖慢（本次实测：并行后 embedding 单流掉到 ~500KB/s）。大下载应独占带宽。
- 判断大下载是否真的在增长，可用 pip 缓存监控（进度条被重定向时看不到）：
  `%LOCALAPPDATA%\pip\cache\http-v2\**\*.body` 大小随时间增长即在下。
- **modelscope snapshot_download 会 spawn 子进程做并行分片下载**（实测父子进程：
  主进程挂 PowerShell，子进程 CPU 高），**勿把父子进程误判为"重复下载"而乱杀**；
  用 `Win32_Process` 查 `ParentProcessId` 确认关系后再处置。
- **自建临时 .ps1 也要加 UTF-8 BOM**（本次自建的模型下载脚本就踩了 §1 同款编码坑，
  首跑报 ParserError）。任何含中文的 ps1 在 PS 5.1 下都必须带 BOM。
- `download.pytorch.org` 直连实测 ~33KB/s（2.6GB 需 20+ 小时）→ torch 必须走代理。
- **pip 大文件经代理会卡死（实测 25s 0 字节），而 curl 走代理 11MB/s 正常**。原因疑似 pip 的 HTTP
  栈与代理/大文件响应兼容问题。**处置**：torch wheel 用 `curl -L -C - -x 代理 -o <wheel> <url>` 下载
  （断点续传），再 `pip install <本地wheel>`；setup 的 torch 探针发现已装好会自动跳过。
- 国内 pytorch 镜像（阿里云/腾讯 `pytorch-wheels/cu126`）**均无 Windows win_amd64 wheel**，Windows 上
  torch 只能走 download.pytorch.org（代理）。
- **【脚本 Bug #3】setup 的 `Get-TorchIndex` 对 Blackwell GPU 选错 CUDA 构建**：驱动 CUDA ≥12.6 一律选
  `cu126`，但 **RTX 50xx（Blackwell, sm_120/CC 12.0）的 cu126 torch 不含对应内核**。`torch.cuda.is_available()`
  返回 **True 但推理会报 "no kernel image for sm_120"**，`setup` 第 3 步的 GPU 实测校验**假通过**。
  torch 2.13.0 提示需 cu129/cu130/cu132 构建。**本次处置**：改用 `cu130` wheel（驱动 CUDA 13.1 最匹配）。
  建议脚本按 GPU 型号/驱动 CUDA 版本选源：驱动 ≥13.0 → cu130，≥12.6 → cu128/cu129，并**实测
  `torch.zeros(1).cuda()` 跑一个真实 kernel**（而非仅 `is_available()`）来兜底。

## 8. 【发现】pip 大文件下载卡死是通病，curl 兜底是通用方案

- **pip 对"大文件"下载普遍卡死**（不止 torch/proxy）：
  - torch 2.6GB：直连/代理/镜像均卡死；
  - onnxruntime-gpu 241MB：经 **Aliyun 国内镜像** 也卡在 ~100MB 停滞；
  - 小包（transformers 11MB / pillow 7MB / 元数据）均正常。
  → 结论：**>~100MB 的文件下载一律用 curl + 本地 `pip install <wheel>`**，不要依赖 pip 拉大文件。
- **curl `-C -` 断点续传的坑**：若磁盘残留文件是不完整的错误响应（如 HTML 错误页 2318B），
  `-C -` 会把新数据**追加到错误内容之后** → 生成损坏 wheel（`BadZipFile: Bad magic number`）。
  → 下载前先删除残留文件，或下载后用 `zipfile` / `unzip -t` 校验完整性。
- **Aliyun pypi simple index 的 wheel 真实 URL 是相对路径**：index 页里
  `href="../../packages/<hash>/<wheel>"`，直接拼 `…/pypi/simple/<pkg>/<wheel>` 会拿到镜像首页 HTML。
  → 需从 index 页解析出完整 href 再下载。
- **onnxruntime-gpu 换装中断状态**：setup 第 3 步先卸载了 CPU 版 onnxruntime，再下载 gpu 版卡死。
  若中途失败，venv 里 onnxruntime 处于**缺失**状态（`import onnxruntime` 异常），需先装回
  onnxruntime-gpu 再重跑 setup（探针发现 CUDA provider 后会自动跳过换装）。

## 9. 【依赖 Bug】requirements.txt 缺 `accelerate` → embedder 启动失败

- **症状**：`start_windows.ps1` 起后端时报
  `PluginLoadError: ... QwenVLEmbedder: Using a device_map ... requires accelerate`，启动即退出。
- **根因**：embedder（`plugins/embedder/qwen_vl_embedder.py`）用 `device_map`，依赖 `accelerate`；
  `requirements.txt` 未列它。新版 transformers（5.14.1）不再把 accelerate 作为硬依赖自动带上
  （旧版开发机可能是 transformers 顺带装的，部署全新环境就暴露了）。
- **修复**：`pip install accelerate`（本次手动装 accelerate-1.14.0）。
- **建议**：把 `accelerate` 加进 `requirements.txt` 和 `Dockerfile`。

## 10. 【脚本行为】setup 模型步失败后仍显示 [9/9] 完成、退出码为 0

- **现象**：模型步 plate 下载失败（download_models.py 抛 RuntimeError）后，setup 打印了 `[error] 模型准备未完成`
  但仍继续打印 `[9/9] 完成`，且进程退出码为 0。
- **可疑点**：`Invoke-DownloadModels` 返回 `$false` 后本应 `throw "模型准备失败"` 中止，实际未中止。
  疑似 download_models.py 的 stderr（RuntimeError traceback）在 `$ErrorActionPreference="Stop"` 下
  触发了 **NativeCommandError 提前中断**，绕过了后续的 `if/throw` 逻辑，导致脚本走到 [9/9]。
- **建议**：核实该流程；模型步骤失败应可靠地设置非零退出码 + 明确报错，避免"半成品当作完成"。

## 11. 部署结论（2026-08-04）

**部署成功，全栈跑通：**

| 项 | 状态 |
|---|---|
| 后端 | `http://127.0.0.1:8011` — `/health` 200，`{"status":"ok","service":"zhiying","database":"ok"}` |
| 前端 | `http://localhost:5173` — Vite 6.4.3，`/api` 代理到 8011 正常 |
| 数据库 | `zhiying_postgres`（pgvector:pg17）容器 healthy |
| 模型 | embedding 16GB / yolo / face / plate / segmenter **全部就绪** |
| GPU | torch 2.13.0+cu130 真实 kernel 验证通过；embedder 16GB 已载入（显存 15.8/24.5GB） |

**部署流程中的关键踩坑（详见上文各节）：**
1. `.ps1` 无 BOM → PS 5.1 解析崩溃（§1）
2. 探针被 `$ErrorActionPreference=Stop` 误杀 ×2（torch/onnxruntime §2、docker info §4→§2 同款）
3. Blackwell GPU 需 cu130（§7）
4. pip 大文件下载卡死 → curl 兜底（§8）
5. requirements 缺 `accelerate`（§9）
6. plate 模型 WinError 32 文件锁 → 手动解压（§8 后续）
7. Docker 直连不通 → Docker Desktop 手动代理（§6）

**留给用户的手动步骤：**
- 前端设置页填 DashScope + DeepSeek API key（摘要 vlm_llm 模式）
- 上传真实视频做端到端验证（检测/人脸/车牌/搜索）

**已落地在仓库的改动（建议 review 后提交）：**
- `deploy/setup_windows.ps1`：加 BOM + 修复 2 个探针 + docker info 检查（try/catch）
- `deploy/start_windows.ps1`：加 BOM
- `deploy/deploy_feedback.md`：本文档（11 节）

## 12. 配置统一（2026-08-04）— 不再需要 `config.windows.yaml` / `ZHIYING_CONFIG`

**背景**：部署机曾需要独立 `config/config.windows.yaml` + `ZHIYING_CONFIG` 环境变量才能起后端，
因为默认 `config.yaml` 指向本地 8B captioner 模型（部署机未下载）。用户希望「activate 后 uvicorn 就能跑」。
核实后发现三个差异中两个本可消除：路径是 embedder 代码不一致（detector 会解析、embedder 不会），
摘要模式已有 `effective_summary_mode` 自动兜底。真正的差异只有 captioner（本地模型 vs API）这一个资源选择。

**改动（已验证）**：
1. `plugins/embedder/qwen_vl_embedder.py` — 相对模型路径自动解析到项目根（对齐 `yolo.py`），
   HF 模型 ID 保持原样。摆脱 cwd 依赖。
2. `core/config_loader.py` — 新增 `_auto_fallback_captioner()`：`load_config()` 时若 captioner 是
   `qwen3_vl` 但本地模型目录缺失 → 自动降级为 `qwen_api`（DashScope），打醒目 WARNING 日志；
   在 `_apply_settings_overrides` **之前**执行，让设置页注入的 base_url/model 能继承。
3. `deploy/start_windows.ps1` — `$ConfigFile` 改为 `config/config.yaml`，不再设置 `ZHIYING_CONFIG`。
4. 删除 `config/config.windows.yaml`。

**验证结果**（纯 `uvicorn main:app`，无任何 env）：
- `/health` 200，`{"status":"ok","service":"zhiying","database":"ok"}`
- 启动日志出现：`[Config] captioner 本地模型缺失 (...) → 自动降级 captioner 为 qwen_api`
- embedder 经相对路径成功加载（`Embedder loaded, GPU ready`）
- `effective_summary_mode(native_video) → vlm_llm`（摘要走 DeepSeek API）

**保留机制**：`ZHIYING_CONFIG` 环境变量仍可用作「自定义配置文件」的通用覆盖入口（机制无害）；
但默认部署不再需要它。开发机有本地 8B 模型时 captioner 保持 `qwen3_vl` 不受影响。

**遗留**：`deploy/deploy.md` 与 `write_windows_config.py` 仍描述旧的两配置流程，可按需更新为
"单配置 + 自动降级"说明。

## 13. 【首次试跑】ultralytics tracker 的两个运行时坑（2026-08-04）

首次上传真实视频跑管道时，detection/tracking 阶段暴露两个 ultralytics 运行时问题：

**① ReID 模型仍从 GitHub 下载（ultralytics 8.4.115）**
- `config/botsort.yaml` 曾用 `model: "auto"`（CLAUDE.md 声称 8.4 起"检测骨干特征直通、不再下载 ReID 模型"）。
  **实测 8.4.115 仍会下载 `yolo26n-cls.pt`**（ReID 外观模型），GitHub 直连被墙 → 卡死在 7%。
- **修复**：代理预下载 `yolo26n-cls.pt`（5.5MB）到 `models/`，`botsort.yaml` 的 `model` 显式改为
  `"models/yolo26n-cls.pt"` → 本地加载，零下载。

**② torchvision CPU/CUDA 不匹配**
- torch 走 pytorch cu130 源装（2.13.0+cu130），但 **torchvision 是 ultralytics 从 PyPI 默认拉的
  `0.28.0+cpu`（CPU 版）** → 推理时报 `NotImplementedError: Could not run 'torchvision::nms' ... CUDA backend`。
- **修复**：同样从 cu130 源装 `torchvision-0.28.0+cu130`（wheel 仅 9.2MB，链接 torch 的 CUDA 库）。

**③ 顺带**：ultralytics 自动装 `lap>=0.5.12`（BoT-SORT 匹配依赖）成功，但提示"重启才生效"——重启后正常。
建议未来 `requirements.txt` 显式加 `lap` + `torchvision==<torch 对应版本>+cu<ver>`，并在
`download_models.py` 增加 reid（yolo26n-cls.pt）组件，避免运行时自动下载。

**验证**：`model.track(dummy, tracker=config/botsort.yaml)` 完整走通 → `TRACKER_INIT_RESULT=OK`。

## 14. 安装器重写（2026-08-04）— `setup_windows.ps1` 升级为裸机一键安装器

按需求把 `setup_windows.ps1` 从"部署向导"重写为**从零到环境就绪的完整安装器**：
- **安装系统级**：Python（缺失时 winget 装）、FFmpeg（缺失/无 CUDA 编解码时装）、WSL2 + Docker Desktop（缺失时**放最后装**并提示重启，幂等续跑）
- **安装依赖级**：CUDA torch（**按 GPU/驱动选源**，Blackwell→cu130，实测真实 kernel）、匹配 torchvision、requirements 全部包
- **安装模型级**：embedding/yolo/**reid**/face/plate/segmenter（`download_models.py` 新增 reid 组件）
- **代理必填**：开始时强制输入 + 测试；需要代理的 host 走代理、国内源直连、超时自动回退代理
- **交互**：注意事项醒目提示 + 代理输入；错误如实反映终端不闪退
- **边界**：装完自校验 + 打印 db/后端/前端启动指令（用户自行启动）
- 辅助开关：`-NonInteractive`、`-SkipDeps/-SkipModels/-SkipDocker`、`-NoElevate`、`-SkipProxyTest`（排障用）

**测试暴露的 PS5.1 坑（已修进脚本）：**
1. **形参名不能叫 `$Args`**（内置自动变量）——会失效导致无参调用进 REPL（Python 3.13 交互 REPL 在非控制台环境报 WinError 123）。→ 改名 `$ArgumentList`。
2. **`$ErrorActionPreference=Stop` + 原生命令 stderr**：命令写 stderr（如 torch import 警告）时，**进程未退出就抛 NativeCommandError**，`$LASTEXITCODE` 是上一条残留值。→ `Invoke-Native` 执行期间临时切 `Continue`，跑完再恢复。
3. **函数内 `& 命令` 的 stdout 会泄漏成函数返回值** → `$exit = Invoke-Native ...` 收到 `@("cuda-ok", "0")` 数组，`-ne 0` 误判。→ 捕获输出后 `Out-Host` 转交控制台，函数只返回退出码。
4. **Aliyun pypi simple index 的 href** 是 `../../packages/<hash>/<wheel>.whl#sha256=...`：正则要允许 `#sha256` 后缀，相对路径要解析为 `https://mirrors.aliyun.com/pypi/packages/...`。

**onnxruntime CPU/GPU 幂等性缺陷（requirements.txt 已修）：**
- `requirements.txt` 原为 `onnxruntime>=1.18.0`（CPU）。部署装完 onnxruntime-gpu 后，`pip install -r` 会把 CPU 版再装一遍、与 GPU 版**共用 site-packages/onnxruntime 目录**互相踩 → 人脸/车牌静默回退 CPU，且卸载任一版会弄坏共享文件。
- **修复**：`requirements.txt` 改为 `onnxruntime-gpu>=1.18.0`（项目本身全 GPU）；安装器在装 requirements 时**剔除 onnxruntime 行**（`^\s*onnxruntime` 同时匹配两版），gpu 版由脚本 curl + 本地安装统一处理。
- **依赖冲突优雅解决（pip check 全绿）**：
  ① numpy 钉 `numpy>=1.26.4,<2.4`（paddlex 3.7 要求 `numpy<2.4`）；
  ② 创建**虚拟 onnxruntime dist-info 桩**（无文件，仅声明 `Name: onnxruntime` 已装），满足 hyperlpr3/insightface 的
  `Requires-Dist: onnxruntime`，避免 CPU 版被拉回。注：`Provides-Dist` 不被 pip check 识别，故用无文件桩；
  安装器内置 `New-OnnxruntimeStub` 在 onnxruntime-gpu 装完后自动建桩。
- **教训**：在已配置好的机器上跑"完整安装测试"会重装依赖、踩坏现有环境。测试应针对脚本逻辑片段（URL 解析/探针/退出码）而非全流程。

**遗留**：`deploy/deploy.md` 仍描述旧的两配置 + 部署向导流程，需更新为新安装器说明。

---

*最后更新：2026-08-04（部署完成 + 配置统一 + 安装器重写）*
