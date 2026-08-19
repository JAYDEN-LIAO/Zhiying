# 文件库 / 多版本解析 / 任务中心 — 后端实施计划（方案 B：版本 = videos 行链）

> 依据智影 v2 演示三块能力，基于现有 Zhiying 地基实现。
> **复核结论（2026-08-13）**：原「方案 A 产物表加 version_id」与真实 schema 冲突——`transcripts.video_id` UNIQUE、`tracks` UNIQUE(video_id,track_id)、`face_identities` UNIQUE(video_id,identity_label)、`Video.transcript` 一对一、`bulk_insert_scenes` 不先删旧。**废弃 A，采用 B**：
> **每版一次解析 = 一个 `videos` 行**，产物天然按 video_id 隔离，零产物迁移、唯一约束/ORM/persist 全不动。

## 一、核心模型（最小改动）

### 1.1 `videos` 加两列
```
├─ file_id   UUID null, indexed       # 逻辑文件 ID：首次解析时生成，同文件后续版本共享
└─ version_no int null                 # 每文件版本号 1,2,3…；唯一索引 (file_id, version_no)
```

- **文件** = 该 `file_id` 的**根 videos 行**（文件元信息 file_path/name/size/duration/format 就存在根行上，**不新建 files 表，零数据重复**）
- **版本** = `file_id` 相同的多行 videos（各自 `video_id` → 产物/搜索/检测/人脸天然隔离，**现有端点直接作用于版本行**）
- **遗留视频**（`file_id` NULL）= 独立文件（自身即版本 1，向后兼容零迁移）
- **reanalyze** = 复制根文件信息建新 videos 行 + 写 `file_id` + `version_no` 递增（复用 `reuse` 的复制机制）

### 1.2 `video_groups` 加列（② 案例）
- `number` String null（文件编号）、`owner` String null（负责人）

### 1.3 任务日志（③，当前无日志系统）
- 无现成日志机制（`pipeline_tasks.error` 单列）。**新增 `task_logs` 表**（`task_id, seq, level, message, created_at`）或 `videos.log` Text 列，由管道状态钩子写行。选型待定（见 5）。

## 二、迁移（core/db.py init_db 增量）
- `ADD COLUMN IF NOT EXISTS file_id/version_no` on videos + 唯一索引
- `ADD COLUMN IF NOT EXISTS number/owner` on video_groups
- `CREATE TABLE IF NOT EXISTS task_logs`（若采用）

## 三、管道改造（加性，不碰产物写入）
- `services/video_service.py`：`reanalyze(video_id, params)` = 建版本行（复制 file 信息 + file_id/version_no）→ 入队管道；`process_video(version_id)` 不变
- `engine.py`：无需改 persist（产物按 video_id 写，版本行自带隔离）；仅 `_set_processing`/tracker 同时镜像版本行状态（可选，`videos.status` 就是版本状态，无需额外镜像）
- **日志钩子**：status_tracker/engine 各阶段写 `task_logs`（新增）

## 四、后端端点（全为新增，现有不动）
| 能力 | 端点 | 说明 |
|---|---|---|
| ② 文件 | `GET /files` | 每 file_id 一行（根行信息 + 当前版本状态/摘要），含遗留 NULL |
| ② 组 | `GET/POST /groups`、`PUT/DELETE /groups/{id}` | 组 CRUD（name/number/owner） |
| ① 版本 | `GET /videos/{id}/versions` | WHERE file_id 相同（或自身 standalone） |
| ① 重解析 | `POST /videos/{id}/reanalyze` | 建版本行 + 入队 {params} |
| ③ 任务 | `GET /tasks?scope`、`GET /tasks/{id}/log`、`POST /tasks/{id}/retry` | 读版本行 + task_logs；retry = 重跑同版本 |
| 现有 | `GET /videos/` | **改为只返回根文件**（避免版本行刷屏） |

## 五、待定小决策
1. 任务日志：`task_logs` 一对多表（干净）vs `videos.log` Text（轻量）——推荐 `task_logs`（健壮，日志可增长）
2. `DELETE /groups/{id}` 组内有视频：清 `group_id`（SET NULL）vs 拒绝——推荐清空（与现有 FK 一致）
3. 删除「文件」= 删该 file_id 全部版本行（CASCADE 产物）；删除「单个版本」= 只删该行

## 六、实施顺序
1. DB：videos +file_id/version_no、video_groups +number/owner、task_logs
2. Repository/schemas：文件/版本/任务 DTO + 查询 helper
3. 管道：reanalyze 服务 + 日志钩子
4. 组端点 + 文件列表（②）
5. 版本端点（①）+ 版本切换
6. 任务端点（③）+ retry
7. 对接层 + 桌面前端（FileLibrary/Workbench 版本切换器/TaskCenter）
8. 服务器前端最小接入
9. bump 发版 + 部署 + 验证

## 七、风险/注意
- **版本行复制 file 信息**：删除源文件语义要理清（file_id 根行删除 = 删整个文件族）
- **`GET /videos/` 列表过滤**：改成根文件语义，现有服务器前端兼容性需回归
- **并发 reanalyze**：`(file_id, version_no)` 唯一索引兜底版本号冲突
- **incremental**：作用于当前版本行（其 video_id），天然隔离
