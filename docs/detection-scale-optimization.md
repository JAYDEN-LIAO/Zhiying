# Detection 大规模数据渲染链路 — 完整优化方案

> 状态：**S0-S4 ✅ 已实施**（2026-07-31）。S0 gzip + rAF 暂停 + 惰性 best；S1 tracks/detections 接口拆分 + 缩略图读盘/落盘 + face 瘦身；S2 useDetectionRanges 区间加载 + Overlay 改造 + 旧端点删除；S3 DetectionPanel 虚拟滚动 + DetectionTimeline Canvas 化；S4 打磨（元素生命周期修复 + useDetectionRanges LRU 淘汰/网格化 + Timeline memo + 空筛选提示）。附：S3 上线后元素生命周期 bug 已修复（时间轴空白 / 检测栏 5 条），根因=effect 捕获元素引用但对挂载/卸载无感知，统一改为"effect 依赖=元素存在性门禁"。
> 关联：`docs/arch.md`（架构）、`docs/format-compat-fix.md`（既有方案文档惯例）。
> 决策：D1 Canvas 时间轴直上 ✅ | D2 缩略图**惰性落盘（读盘优先 + miss→ffmpeg→写盘）** ✅ | D3 虚拟滚动手写零依赖 ✅（见 §3.1）
> 修订：v1.1 自审查修正（落盘时机对齐缝合 / face detections 瘦身 / gzip 排除流 / 细节 5 项）
> 修订：v1.2 影响性审查修正（best 准则改最大面积=缩略图零变化 / 旧视频惰性补算=零回退 / 缩略图入 StorageManager 目录 / S0 去 useTransition / 校验清单与影响分析表）
> 修订：**v2.0 施工评审修正（本版）** — A2/A3 坍缩为**单一惰性路径**：`/detection/tracks` 用 SQL 惰性算 best（`frame_detections` DISTINCT ON 最大面积）+ 按 video_id 内存缓存；缩略图端点**读盘优先 + miss→ffmpeg→写盘**。**零 DB 迁移（仅加一个索引）、零 Pipeline 改动**（不再触碰 detection.py / track_encode.py / engine.py / VideoContext）。thumbnail URL 带 `track_id`（磁盘缓存文件名依赖它）。旧 `/detection/data` 去留统一为**删除**（同仓硬切）。Canvas 时间轴修正"尺寸恒定"表述（高度随 laneCount 增长，需垂直滚动）。
> 涉及：`api/detection_routes.py`、`core/models.py`（frame_detections 加索引）、`core/db.py`、
> `frontend/src/hooks/useDetectionData.ts`、`frontend/src/components/DetectionPanel.tsx`、
> `DetectionTimeline.tsx`、`DetectionOverlay.tsx`、`frontend/src/types/index.ts`、`main.py`。

---

## 1. 问题报告

**复现**：长视频（≥30min，10fps 检测）处理完成后，可能产生**数千条 track**。此时：

1. **物体检测栏**（DetectionPanel）直接渲染全部 track 行（每条含缩略图 `<img>`），浏览器卡死；
2. **时间轴**（DetectionTimeline）每个 track 独占一行，渲染出几千个绝对定位 DOM 节点；
3. 缩略图是**实时 ffmpeg 抽帧**，几千个 track 触发几千次 ffmpeg 进程，后端雪崩；
4. 每个 track 渲染时对全量检测数据做 `getThumbBbox` 全表扫描（O(tracks×detections)）。

**性质**：不是单点 bug，而是**后端一次性吐全量数据 → 前端无虚拟化全量渲染 → 缩略图实时计算**三层叠加的架构性缺陷。长视频下必然出现，视频越长越严重。

---

## 2. 现状诊断

### 2.1 数据量级（1 小时视频 @10fps）

| 项目 | 数量 | 说明 |
|---|---|---|
| frame_detections 记录 | **10 万+ 条** | 36000 帧 × ~3 检测/帧 |
| `/detection/data` 单次响应 | **~10–15 MB** | 全量 JSON，前端 `JSON.parse` 卡主线程数百 ms |
| tracks | **~3000 条** | 用户报告的数量级 |
| 前端 DOM 节点 | **3000 button + 3000+ 时间条 div** | 无任何虚拟化 |
| 缩略图 HTTP 请求 | **~3000 个** | 每个 = 一次实时 ffmpeg seek + 裁剪 + LANCZOS 缩放 |

### 2.2 渲染路径

```
useDetectionData (hooks/useDetectionData.ts:33)
  └─ GET /detection/data (detection_routes.py:49) ── 一次性返回全部 tracks + 全部 detections JSON
       ├─ DetectionPanel.tsx:267  filtered.map(...)  → 3000 个 <button>，每个含 <img loading="lazy">
       │     └─ getThumbBbox(data, t)  :29-42  → 每个 track 遍历全部 detections key（O(n×m)）
       │     └─ <img src="/detection/thumbnail?timestamp&bbox">  → ffmpeg 实时抽帧
       ├─ DetectionTimeline.tsx:100  lanes.map(...)  → 3000 个 lane、3000+ 个绝对定位 div
       │     └─ computeLanes :29-34 → sorted.map((t,i)=>({lane:i})) 每人独占一行，无装箱
       └─ DetectionOverlay.tsx:26   Canvas draw → 只画当前时间 floor/ceil 两帧（✅ 唯一健壮者）
```

> **v2.0 实测消费面**：`data.detections` 只有 Overlay（当前帧查找 `:68-69/:107/:221/:246`）和 Panel 的 `getThumbBbox`（`:33-34`，将被删除）在用；Timeline 完全不用 detections dict。这印证"接口拆分"方向——detections 本来就只服务于 Overlay。

