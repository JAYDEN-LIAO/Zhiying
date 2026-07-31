# 视频格式兼容问题 — 调查记录与完整修复方案

> 状态：**调查完成，方案已定稿，尚未实施**（2026-07-31）。
> 本文件完整保留调查过程、证据链、根因与后续施工方案，供实施时直接参考。
> 关联：`docs/arch.md`（架构）、`services/format_service.py`、`frontend/src/hooks/useStreamReady.ts`。

---

## 1. 问题报告

**复现**：上传 `/home/tj/Desktop/video2/ch01_20260721000000.mp4` 后，浏览器立即在播放器区域显示 **「没有找到支持的视频格式和 MIME 类型」**（Chromium 原生错误文案，应用代码里不存在此字符串）。**刷新页面**后，从历史记录重新进入该视频，可以正常播放，也可以正常处理（Pipeline）。

**用户实际影响**：仅此一个文件需要刷新；历史记录里其余视频（mp4/h264、mp4/hevc）均能瞬时访问与处理。

---

## 2. 调查过程与证据

### 2.1 文件本身 —— 不是 MP4

对文件做 `file`、`xxd`、`ffprobe` 三路检测：

| 探测项 | 结果 | 结论 |
|---|---|---|
| `file` 命令 | `data` | 魔数非标准 MP4 |
| 魔数（前 4 字节） | `49 4d 4b 48` = **"IMKH"** | 海康威视（Hikvision）NVR 导出专有文件头 |
| ffprobe 容器 | `format_name=mpeg` → **MPEG-PS (MPEG-2 Program Stream)**, probe_score=52 | 实际容器是 PS，不是 MP4 |
| 视频流 | H.264 1920×1080 25fps, `is_avc=false`, 无 codec_tag, 流 id `0x1e0`（PS 典型 PES 流 ID） | 单一 H.264 视频流，无音频 |
| 时长/大小 | 1036.04s（约 17 分钟）/ 520MB | |
| 文件名 | `ch01_20260721000000.mp4` | NVR 通道号+时间戳命名，与海康模式吻合 |

**判定**：海康 DVR/NVR 导出的 **MPEG-PS 容器 + H.264** 录像，扩展名挂 `.mp4`。`classify_container("mpeg")` → `"mpeg_ps"`（`utils/metadata.py:67`）。

### 2.2 前端调用链 —— 就绪判定只看编码

`frontend/src/hooks/useStreamReady.ts:21`：

```ts
if (vc === "h264") return true;   // 无条件判定"流就绪"，完全忽略容器维度
```

- 上传响应一返回（含同步 probe 出的 `video_codec="h264"`），`streamReady=true`。
- `VideoPlayer.tsx` 立刻渲染 `<video src="/videos/{id}/stream?hevc_ok=…">`。

### 2.3 后端调用链 —— 兜底分支把原文件错标 MIME

`services/format_service.py` `get_stream_target()` 对 `(mpeg_ps, h264, none)` 的判定：

1. 步骤1 浏览器原生检查（`_is_browser_native`，`:431`）：`("mpeg_ps","h264","none")` 不在 `_BROWSER_NATIVE_FORMATS` → **跳过**
2. 步骤1.5 MP4+HEVC+Safari：不适用（h264）
3. 步骤2 remuxed（`:450`）：上传时 `remuxed_path` 仍为 NULL（remux 异步未完成）→ **跳过**
4. 步骤3 proxy（`:465`）：h264 不在需转码编码表 → **跳过**
5. 步骤4 未探测（`:486`）：`container_format` 非空 → **跳过**
6. **步骤5 兜底（`:493-502`）**：`file_path = row.remuxed_path or row.file_path` → **把原始 PS 文件原样返回，硬编码 `Content-Type: video/mp4`**

### 2.4 上传时序 —— 同步 probe + 异步 remux

`api/video_routes.py:131-135`：

```python
await format_service.probe_and_save(video.id, dest_path)          # 同步，格式信息立即入库
asyncio.create_task(format_service.process_format(video.id, dest_path))  # 异步 remux（数秒）
```

上传响应返回时 `remuxed_path=NULL`；remux 要把 520MB 重新封装，需要数秒。

### 2.5 数据库实锤

实际系统中该记录（`248fd208-…`）：

```
file_name | container_format | video_codec | audio_codec | has_audio | remuxed_path | proxy_status
ch01_20260721000000.mp4 | mpeg_ps | h264 | NULL | f | data/videos/248fd208-…_remuxed.mp4 | none
```

