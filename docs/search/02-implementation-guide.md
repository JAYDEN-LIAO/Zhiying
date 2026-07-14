# Cerno 统一搜索架构 — 施工改造文档

> 配套设计文档: `docs/search/01-search-architecture.md`

## 施工概览

按依赖链分 6 个阶段，每阶段独立可验证。

| 阶段 | 改动范围 | 完成后可验证 |
|---|---|---|
| S1 数据模型 | `core/models.py` + `core/db.py` | 新表创建成功 |
| S2 embedder 扩展 | `plugins/embedder/qwen_vl_embedder.py` + `core/interfaces.py` | `encode_video` 返回 2048 维向量 |
| S3 编码流程 | `pipeline/engine.py` + `core/repository.py` + `pipeline/phase4_caption.py` | 新表正确填充数据 |
| S4 搜索函数 | `core/search.py` | frame/chunk 向量搜索返回正确结果 |
| S5 搜索引擎 | `pipeline/search_engine.py` | 四路并行召回 + 结果合并 |
| S6 API + 前端 | `api/routes.py` + frontend | 搜索接口返回统一格式，前端自适应展示 |

---

## S1: 数据模型

### 涉及文件

- `core/models.py` — 新增 `FrameEmbedding`, `Chunk` ORM 模型
- `core/db.py` — `init_db()` 自动建表

### 实施步骤

**1.1 `core/models.py` 末尾新增**

```python
# ═══════════════════════════════════════════════════════════
# FrameEmbedding — 逐帧向量，1fps 采样
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# Chunk — 场景内滑动窗口，多帧原生编码
# ═══════════════════════════════════════════════════════════

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

**1.2 `core/db.py` 的 `init_db()` 确认**

已调用 `Base.metadata.create_all`，新增的两个 ORM 模型会自动建表。无需额外改动。

**验证**：重启后端，检查 PostgreSQL 中 `frame_embeddings` 和 `chunks` 两个表是否创建成功。

---

## S2: embedder 扩展

### 涉及文件

- `core/interfaces.py` — `BaseEmbedder` 新增 `encode_video` 抽象方法
- `plugins/embedder/qwen_vl_embedder.py` — 实现 `encode_video`

### 实施步骤

**2.1 `core/interfaces.py` 的 `BaseEmbedder` 类新增**

在 `encode_text` 方法之后加入：

```python
@abstractmethod
async def encode_video(self, images: list[np.ndarray]) -> list[float]:
    """多帧原生视频编码 — 时序感知的场景/chunk 级向量。

    Args:
        images: 按时间顺序排列的帧序列 (N, H, W, C) uint8。

    Returns:
        2048 维归一化向量（Qwen3-VL-Embedding-2B 输出维度）。
    """
    ...
```

**2.2 `qwen_vl_embedder.py` 新增 `encode_video` 和 `_sync_encode_video` 方法**

在 `encode_text` 方法之后加入：

```python
async def encode_video(self, images: list[np.ndarray]) -> list[float]:
    """多帧原生视频编码 — 一次传入所有帧，模型内部跨帧注意力捕获时序。"""
    if not images:
        logger.warning("[QwenVLEmbedder] encode_video called with empty images")
        return []
    try:
        vector = await asyncio.to_thread(self._sync_encode_video, images)
        return vector
    except Exception as e:
        logger.exception("[QwenVLEmbedder] Video encoding failed")
        raise

