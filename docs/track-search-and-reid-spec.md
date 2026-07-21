# Track 搜索 + 全局 ReID — 施工文档

> v0.9 → v0.10  
> 新增 `track_encode` runner：对每条 track 选最佳帧 → crop → 跨模态嵌入 → 存入新表 `track_embeddings`。  
> 搜索新增第 5 路 "track"：`encode_text("红衣服的人")` vs `track_embeddings.embedding` 直接命中具体物体。  
> 利用同一份嵌入做强依赖的全局 ReID——超时消失后重出现的同一个人/车，自动合并为一条 track。  
> caption 在纯检索场景（摘要关闭 + scene < 4）自动跳过，节省 30s/视频。

---

## 1. 数据库 — 新表 `track_embeddings`

### 1.1 表结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | SERIAL PK | — |
| `video_id` | UUID FK → videos.id ON DELETE CASCADE | 所属视频 |
| `track_id` | INTEGER NOT NULL | 合并后的最终 track ID（不是 YOLO 原始 ID） |
| `class_name` | VARCHAR(64) NOT NULL | COCO 类别名 |
| `embedding` | Vector(2048) | Qwen3-VL-Embedding-2B 输出的跨模态嵌入 |
| `timestamp_sec` | FLOAT NOT NULL | 最佳帧的时间戳 |
| `bbox` | JSONB NOT NULL | 最佳帧的归一化 bbox `{x1,y1,x2,y2}` |
| `created_at` | TIMESTAMPTZ DEFAULT now() | — |

### 1.2 ORM 模型 (`core/models.py`)

```python
class TrackEmbedding(Base):
    __tablename__ = "track_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    track_id: Mapped[int] = mapped_column(Integer, nullable=False)
    class_name: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(2048), nullable=True)
    timestamp_sec: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video")

    __table_args__ = (
        Index("ix_track_emb_video_track", "video_id", "track_id"),
        {"comment": "Track 语义嵌入表 — YOLO crop 跨模态编码，用于 track 路搜索 + 全局 ReID"},
    )
```

### 1.3 增量迁移 (`core/db.py`)

```python
# ── 增量迁移 v0.10: track 嵌入表 ──
await conn.run_sync(Base.metadata.create_all, tables=[TrackEmbedding.__table__])
```

用 `create_all(tables=[...])` 只建新表，不动已有表。

### 1.4 repository — 批量写入

```python
# core/repository.py

async def bulk_insert_track_embeddings(
    session: AsyncSession,
    video_id: uuid.UUID,
    embeddings: list[dict],
) -> None:
    """批量写入 track_embeddings。每项: {track_id, class_name, embedding, timestamp_sec, bbox}"""
    from core.models import TrackEmbedding

    rows = [
        TrackEmbedding(
            video_id=video_id,
            track_id=e["track_id"],
            class_name=e["class_name"],
            embedding=e["embedding"],
            timestamp_sec=e["timestamp_sec"],
            bbox=e["bbox"],
        )
        for e in embeddings
    ]
    session.add_all(rows)
    await session.commit()
```

---

## 2. Track Encode Runner — 核心

### 2.1 文件

`pipeline/runners/track_encode.py`（新建）

### 2.2 输入

- `pctx.ctx.track_best_frames: dict[int, dict]`（DetectionRunner 产出）
  ```python
  {track_id: {"frame": np.ndarray, "bbox": dict, "timestamp": float, "conf": float}}
  ```
- `pctx.shared_embedder` 或 `pctx.plugins.get("embedder")`
- `pctx.ctx.frame_detections`
- `pctx.ctx.tracks`
- `pctx.video.id`

### 2.3 阶段 1：嵌入提取

```
for each track in pctx.ctx.tracks:
    从 best_cache[track_id] 取最佳帧和 bbox:

    crop = 裁剪最佳帧, bbox 外扩 15%, clamp 到 [0, 1]
        cx, cy = (x1+x2)/2, (y1+y2)/2
        w, h = (x2-x1)*1.3, (y2-y1)*1.3
        x1' = max(0, cx - w/2)
        x2' = min(1, cx + w/2)
        y1' = max(0, cy - h/2)
        y2' = min(1, cy + h/2)
        crop = frame[int(y1'*H):int(y2'*H), int(x1'*W):int(x2'*W)]

    embedding = await embedder.encode_image(crop)

    写入 track_embeddings（临时数据结构）
```

