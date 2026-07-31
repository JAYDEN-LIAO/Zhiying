# Detection 大规模数据渲染链路 — 完整优化方案

> 状态：**方案定稿，尚未实施**（2026-07-31）。
> 关联：`docs/arch.md`（架构）、`docs/format-compat-fix.md`（既有方案文档惯例）。
> 决策：D1 Canvas 时间轴直上 ✅ | D2 缩略图复用 best_cache crop ✅ | D3 虚拟滚动手写零依赖 ✅（见 §3.1）
> 修订：v1.1 自审查修正（落盘时机对齐缝合 / face detections 瘦身 / gzip 排除流 / 旧视频 NULL 契约 / 细节 5 项）
> 涉及：`api/detection_routes.py`、`core/models.py`（Track）、`pipeline/runners/detection.py`、
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
  └─ GET /detection/data (detection_routes.py:27) ── 一次性返回全部 tracks + 全部 detections JSON
       ├─ DetectionPanel.tsx:267  filtered.map(...)  → 3000 个 <button>，每个含 <img loading="lazy">
       │     └─ getThumbBbox(data, t)  :29-42  → 每个 track 遍历全部 detections key（O(n×m)）
       │     └─ <img src="/detection/thumbnail?timestamp&bbox">  → ffmpeg 实时抽帧
       ├─ DetectionTimeline.tsx:100  lanes.map(...)  → 3000 个 lane、3000+ 个绝对定位 div
       │     └─ computeLanes :29-34 → sorted.map((t,i)=>({lane:i})) 每人独占一行，无装箱
       └─ DetectionOverlay.tsx:26   Canvas draw → 只画当前时间 floor/ceil 两帧（✅ 唯一健壮者）
```

### 2.3 问题清单（按杀伤力排序）

| # | 问题 | 位置 | 杀伤力 |
|---|---|---|---|
| 1 | **每个 track 渲染时全表扫描找缩略图框** | `DetectionPanel.tsx:271` → `getThumbBbox:29-42` | 🔴 1.08 亿次比较/次渲染（3000×36000），render 内同步执行 |
| 2 | **后端全量返回 + 前端全量解析** | `detection_routes.py:56-103` | 🔴 15MB JSON，parse 卡主线程；Overlay 只需当前±几秒却持有全部 |
| 3 | **缩略图实时 ffmpeg 抽帧，无服务端缓存** | `detection_routes.py:106-150` | 🔴 3000 次 ffmpeg 进程雪崩，浏览器 6 连接排队 |
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
│ A2 track 摘要预计算 best_bbox + best_ts + thumbnail_url        │
│    └─ 复用 detection.py:296-304 已有 best_cache，零额外计算     │
│ A3 缩略图管线落盘 + 接口磁盘缓存（ffmpeg 只在首次/缺失时）      │
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
- 缩略图从 **3000 次 ffmpeg → ~0 次（读盘）**。

---

## 3.1 决策记录（已定稿）

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | 时间轴渲染方案 | **直接 Canvas + zoom/pan**（C2 终局） | 一劳永逸；lane 装箱 + DOM 裁剪只是过渡态，未来仍要重写；Canvas 与已有 `DetectionOverlay` 同构，团队已有实现参照 |
| D2 | 缩略图落盘质量 | **复用管线 `best_cache` 的 640×384 crop**（A3 方案一） | 零 ffmpeg 成本；200px 缩略图场景质量足够（`track_embeddings` 本就基于同分辨率 crop）；全分辨率备选否决 |
| D3 | 检测栏虚拟滚动 | **手写固定行高虚拟列表，零新依赖**（C1 定稿） | 现 `dtc-item` 行高固定 ~60px、单列，是虚拟化最简单形态，40 行内可控；前端依赖极简（仅 react），不为此引入依赖；若日后行高动态化再评估 `@tanstack/react-virtual` |

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
      "thumbnail_url": "/api/v1/videos/{id}/detection/thumbnail?timestamp=45.6&x1=0.31&y1=0.42&x2=0.38&y2=0.68"
    }
  ]
}
```

**新端点 B** `GET /api/v1/videos/{id}/detection/detections?start_sec=&end_sec=`