- `remuxed_path` 现在已存在（`ls` 确认 519MB，ffprobe 确认是合法 `mov,mp4,m4a,…` MP4 + H.264）。
- 其余 4 个视频全部 `container_format=mp4`（h264 或 hevc），走原生路径从不出问题。
- **全部 5 个视频 `proxy_path` 均为 NULL** → 佐证第 4.1 节 HEVC proxy 死锁。

### 2.6 为什么刷新后能播

刷新时 remux 已完成，`remuxed_path` 入库 → `get_stream_target` 步骤2（`:450-456`）返回真正 MP4 → 浏览器正常播放。前端对 h264 恒判定 ready、`streamReady` 从不翻转，`VideoPlayer.tsx:41-45` 的重载仅在 `streamReady` 变化时触发 → **必须手动刷新，无自动恢复**。

---

## 3. 根因

**前后端就绪判定标准不一致 + 后端兜底无安全网**：

1. 前端 `useStreamReady` 以**编码**（h264→永远可播）为唯一就绪依据，忽略**容器**维度。
2. 后端在 remux 完成前，对「编码浏览器可播、容器浏览器不可播」的组合**没有等待机制**——既不返回 202，也不等 remux，直接把原文件配错 MIME 发出（步骤5 与 `_mime_for` 默认值都硬编码 `video/mp4`）。

**通用性**：机制上是通用竞态，被「非 mp4/webm/ogg 容器 + H.264 编码」这一类触发（mkv/mov/avi/flv/mpeg_ts/mpeg_ps 均会踩中）。标准 mp4+h264 走 `_is_browser_native` 快路径不出问题。HEVC/AV1/mpeg4 等编码因前端会等 `proxy_status=="ready"`、后端会走 202，也不踩中——**唯独 h264 这条路没有等待机制**。

---

## 4. 调查中发现的其它潜伏缺陷（未实施）

> 均为代码级确认、但用户实际未触发的缺陷，按"完整方案"一并纳入修复范围。

### 4.1 HEVC proxy 死锁（重要）
- `useStreamReady` 对非 h264 编码要求 `proxy_status==="ready"` 才渲染 `<video>`；而 proxy 仅在 `get_stream_target`（被 `/stream` 触发）里懒生成；`/stream` 仅被 `<video>` 加载触发 → **循环依赖，proxy 永不生成**。
- DB 实锤：`手机.mp4`（mp4/hevc/aac）`proxy_status="none"`、`proxy_path=NULL`，在 Chrome/Firefox 下会永远转圈。
- `/proxy-status` 端点（`video_routes.py:610-633`）是纯读，不触发任何工作。

### 4.2 `useVideoPolling` 在 completed 后停轮询 → 状态冻结
- `useVideoPolling` 仅当 `status ∈ {pending, processing}` 时轮询 `getVideo`；completed 后停止。
- 因此已完成视频的 `currentVideo.proxy_status` / `remuxed_path` 冻结 → 即使后端生成了 proxy/remux，前端 `streamReady` 也不翻转。
- **推论**：修复 4.1 光靠后端触发不够，必须让前端轮询 `/proxy-status` 携带**实时的、后端算好的 `stream_ready`**。

### 4.3 wmv/wmv3 无法 remux 进 MP4
- `remux_to_mp4` 对 wmv/wmv3 会失败（mp4 muxer 拒绝 wmv3）→ 这类必须走 proxy，不能走 remux。需引入 `_can_remux_to_mp4(info)`。

### 4.4 mp4 + 非浏览器音频（opus/ac3）→ 无声
- `needs_remux = container not in (mp4,webm,ogg)` 只看容器，`mp4+h264+opus` 不会被 remux，浏览器无声。
- 需 `_needs_remux` 纳入音频维度：`container=="mp4" and audio ∉ {aac,mp3} → remux`。

### 4.5 `/videos/reuse` 不探测格式
- `reuse_video`（`video_routes.py:255-306`）创建记录后不调用 `probe_and_save`/`process_format` → 复用记录 `container_format=NULL`，流路由会 202 永久、前端"正在分析视频格式…"卡死。

### 4.6 损坏文件 → 202 永久
- `probe_and_save`（`:548-560`）probe 失败仅 log，**不落任何失败状态** → `container_format=NULL` 永远 → `get_stream_target` 永久 202。

### 4.7 崩溃残留 `processing`
- remux 中途 kill 服务 → `format_status`（若引入）或当前无状态；`proxy_status="processing"` 残留会让懒触发永远跳过 → 永久等待。需启动对账重置。