### 2.4 阶段 2：全局 ReID（同类合并）

**设计原则：手搓，零新依赖。** 余弦矩阵用 numpy 一行矢量化，约束过滤用显式 for 循环——透明、可控、不引入 sklearn/scipy 等额外依赖。单视频 track 数 < 100，O(n²) 完全不是瓶颈（25 次比对 < 1ms）。

#### 2.4.1 合并约束（4 条，不多不少）

```
1. 同类别     — person 不跟 car 比
2. 时间不重叠  — 同一时刻出现的两条 track 不可能是同一个人（硬约束）
3. 余弦 ≥ 0.85 — 外观嵌入说"长得像"（主角, 2048 维跨模态信号）
4. 宽松空间门  — 只排除物理上不可能的瞬移（配角, 安全网）
```

只有同时满足 4 条才进入合并候选。

#### 2.4.2 约束详细实现

**时间不重叠 (`time_overlap`)：**

```python
def time_overlap(t1: dict, t2: dict) -> bool:
    """含 1s 缓冲, 防止边界剪裁误差"""
    return not (t1["last_seen"] + 1.0 < t2["first_seen"]
                or t2["last_seen"] + 1.0 < t1["first_seen"])
```

**余弦矩阵 (`cosine_similarity_matrix`)：**

```python
import numpy as np

def cosine_similarity_matrix(embs: np.ndarray) -> np.ndarray:
    """输入 (n, 2048), 输出 (n, n) 余弦相似度矩阵。一行矢量化, 无循环。"""
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    embs = embs / np.maximum(norms, 1e-8)  # L2 归一化
    return embs @ embs.T                     # (n, n), 每个元素 = dot(emb[i], emb[j])
```

**宽松空间门 (`spatial_gate`)：**

只排除物理上不可能的瞬移。不设置严格的硬阈值：

```python
def spatial_gate(t1: dict, t2: dict, frame_width: float = 1.0) -> bool:
    """
    Returns True if the spatial gap is physically plausible (passes the gate).

    frame_width: 归一化画面宽度，默认 1.0（bbox 坐标单位）。

    允许:
      - 任意位置位移 ≤ 50% 画面宽度（正常走/跑）
      - 或者以 ≤ 1.5 画面宽度/秒 的速度移动（快跑/车辆）
    拦截:
      - 人在最左消失, 0.5s 后突然出现在最右 → 物理上不可能
    """
    # bbox 中心坐标
    b1 = t1.get("last_bbox", t1.get("bbox"))  # track_i 消失前最后一帧
    b2 = t2.get("first_bbox", t2.get("bbox")) # track_j 出现后首帧
    if not b1 or not b2:
        return True  # 缺数据 → 不拦

    cx1 = (b1["x1"] + b1["x2"]) / 2
    cy1 = (b1["y1"] + b1["y2"]) / 2
    cx2 = (b2["x1"] + b2["x2"]) / 2
    cy2 = (b2["y1"] + b2["y2"]) / 2

    distance = np.sqrt((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2)
    time_gap = max(t2["first_seen"] - t1["last_seen"], 0.01)  # 避免除零

    max_allowed = max(
        frame_width * 0.5,              # 绝对距离: 最多 50% 画面
        time_gap * frame_width * 1.5,   # 速度上限: 1.5 画面/秒
    )
    return distance <= max_allowed
```

#### 2.4.3 合并算法