返回**时间窗内**的逐帧框（默认窗宽 ±30s，最大 300s），Overlay 用。

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

**兼容策略（v1.1 修正：直接替换，不保留 deprecated 双轨）**：cerno 是单体仓库（前后端同仓发布），无外部 API 消费者；`detection/data` 前端仅在 `services/api.ts` + `hooks/useDetectionData.ts` 两处调用、tests 无依赖。故**删除旧端点，前端同步改调新端点**，避免双轨维护与施工复杂度。Vite 代理无影响。

改动点：
- `detection_routes.py` — 新增两个端点，`get_detection_data` 改为内部复用；
- `frontend/src/services/api.ts` — `fetchDetectionTracks()`、`fetchDetectionRange(videoId, start, end)`。

#### A2 track 摘要预计算 best_bbox / best_ts / thumbnail_url

**现状**：`getThumbBbox`（`DetectionPanel.tsx:29-42`）在前端对每个 track 遍历全部 detections，**1.08 亿次比较/次渲染**。

**方案**：把"最佳框"计算下沉到**后端一次性算好**，前端不再扫描。

关键事实：`pipeline/runners/detection.py:296-304` 检测期间已维护 `best_cache`（每 track 最高置信度帧）：

```python
if tid not in best_cache or conf > best_cache[tid]["conf"]:
    best_cache[tid] = {
        "frame": frames[i], "bbox": t["bbox"],
        "timestamp": float(timestamp), "conf": conf,
    }
```

**落盘时机（v1.1 修正：必须在 track_stitch 缝合之后，不是 detection persist）**：
`track_encode._stitch_tracks` 会用 `merge_map`（`track_encode.py:192-248`）把被合并 track 的 `track_id` 重映射到主 track，并把 segments/last_seen/frame_count 并入主 track——若在缝合前按旧 track_id 写入，缩略图/best 信息会变孤儿或错位。做法：
1. 检测期间把每 track **最佳帧 crop 存入 `pctx`**（与 `track_crop_cache` 并列，如 `pctx.ctx.best_crop_cache[tid] = (ts, crop, conf)`）——这是把 best_cache 的帧带过缝合期的关键，保持"零 ffmpeg"；
2. **track_encode 缝合完成后**：用 `merge_map` 对 `best_crop_cache` 合并（merge 组内取置信度最高帧），按**最终** track_id 写 `best_thumb_ts` / `best_bbox` 入库并落盘缩略图。

改动点：
- `pipeline/runners/detection.py` — 最佳帧 crop 存入 `pctx.ctx.best_crop_cache`；
- `pipeline/runners/track_encode.py`（缝合完成后）— merge_map 合并 best_crop_cache → 写库 + 落盘缩略图；
- `api/detection_routes.py` — `tracks` 端点回读两列并拼 `thumbnail_url`；**对 best_* 为 NULL 的旧视频 track，返回 `best_bbox=null, thumbnail_url=null`**（前端落色点分支，§C1）；
- `frontend/src/components/DetectionPanel.tsx` — **删除 `getThumbBbox` 与 `:271` 调用**，改用 `track.thumbnail_url`；无 `thumbnail_url` 时显示现有 `dtc-dot` 色点。

#### A3 缩略图管线落盘 + 接口磁盘缓存

**现状**：`detection_routes.py:127` 每次请求都 `extract_keyframe_to_memory`（ffmpeg seek）。3000 次 ffmpeg。

**方案（D2 定稿 + v1.1 修正：管线落盘，复用 best crop，零 ffmpeg 成本，落盘时机对齐缝合）**：

1. **管线落盘**：检测期间把每 track 最佳帧 crop 存入 `pctx.ctx.best_crop_cache`（见 A2 步骤 1）；**track_encode 缝合完成后**用 `merge_map` 合并 → 按最终 track_id `resize(200)` → JPEG → 写 `data/track_thumbs/{video_id}/{track_id}.jpg`。
   - 复用 `_expand_crop`（`detection.py:37`）的裁剪逻辑；
   - 质量：200px 缩略图场景 640×384 crop 足够（`track_embeddings` 本就基于同分辨率 crop）。全分辨率备选已否决——长视频每 track 一次 ffmpeg 的额外成本不值；
   - **缝合迁移**：被合并 track 的缩略图不单独写盘（merge_map 已把 best 归并到主 track），最终缩略图集合与 `tracks` 表一一对应；
   - 目录 `data/track_thumbs/` 与视频存储同级，删除视频时级联清理（`api/video_routes.py` DELETE 分支）。