### 2.3 问题清单（按杀伤力排序）

| # | 问题 | 位置 | 杀伤力 |
|---|---|---|---|
| 1 | **每个 track 渲染时全表扫描找缩略图框** | `DetectionPanel.tsx:271` → `getThumbBbox:29-42` | 🔴 1.08 亿次比较/次渲染（3000×36000），render 内同步执行 |
| 2 | **后端全量返回 + 前端全量解析** | `detection_routes.py:49-103` | 🔴 15MB JSON，parse 卡主线程；Overlay 只需当前±几秒却持有全部 |
| 3 | **缩略图实时 ffmpeg 抽帧，无服务端缓存** | `detection_routes.py:107-153` | 🔴 3000 次 ffmpeg 进程雪崩，浏览器 6 连接排队 |
| 4 | **检测栏无虚拟滚动** | `DetectionPanel.tsx:267-348` | 🟠 3000 DOM 节点 + 各自事件 handler |
| 5 | **时间轴一 track 一行 + 全量 DOM** | `DetectionTimeline.tsx:29-34,100-142` | 🟠 3000 lane / 42000px 容器 / 3000+ div |
| 6 | **选中 track → 全量重渲** | `Dashboard.tsx:136-145` + 两组件无 memo | 🟠 每次选中都触发 1+5 的整棵重渲 |
| 7 | **playhead rAF 永不停歇** | `DetectionTimeline.tsx:62-71` | 🟡 暂停时也逐帧写 style.left |

**结论**：模式确实"简陋"——是典型 naive 全量渲染。而项目里 `DetectionOverlay` 的 Canvas 模式恰好证明团队已掌握正确解法（每帧复杂度与 track 总数无关），时间轴与检测栏没有沿用这一思路。

---

## 3. 目标架构

核心思想：**把"一次性全量"改为"摘要 + 按需 + 虚拟化 + Canvas"四件套**。

```
┌─ 数据层(后端) ─────────────────────────────────────────────────┐
│ A1 接口拆分：tracks(轻量摘要) / detections(时间窗按需)        │
│ A2 track 摘要 best_bbox + best_ts + thumbnail_url — SQL 惰性算 │
│    └─ frame_detections DISTINCT ON 最大面积 + 按 video_id 缓存 │
│ A3 缩略图读盘优先 + miss→ffmpeg→写盘（惰性落盘）               │
│ A4 响应 gzip（15MB → ~1.5MB，一次性红利）                       │
├─ 前端数据层 ──────────────────────────────────────────────────┤
│ B1 useDetectionData 拆分：tracks 全量拉，detections 按区间拉    │
│ B2 Overlay 滑动窗口：当前 ±30s 区间缓存 + LRU 淘汰              │
├─ 前端渲染层 ──────────────────────────────────────────────────┤
│ C1 DetectionPanel 虚拟滚动（只渲染视口 ~30 行）+ TrackRow memo  │
│ C2 DetectionTimeline Canvas 化（lane packing + 时间视口缩放）   │
│ C3 playhead rAF 暂停判断 + 选中交互降优先级                     │
└────────────────────────────────────────────────────────────────┘
```

**分层目标**：
- 数据层是治本 —— 前端持有的检测数据从 **15MB → 几十 KB（tracks 摘要）+ 按需区间**；
- 渲染层是治标 —— 从 **3000 DOM → 30 行 + 1 个固定尺寸 canvas**；
- 缩略图从 **3000 次 ffmpeg → ~30-40 次（虚拟滚动兜住首开突发）+ 读盘**。

---

## 3.1 决策记录（已定稿）

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | 时间轴渲染方案 | **直接 Canvas + zoom/pan**（C2 终局） | 一劳永逸；lane 装箱 + DOM 裁剪只是过渡态，未来仍要重写；Canvas 与已有 `DetectionOverlay` 同构，团队已有实现参照 |
| D2 | 缩略图来源 | **惰性落盘**：读盘优先 + miss→ffmpeg→写盘，**保持现 `/detection/thumbnail` 精确 bbox 裁剪逻辑** | 缩略图内容零变化（若管线期用 `_expand_crop` 1.3× 外扩写图，反而会改变现有精确 bbox 裁剪的内容，违反零回退原则）；虚拟滚动已把并发 ffmpeg 限制到 ~30-40；**不触碰 Pipeline** |
| D3 | 检测栏虚拟滚动 | **手写固定行高虚拟列表，零新依赖**（C1 定稿） | 现 `dtc-item` 行高固定 ~60px、单列，是虚拟化最简单形态，40 行内可控；前端依赖极简（仅 react），不为此引入依赖；若日后行高动态化再评估 `@tanstack/react-virtual` |

**v2.0 关键取舍**：不再做管线期预计算（best_crop_cache + merge_map 合并 + _persist 写 3 列）。理由见 A2 末尾"为什么不用管线期预计算"。

---

## 4. 施工方案

### Phase A — 数据层（后端）

#### A1 接口拆分：tracks 摘要 + detections 时间窗

**新端点 A** `GET /api/v1/videos/{id}/detection/tracks`

返回全量 track 摘要（几千条，几十 KB）。前端检测栏 + 时间轴只依赖此端点。