### 4.8 并发 remux/proxy 无防护
- `remux_to_mp4` 只有 `os.path.exists` 跳过，两个并发请求会双跑 ffmpeg（第二个 `-y` 覆盖）。
- 需 DB CAS 抢注 + 进程内 in-flight 集合。

### 4.9 来源分析品牌丢失（文件名 bug）——**已在 B 中修复**
- `api/video_routes.py:722` 把 `os.path.basename(file_path)`（UUID 重命名后的存储名）传给 `classify_video_source`，原始文件名丢失 → 海康文件名模式 `ch\d+_\d{14}\.mp4` 永不命中，`surveillance_brand=null`。
- 已在本项目后续工作中通过「改用 `row.file_name` + 文件魔数嗅探」修复（见 `docs/arch.md` 来源分析 / `utils/video_source.py`）。

---

## 5. 完整修复方案（未实施）

### 5.1 设计原则

1. **`format_status` 状态列**（容器标准化生命周期）：`none` / `processing` / `ready` / `failed`，与 `proxy_status`（编码转码生命周期）正交，不再互相占用。
2. **后端 `_route_decision(row, hevc_ok)` 纯函数**是唯一路由决策源，`get_stream_target` 与 `/proxy-status` 共用；前端通过 `/proxy-status` 轮询拿到后端权威的 `stream_ready`。
3. **永不把非原生容器以错误 MIME 返回**：`_mime_for` 全量映射；非原生容器未 remux 完成 → 202 等待而非直出。
4. **所有后台工作可幂等重入**：DB CAS 抢注（`format_status none|ready → processing`）+ 进程内 in-flight 集合 + 原子 `tmp → os.replace` 写盘。
5. **崩溃自愈**：启动时重置 stale `processing`；remux/proxy 任务在任何请求路径（上传/复用/轮询）都能被重新调度。

### 5.2 后端改动

**`core/models.py`**：`Video` 加 `format_status: Mapped[str]`（`String(16)`, default `"none"`）。

**`core/db.py` `init_db()`**：
- `ALTER TABLE videos ADD COLUMN IF NOT EXISTS format_status VARCHAR(16) DEFAULT 'none' NOT NULL`
- 启动对账（每次启动幂等执行）：
  - `UPDATE videos SET format_status='none' WHERE format_status='processing'`
  - `UPDATE videos SET proxy_status='none', proxy_progress=0.0 WHERE proxy_status='processing'`

**`core/schemas.py`**：
- `VideoResponse` / `VideoListItem` 加 `format_status: str = "none"`。
- `ProxyStatus` 扩为 `{status, progress, proxy_path, format_status, remuxed_path, stream_ready}`。

**`services/format_service.py`**（核心）：
- 常量：`_NATIVE_CONTAINERS = frozenset({"mp4","webm","ogg"})`；`_mime_for` 全量映射（mp4→video/mp4, webm→video/webm, ogg→video/ogg, mpeg_ts→video/mp2t, mpeg_ps→video/mpeg, mkv→video/x-matroska, mov→video/quicktime, avi→video/x-msvideo, flv→video/x-flv, wmv→video/x-ms-wmv）。
- 新静态方法：
  - `_needs_remux(info)`：`container ∉ NATIVE` 或（`container=="mp4"` 且 `has_audio` 且 `audio_codec ∉ {aac,mp3}`）。
  - `_needs_proxy(info)`：`codec ∈ {hevc,av1,wmv3,mpeg4,prores}` 或 `container=="wmv"`。
  - `_can_remux_to_mp4(info)`：`container≠"wmv" and codec≠"wmv3"`。
