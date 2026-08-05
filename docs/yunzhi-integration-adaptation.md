# Zhiying 接入云智平台：改动、适配、对齐与交接记录

> 分支：`feature/yunzhi`（未合并，未提交）
> 日期：2026-08-05
> 前置阅读：`docs/arch.md`（Zhiying 架构）、`docs/yunzhi-integration-plan.md`（接入方案）、云智平台侧三份资料（`existing-frontend-application-bridge-integration.md`、`react-antd(1)`、`extension-automation-demo (2)`）

## 1. 背景与目标

Zhiying 作为扩展应用模块并入公司内部云智（Yunzhi）智能平台。两个需求：

1. 本地文件上传改为平台 SDK，从平台文件库选择文件。
2. 暴露一个异步非阻塞接口，立即返回开始处理，再通过平台已有回调接口汇报进度。

两份需求分别对应云智平台的两种接入形态：交互式扩展应用（iframe + Bridge）与后台自动化任务（Manifest automations + 任务回调）。两者均已实现，其中需求 2 已通过本地全链路验证，需求 1 的代码已实现，真实宿主握手待服务器联调阶段验证。

## 2. 需求到实现的映射

| 需求 | 实现方案 | 实现层 |
|---|---|---|
| 需求 1：上传改为 SDK | 前端使用 `bridge.files.select()` 从平台文件库选文件，取得服务器绝对路径 `absolutePath`；后端新增 `POST /api/v1/videos/register-external`，按共享路径就地引用注册视频（不传输文件字节），源文件标记为平台所有（`source_owned=false`） | A3（前端）+ A1（后端） |
| 需求 2：异步非阻塞 + 进度回调 | 新增 `POST /internal/yunzhi/jobs`（根路径挂载，非 `/api/v1`），立即返回 `202 {accepted, bizTaskId}`；后台执行 Zhiying 管道，进度通过 `callback.progressUrl` 上报，完成/失败通过 `callback.completeUrl` / `callback.failUrl` 上报 | A2（后端） |

两个需求互补：需求 2 由平台文件库上传自动触发，在平台任务中心可见进度；需求 1 供用户在 Zhiying iframe 内交互式选择并查看分析结果。

## 3. 改动清单

### 3.1 A1 后端：共享路径注册与存储卫生

目的：平台共享文件就地引用（不复制、不转字节），且删除视频时不得误删平台源文件。

| 文件 | 改动 | 说明 |
|---|---|---|
| `core/models.py` | `Video` 新增 `source_owned` 列（Boolean，默认 `true`，非空） | 源文件所有权标志；平台共享文件置 `false` |
| `core/db.py` | 增量迁移 `ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_owned boolean DEFAULT true NOT NULL` | 已有库启动 `init_db()` 自动补列 |
| `core/schemas.py` | `VideoCreate` 增加 `source_owned` 字段（默认 `true`）；新增 `ExternalVideoRegister` 请求 DTO（继承 `PipelineParams` + `file_path`/`file_name`）；`VideoResponse` 增加 `source_owned` | 请求/响应 DTO 对齐 |
| `api/video_routes.py` | 新增 `POST /api/v1/videos/register-external` | 校验共享文件存在且非空，`os.path.getsize` 取大小，`source_owned=false` 建记录，同步 probe + 异步 remux/proxy，与上传流程一致 |
| `core/storage_manager.py` | `remove_video_artifacts` 增加 `source_owned` 参数 | 当 `source_owned=False` 时跳过 unlink 原始源文件（平台共享文件归平台所有）；remux/proxy 仍按引用清理 |
| `core/repository.py` | `delete_video` 删除前捕获 `source_owned` 并透传；`create_video` 构造时传入 `source_owned` | `create_video` 传参为验证阶段修复的问题 1（见第 6 节） |

### 3.2 A2 后端：自动化任务接口

目的：实现云智扩展自动化任务契约（对照 `extension-automation-demo/server.py`）。