```json
{
  "has_detection": true,
  "tracks": [
    {
      "track_id": 17,
      "class_name": "person",
      "first_seen": 12.3,
      "last_seen": 88.9,
      "frame_count": 320,
      "segments": [{ "start": 12.3, "end": 88.9 }],
      "best_thumb_ts": 45.6,
      "best_bbox": { "x1": 0.31, "y1": 0.42, "x2": 0.38, "y2": 0.68 },
      "thumbnail_url": "/api/v1/videos/{id}/detection/thumbnail?track_id=17&timestamp=45.6&x1=0.31&y1=0.42&x2=0.38&y2=0.68"
    }
  ]
}
```

> **v2.0**：`thumbnail_url` 必须带 `track_id` —— A3 磁盘缓存文件名 `track_{track_id}.jpg` 依赖它。

**新端点 B** `GET /api/v1/videos/{id}/detection/detections?start_sec=&end_sec=`

返回**时间窗内**的逐帧框（默认窗宽 ±30s，最大 300s），Overlay 用。命中现有 `ix_frame_detections_video_ts` 索引。

```json
{
  "has_detection": true,
  "start_sec": 30.0,
  "end_sec": 60.0,
  "detections": {
    "30.1": [{ "bbox": {...}, "class_name": "person", "track_id": 17 }],
    "...": []
  }
}
```

**兼容策略（v1.1 定稿 + v2.0 统一：直接替换，删除旧端点）**：zhiying 是单体仓库（前后端同仓发布），无外部 API 消费者；`detection/data` 前端仅在 `services/api.ts` + `hooks/useDetectionData.ts` 两处调用（已 grep 证实）、tests 无依赖。故**删除旧端点，前端同步改调新端点**。§5/§10 相应统一为此口径，不再保留 deprecated 双轨。

改动点：
- `detection_routes.py` — 新增两个端点，`get_detection_data` 删除；
- `frontend/src/services/api.ts` — `fetchDetectionTracks()`、`fetchDetectionRange(videoId, start, end)`。

#### A2 track 摘要 best_bbox / best_ts / thumbnail_url — SQL 惰性计算 + 内存缓存

**现状**：`getThumbBbox`（`DetectionPanel.tsx:29-42`）在前端对每个 track 遍历全部 detections，**1.08 亿次比较/次渲染**。

**方案**：把"最佳框"计算下沉到**后端**，前端不再扫描。

- **计算来源**：`frame_detections` 表——它已是**缝合后最终 track_id**（track_encode 在写回 `pctx.ctx.frame_detections` 时已用 `merge_map` 重映射，见 `track_encode.py:264-269`），天然一致，**不需要处理 merge_map 时序**。
- **一条 SQL 按最大面积取每 track 最佳帧**（与现 `getThumbBbox` 准则完全一致 → 缩略图内容零变化）：

```sql
SELECT DISTINCT ON (track_id) track_id, timestamp_sec, bbox
FROM frame_detections
WHERE video_id = :vid
ORDER BY track_id,
  ((bbox->>'x2')::float - (bbox->>'x1')::float)
  * ((bbox->>'y2')::float - (bbox->>'y1')::float) DESC
```

- **缓存**：按 `video_id` 的内存缓存（简单 LRU，上限 ~64 视频）。`frame_detections` 在管道完成后不可变（track 不会在不建新记录的情况下重缝合），**无失效窗口**；删除视频后对应 key 不再被访问（tracks 端点先查 video 存在性，404 兜底）。
- **索引**：给 `frame_detections` 加 `(video_id, track_id)` 复合索引（现仅 `ix_frame_detections_video_ts`），DISTINCT ON 按 track 分组受益。见 §6。

改动点：
- `api/detection_routes.py` — 新增 DISTINCT ON 查询 + LRU 缓存；tracks 端点拼 `thumbnail_url`（含 `track_id`）；
- `core/models.py` + `core/db.py` — frame_detections 加 `(video_id, track_id)` 索引；
- `frontend/src/components/DetectionPanel.tsx` — **删除 `getThumbBbox` 与 `:271` 调用**，改用 `track.thumbnail_url`。后端恒返回真实 URL，**前端不需要任何 NULL 分支**。

**为什么不用管线期预计算（v2.0 修正，替代原 best_crop_cache + _persist 写 3 列方案）**：

管线期方案（检测期存 best crop → track_encode 缝合后用 merge_map 合并 → `_persist` 写 `best_thumb_ts/best_bbox/thumb_path` 三列 → 旧视频再走惰性兜底）会引入：

1. **两条并行代码路径**（新视频管线写 / 旧视频惰性算）维护同一份数据，未来每个改动都要同步两处；
2. **触碰刚稳定（v0.20 缝合）的热路径**：`_stitch_tracks` 当前不返回 `merge_map`（需改签名），`detection.py` 要新增 best-crop 缓存——耦合面大、回归风险高；
3. **`bulk_insert_tracks` 是 `ON CONFLICT DO NOTHING`**（`repository.py:354`）——重跑管线时 `best_*` 列不会更新，等于新视频也依赖惰性兜底；
4. **缩略图内容会变**：管线期若用 `_expand_crop`（1.3× 外扩，`detection.py:37-51`）写图，而现端点按**精确 bbox** 裁剪（`detection_routes.py:133-139`）——内容不一致，违背"零回退"原则；
5. **额外显存**：best_crop_cache 每 track 一帧 crop，长视频下 `track_crop_cache` 本身已很大，再叠加加重管线内存。

惰性路径用现成的 `frame_detections` 表，**零 Pipeline 改动、零 DB 迁移（仅索引）、零 VideoContext 字段**，正确性由构造保证（post-stitch 一致）。唯一代价：每视频一次性 DISTINCT ON 查询（~100ms，缓存后消失）。