```python
def global_reid_merge(
    tracks: list[dict],
    embeddings: list[np.ndarray],
    frame_detections: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    tracks:       [{track_id, class_name, first_seen, last_seen, frame_count, ...}]
    embeddings:   [np.ndarray(2048,), ...]  顺序和 tracks 对应
    frame_detections: [{track_id, timestamp_sec, ...}]

    Returns: (merged_embeddings, merged_tracks, merged_dets)
    """
    n = len(tracks)
    if n < 2:
        return embeddings, tracks, frame_detections

    # ── Step 1: 余弦矩阵 (矢量, 一行) ──
    embs = np.stack(embeddings)          # (n, 2048)
    sim = cosine_similarity_matrix(embs) # (n, n)

    # ── Step 2: 类内 + 约束过滤 + 找最佳匹配 ──
    best_match: dict[int, tuple[int, float]] = {}  # j → (i, sim)
    for i in range(n):
        for j in range(i + 1, n):
            if tracks[i]["class_name"] != tracks[j]["class_name"]:  # 约束 1
                continue
            if time_overlap(tracks[i], tracks[j]):                  # 约束 2
                continue
            if sim[i][j] < 0.85:                                    # 约束 3
                continue
            if not spatial_gate(tracks[i], tracks[j]):              # 约束 4
                continue
            if j not in best_match or sim[i][j] > best_match[j][1]:
                best_match[j] = (i, float(sim[i][j]))

    # ── Step 3: 贪心合并 ──
    merged_ids: set[int] = set()
    merge_map: dict[int, int] = {}   # old_id → new_id
    for j, (i, _) in best_match.items():
        root = i
        while root in merge_map:
            root = merge_map[root]
        merge_map[j] = root
        merged_ids.add(j)

    # 应用合并
    for old_id, new_id in merge_map.items():
        for det in frame_detections:
            if det["track_id"] == old_id:
                det["track_id"] = new_id
        for trk in tracks:
            if trk["track_id"] == old_id:
                # 不删 record, 仅标记 (保留间隙用于时间轴断点显示)
                trk["merged_into"] = new_id

    # 更新主 track
    for trk in tracks:
        if trk["track_id"] in merge_map.values():
            merged = [t for t in tracks if t.get("merged_into") == trk["track_id"]]
            for m in merged:
                trk["first_seen"] = min(trk["first_seen"], m["first_seen"])
                trk["last_seen"] = max(trk["last_seen"], m["last_seen"])
                trk["frame_count"] += m["frame_count"]

    # 仅保留未被合并的 track 的嵌入
    merged_embeddings = [
        emb for i, emb in enumerate(embeddings)
        if tracks[i]["track_id"] not in merged_ids
    ]

    return merged_embeddings, tracks, frame_detections
```

**注意 ** `merged_into` 字段：被合并的 track 不直接删，而是标记引用。前端时间轴渲染时若遇到 `merged_into`，继续在原 lane 画条（只是 track_id 指向合并后的主 track），间断 3 秒清晰可见而不会凭空消失。

### 2.5 集成到 engine.py

#### `DetectionRunner` 增加最佳帧缓存

在 `pipeline/runners/detection.py` 中，`_process_batch` 的上级逻辑里维护：

```python
best_cache: dict[int, dict] = {}  # track_id → {frame, bbox, timestamp, conf}

# 在每帧处理循环中:
for det in batch_dets_for_one_frame:
    tid = det["track_id"]
    conf = det["confidence"]
    if tid not in best_cache or conf > best_cache[tid]["conf"]:
        # 避开头尾 15%: 仅在 track 中间区域替换最佳帧
        # （track 的生命周期在处理时未知，因此先全缓存，最后在 track_encode 中按时间位置过滤）
        best_cache[tid] = {
            "frame": frame,
            "bbox": det["bbox"],
            "timestamp": timestamp,
            "conf": conf,
        }

# DetectionRunner.run() 末尾:
pctx.ctx.track_best_frames = best_cache
```

#### Track Encode Runner 里做头尾过滤

```python
# 对于 track_i，已知其 (first_seen, last_seen)
duration = last_seen - first_seen
head_cut = first_seen + duration * 0.15
tail_cut = last_seen - duration * 0.15

if best_cache[tid]["timestamp"] < head_cut or best_cache[tid]["timestamp"] > tail_cut:
    # 最佳帧落在头尾区 → 用中间时间点重新抽帧
    ts = first_seen + duration * 0.5
    frame = 从 pctx.ctx.file_path 抽帧(ts)
```

fallback 到中间帧的概率很低（best_cache 是全局最佳，天然倾向于中间区域），但仍有防御。