| 文件 | 改动 | 说明 |
|---|---|---|
| `core/schemas.py` | 新增 `YunzhiJobPayload` / `YunzhiJobFile` / `YunzhiJobTask` / `YunzhiJobCallback` | job 请求体契约，`extra="allow"` 容忍平台扩展字段 |
| `api/yunzhi_routes.py` | 新增 `POST /internal/yunzhi/jobs`（根路径挂载） | 立即 202；按 `Idempotency-Key` 或 `eventId` 幂等去重（进程内登记）；`bizTaskId = yunzhi-{automationJobId}`；后台 `asyncio.create_task` 执行 |
| `services/yunzhi_job_service.py` | 新增 `run_yunzhi_job` / `default_params_for_operation` / `post_callback` / `_write_report` | 共享文件 → 建视频（`source_owned=false`）→ probe + 异步 remux → 推 5% 进度 → 跑管道 → 按 DB 终态回 complete/fail；结果指针 JSON 写入平台 `workDirectory` |
| `core/status_tracker.py` | `StatusTracker` 增加可选 `on_progress(progress, message)` 回调 | `update()` / `mark_completed()` / `mark_failed()` 触发；回调异常吞掉，不阻塞管道 |
| `pipeline/engine.py` | `PipelineEngine` 增加 `progress_callback` 参数，新增 `_new_tracker()` 辅助 | 三处 `StatusTracker` 构造统一走 `_new_tracker`，注入回调 |
| `services/video_service.py` | `process_video` / `_process_video` 增加 `progress_callback` 透传 | 复用并发限流（`max_concurrent_videos`）、GPU 锁、删除取消登记 |
| `main.py` | 根路径挂载 `yunzhi_router` | `/internal/yunzhi/jobs` 不走 `/api/v1` 前缀，平台按应用后台地址直调 |

补充：job payload 支持携带 `params` 对象覆盖默认参数（白名单限定为默认参数集合内的键），用于平台按自动化任务类型定制参数，亦用于轻量验证（跳过摘要链路）。

### 3.3 A3 前端：Bridge SDK 集成

目的：平台宿主模式下用 Bridge 从文件库选文件，替换本地文件上传。

| 文件 | 改动 | 说明 |
|---|---|---|
| `frontend/src/platform/yunzhi-bridge.ts` | 新增，自云智 React 脚手架原样复制 | Bridge 协议、类型与消息收发；保留全部 Origin/sessionId/protocol 校验 |
| `frontend/src/platform/client.ts` | 新增 | 真实 Bridge / Mock 切换（`VITE_YUNZHI_MOCK`，缺省 true）；可选 Ticket 转交 |
| `frontend/src/platform/YunzhiProvider.tsx` | 新增 | React Context，提供 `context/resources/connect/selectFiles/selectFolders` |
| `frontend/src/platform/mock-yunzhi-client.ts` | 新增 | 独立开发模拟数据（视频文件） |
| `frontend/src/main.tsx` | 根组件包裹 `YunzhiProvider` | Bridge 生命周期与整个应用一致 |
| `frontend/src/Dashboard.tsx` | `useYunzhi`；新增 `registerExternal`；`handleUpload` 按模式分流 | 平台宿主模式（`mock=false`）走 `bridge.files.select()` → `registerFromPath`；独立开发（mock 默认）保持本地上传 |
| `frontend/src/services/api.ts` | 新增 `registerFromPath(filePath, fileName, params)` | 调 `POST /videos/register-external` |
| `frontend/src/vite-env.d.ts` | 增加 `VITE_YUNZHI_*` 类型声明 | ImportMetaEnv 扩展 |
| `frontend/.env` | 新增 `VITE_YUNZHI_HOST_ORIGIN` / `VITE_YUNZHI_MOCK` | 缺省 mock=true；联调置 false 并配精确宿主 Origin |

### 3.4 验证工具与文档

| 文件 | 说明 |
|---|---|
| `scripts/mock_yunzhi_platform.py` | 本地 mock 平台回调服务器，监听 `/progress` `/complete` `/fail` 记录回调，用于本地全链路验证 |
| `docs/yunzhi-integration-plan.md` | 接入方案与决策记录 |

### 3.5 本地环境修复（不涉及 git 改动）