#### A3 缩略图读盘优先 + 惰性落盘

**现状**：`detection_routes.py:130` 每次请求都 `extract_keyframe_to_memory`（ffmpeg seek）。3000 次 ffmpeg。

**方案（D2 定稿：惰性落盘，无管线改动）**：

1. **读盘优先**：URL 带 `track_id` → 磁盘路径 `{thumbnail_dir}/{track_id}.jpg`（`thumbnail_dir(video_id)` = `{artifact_dir}/thumbnails/{video_id}`，`storage_manager.py:74-75`）。命中 → 直接返回文件字节（带现有 `Cache-Control: public, max-age=86400`）。
2. **miss → ffmpeg → 写盘**：走现有逻辑（ffmpeg seek + **精确 bbox 裁剪** + 200px LANCZOS，与现行为完全一致），生成后写入 `{thumbnail_dir}/track_{track_id}.jpg`，返回图像。写入 best-effort，失败仍返回（下次再补）。
3. **并发雪崩已被 C1 虚拟滚动消除**：视口 ~30-40 行 → 首开最多 ~30-40 次 ffmpeg（一次性，之后全读盘），不再有 3000 并发。
4. **存储卫生零新登记**：目录在 StorageManager 管控内——删除视频 `_safe_rmtree(thumbnail_dir)`（`storage_manager.py:142`）+ 孤儿清扫按 video_id 判定（`:210-227`），`track_*` 文件自动被覆盖。

改动点：
- `api/detection_routes.py:107-153` — 读盘优先分支 + miss 写盘；经 `request.app.state.storage_manager` 取目录；
- **无 Pipeline 改动、无 StorageManager 改动**。

#### A4 响应压缩

**现状**：`main.py` 无任何压缩中间件（已核实 `:110` 起 app、`:145` include_router，无 middleware），15MB JSON 原样传输。

**方案（v1.1 修正：必须排除视频流与二进制）**：`main.py` 挂 `GZipMiddleware(minimum_size=1024)`（starlette 内置，零依赖），但**不能全局压**：
- `/videos/{id}/stream` 返回 206/Range 视频流——全局压缩会压已压缩的 H.264（纯费 CPU）且破坏播放器 seek 语义；
- `/detection/thumbnail`、`/face/thumbnail` 等 JPEG 已压缩，再压无收益。

实现：自定义轻量中间件（继承 `GZipMiddleware` 或在其中加判定），**仅当响应 `media_type == "application/json"` 时压缩**。高熵 JSON 压缩比 >10×，一次性红利。

### Phase B — 前端数据层

#### B1 useDetectionData 拆分

**现状**：`useDetectionData.ts:33` 单次 `fetchDetectionData` 全量拉。

**方案**：
- `tracks`：一次 `fetchDetectionTracks()`（轻量，常驻 state）；
- `detections`：不再预拉全量，由 Overlay 按区间请求（见 B2）；
- **`face/data` 瘦身（v1.1 修正）**：`face_routes.py:71-80` 目前全量返回 per-frame `detections`，但前端**完全不用**（v2.0 已 grep 复核：`faceData.detections` 零引用；人脸 tab 只读 `identities`，Overlay 不渲染人脸框）。长视频 + 人脸开启时这是与 detection 同级的第二颗 15MB 炸弹。修正：face/data 接口**只返回 `identities`，删除 `detections` 字段**（前端 `FaceData` 类型同步删）；若未来要画人脸框，再按 A1 的区间模式补；
- `PlateData` 保持现状（per-track 聚合，量级 = 车辆 track 数，前端 `plateByTrack` 真实使用）。

`DetectionData` 类型（`types/index.ts:259-263`）拆分：

```ts
export interface TrackSummary {           // 原 Track + 新增
  track_id: number;
  class_name: string;
  first_seen: number;
  last_seen: number;
  frame_count: number;
  segments?: { start: number; end: number }[];
  best_thumb_ts: number;
  best_bbox: { x1: number; y1: number; x2: number; y2: number };
  thumbnail_url: string;
}
export interface DetectionRange {
  start_sec: number;
  end_sec: number;
  detections: Record<string, Detection[]>;   // 区间内 {ts → []}
}
```

#### B2 Overlay 滑动窗口 + 区间缓存

**现状**：`DetectionOverlay.tsx:68-69` 用 `data.detections[floor.toFixed(1)]` 直接查全量对象。

**方案**：引入 `useDetectionRanges` hook：

- 状态：`Map<rangeKey, DetectionRange>`（LRU 保留最近 ~10 分钟窗口）；
- 逻辑：根据 `video.currentTime`，确保 `[t-30, t+30]` 已加载；跨区间边界时后台预取下一段；seek 时立即请求目标段（未达先画已有数据，空则跳过绘制）；
- **区间带 buffer（v1.1）**：实际请求 `[t-31, t+31]`——Overlay 插值需 floor/ceil 两帧（`DetectionOverlay.tsx:63-66`）且 trail 读过去 2s 帧（`:97-113 TRAIL_DURATION=2.0`），端点帧 miss 会导致插值/trail 断裂；
- **重叠去重（v1.1）**：多个区间拼接时按 `ts` 去重（预取与补拉可能重叠）；
- **组切换清缓存（v1.1）**：`detectionVideoId` 变化时清空区间缓存，对齐 `useDetectionData.ts:26-41` 的清理模式；
- 查找：Overlay 绘制函数改为先查区间缓存，`floor/ceil` 取 `detections[ts] ?? []`；
- 兼容：`has_detection` 空区间返回空，无行为回归。
- **seek 空绘体验（备注，非必须）**：seek 到未加载区间时，加载延迟期 bbox 短暂消失，加载完成后重绘即可；如需可加轻量"加载中"提示。

