# Cerno 统一搜索架构设计文档

> 版本: 0.2 | 日期: 2026-07-13 | 状态: 设计阶段

## 一、设计目标

构建四路并行召回、按 scene 合并、精度分级输出的统一搜索架构。每条路径独立工作，搜索结果统一格式，前端自适应展示。

---

## 二、存储层

### 2.1 frame_embeddings（新表）

逐帧向量存储，1fps 采样精度。用于帧级精确时间定位。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | SERIAL PK | |
| `video_id` | UUID FK → videos.id ON DELETE CASCADE | |
| `scene_index` | INTEGER | 所属场景序号 |
| `timestamp_sec` | FLOAT | 精确时间戳（秒） |
| `embedding` | Vector(2048) | `encode_image(单帧)` 输出 |
| `thumbnail_path` | VARCHAR(1024) | 帧缩略图路径 |
| `is_keyframe` | BOOLEAN | 是否被 VLM caption 选中 |
| `created_at` | TIMESTAMPTZ | |

索引:
- `idx_frame_embeddings_video_scene` (video_id, scene_index)
- `idx_frame_embeddings_video_time` (video_id, timestamp_sec)

```python
class FrameEmbedding(Base):
    __tablename__ = "frame_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    scene_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp_sec: Mapped[float] = mapped_column(Float, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(2048), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_keyframe: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video")

    __table_args__ = (
        Index("idx_frame_emb_video_scene", "video_id", "scene_index"),
        Index("idx_frame_emb_video_time", "video_id", "timestamp_sec"),
        {"comment": "逐帧向量表 — 1fps 采样，用于帧级精确搜索定位"},
    )
```

### 2.2 chunks（新表）

多帧原生视频编码，窗口级语义搜索。场景内滑动窗口切片，不跨场景边界。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | SERIAL PK | |
| `video_id` | UUID FK → videos.id ON DELETE CASCADE | |
| `scene_index` | INTEGER | 所属场景序号 |
| `chunk_index` | INTEGER | 场景内窗口序号 |
| `start_sec` | FLOAT | 窗口开始时间 |
| `end_sec` | FLOAT | 窗口结束时间 |
| `embedding` | Vector(2048) | `encode_video(该窗口全部帧)` 输出 |
| `thumbnail_path` | VARCHAR(1024) | 窗口中间帧缩略图 |
| `created_at` | TIMESTAMPTZ | |

索引:
- `idx_chunks_video_scene` (video_id, scene_index)
- `idx_chunks_time_range` (video_id, start_sec, end_sec)

```python
class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    scene_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(2048), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    video: Mapped["Video"] = relationship("Video")

    __table_args__ = (
        Index("idx_chunks_video_scene", "video_id", "scene_index"),
        Index("idx_chunks_time_range", "video_id", "start_sec", "end_sec"),
        {"comment": "视频窗口向量表 — 场景内滑动窗口，用于过程语义搜索"},
    )
```

### 2.3 scenes（现有表，调整用途）

| 列 | 当前用途 | 新用途 |
|---|---|---|
| `embedding` | 搜索召回源 | **废弃搜索用途**，保留兼容；Phase 4b 不再填充 |
| `search_vector` | fulltext 召回 | **不变**，继续由触发器维护 |
| `entities` | label 召回 | **不变**，未来 YOLO 填充 |

Scene 退居幕后，仅负责组织：
- 语义边界 — chunk 不跨 scene 切
- caption 归属 — 全文检索的文本来源
- 摘要编目 — Phase 5 按 scene 组织
- 前端导航 — 场景列表

---

## 三、编码流程（帧池复用）

### 3.1 帧池：一次抽取，三个用途

```
Phase 4 入口
  ↓
scene 按 1fps 抽帧（FFmpeg pipe → memory）
  ↓
内存帧池: List[Frame]  (每帧 = (H,W,C) uint8 numpy + timestamp_sec)
  │
  ├─→ 帧级路: 逐帧 encode_image
  │       ↓
  │   frame_embeddings 表（每帧一行）
  │
  ├─→ chunk路: 每 ≤30 帧编组，一次 encode_video
  │       ↓
  │   chunks 表（每个窗口一行）
  │
  └─→ VLM 路: 每场景选 3-7 帧，Qwen-VL-Max 做 caption
          ↓
      scenes 表（caption 列填充）
```