2. **接口读盘优先**：`GET /detection/thumbnail` 命中 `thumb_path` 直接返回文件字节（带现有 `Cache-Control: max-age=86400`）；miss 才走现有 ffmpeg 逻辑，生成后写盘供下次。

改动点：
- `pipeline/runners/track_encode.py`（缝合完成后）— 缩略图落盘 + `thumb_path` 入库（与 A2 同一处，一次遍历完成）；
- `api/detection_routes.py:106-150` — 读盘优先分支；
- 存储根路径从 config `storage` 读取（不硬编码）。

#### A4 响应压缩

**现状**：`main.py` 无任何压缩中间件，15MB JSON 原样传输。

**方案（v1.1 修正：必须排除视频流与二进制）**：`main.py` 挂 `GZipMiddleware(minimum_size=1024)`（starlette 内置，零依赖），但**不能全局压**：
- `/videos/{id}/stream` 返回 206/Range 视频流——全局压缩会压已压缩的 H.264（纯费 CPU）且破坏播放器 seek 语义；
- `/detection/thumbnail`、`/face/thumbnail` 等 JPEG 已压缩，再压无收益。

实现：自定义轻量中间件（继承 `GZipMiddleware` 或在其中加判定），**仅当响应 `media_type == "application/json"` 时压缩**。高熵 JSON 压缩比 >10×，一次性红利。main.py 目前无任何 middleware（`:110` 起 app，`:145` include_router），加在此处即可。

### Phase B — 前端数据层

#### B1 useDetectionData 拆分

**现状**：`useDetectionData.ts:33` 单次 `fetchDetectionData` 全量拉。

**方案**：
- `tracks`：一次 `fetchDetectionTracks()`（轻量，常驻 state）；
- `detections`：不再预拉全量，由 Overlay 按区间请求（见 B2）；
- **`face/data` 瘦身（v1.1 修正）**：`face_routes.py:71-80` 目前全量返回 per-frame `detections`，但前端**完全不用**（已 grep 证实：人脸 tab 只读 `identities`，Overlay 不渲染人脸框）。长视频 + 人脸开启时这是与 detection 同级的第二颗 15MB 炸弹。修正：face/data 接口**只返回 `identities`，删除 `detections` 字段**（前端 `FaceData` 类型同步删）；若未来要画人脸框，再按 A1 的区间模式补；
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
- **缩略图 NULL 兜底**：`track.thumbnail_url == null`（旧视频无 best_*）时渲染现有 `dtc-dot` 色点分支（`:292-294`），不显示 `<img>`——删掉 `getThumbBbox` 后旧视频零功能回退。

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
// 拥挤人群场景 laneCount 会接近 track 数 → 高度 = laneCount × LANE_H，
// 但配合 ③ 时间视口，画布尺寸恒定，不再有 42000px 容器。
```

**③ 时间视口（核心，zoom/pan 的引擎）**

- canvas 尺寸 = 容器尺寸（固定，非 42000px）；维护 `[viewStart, viewEnd]`；
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
| `GET /detection/tracks` | **新增** | track 摘要 + 预计算缩略图信息，几十 KB |
| `GET /detection/detections?start_sec&end_sec` | **新增** | 时间窗逐帧框，Overlay 用 |
| `GET /detection/thumbnail` | **改** | 读盘优先，miss 才 ffmpeg + 落盘 |
| `GET /detection/data` | **保留 deprecated** | 内部复用新查询，旧前端兼容 |
| `GET /videos/` 列表、`GET /videos/{id}` | 不变 | — |

---

## 6. DB 迁移

按 `core/db.py` 增量迁移模式（`ALTER TABLE ADD COLUMN IF NOT EXISTS`），Track 表加 3 列：

```sql
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS best_thumb_ts DOUBLE PRECISION;   -- 最佳帧时间戳
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS best_bbox JSONB;                  -- 最佳框(归一化 0-1)
ALTER TABLE tracks ADD COLUMN IF NOT EXISTS thumb_path TEXT;                  -- 落盘缩略图路径(可空)
```

无新表。旧数据（已完成视频）缩略图走接口 miss → ffmpeg → 落盘的惰性路径自动补齐，无需重跑管线；`best_thumb_ts/best_bbox` 为 NULL 时前端用 `first_seen` 兜底。

---

## 7. 依赖变更

| 层 | 依赖 | 说明 |
|---|---|---|
| 前端 | **无新增** | 虚拟滚动手写（固定行高，零依赖）；Canvas 为浏览器原生 API |
| 后端 | 无新增 | gzip 为 starlette 内置；缩略图落盘复用 PIL |

---

## 8. 实施顺序与依赖图

```
S0 快速红利（无依赖，先上）
  ├─ A4 gzip（main.py，JSON-only 中间件）
  ├─ C3 rAF 暂停 + useTransition
  └─ A2 + C1 前置：后端 tracks 带 best_bbox/best_ts → 前端删 getThumbBbox
         └─ 依赖：§6 DB 迁移 + track_encode 缝合后写入（v1.1 对齐）
         └─ 旧视频 best_* = NULL → 前端落色点分支，零回退