改动点：
- 新 `frontend/src/hooks/useDetectionRanges.ts`；
- `DetectionOverlay.tsx` 绘制/点击/悬停改用区间缓存；
- Dashboard 把 `detectionData` 的"tracks 部分"继续下发到 Panel/Timeline，"detections 部分"改为 Overlay 自取。

### Phase C — 前端渲染层

#### C1 DetectionPanel 虚拟滚动

**现状**：`DetectionPanel.tsx:267` `filtered.map(...)` 全量渲染。

**方案（D3 定稿：手写固定行高虚拟列表，零新依赖）**：

现 `dtc-item` 行高固定 ~60px、单列，是最简单的虚拟化形态，手写足够稳定：

1. **占位高度**：外层 `dtc-list`（`position:relative; overflow-y:auto`）内部放一个高 = `tracks.length × ROW_H` 的占位 div（撑出正确滚动条）；
2. **滚动计算**：监听容器 `scroll`（rAF 节流）→ `startIdx = floor(scrollTop / ROW_H)`、`endIdx = startIdx + ceil(视口高 / ROW_H)`；
3. **只渲染窗口**：`tracks.slice(startIdx - overscan, endIdx + overscan)`（overscan=5），每行 `position:absolute; top: idx × ROW_H`（不随滚动回流，靠 translateY 定位）；
4. **缩略图天然按需**：`<img>` 只在行渲染时挂载（虚拟列表已保证只有视口附近有 DOM），配合 `loading="lazy"`；
5. **scrollToIndex**：原 `listRef.scrollIntoView`（`DetectionPanel.tsx:59-63`）改为 `容器.scrollTop = idx × ROW_H - 视口高/2`（选中居中）；
6. **TrackRow 抽 `React.memo`**：props 用原始值（track / isSel / thumbnailUrl / handlers），选中只重渲该行；
7. 导出 dropdown / hover 大图逻辑保留在行内，不受影响。

**v1.1 补充细节**：
- **listRef 被两个 tab 共用**（`DetectionPanel.tsx:59-63` objects、`:354` faces）——虚拟化与 `scrollToIndex` 只对 objects tab 生效；faces tab 行数 = identity 数（量小），保持普通渲染；
- **缩略图来源（v2.0）**：`track.thumbnail_url` 恒有值——惰性路径对**全部视频**（新旧统一）生效，前端删除 `getThumbBbox` 后直接用它即可，现有 `dtc-dot` 色点分支仅作极端 fallback 保留，不承担功能。

> 不引库的理由：单列固定行高场景手写 40 行内可控且稳定；项目前端依赖极简（仅 react），避免新增依赖与网络安装成本。若日后行高动态化（如可变高度缩略图），再评估 `@tanstack/react-virtual`（此时其 `measureElement` 动态测量价值才显现）。

#### C2 DetectionTimeline Canvas 化（终局方案）

**现状**：`DetectionTimeline.tsx` 全量 DOM 时间条。

**方案（D1 定稿：Canvas + zoom/pan）**：彻底转向 Canvas，与 `DetectionOverlay` 同构，天然获得缩放/平移。内部设计如下：

**① 数据结构（单一事实源）**

```ts
// 每个 segment 摊平成一条 Rect；buildRects() 结果缓存，tracks 不变则不重建
type Rect = {
  trackId: number; className: string; color: string;
  start: number; end: number;      // 秒
  lane: number;                    // 泳道行号（packLanes 后）
  label: string;                   // 预渲染用："人#1"
};
type Layout = { rects: Rect[]; laneCount: number };
```

**② lane packing（区间装箱，贪心）**

```ts
// 按 first_seen 升序，把每个 segment 分配到首个不与已有段重叠的 lane
function packLanes(tracks: Track[]): Layout {
  const events = [];               // 每个 segment 一个区间
  for (const t of tracks)
    for (const seg of (t.segments ?? [{start:t.first_seen,end:t.last_seen}]))
      events.push({ trackId:t.track_id, className:t.class_name, start:seg.start, end:seg.end });
  events.sort((a,b) => a.start - b.start);
  const laneEnd: number[] = [];    // 每条 lane 当前占用到哪
  for (const e of events) {
    let lane = laneEnd.findIndex(end => e.start >= end);
    if (lane === -1) { lane = laneEnd.length; laneEnd.push(0); }
    laneEnd[lane] = e.end;
    rects.push({ ...e, lane, color: colorOf(e.class_name), label: zhLabel(e.class_name, e.trackId) });
  }
  return { rects, laneCount: laneEnd.length };
}
```

> **v2.0 修正**：时间缩放只降低**水平**密度，不降低 lane 数——拥挤人群场景 `laneCount` 仍可能接近 track 数，画布**高度** = `laneCount × LANE_H` 仍会增长。处理：Canvas 高度设上限（如 480px）+ **垂直滚动**，或直接接受高画布（Canvas 本身扛得住，无 DOM 节点）。不再声称"画布尺寸恒定"；"恒定"仅对宽度/时间视口成立。

**③ 时间视口（核心，zoom/pan 的引擎）**

- canvas 宽度 = 容器宽度（固定，非 42000px）；维护 `[viewStart, viewEnd]`；
- 时间↔像素映射（两条纯函数，一切绘制/命中都走它）：
  ```ts
  timeToX = t => (t - viewStart) / (viewEnd - viewStart) * canvasW;
  xToTime = x => viewStart + x / canvasW * (viewEnd - viewStart);
  ```