| 项 | 说明 |
|---|---|
| ReID 模型路径 | 本机 `yolo26n-cls.pt` 位于 `weights/`，而 `config/botsort.yaml` 指向 `models/yolo26n-cls.pt`；已建软链 `models/yolo26n-cls.pt -> ../weights/yolo26n-cls.pt` 修复（`models/`、`weights/` 均 gitignored，纯本机操作）。部署到服务器时模型必须放在 `models/`，避免运行时触发 GitHub 下载 |

## 4. 与平台契约的对齐情况

### 4.1 已对齐（有资料依据）

| 契约项 | 依据 | 实现 |
|---|---|---|
| 202 立即返回 `{accepted, bizTaskId}` | `server.py` `do_POST` | `api/yunzhi_routes.py` |
| 回调携带 `X-Yunzhi-Job-Token` 头 | `server.py` `post_json` | `services/yunzhi_job_service.py` |
| 进度、完成、失败三回调 | `server.py` `callback.progressUrl/completeUrl/failUrl` | 已实现 |
| `eventId` / `Idempotency-Key` 幂等 | `server.py` 幂等登记 | 已实现（进程内） |
| 结果写入平台 `workDirectory` | `server.py` 报告文件约定 | `_write_report` 写 `zhiying-result.json` |
| 文件经共享绝对路径就地读取 | bridge 文档 6.1 节 | `register-external` 就地引用 |
| Bridge SDK 原样接入 | bridge 文档第 3、5 节 | `frontend/src/platform/` |
| Mock / 真实宿主切换 | bridge 文档 `.env` 约定 | `client.ts` |

### 4.2 未对齐或待部署阶段完成

| 项 | 现状 | 完成阶段 |
|---|---|---|
| 真实 Bridge 握手与 `files.select` | 需平台 iframe 环境 | 服务器联调（B3） |
| Zhiying 专用 Manifest（automation 接受视频扩展名） | 未创建 | 平台登记（B2） |
| iframe CSP `frame-ancestors` 与 nginx `try_files` 回退 | 未配置 | 部署（B1） |
| Ticket 转交与后端会话端点 | 前端有 stub，后端未实现 | 视平台鉴权要求 |
| 分析产物 `saveToLibrary` 登记回文件库 | 未实现（开放项） | 视产品决策 |

## 5. 验证结果（本地，2026-08-05）

验证环境：DGX Spark（GB10，统一内存）、`zhiying_postgres`（pgvector:pg17）、本地样本视频（`/home/tj/Desktop/video1/`）。测试链路统一走检索 + YOLO 检测，跳过摘要链路。

| 阶段 | 内容 | 结果 |
|---|---|---|
| V0 | `source_owned` 列迁移 | 通过：`boolean default true` |
| V1 | 共享路径注册 → 删除不误删源文件 | 通过（修复问题 1 后）：注册返回 `source_owned=false`，DB 确认，删除 `freed_bytes=0`，平台源文件原封不动 |
| V2 | jobs 全链路：202 → 进度回调 → complete + 结果文件 + 幂等 | 通过（修复问题 2 后）：回调序列 5 → 26 → 87 → 99 → complete；`resultData.videoId` + `workDirectory/zhiying-result.json`；同 eventId 重发返回同一 bizTaskId 且不重复处理；管道真实产出 `frame_detections:45`、`tracks:9`、`track_embeddings:9`、`frame_embeddings:19`、`scenes:1` |
| V3 | 前端独立模式 + 构建 | 通过：`tsc --noEmit` 与 `vite build`（61 模块）无错误；浏览器点验独立模式上传/列表/播放正常 |
| V4 | 回归：普通上传 → 管道 → 搜索 → 删除清盘 | 通过：上传（`source_owned=true` 默认）→ 管道约 25s 完成 → 语义搜索返回结果 → 删除清盘 8.8MB |

## 6. 验证中发现并修复的问题

| 问题 | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 共享视频删除后平台源文件被误删 | `create_video` 构造 `Video` ORM 时未传入 `source_owned`，落到模型默认 `true`，StorageManager 按自有文件 unlink | `core/repository.py` `create_video` 增加 `source_owned=video_dto.source_owned` |
| 2 | 管道正常完成但 `completeUrl` 发送失败，走 fail 兜底 | `completeUrl`/`failUrl` 发送在 `httpx.AsyncClient` 的 `async with` 块之外，块退出客户端已关闭，报 `client has been closed` | `services/yunzhi_job_service.py` 将状态查询与 complete/fail 发送整体移入 `async with` 块内 |