编码实现：

```python
# 帧级路
for i, frame in enumerate(frame_pool):
    emb = await embedder.encode_image(frame.image)
    await bulk_insert_frames(session, [
        {"video_id": ..., "scene_index": scene_idx,
         "timestamp_sec": frame.t, "embedding": emb, ...}
    ])

# chunk 路
for window in sliding_windows(frame_pool):
    emb = await embedder.encode_video([f.image for f in window])  # 原生视频编码
    await bulk_insert_chunk(session, ...)
```

### 3.2 1fps 抽帧逻辑（替换当前自适应抽帧）

```
// 伪代码
frames = []
for t = scene.start_sec; t < scene.end_sec; t += 1.0:
    frame = extract_keyframe_to_memory(video_path, t)
    frames.append(Frame(image=frame, timestamp=t))

// VLM 路从帧池中选取 3-7 帧（保持当前规则）
keyframe_subset = select_subset(frames, count=3-7)
caption = await captioner.caption(keyframe_subset, prompt)
```

---

## 四、chunk 切分规则

### 4.1 窗口参数

| 参数 | 值 | 根由 |
|---|---|---|
| 窗口长度 | 30s | 完整动作理解单元 |
| 步长 | 15s | 50% 重叠，保证 ≤15s 事件至少被一个完整窗口覆盖 |
| 最小窗口 | 5s | <5 帧无跨帧注意力价值 |
| 最大窗口 | 60s | 受 embedder processor max_frames 和 RTX 4060 8GB 显存约束 |
| 帧采样间距 | 1fps | 30帧/chunk，满足模型输入要求 |

### 4.2 切分策略

```
if scene.duration ≤ 30s:
    不切 → 整个场景即一个 chunk

if scene.duration > 30s:
    窗口 = 30s, 步长 = 15s
    从 scene.start_sec 开始滑动到 scene.end_sec
    起止严格在场景边界内（不跨 scene）
    末窗口 < 15s → 合并到前一窗口
```

### 4.3 示例

```
Scene 1 (0-35s) / Scene 2 (35-45s) / Scene 3 (45-60s)

Scene 1 (>30s → 切):
  chunk 1.0: 0-30s
  chunk 1.1: 15-35s    ← 顶到边界，不跨
Scene 2 (≤30s → 不切):
  chunk 2.0: 35-45s
Scene 3 (≤30s → 不切):
  chunk 3.0: 45-60s
```

---

## 五、搜索层

### 5.1 四路并行召回

```
查询 "红色卡车"
  ↓
embedder.encode_text(query) → query_vec

① 帧向量路                              ② chunk 视频向量路
   query_vec vs                             query_vec vs
   frame_embeddings.embedding               chunks.embedding
   cosine_distance 升序                     cosine_distance 升序
   → 返回: frame.timestamp_sec               → 返回: chunk.start_sec—end_sec

③ 全文检索路                             ④ 物体标签路（未来）
   to_tsquery(query) vs                     entities @> {"label": "query"}
   scenes.search_vector @@ tsquery          JSONB 精确匹配
   ts_rank 降序                             → 返回: entity.start_sec—end_sec
   → 返回: scene.start_sec—end_sec
```

### 5.2 核心 SQL

帧向量搜索（新增到 `core/search.py`）：

```python
async def frame_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[FrameEmbedding, float]]:
    similarity = (1.0 - FrameEmbedding.embedding.cosine_distance(query_vector)).label("sim")
    stmt = (
        select(FrameEmbedding, similarity)
        .where(FrameEmbedding.embedding.isnot(None))
        .order_by(similarity.desc())
        .limit(limit)
    )
    if video_ids:
        stmt = stmt.where(FrameEmbedding.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.FrameEmbedding, row.sim) for row in result]
```

chunk向量搜索（新增到 `core/search.py`）：

```python
async def chunk_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[Chunk, float]]:
    similarity = (1.0 - Chunk.embedding.cosine_distance(query_vector)).label("sim")
    stmt = (
        select(Chunk, similarity)
        .where(Chunk.embedding.isnot(None))
        .order_by(similarity.desc())
        .limit(limit)
    )
    if video_ids:
        stmt = stmt.where(Chunk.video_id.in_(video_ids))
    result = await session.execute(stmt)
    return [(row.Chunk, row.sim) for row in result]
```