- **只绘制与视口相交的 Rect**：`rect.end >= viewStart && rect.start <= viewEnd`。zoom 到局部后视口内通常只剩几十~几百条，`fillRect` 全量也就几 ms；
- **wheel = zoom**：以鼠标 x 为锚点缩放时间范围（`viewSpan *= 1.1` 或 `0.9`，保持 `xToTime(mouseX)` 不变——即锚定鼠标指向的时间点）；
- **drag = pan**：mousedown+mousemove 改变 `viewStart/viewEnd`（位移量 = Δpx × 当前秒/px）。数据不变，只改映射，重绘一遍。

**④ 绘制流程（render() 单函数）**

```ts
function render() {
  // 1. ruler：按当前 zoom 自适应 tick 间隔（如 1s/5s/30s/1m/5m，保证 ≥40px 一根）
  // 2. lanes：for rect of visibleRects → ctx.fillRect(timeToX(rect.start), lane*LANE_H, w, LANE_H)
  //          选中 track 高亮（金色）；hover 中的 rect 不透明度提高
  // 3. face markers：identities 的 best_face_timestamp 画竖短线
  // 4. playhead：video.currentTime 画金色垂直线（rAF，paused 时停）
}
```

**⑤ 命中检测（替代 DOM 事件）**

- `hover`：mousemove → `y → lane`（`floor(y / LANE_H)`）→ 遍历该 lane 的 rect 看 `xToTime(x) ∈ [start,end]` → 更新 hover 状态 + 局部重绘；
- `click`：同一套命中 → 命中时 `onTrackSelect(trackId, className, 点击对应秒)`；
- **选中定位（v1.1）**：`selectedTrackId` 变化时，**pan 视口使该 track 的 `first_seen` 居中**——对应现 DOM 版 `scrollIntoView`（`DetectionTimeline.tsx:54-59`）的行为；若已在视口内则不动；
- tooltip：hover 命中后，在鼠标处用 **DOM 浮层**（`position:fixed`）显示类名/时间——浮层只有 1 个 DOM 节点，不受条数量影响。

**⑥ 其他平移**
- face markers（原 `DetectionTimeline.tsx:146-157`）、ruler（`:83-97`）全部画入 canvas；
- `LANE_H=9, LANE_GAP=5, RULER_H=20, PAD=5` 常量沿用；`.tl-*` CSS 只留容器尺寸类。

改动点：
- 重写 `DetectionTimeline.tsx`（DOM → canvas）；`computeLanes` 换为 `packLanes` + `buildRects`（`useMemo` 缓存）；
- `index.css` 中 `.tl-*` 样式仅保留容器尺寸类，删时间条类；
- 新增组件内 `render()` + `xToTime/timeToX` + 命中检测三件套。

#### C3 playhead rAF 暂停 + 交互降优先级

- `DetectionTimeline.tsx:62-71` — rAF 内加 `if (video.paused) return`；
- `Dashboard.tsx` 大数据场景的 `setSelectedTrackId` 包 `useTransition()`，低优先级渲染；`classFilter` 切换同理；
- TrackRow / 时间条选中态依赖 memo + 局部 state，避免整树重渲。

---

## 5. 接口契约汇总（新/改/删）

| 接口 | 变更 | 说明 |
|---|---|---|
| `GET /detection/tracks` | **新增** | track 摘要 + 惰性计算 best_bbox/best_ts/thumbnail_url，几十 KB |
| `GET /detection/detections?start_sec&end_sec` | **新增** | 时间窗逐帧框，Overlay 用 |
| `GET /detection/thumbnail` | **改** | 读盘优先 + miss→ffmpeg→写盘；URL 带 track_id |
| `GET /detection/data` | **删除** | 唯一消费者（api.ts + useDetectionData.ts）同仓同步迁移，无外部消费者（v2.0 统一口径，不保留 deprecated） |
| `GET /videos/` 列表、`GET /videos/{id}` | 不变 | — |

---

## 6. DB 迁移

**v2.0：无新列、无新表。** 唯一变更是给 `frame_detections` 加一个复合索引（`core/db.py` 增量迁移模式 `CREATE INDEX IF NOT EXISTS`）：

```sql
CREATE INDEX IF NOT EXISTS ix_frame_detections_video_track
  ON frame_detections (video_id, track_id);
```

- 服务 A2 的 DISTINCT ON 分组查询；
- 服务 A1 的区间查询已有 `ix_frame_detections_video_ts`，无需新增。
- 旧数据（已完成视频）与新增量**统一走惰性路径**，无任何 NULL 分支、无需重跑管线。

---

## 7. 依赖变更

| 层 | 依赖 | 说明 |
|---|---|---|
| 前端 | **无新增** | 虚拟滚动手写（固定行高，零依赖）；Canvas 为浏览器原生 API |
| 后端 | 无新增 | gzip 为 starlette 内置；缩略图复用现有 ffmpeg + PIL 逻辑 |

---

## 8. 实施顺序与依赖图