### 2.6 runner 伪代码

```python
class TrackEncodeRunner(OperationRunner):
    async def run(self, pctx: PipelineContext) -> None:
        embedder = pctx.shared_embedder or pctx.plugins.get("embedder")
        if not embedder or not pctx.ctx.tracks:
            return

        best_cache = getattr(pctx.ctx, "track_best_frames", {}) or {}

        # ── Phase 1: crop + embed ──
        crops: list[np.ndarray] = []
        emb_metas: list[dict] = []

        for trk in pctx.ctx.tracks:
            tid = trk["track_id"]
            cache = best_cache.get(tid)
            if not cache:
                continue
            crop = self._expand_crop(cache["frame"], cache["bbox"])
            crops.append(crop)
            emb_metas.append({
                "track_id": tid,
                "class_name": trk["class_name"],
                "timestamp_sec": cache["timestamp"],
                "bbox": cache["bbox"],
            })

        # 批量编码 (若 embedder 不支持 batch 则逐张)
        if hasattr(embedder, "encode_images_batch"):
            emb_vectors = await embedder.encode_images_batch(crops)
        else:
            emb_vectors = [await embedder.encode_image(c) for c in crops]

        for meta, vec in zip(emb_metas, emb_vectors):
            meta["embedding"] = vec

        # ── Phase 2: global ReID merge (手搓, 零新依赖) ──
        embeddings, merged_tracks, merged_dets = global_reid_merge(
            emb_metas, [e["embedding"] for e in emb_metas],
            pctx.ctx.tracks, pctx.ctx.frame_detections,
        )

        # ── Persist ──
        pctx.ctx.track_embeddings = embeddings
        pctx.ctx.tracks = merged_tracks
        pctx.ctx.frame_detections = merged_dets
```

---

## 3. DAG — 操作声明

### 3.1 新操作 (`pipeline/operations.py`)

```python
from pipeline.runners.track_encode import TrackEncodeRunner

Operation(
    name="track_encode", runner=TrackEncodeRunner(),
    depends_on=["detection", "text_encode"],
    gate=lambda v, cfg: (
        v.detection_enabled
        and v.search_index_enabled
        and v.vision_enabled
        and cfg.get("plugins", {}).get("detector", {}).get("backend") is not None
    ),
    required_plugins=["embedder"],
    label="物体语义编码", description="Track 跨模态嵌入 + 全局重识别",
    progress_weight=0.03,
),
```

### 3.2 新的拓扑顺序

```
Batch 0: [duration]                          0.5s
Batch 1: [segmentation]                      2s
Batch 2: [keyframes, detection]            max(3, 26) = 26s
Batch 3: [caption, frame_encode]            30s    ← caption 可能跳过
Batch 4: [text_encode, summary]              5s
Batch 5: [track_encode]                      0.2s  ← ReID 比对 (< 0.5s)
```

### 3.3 Caption 条件化 (`pipeline/runners/caption.py`)

`CaptionRunner.run()` 头部加运行时跳过逻辑：

```python
async def run(self, pctx: PipelineContext) -> None:
    # 仅检索模式（摘要未开）+ scene 太少 → 跳过 caption
    scenes = pctx.ctx.scenes
    if not pctx.video.summary_enabled and len(scenes) < 4:
        logger.info("[CaptionRunner] Skipping: summary off + only %d scenes (< 4)", len(scenes))
        return

    # ... 原有逻辑
```

注意: caption 跳过后，`text_encode` 的 gate 检查 `caption_enabled`，会自动跳过（之前已修复该 gate bug）。summary 也因 disable 而跳过。整个 Batch 3 和 4 会大幅加速。

---

## 4. 搜索 — 新增 track 路

### 4.1 `core/search.py` 新增函数

```python
async def track_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[TrackEmbedding, float]]:
    """track 嵌入搜索 — encode_text(query) vs track c crop 跨模态嵌入。"""
    from core.models import TrackEmbedding

    similarity = (1.0 - TrackEmbedding.embedding.cosine_distance(query_vector)).label("sim")
    stmt = (
        select(TrackEmbedding, similarity)
        .where(TrackEmbedding.embedding.isnot(None))
        .order_by(similarity.desc())
        .limit(limit)
    )
    if video_ids:
        stmt = stmt.where(TrackEmbedding.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.TrackEmbedding, row.sim) for row in result]
```