验证本身的价值：问题 1 属存储卫生高危缺陷（会删平台数据），问题 2 属异步资源生命周期缺陷，均未进入部署即被拦截。

## 7. 开放项与待决策

1. 分析产物是否需要登记回平台文件库（`bridge.files.saveToLibrary`）。当前实现为最小闭环：分析数据留在 Zhiying，平台仅获得 `videoId` 指针，结果经 Zhiying iframe 展示。若平台期望产物文件入文件库，需在完成回调阶段补充登记逻辑。
2. 自动化任务默认参数（`default_params_for_operation` 当前默认开启 detection + search + caption + summary）。是否与平台对每个自动化任务类型的期望对齐，需确认。
3. Ticket 转交是否需要后端会话端点。仅当平台要求应用后端鉴权时实现。
4. 真实宿主握手与 `files.select` 的功能验证，依赖服务器联调。

## 8. 部署与联调路线

部署目标：`10.0.0.176`（openEuler 24.03，2×L20，根分区 90% 满，数据与项目须置于 `/home`）。

1. B1 服务器基线：编译带 CUDA 的 ffmpeg（现存 6.1.1 无 CUDA，NVDEC/NVENC 会静默退 CPU）→ `/home/zhiying` venv 与依赖 → 模型（含 reid，必须置于 `models/`）→ `docker pgvector/pgvector:pg17` → nginx 托管前端 dist + 后端反代 → systemd 托管 uvicorn。GPU 以 `CUDA_VISIBLE_DEVICES=1` 固定 GPU1（vLLM 已占 GPU0）。
2. B2 平台登记：应用标识、入口 URL、Entry Origin、接入方式（iframe + Bridge）、后台服务地址与 `/health` 健康路径、Zhiying 专用 Manifest（automation 接受视频扩展名）。
3. B3 联调：按 `existing-frontend-application-bridge-integration.md` 第 11 节清单逐项验证（Origin/CSP、文件选择、任务中心进度、子路由刷新、Ticket 仅转发一次、无遗留 Timer/WebSocket）。
4. 平台文件库与 Zhiying 必须共享同一套绝对路径视角（Zhiying 以宿主 venv 运行，天然同视角，需确认平台文件库根路径）。

## 9. 交接注意事项

1. 源文件所有权：凡 `source_owned=false` 的记录，其 `file_path` 指向平台共享文件，Zhiying 删除视频时绝不 unlink 该文件。新增任何会触发磁盘删除的功能须遵循此约定。
2. ReID 模型路径：`config/botsort.yaml` 的 `model: "models/yolo26n-cls.pt"` 必须真实存在，否则 ultralytics 回退 GitHub 下载（实测 8.4.115 会下载）。本机已软链修复；服务器部署须直接放置于 `models/`。
3. 进度回调粒度：Zhiying 按操作阶段上报进度（每视频约数次），不同于 demo 的每秒上报；平台任务中心若需更平滑的进度展示，可考虑在回调层做节流或插值。
4. jobs 路由在根路径：`/internal/yunzhi/jobs` 不经 `/api/v1` 前缀，挂载于 `main.py`。改动路由装配时勿将其移入 API 前缀。
5. 回调客户端生命周期：`run_yunzhi_job` 中所有平台回调必须在共享 `httpx.AsyncClient` 的 `async with` 块内发送，块外发送会报 `client has been closed`。
6. 幂等登记为进程内集合：单 worker 有效；若部署多 worker，需将幂等登记迁移至数据库或共享存储。
7. 前端模式：`VITE_YUNZHI_MOCK` 缺省 `true`（独立开发走本地上传）；真实联调须置 `false` 并配置精确 `VITE_YUNZHI_HOST_ORIGIN`（协议 + 主机 + 端口，禁 `*`）。
8. job 参数覆盖：payload 内 `params` 仅接受默认参数集合内的键，防注入 `file_path` 等字段。
9. 验证工具 `scripts/mock_yunzhi_platform.py` 可复用于联调阶段模拟平台回调。