```
S0 快速红利（无依赖，先上）
  ├─ A4 gzip（main.py，JSON-only 中间件）
  ├─ C3 rAF 暂停（useTransition 已从 S0 移除，v1.2——收益小且有边界风险，留到 S3 虚拟滚动后数据量大时才有真实收益）
  └─ A2 后端 tracks 带 best_bbox/best_ts（SQL 惰性 + LRU 缓存）→ 前端删 getThumbBbox
         └─ 依赖：§6 frame_detections 索引（无它也能跑，首次全扫 ~100ms 后进缓存）

S1 数据层（依赖 S0）✅ 已实施
  ├─ A1 接口拆分（tracks / detections 时间窗）
  ├─ A3 缩略图读盘优先 + 惰性落盘
  └─ ⚠️ 实施修正：旧 /detection/data **暂留**（Overlay 唯一数据源，删它需等 S2 前端迁移后零消费者再删）

S2 前端数据层（依赖 S1）✅ 已实施
  ├─ B1 useDetectionData 拆分（tracks 走 /detection/tracks，DetectionData 删 detections）
  ├─ B2 useDetectionRanges 滑动窗口 + Overlay 改造（±30s + 预取 + LRU，seeked 立即重绘）
  └─ 删除旧 /detection/data（同仓硬切，已 grep 零残留；CLAUDE.md 文件地图同步更新）

S3 渲染层（依赖 S2）✅ 已实施
  ├─ C1 DetectionPanel 虚拟滚动 + TrackRow memo（手写固定行高 68px，滚动窗口 + overscan，选中居中/filter 回顶）
  └─ C2 DetectionTimeline Canvas 化（buildRects lane packing + 时间视口 + 垂直 lane 虚拟化 + 命中检测）
      └─ ⚠️ 实施偏差：zoom 改为 **Ctrl/Cmd+滚轮**（普通滚轮保留垂直滚动——否则 3000 lane 无法滚轮上下滚；原生非被动 wheel 监听 preventDefault）

S4 打磨 ✅ 已实施
  ├─ 元素生命周期修复：时间轴空白 / 检测栏 5 条（effect 依赖 = hasTracks/listVisible 门禁，与 JSX 共用变量防漂移；每轮新建 ResizeObserver 消灭陈旧闭包；playhead 依赖 streamReady/videoId）
  ├─ useDetectionRanges：LRU 淘汰同步清除 loadedKeys（revisit 重新拉取）+ 30s 网格窗口（播放中 ~30s 一次请求，替代 ~1s 一次）
  ├─ DetectionTimeline memo（props 全稳定，跳过 4s 轮询无关重渲染）
  └─ Panel 空筛选提示（切视频后陈旧 filter 命中空类）
  └─ 待做：§9 性能指标回归、长视频实测、hover/选中/导出回归（浏览器侧）
```

每阶段可独立上线且不回退体验：S0 已解决"点开检测栏卡死"的 80%（getThumbBbox 删除 + gzip）；S1/S2 解决"长视频整体流畅"；S3 是时间轴终局形态。

---

## 9. 验收标准

| 指标 | 目标（3000 track 场景） | 度量方式 |
|---|---|---|
| 检测栏首屏渲染 | < 200ms | DevTools Performance |
| 检测栏滚动 | 60fps，缩略图不雪崩 | 滚动期间无长任务；Network 无 >50 并发缩略图 |
| Overlay 内存/传输 | detections 峰值 < 2MB（按需区间） | Network + Memory 面板 |
| 缩略图后端成本 | ffmpeg 调用趋近 0（读盘） | 后端日志 / CPU |
| 时间轴交互 | 缩放/平移/hover 流畅，画布宽度恒定 | 实测 |

## 9.1 每阶段独立校验（v1.2 + v2.0）

> 现状：项目**无 tests 目录**（CLAUDE.md 所述 30+ 测试文件实际不存在，已复核）、前端无 test script，只有 `tsc -b` + `vite build`。故每阶段校验 = 前端类型/构建闸门 + 后端 curl 冒烟 + 手动回归。是否新建 pytest 基建为独立决策，不混入本方案。

| 阶段 | 校验操作 | 通过标准 |
|---|---|---|
| **S0** | `curl -H "Accept-Encoding: gzip" -I <JSON接口>` | `Content-Encoding: gzip`；同法打 `/stream`、`/thumbnail` → **无** gzip |
| | 浏览器暂停视频 | playhead 位置正确且不再持续重绘（无 rAF 活动） |
| | `init_db()` 跑两次 | 幂等无错（`CREATE INDEX IF NOT EXISTS`） |
| | `curl /detection/tracks` | 新视频与**旧视频**（此前已处理）都返回 best_thumb_ts/best_bbox/thumbnail_url；二次请求走缓存 |
| | `npx tsc -b` + 手动 | 检测栏缩略图正常；删除 getThumbBbox 后无类型错误 |
| **S1** | 全仓 `grep /detection/data` | 零残留（后端删端点 + 前端同步改） |
| | `npx tsc -b` | 通过（接口类型变更，漏改必编译错） |
| | curl 两个新端点 | `/detection/tracks` 量小；`/detection/detections?start_sec&end_sec` 区间正确 |
| | curl `/face/data` | 无 detections 字段；前端人脸 tab 正常 |
| | `/detection/thumbnail?track_id=..` 两次请求 | `thumbnails/{video_id}/track_{track_id}.jpg` 存在；第二次不触发 ffmpeg（读盘） |
| | **删除一个视频** | 缩略图目录被 StorageManager 清空（验证存储卫生集成） |
| **S2** | 播放 / seek / 来回 seek | 区间按需加载、LRU 命中（Network 无重复/无全量大 JSON） |
| | 组切换 `detectionVideoId` | 缓存清空并重新加载 |
| | Overlay | 播放/暂停/seek bbox 正常；插值/trail 连续（buffer 生效）；点击命中/悬停正常 |
| **S3** | 虚拟滚动 | 滚动流畅（无长任务）；滚动到底/顶；filter 后从顶开始；选中居中；faces tab 不回归 |
| | Canvas 时间轴**功能对照清单**（每项与现 DOM 版对比） | ① ruler 刻度自适应 ② 条颜色/选中金色高亮 ③ hover tooltip（类名+frame_count+时间段）一致 ④ 点击 seek（条内比例 `start + ratio×(end-start)`，复刻 `DetectionTimeline.tsx:120-127`）⑤ face markers 位置 ⑥ playhead 播放移/暂停停 ⑦ 选中 pan 到 first_seen 居中 ⑧ zoom/pan 不破坏默认全片视图 ⑨ `wPct > 3` 才显示标签 |
| **S4** | §9 性能指标 + 非长视频（几百 track）全量回归 | 达标 |