- `__init__`：加 `self._remux_in_flight: set[uuid.UUID]`、`self._proxy_in_flight: set[uuid.UUID]`。
- `probe_and_save`：成功 → 存格式信息（status 留 `none` 待抢注）；异常 → `_set_format_status('failed')` 并返回 None。
- `process_format`（eager）：入口 `format_status=='failed'` 直接 return；读 info；若 `_is_browser_native` 或 `not _needs_remux` 或 `not _can_remux_to_mp4` → `_set_format_status('ready')`；否则 `await self._schedule_remux(video_id)`。
- `remux_to_mp4`：输出改 `{id}_remuxed.mp4.tmp`，成功 `os.replace(tmp, final)`；保留 final 路径 exists-skip。
- 并发/懒触发：
  - `_claim_remux(video_id) -> bool`：CAS `UPDATE videos SET format_status='processing' WHERE id=$1 AND format_status IN ('none','ready')`。
  - `_schedule_remux(video_id)`（async）：in_flight 防重 + CAS + `create_task(_run_remux)`。
  - `_run_remux(video_id)`：`remux_to_mp4` → 成功存 `remuxed_path` + `ready` / 失败 `failed`；`finally` discard。
  - `_schedule_proxy(video_id, source)` / `_run_proxy(video_id, source)`：同上，调 `transcode_proxy`。
  - `ensure_format_work(video_id)`：failed 守卫；`container NULL + none` → 兜底 probe；`_needs_remux` 且缺 remuxed → schedule remux；`_needs_proxy` 且缺 proxy 且 `proxy_status=='none'` → schedule proxy（source=remuxed-or-original）。
- `_route_decision(row, hevc_ok)` → 纯 `(action, file_path, media_type, source)`，action ∈ {serve, remux, proxy, failed, wait}：
  1. `_is_browser_native(info)` → serve original（正确 MIME）
  2. `mp4 + hevc + hevc_ok` → serve original
  3. `remuxed_path` 存在且 on disk：h264 → serve remuxed；hevc+hevc_ok → serve remuxed；`_needs_proxy` → proxy(source=remuxed)；否则 → serve remuxed
  4. `_needs_proxy` 且（container ∈ NATIVE 或 `not _can_remux_to_mp4`）→ proxy(source=original)
  5. `format_status=='failed'` → failed（→ 415）
  6. `container is None` → wait
  7. `_needs_remux` 且 `_can_remux_to_mp4` → remux
  8. `container ∈ NATIVE` 且文件存在 → serve original（正确 MIME）
  9. → wait
- `get_stream_target`：调 `_route_decision` 后按 action 执行副作用；failed → `HTTPException(415)`。
- `_update_format_error` → 改设 `format_status='failed'`。

**`api/video_routes.py`**：
- `reuse_video`：加 `probe_and_save` + `create_task(process_format)`。
- `get_proxy_status`：加 `request` + `hevc_ok`；先 `ensure_format_work`；SELECT 扩到全部格式字段；`stream_ready = (_route_decision(...).action == "serve")`；返回扩展 ProxyStatus。
- `stream_video`：202 detail 改 "Format processing in progress"。

### 5.3 前端改动

**`frontend/src/types/index.ts`**：`VideoResponse`/`VideoListItem` 加 `format_status`；`ProxyStatus` 加 `format_status`/`remuxed_path`/`stream_ready`。

**`frontend/src/services/api.ts`**：`getProxyStatus(videoId, hevcOk)`。

**`frontend/src/hooks/useProxyStatus.ts` → `useFormatStatus.ts`**：
- `useFormatStatus(videoId, active, hevcOk, onReady)`；`active=needsFormatWork`。
- `videoId` 变化先 `setStatus(null)`（防上一视频残留）。
- 轮询 `/proxy-status?hevc_ok=…`，`stream_ready || format_status=='failed' || status=='failed'` 停止；`stream_ready` 调 `onReady`（`videoRef.load()`）。

**`frontend/src/hooks/useStreamReady.ts`**：
```ts
if (formatStatus?.stream_ready !== undefined) return formatStatus.stream_ready;  // 后端权威
if (video.format_status === "failed") return false;
return isBrowserNative(video, hevcOk);  // 瞬时路径：仅原生直出；其余交给轮询
```
`isBrowserNative` 用 `BROWSER_NATIVE_COMBOS: Set<string>` 精确镜像后端 `_BROWSER_NATIVE_FORMATS`（audio key 归一化：`!has_audio ? "none" : audio_codec`）。镜像 false 只导致多余轮询，绝不把坏流喂给浏览器。

**`frontend/src/Dashboard.tsx`**：`needsFormatWork = video_codec 存在 && format_status!=='failed' && !isBrowserNative(...)`；`formatStatus = useFormatStatus(...)`；`streamReady = useStreamReady(currentVideo, hevcOk, formatStatus)`；`proxyStatus` 传参替换为 `formatStatus`。

**`frontend/src/components/VideoPlayer.tsx`**：
- 失败 overlay：`video.format_status==='failed' || formatStatus?.status==='failed'`（区分格式处理失败 / 代理生成失败文案）。
- spinner 文案：`formatStatus?.format_status==='processing'` → "正在转换视频格式…"；`formatStatus?.status==='processing'` → "正在生成浏览器兼容代理…"（保留进度条）。