---

## 六、结果融合

### 6.1 算法

```
各路输出按 (video_id, scene_index) 分组:

  scene 0:
    帧  路 → frame @215s, sim=0.85
    chunk路 → chunk (210-240s), sim=0.78
    全文路 → scene (0-600s), sim=0.50

  → 合并:
    scene_range:   0-600s          ← 始终有
    precise_range: 215s            ← 取最高精度: frame > chunk > text
    precision:     "frame"
    similarity:    0.85            ← max(各路)
    match_paths:   ["frame","chunk","text"]

不同 scene 间排序: max_sim 降序
```

### 6.2 精度层级（降级策略）

```
entity 时间  →  frame 时间  →  chunk 窗口  →  scene 范围
  (最高)         (高)           (中)            (最低回退)
```

---

## 七、统一搜索响应

### 7.1 Pydantic 模型

```python
class SearchResultItem(BaseModel):
    scene_id: int
    video_id: str
    scene_index: int

    # 场景范围（始终有）
    scene_start: float
    scene_end: float

    # 精确范围（有更高精度时填充）
    precise_start: float | None = None
    precise_end: float | None = None

    # 精度标识
    precision_level: str  # "frame" | "chunk" | "text" | "label"
    match_paths: list[str] = Field(default_factory=list)

    # 内容
    caption: str | None = None
    ocr_text: str | None = None
    aligned_transcript: str | None = None
    similarity: float | None = None
    thumbnail_url: str | None = None
```

### 7.2 前端自适应

```
有 precise_start/end？
  → "红色卡车出现在 03:35" + frame.thumbnail_url 缩略图
只有 scene_start/end？
  → "场景片段 00:00 — 10:00" + caption 摘要文本
```

---

## 八、embedder 能力扩展

### 8.1 新增 encode_video 方法

`BaseEmbedder` 接口新增：

```python
@abstractmethod
async def encode_video(self, images: list[np.ndarray]) -> list[float]:
    """多帧原生视频编码 — 时序感知的 scene/chunk 级向量。

    Args:
        images: 按时间顺序排列的帧序列 (N, H, W, C) uint8。

    Returns:
        2048 维归一化向量。
    """
    ...
```

QwenVLEmbedder 实现：

```python
async def encode_video(self, images: list[np.ndarray]) -> list[float]:
    """processor 接受 videos=[] 参数，一次输入全帧，
    模型内部跨帧注意力捕获时序变化。"""
    return await asyncio.to_thread(self._sync_encode_video, images)

def _sync_encode_video(self, images: list[np.ndarray]) -> list[float]:
    inputs = self.processor(
        text=[self.IMAGE_PROMPT],
        images=images,  # ← 多帧直接传入
        return_tensors="pt",
    )
    inputs = {k: v.to(self.device) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = self.model(**inputs)
    hidden = outputs.last_hidden_state
    embedding = hidden.mean(dim=1).squeeze(0)
    embedding_np = embedding.cpu().numpy().astype(np.float64)
    norm = np.linalg.norm(embedding_np)
    if norm > 0:
        embedding_np = embedding_np / norm
    return embedding_np.tolist()
```

---

## 九、Scene 角色变更

| 变更 | 之前 | 之后 |
|---|---|---|
| `scene.embedding` 搜索用途 | 第①路召回源 | 废弃，不再填充 |
| `scene.embedding` 存储 | 每 scene 存 | 保留列但不再由 Phase 4b 写入 |
| Scene 组织作用 | 无 | chunk 边界约束、caption 归属、摘要编目、前端导航 |

---

## 十、架构约束与设计原则

1. **帧池复用**: 一次 1fps 抽帧，三个消费方（帧向量、chunk向量、VLM caption）共用同一帧池，不重复抽取。
2. **chunk 不跨 scene**: TransNetV2 保证语义边界完整，chunk 严格遵守。
3. **降级策略**: 所有搜索路径产出统一格式，精度从高到低自动回退。
4. **Plugin 可插拔**: 每条搜索路径可独立启用/禁用（通过 search_types 参数）。
5. **数据库最小改动**: 新增 frame_embeddings 和 chunks 两张表，不修改现有 scenes 表结构。
6. **embedder 单一实例**: 复用 `app.state.embedder`，搜索和 Pipeline 共用同一个模型实例。