def _sync_encode_video(self, images: list[np.ndarray]) -> list[float]:
    """同步多帧编码 — 在线程池中执行。"""
    inputs = self.processor(
        text=[self.IMAGE_PROMPT],
        images=images,
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

**验证**：Python 交互测试，传入 3 帧随机 numpy 数组，验证返回 2048 维 float list。

---

## S3: 编码流程（帧池复用 + 批量写入）

### 涉及文件

- `pipeline/engine.py` — `_extract_keyframes()` 改为 1fps 抽帧，新增 chunk 切分和批量编码
- `core/repository.py` — 新增 `bulk_insert_frames` 和 `bulk_insert_chunks`
- `pipeline/phase4_caption.py` — 从帧池中取代表帧做 VLM caption

### 实施步骤

**3.1 `pipeline/engine.py` — 重写 `_extract_keyframes()`**

当前逻辑：每场景取 3-7 帧 → 只存 scene.keyframes 到内存。

新逻辑：

```python
async def _extract_keyframes(self) -> None:
    from utils.video_util import extract_keyframe_to_memory

    scenes = self.ctx.scenes
    if not scenes:
        return

    logger.info("[Pipeline] Extracting frame pool @ 1fps ...")

    for i, scene in enumerate(scenes):
        duration = scene.end_sec - scene.start_sec
        # ---- 1fps 抽帧 ----
        frame_pool: list[tuple[float, np.ndarray]] = []
        t = scene.start_sec
        while t < scene.end_sec:
            try:
                frame = await extract_keyframe_to_memory(self.ctx.file_path, t)
                if frame is not None:
                    frame_pool.append((t, frame))
            except Exception:
                pass
            t += 1.0

        if not frame_pool:
            continue

        scene.keyframes = [f[1] for f in frame_pool]  # 全部帧
        midpoint_idx = len(frame_pool) // 2
        scene.keyframe = frame_pool[midpoint_idx][1]

        # ---- 选取 VLM caption 代表帧 ----
        num_caption_frames = min(len(frame_pool), 7)
        step = max(1, len(frame_pool) // num_caption_frames)
        caption_frames = [frame_pool[k * step][1] for k in range(num_caption_frames)]
        scene._caption_frames = caption_frames

        # ---- 保存帧缩略图（同现有逻辑） ----
        self._save_thumbnails(frame_pool, i, scene)

        # ---- frame_embeddings 批量编码 ----
        #   (注: 实际编码在 Phase 4 进行，这里只存储帧池到 ctx)

    total_frames = sum(len(s.keyframes) for s in scenes if s.keyframes)
    logger.info("[Pipeline] Frame pool: %d frames @ 1fps", total_frames)
```

**3.2 `pipeline/engine.py` — 新增 `_encode_frames()` 方法**

在 Phase 4 调用，对帧池进行两条路的编码：

```python
async def _encode_frames(self) -> None:
    from core.repository import bulk_insert_frames, bulk_insert_chunks

    embedder = self.plugins.get("embedder")
    if embedder is None:
        return

    for scene in self.ctx.scenes:
        if not scene.keyframes:
            continue

        # ---- a. 帧级路: 逐帧 encode_image ----
        frame_embs: list[dict] = []
        for t, frame in scene_frame_pool:  # (timestamp, image)
            emb = await embedder.encode_image(frame)
            frame_embs.append({
                "video_id": self.video.id,
                "scene_index": scene.scene_index,
                "timestamp_sec": t,
                "embedding": emb,
                "thumbnail_path": ...,
                "is_keyframe": frame in scene._caption_frames,
            })
        async with self.db_session_factory() as session:
            await bulk_insert_frames(session, frame_embs)

        # ---- b. chunk路: 滑动窗口 + 原生编码 ----
        duration = scene.end_sec - scene.start_sec
        if duration <= 30:
            # 整个 scene 即一个 chunk
            emb = await embedder.encode_video(scene.keyframes)
            async with self.db_session_factory() as session:
                await bulk_insert_chunks(session, [{
                    "video_id": self.video.id,
                    "scene_index": scene.scene_index,
                    "chunk_index": 0,
                    "start_sec": scene.start_sec,
                    "end_sec": scene.end_sec,
                    "embedding": emb,
                }])
        else:
            # 滑动窗口
            window_sec = 30
            step_sec = 15
            chunk_rows = []
            idx = 0
            pos = scene.start_sec
            while pos + window_sec <= scene.end_sec:
                window_frames = [f for t, f in frame_pool if pos <= t < pos + window_sec]
                if len(window_frames) >= 5:
                    emb = await embedder.encode_video(window_frames)
                    chunk_rows.append({
                        "video_id": self.video.id,
                        "scene_index": scene.scene_index,
                        "chunk_index": idx,
                        "start_sec": pos,
                        "end_sec": min(pos + window_sec, scene.end_sec),
                        "embedding": emb,
                    })
                    idx += 1
                pos += step_sec
            async with self.db_session_factory() as session:
                await bulk_insert_chunks(session, chunk_rows)
```

**3.3 `core/repository.py` — 新增两个批量写入函数**

```python
async def bulk_insert_frames(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    if not rows:
        return
    stmt = insert(FrameEmbedding.__table__)
    await session.execute(stmt, rows)
    await session.commit()
    logger.info("[Repo] Bulk inserted %d frame embeddings", len(rows))


async def bulk_insert_chunks(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    if not rows:
        return
    stmt = insert(Chunk.__table__)
    await session.execute(stmt, rows)
    await session.commit()
    logger.info("[Repo] Bulk inserted %d chunk embeddings", len(rows))
```

注意：`from core.models import FrameEmbedding, Chunk` 需要在 `repository.py` 顶部新增 import。

**3.4 `pipeline/phase4_caption.py` — 适配帧池**

当前取值：`scene.keyframes`。改动轻微——代表帧从 `scene._caption_frames` 取：

```python
# 当前
frames = scene.keyframes  # 全部帧

# 改为
frames = getattr(scene, '_caption_frames', scene.keyframes or [])
```

`scene.embedding` 写入行删除（场景向量不再作为召回源）：

```python
# 删除这两行
scene.embedding = await self._encode_scene(embedder, frames)
```

**3.5 `pipeline/engine.py` — `run()` 中新增 `_encode_frames` 调用**

在 Phase 4 之后、Phase 5 之前插入：

```python
await self._phase4()
await self._encode_frames()  # ← 新增
await self._phase5()
```

**验证**：上传视频，检查 `frame_embeddings` 和 `chunks` 表中是否有数据。

---

## S4: 搜索函数

### 涉及文件

- `core/search.py` — 新增 `frame_vector_search()` 和 `chunk_vector_search()`

### 实施步骤

**4.1 新增 import**

```python
from core.models import Scene, Transcript, FrameEmbedding, Chunk
```

**4.2 新增两个函数**

```python
# ═══════════════════════════════════════════════════════════
# 5. 帧级向量搜索
# ═══════════════════════════════════════════════════════════

async def frame_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[FrameEmbedding, float]]:
    """1fps 帧级搜索 — 逐帧匹配，返回精确时间戳。"""
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


# ═══════════════════════════════════════════════════════════
# 6. chunk 窗口向量搜索
# ═══════════════════════════════════════════════════════════

async def chunk_vector_search(
    session: AsyncSession,
    query_vector: list[float],
    limit: int = 20,
    video_ids: list[str] | None = None,
) -> list[tuple[Chunk, float]]:
    """chunk 窗口搜索 — 多帧原生编码，捕获过程语义。"""
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

**验证**：在已有数据的数据库上执行两函数，确认返回结构正确。

---

## S5: 搜索引擎重组

### 涉及文件

- `pipeline/search_engine.py` — 新增 frame/chunk 召回路，重写结果融合

### 实施步骤

**5.1 import 更新**

```python
from core.models import Scene, FrameEmbedding, Chunk
from core.search import (
    vector_similarity_search, full_text_search,
    frame_vector_search, chunk_vector_search,
)
```

**5.2 `search()` 方法新增 frame 和 chunk 路**

在现有 `search_types` 逻辑中扩展：

```python
search_types = search_types or ["frame", "chunk", "fulltext", "label"]

tasks = []
if "frame" in search_types and vec is not None:
    tasks.append(self._frame_search(vec, video_ids, top_k * 2))
if "chunk" in search_types and vec is not None:
    tasks.append(self._chunk_search(vec, video_ids, top_k * 2))
if "fulltext" in search_types and query:
    tasks.append(self._fulltext_search(query, video_ids, top_k * 2))
if "label" in search_types and query:
    tasks.append(self._label_search(query, video_ids, top_k * 2))
```

删除旧的 vector (scene embedding) 路。

**5.3 新增两个召回方法**

```python
async def _frame_search(self, vec, video_ids, limit):
    async with self.db_session_factory() as session:
        results = await frame_vector_search(session, vec, limit=limit, video_ids=video_ids)
    return [self._frame_to_dict(f, sim) for f, sim in results]

async def _chunk_search(self, vec, video_ids, limit):
    async with self.db_session_factory() as session:
        results = await chunk_vector_search(session, vec, limit=limit, video_ids=video_ids)
    return [self._chunk_to_dict(c, sim) for c, sim in results]

@staticmethod
def _frame_to_dict(frame: FrameEmbedding, sim: float) -> dict:
    return {
        "video_id": str(frame.video_id),
        "scene_index": frame.scene_index,
        "precise_start": frame.timestamp_sec,
        "precise_end": None,  # 单帧无区间
        "precision_level": "frame",
        "similarity": float(sim),
        "source": "frame",
        "thumbnail_url": f"/api/v1/videos/{frame.video_id}/thumbnail/{frame.scene_index}",
    }

@staticmethod
def _chunk_to_dict(chunk: Chunk, sim: float) -> dict:
    return {
        "video_id": str(chunk.video_id),
        "scene_index": chunk.scene_index,
        "start_sec": chunk.start_sec,
        "end_sec": chunk.end_sec,
        "precise_start": chunk.start_sec,
        "precise_end": chunk.end_sec,
        "precision_level": "chunk",
        "similarity": float(sim),
        "source": "chunk",
        "thumbnail_url": f"/api/v1/videos/{chunk.video_id}/thumbnail/{chunk.scene_index}",
    }
```

**5.4 结果融合逻辑**

替换当前的 RRF + 单路路径分岔逻辑为按 `(video_id, scene_index)` 分组合并：

```python
def _merge_results(self, ranked_lists: list[list[dict]]) -> list[dict]:
    """按 (video_id, scene_index) 分组合并，每组合取最高精度。"""
    groups: dict[tuple[str, int], dict] = {}

    for ranked in ranked_lists:
        for item in ranked:
            key = (item["video_id"], item["scene_index"])
            if key not in groups:
                groups[key] = dict(item)
            else:
                existing = groups[key]
                # 取最高相似度
                if item["similarity"] > existing["similarity"]:
                    existing["similarity"] = item["similarity"]
                # 升级精度
                existing["precision_level"] = _best_precision(
                    existing["precision_level"], item["precision_level"],
                )
                if item.get("precise_start") is not None:
                    existing["precise_start"] = item["precise_start"]
                    existing["precise_end"] = item.get("precise_end")
                # 合并 match_paths
                if "source" in item:
                    sources = existing.setdefault("match_paths", [existing.get("source", "")])
                    if item["source"] not in sources:
                        sources.append(item["source"])

    merged = list(groups.values())
    merged.sort(key=lambda x: x["similarity"], reverse=True)
    return merged

def _best_precision(a: str, b: str) -> str:
    order = {"frame": 0, "chunk": 1, "label": 0, "fulltext": 3, "text": 3}
    return a if order.get(a, 9) < order.get(b, 9) else b
```

**5.5 Scene 关联信息补全**

合并后，由 scene_index 反查 scenes 表补全 caption、ocr_text、scene 范围等信息：

```python
async def _enrich_merge(self, merged: list[dict]) -> list[dict]:
    """为合并结果补全 scene 级别信息。"""
    # 批量查询 scene 信息
    video_ids = list(set(m["video_id"] for m in merged))
    async with self.db_session_factory() as session:
        stmt = select(Scene).where(Scene.video_id.in_(video_ids))
        result = await session.execute(stmt)
        scenes = {(str(s.video_id), s.scene_index): s for s in result.scalars().all()}

    for item in merged:
        key = (item["video_id"], item["scene_index"])
        s = scenes.get(key)
        if s:
            item["scene_id"] = s.id
            item["scene_start"] = s.start_sec
            item["scene_end"] = s.end_sec
            item["caption"] = s.caption
            item["ocr_text"] = s.ocr_text
            item["aligned_transcript"] = s.aligned_transcript
    return merged
```

**验证**：发送搜索请求，确认 API 返回四路结果并按 scene 合并。

---

## S6: API + 前端适配

### 涉及文件

- `api/routes.py` — 更新 `SearchResultItem` 模型
- `frontend/src/types/index.ts` — 同步前端类型
- `frontend/src/Dashboard.tsx` — 自适应展示

### 实施步骤

**6.1 `api/routes.py` — 更新 `SearchResultItem`**

```python
class SearchResultItem(BaseModel):
    scene_id: int
    video_id: str
    scene_index: int

    # 场景范围（始终有）
    scene_start: float
    scene_end: float

    # 精确范围（可选）
    precise_start: float | None = None
    precise_end: float | None = None

    precision_level: str = "scene"  # frame/chunk/text/label
    match_paths: list[str] = Field(default_factory=list)

    caption: str | None = None
    ocr_text: str | None = None
    aligned_transcript: str | None = None
    similarity: float | None = None
    thumbnail_url: str | None = None
```

**6.2 搜索端点返回适配**

`search_semantic` 结果构造改为读取合并后的 dict：

```python
items = [
    SearchResultItem(
        scene_id=r.get("scene_id", 0),
        video_id=r["video_id"],
        scene_index=r["scene_index"],
        scene_start=r.get("scene_start", r.get("start_sec", 0)),
        scene_end=r.get("scene_end", r.get("end_sec", 0)),
        precise_start=r.get("precise_start"),
        precise_end=r.get("precise_end"),
        precision_level=r.get("precision_level", "scene"),
        match_paths=r.get("match_paths", []),
        caption=r.get("caption"),
        similarity=r.get("similarity"),
        thumbnail_url=r.get("thumbnail_url"),
    )
    for r in results
]
```

**6.3 frontend — 类型同步**

`frontend/src/types/index.ts`:

```typescript
export interface SearchResultItem {
  scene_id: number;
  video_id: string;
  scene_index: number;
  scene_start: number;
  scene_end: number;
  precise_start: number | null;
  precise_end: number | null;
  precision_level: "frame" | "chunk" | "text" | "label";
  match_paths: string[];
  caption: string | null;
  ocr_text: string | null;
  aligned_transcript: string | null;
  similarity: number | null;
  thumbnail_url: string | null;
}
```

**6.4 frontend — 自适应展示**

搜索结果卡片根据 `precision_level` 选择展示方式：

```
precision_level === "frame"
  → 显示精确时间戳 + frame.thumbnail_url
precision_level === "chunk"
  → 显示时间窗口 + chunk 中间帧
否则
  → 显示 scene 范围 + caption 文本
```

---

## 施工顺序

```
S1 数据模型 → S2 embedder 扩展 → S3 编码流程 → S4 搜索函数 → S5 搜索引擎 → S6 API+前端
  │               │                  │                │               │
  └─ 可独立测试 ──┤                  │                │               │
                  └─ 可独立测试 ──────┤                │               │
                                     └─ 可独立测试 ────┤                │
                                                       └─ 可独立测试 ──┤
                                                                       └─ E2E 验证
```

每个阶段完成后均可独立验证，不依赖后续阶段。