### 5.4 边界情况覆盖表

| 场景 | 行为 |
|---|---|
| mpeg_ps+h264 remux 前 | 202 + 懒触发 remux，前端 spinner，自动恢复（本 bug） |
| mpeg_ps+h264 remux 后 | serve remuxed MP4 |
| mp4+hevc+Chrome | /proxy-status 轮询触发 proxy → 进度条 → 播放（死锁修复） |
| mp4+hevc+Safari | 原生直出 |
| mkv+hevc+Chrome | 先 remux 后 proxy（`ensure_format_work` 顺序保证） |
| wmv/wmv3 | 不 remux（mp4 拒绝 wmv3），直接 proxy |
| webm+vp9/av1+opus | 原生直出 |
| mp4+vp9+opus | remux 转 AAC → serve remuxed（无 proxy 悬挂） |
| probe 失败/损坏文件 | `format_status=failed` → 415 + 前端终态错误 |
| remux 失败 | `format_status=failed` → 415 |
| remuxed 文件被删 | CAS 从 `ready` 抢注 → 自动重 remux |
| 崩溃残留 processing | 启动对账重置 + 原子 tmp 写盘 + 任务级 finally |
| `/videos/reuse` | 新增 probe + process |
| 已 completed 视频的延迟 remux/proxy | /proxy-status 轮询携带 `stream_ready` 解决状态冻结 |
| 删除中处理 | DB UPDATE 0 行不崩溃；孤儿文件与现状一致（非回归） |

### 5.5 验证方案

1. **后端纯函数单测**（新建 `tests/test_format_service.py`）：`_needs_remux`/`_needs_proxy`/`_can_remux_to_mp4`/`_mime_for`/`_route_decision` 判定矩阵（项目当前无测试框架）。
2. **本 bug 回归**：curl 上传海康文件（新记录）→ 立即 `GET /stream` 应 202 → 数秒后 200 `video/mp4`；浏览器前端 spinner → 自动播放，无需刷新。
3. **现有 5 视频无回归**：mp4/h264 直出字节一致；`248fd208`（remuxed 已存在）直接 serve remuxed；`9bf42bd1`（mp4/hevc）Chrome 下生成 `_proxy.mp4` → 播放。
4. **崩溃自愈**：remux 中途 kill 服务 → 重启（对账重置）→ 重新请求自动重 remux；删除 remuxed 文件 → 自动重生成。
5. **前端**：`npm run dev` 真实交互。

---

## 6. 涉及文件清单（完整版实施时）

| 层 | 文件 |
|---|---|
| 后端模型/迁移 | `core/models.py`、`core/db.py` |
| 后端 Schema | `core/schemas.py` |
| 后端服务 | `services/format_service.py`（核心重构） |
| 后端路由 | `api/video_routes.py` |
| 前端类型/API | `frontend/src/types/index.ts`、`frontend/src/services/api.ts` |
| 前端 Hooks | `frontend/src/hooks/useProxyStatus.ts`（→useFormatStatus）、`frontend/src/hooks/useStreamReady.ts` |
| 前端组件 | `frontend/src/Dashboard.tsx`、`frontend/src/components/VideoPlayer.tsx` |
| 测试 | `tests/test_format_service.py`（新建） |

---

## 7. 关键代码位置速查

- `services/format_service.py`：
  - `_BROWSER_NATIVE_FORMATS` `:31-42`、`_is_browser_native` `:177-183`
  - `probe_and_save` `:548-560`、`process_format` `:564-620`
  - `remux_to_mp4` `:194-260`（exists-skip `:208-210`）
  - `get_stream_target` `:397-502`（兜底 `:493-502`）
  - `_mime_for` `:504-512`、`_update_format_error` `:533-544`
- `api/video_routes.py`：upload `:54-137`（probe `:133` + async process `:135`）、`reuse_video` `:255-306`、`stream_video` `:562-607`、`get_proxy_status` `:610-633`
- `frontend/src/hooks/useStreamReady.ts:21`（`if (vc==="h264") return true`）
- `frontend/src/hooks/useProxyStatus.ts`、`frontend/src/hooks/useVideoPolling.ts`（completed 后停止）
- `frontend/src/components/VideoPlayer.tsx:41-45`（streamReady 变化重载）、`:56-89`（spinner/video 条件渲染）
- `frontend/src/Dashboard.tsx:87-97`（needsProxy + useProxyStatus）