### 4.2 `search_engine.py` 新增

```python
# 在 search() 方法的 tasks 列表中:
if "track" in search_types and vec is not None:
    tasks.append(self._track_search(vec, video_ids, top_k * 2))

# 新增方法:
async def _track_search(self, vec, video_ids, limit):
    async with self.db_session_factory() as session:
        results = await track_vector_search(session, vec, limit=limit, video_ids=video_ids)
    return [self._track_to_dict(t, sim) for t, sim in results]

@staticmethod
def _track_to_dict(track_emb, sim):
    return {
        "video_id": str(track_emb.video_id),
        "track_id": track_emb.track_id,
        "class_name": track_emb.class_name,
        "precise_start": track_emb.timestamp_sec,
        "precise_end": None,
        "precision_level": "track",
        "similarity": float(sim),
        "source": "track",
        "bbox": track_emb.bbox,
    }
```

### 4.3 合并逻辑 (`_merge_results`)

track 路结果归入 `others` 分支（和 chunk/text 一样），按时间重叠去重。帧簇优先。

### 4.4 前端

- `precision_level` 新增 `"track"` 值
- 搜索结果展示 track 级信息（class_name + track_id + timestamp）
- 现有的 `DetectionOverlay`、`DetectionPanel`、`DetectionTimeline` 不需要改

---

## 5. engine.py 调整

### 5.1 `_persist()` 新增

```python
# 6. 写入 track_embeddings
if self.ctx.track_embeddings:
    async with self.db_session_factory() as session:
        await bulk_insert_track_embeddings(
            session, self.video.id, self.ctx.track_embeddings
        )
```

### 5.2 `VideoContext` 新增字段

```python
@dataclass
class VideoContext:
    # ... 现有字段 ...
    track_best_frames: dict | None = None       # DetectionRunner 产出
    track_embeddings: list[dict] | None = None   # TrackEncodeRunner 产出
```

---

## 6. 文件变更清单

| 文件 | 改动 |
|------|------|
| `core/models.py` | 新增 `TrackEmbedding` ORM 模型 |
| `core/db.py` | 增量迁移：`create_all(tables=[TrackEmbedding])` |
| `core/interfaces.py` | `VideoContext` 加 `track_best_frames`、`track_embeddings` |
| `core/repository.py` | 新增 `bulk_insert_track_embeddings()` |
| `core/search.py` | 新增 `track_vector_search()` |
| `pipeline/search_engine.py` | 新增 `_track_search()`、`_track_to_dict()`，task 列表加 track 路 |
| **`pipeline/runners/track_encode.py`** | **新文件**：嵌入提取 + 全局 ReID |
| `pipeline/runners/detection.py` | 新增 `best_cache` 维护 |
| `pipeline/runners/caption.py` | 新增 scene < 4 + summary off 跳过逻辑 |
| `pipeline/operations.py` | 新增 `track_encode` Operation |
| `pipeline/engine.py` | `_persist` 加 `track_embeddings` |

---

## 7. 不变项

以下保持原样，不做任何改动：

- YOLO 检测、BoT-SORT 追踪（`yolo.py`）
- 帧/片段/文本编码器（`frame_encode.py`、`chunk_encode.py`、`text_encode.py`）
- 前端 DetectionOverlay / DetectionPanel / DetectionTimeline
- 参数面板 / PipelineParams / 物体栏

---

## 8. 实施顺序

1. `core/models.py` + `core/db.py` — 新表
2. `core/interfaces.py` — VideoContext 字段
3. `core/repository.py` — 批量写入
4. `pipeline/runners/detection.py` — best_cache
5. `pipeline/runners/caption.py` — 条件跳过
6. **`pipeline/runners/track_encode.py`** — 核心新 runner
7. `pipeline/operations.py` — DAG 注册
8. `pipeline/engine.py` — persist
9. `core/search.py` + `pipeline/search_engine.py` — 搜索 track 路