## 9.2 对原有功能影响分析（v1.2 + v2.0）

> 原则：任何改动不允许回退原有功能；影响只允许为零或正面。⚠️ 项已在方案中缓解。

| 改动点 | 影响判定 | 说明 |
|---|---|---|
| gzip（JSON-only） | ✅ 零 | 浏览器透明解压；已排除 stream/JPEG |
| playhead rAF 暂停 | ✅ 正面 | 暂停时值不变，不再白耗 rAF |
| frame_detections 加索引 | ✅ 零 | `CREATE INDEX IF NOT EXISTS`，纯增量 |
| 惰性 best 计算 | ✅ 零 | SQL 最大面积准则与现 `getThumbBbox` 完全一致（缩略图内容不变）；对全部视频统一生效，无新旧分支 |
| 删 getThumbBbox | ✅ 零 | 后端恒返回 thumbnail_url，前端无 NULL 分支 |
| 删旧 `/detection/data` | ✅ 零 | 唯一消费者已确认（api.ts + useDetectionData.ts），同仓同步迁移 |
| face 删 detections | ✅ 零 + 正面 | 前端全目录 grep 证实不用；tsc 闸门兜底 |
| 缩略图读盘优先/惰性落盘 | ✅ 零 + 正面 | 保持现 ffmpeg + 精确 bbox 裁剪行为（内容不变）；目录在 StorageManager 管控内，删除/清扫自动；miss→写盘等价于现行为 |
| Overlay 区间加载 | ⚠️ **唯一 UX 小回退（已缓解）** | seek 到未加载区间短暂空绘（几百 ms）——"15MB 首开卡 3s → 秒级可用"的权衡；预取 buffer 缓解，文档明示 |
| 虚拟滚动 | ✅ 等价 + 正面 | filter 重置 / 选中居中 / faces tab 已覆盖 |
| Canvas 时间轴 | ✅ 等价 + 正面 | 交互逐项对照复刻（§9.1 S3 清单）；zoom/pan 为新增能力 |

---

## 10. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 惰性 best 计算首次查询成本 | 按 video_id LRU 缓存（一次视频一次，~100ms）；`(video_id, track_id)` 索引兜底 |
| 惰性缩略图首开 ffmpeg 突发 | C1 虚拟滚动兜住（视口 ~30-40 行）；miss 一次落盘后全读盘；Cache-Control 已设 |
| 虚拟滚动滚动条/高度测量 bug | 固定行高 + `measureElement` 兜底；保留非虚拟 fallback flag |
| Canvas 命中检测误触 | 命中检测与绘制共用同一 `buildRects()`，单一事实源；hover 高亮 + click 分离 |
| Canvas 高度随 laneCount 增长 | 高度上限 + 垂直滚动；时间缩放不降 lane 数（v2.0 已修正表述） |
| 缩略图落盘质量低于全分辨率 | 200px 缩略图场景 640×384 crop 足够；不满意再升级为管线内单次 ffmpeg |
| 接口拆分破坏旧前端 | 同仓硬切：S0 先加新端点，S1 删旧调用；tsc 闸门兜漏改 |
| `frame_detections` 表极大（10 万+）时 DISTINCT ON | 有索引 + LRU 缓存；超出再评估物化/分页 |

---

## 附：代码锚点索引

| 改动点 | 文件:行 |
|---|---|
| getThumbBbox 全表扫描 | `frontend/src/components/DetectionPanel.tsx:29-42`、`:271` |
| 检测栏全量渲染 | `frontend/src/components/DetectionPanel.tsx:267-348` |
| 时间轴一 track 一行 | `frontend/src/components/DetectionTimeline.tsx:29-34` |
| 时间轴全量 DOM | `frontend/src/components/DetectionTimeline.tsx:100-142` |
| playhead rAF 无暂停 | `frontend/src/components/DetectionTimeline.tsx:62-71` |
| 后端全量返回 | `api/detection_routes.py:49-103` |
| 缩略图实时 ffmpeg + 精确 bbox 裁剪 | `api/detection_routes.py:107-153`（裁剪 `:133-139`） |
| frame_detections 现有索引 | `core/models.py:606-609`（仅 `ix_frame_detections_video_ts`） |
| bulk_insert_tracks ON CONFLICT | `core/repository.py:342-363` |
| thumbnail_dir（落盘目录） | `core/storage_manager.py:74-75`、删除清盘 `:142`、清扫 `:210-227` |
| 全量数据加载 | `frontend/src/hooks/useDetectionData.ts:33` |
| 选中全量重渲 | `frontend/src/Dashboard.tsx:136-145` |
| _expand_crop（1.3× 外扩，仅用于 crop 缓存） | `pipeline/runners/detection.py:37-51`、`:313` |
