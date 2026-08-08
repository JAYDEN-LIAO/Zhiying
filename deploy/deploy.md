# Zhiying Windows 部署指南（deploy/）

> 目标：把 Zhiying 后端跑在 **全新的 Windows + NVIDIA GPU 机器** 上。
> 做法：双击 `deploy/setup_windows.ps1`，脚本**自动安装一切**——Python / FFmpeg / WSL2 / Docker Desktop /
> CUDA torch / 全部 Python 依赖 / 全部模型。装完自校验，并打印数据库/后端/前端启动指令（由你自己启动）。
>
> 原则：**开发机上能用的功能，部署机必须能用；所有推理尽量 GPU，禁止静默退化成 CPU。**
>
> 本指南以 Windows 部署为主线；项目同时支持 Linux x86 与 **ARM64（DGX Spark/GB10）**，平台间唯一硬差异是 onnxruntime（见 §6），由 `requirements.txt` 环境标记自动处理。

---

## 1. deploy/ 目录

| 文件 | 作用 |
|---|---|
| `setup_windows.ps1` | **裸机一键安装器**：探测环境 → 复用兼容项、补装缺失项 → 装系统/依赖/模型 → 自校验 → 打印启动指令 |
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

## 3. 快速开始（裸机）

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\deploy\setup_windows.ps1                    # 交互式（输入代理，看注意事项）
# 或全自动（需先开代理）：
.\deploy\setup_windows.ps1 -Proxy http://127.0.0.1:7897 -NonInteractive
```

脚本会：
1. 请求管理员权限（UAC）
2. 打印注意事项 + 强制输入代理地址并测试
3. 探测 Python / FFmpeg / Docker / WSL2 / GPU，**复用兼容项、补装缺失项**
4. 装 Python（缺失时 winget）→ venv → CUDA torch（按 GPU/驱动选源，Blackwell 自动 cu130）→ 匹配 torchvision → requirements → onnxruntime-gpu → accelerate/lap
5. 下载全部模型（embedding / yolo / reid / face / plate / segmenter）
6. 数据库：WSL2 已装则直接配置 Docker + 拉 pgvector；WSL2 缺失则**放最后装 WSL2 + Docker Desktop** 并提示**重启**
7. 自校验（模型齐全 + CUDA kernel 实测）→ 打印启动指令

**WSL2 缺失时的两段式**（Home 裸机常见）：
- 第一段：装完除 WSL2/Docker 外的一切 + 校验通过 → 脚本提示重启
- 重启后再双击一次脚本 → 检测到 WSL2 就绪 → 补拉 pgvector 镜像 → 完成（可选，不重跑也行，见 §4 启动指令）

**总下载量约 25GB+**（torch ~2.6GB + embedding 16GB + 其余模型），请预留磁盘空间。

---

## 4. 安装完成后启动服务（由你手动执行）

```powershell
# 【1】数据库（PostgreSQL + pgvector）—— 先启动 Docker Desktop
docker compose up -d db
docker ps | findstr zhiying_postgres        # 等到 healthy

# 【2】后端 —— 在项目根执行
.\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8011
# 健康检查：http://127.0.0.1:8011/health  →  {"status":"ok","service":"zhiying","version":"<当前版本>","database":"ok"}

# 【3】前端
cd frontend
npm install --registry=https://registry.npmmirror.com
npm run dev
# 访问 http://localhost:5173

# 【4】API key（摘要 vlm_llm 模式需要，可选但推荐）
# 前端 → 设置页 → 系统设置，填 DashScope + DeepSeek key（保存即生效，无需重启）

# 【5】桌面启动器（Windows 桌面机推荐，可选）
# 直接双击 desktop/desktop.bat —— 内部自动：检查模型齐全 → docker compose up -d db → uvicorn main:app
# → 打开 WebView2 窗口加载前端 dist（日志面板）→ 优雅关闭。桌面构建用默认 env 即可
# （VITE_YUNZHI_MOCK 缺省即 mock 本地上传，无云智 Bridge）。
```

---

## 5. 配置统一（无需 config.windows.yaml / ZHIYING_CONFIG）

一份 `config/config.yaml` 通用所有机器：
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

---

## 7. 维护与扩展

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
