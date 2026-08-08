# 智影桌面端（desktop/）

Windows 桌面机（有 NVIDIA GPU）的本地启动器：管理本地后端生命周期——**检查模型齐全 → 起 Docker db → 起 uvicorn → 开 WebView2 窗口加载前端 dist → 日志面板 → 优雅关闭**。壳技术 pywebview（Windows 系统自带 WebView2），纯 Python、纯新增，**不改动任何现有前后端/部署代码**。

## 前置（一次性）

沿用 `deploy/setup_windows.ps1` 的装机流程，确保：

1. `.venv` 已建（Python 3.13 + 全部后端依赖 + **`pip install pywebview`**，见 `desktop/requirements.txt`）。
2. 模型齐全：`python deploy/download_models.py --component all --model-root models --verify-only` 返回 0（含 embedding/yolo/reid/face/plate/segmenter；**不含 captioner 8B**——摘要走 API 模式）。
3. Docker Desktop 运行中（`desktop.bat --check` 会验证）。
4. `config/config.yaml` 已从 `config/config.yaml.example` 复制并按机器修改（至少改 `storage.video_dir/artifact_dir`；`database.uri` 默认 `localhost:5432`，与 docker-compose 的 db 服务对齐）。
5. 前端已构建：`cd frontend && npm run build`（默认 env 即可——`VITE_YUNZHI_MOCK` 缺省即本地模式，无云智 Bridge）。

## 使用

```bat
desktop.bat            # 启动桌面端（双击即可）
desktop.bat --check    # 先自检：config/模型/端口/Docker，输出报告后退出
```

或手动：`python desktop/app.py [--check] [--no-window] [--debug]`

启动后：
- **主窗**：启动页（阶段进度）→ 后端就绪后自动跳转本地前端界面（`http://127.0.0.1:<port>`）。
- **控制窗**：实时日志 + 状态徽标 + 按钮（打开浏览器 / 打开日志目录 / 退出）。
- 关主窗 = 整体退出（优雅停后端；数据库容器保持运行，下次秒启）。

> 端口取自 `config/config.yaml` 的 `server.port`（默认 8011）。桌面端后端**强制绑定 127.0.0.1**（config 里配 0.0.0.0 也不会暴露到局域网）。

## 故障排查

| 症状 | 处理 |
|---|---|
| 启动页报「未找到 config/config.yaml」 | 复制 `config/config.yaml.example` 为 `config/config.yaml` 并修改 |
| 启动页报「模型未齐全」 | 运行 `python deploy/download_models.py --component all`，完成后重启启动器 |
| 启动页报「Docker 不可用 / 数据库未就绪」 | 确认 Docker Desktop 已启动；必要时手动 `docker compose up -d db` 观察 |
| 端口被占用 | 报「端口 X 被其它程序占用」→ 改 `config.yaml` 的 `server.port` |
| WebView2 缺失 | Win10/11 自带；极简安装报错时去微软官网装「WebView2 Runtime」 |
| 后端就绪但界面白屏 | 前端没构建：`cd frontend && npm run build`，然后重启启动器 |
| 摘要不生成 / 报 API 错 | 摘要默认 `vlm_llm`（API 模式），需在前端设置页填 DashScope（画面描述）+ DeepSeek（摘要）key |

## 文件

```
desktop/
├── app.py              # 入口：--check / --no-window / GUI 三模式 + 生命周期状态机
├── state.py            # 生命周期状态机 + 线程安全全局状态
├── checks.py           # 环境检查（config / 模型 verify / 端口 / Docker / /health）
├── db.py               # docker compose db 服务管理（up / 健康等待）
├── backend.py          # uvicorn 子进程（启动 / 日志管道 / /health 轮询 / 优雅关停 / 崩溃监测）
├── logs.py             # 线程安全日志汇聚（环形缓冲 + 落盘 + 增量拉取）
├── webview_panel.py    # 主窗启动页 + 控制窗日志面板（内嵌 HTML，无构建步骤）+ js_api
├── requirements.txt    # 额外依赖（pywebview）
├── desktop.bat         # Windows 入口
└── README.md           # 本文件
```