S1 数据层（依赖 S0）
  ├─ A1 接口拆分（tracks / detections 时间窗）
  ├─ A3 缩略图落盘 + 读盘优先
  └─ 旧 /detection/data 改为复用

S2 前端数据层（依赖 S1）
  ├─ B1 useDetectionData 拆分
  └─ B2 useDetectionRanges 滑动窗口 + Overlay 改造

S3 渲染层（依赖 S2）
  ├─ C1 DetectionPanel 虚拟滚动 + TrackRow memo
  └─ C2 DetectionTimeline Canvas 化（lane packing + 时间视口 + zoom/pan）

S4 打磨
  └─ 性能指标回归、长视频实测、hover/选中/导出回归
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
| 时间轴交互 | 缩放/平移/hover 流畅，画布恒定尺寸 | 实测 |

## 10. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 虚拟滚动滚动条/高度测量 bug | 固定行高 + `measureElement` 兜底；保留非虚拟 fallback flag |
| Canvas 命中检测误触 | 命中检测与绘制共用同一 `buildRects()`，单一事实源；hover 高亮 + click 分离 |
| 接口拆分破坏旧前端 | 旧 `/detection/data` 保留 deprecated，前端两步走（先加新端点，后删旧调用） |
| 缩略图落盘质量低于全分辨率 | 200px 缩略图场景 640×384 crop 足够；不满意再升级为管线内单次 ffmpeg |
| 已完成视频缺 best_* 字段 | NULL 兜底 `first_seen` + 惰性补写 |

---

## 附：代码锚点索引

| 改动点 | 文件:行 |
|---|---|
| getThumbBbox 全表扫描 | `frontend/src/components/DetectionPanel.tsx:29-42`、`:271` |
| 检测栏全量渲染 | `frontend/src/components/DetectionPanel.tsx:267-348` |
| 时间轴一 track 一行 | `frontend/src/components/DetectionTimeline.tsx:29-34` |
| 时间轴全量 DOM | `frontend/src/components/DetectionTimeline.tsx:100-142` |
| playhead rAF 无暂停 | `frontend/src/components/DetectionTimeline.tsx:62-71` |
| 后端全量返回 | `api/detection_routes.py:56-103` |
| 缩略图实时 ffmpeg | `api/detection_routes.py:106-150` |
| best_cache（可复用） | `pipeline/runners/detection.py:296-304` |
| crop 缓存（可复用） | `pipeline/runners/detection.py:306-315` |
| 全量数据加载 | `frontend/src/hooks/useDetectionData.ts:33` |
| 选中全量重渲 | `frontend/src/Dashboard.tsx:136-145` |
