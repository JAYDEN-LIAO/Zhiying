# 事件驱动 DAG 调度器 — 重构方案

> 替代 `topological_batches` → `asyncio.gather(*batch)` 的静态批次模式  
> 改为每个操作只等直接上游 → 就绪即启动 → 真正的细粒度并行

---

## 1. 当前问题

```
topological_batches 的行为:
  按依赖深度分组 → 同深度的 op 放入同一批
  → 批次内全部完成才能进入下一批
  → "同层同批" 是图论习惯, 不是业务需求

实际影响:
  detection(80s) + keyframes(3s) 同批
  → frame_encode 等 keyframes 3s 就绪, 但被 detection 堵 77s
  → caption + frame_encode + detection 三者在语义上无依赖
  → 但被拓扑排序的批次壁垒绑定
```

---

## 2. 目标行为

```
duration 完成 ──→ segmentation 启动
segmentation 完成 ──→ keyframes 启动
                   ├─→ detection 启动        ← 两个独立开跑
                   │
keyframes 完成 ──→ frame_encode 启动        ← 只等 keyframes, 不等 detection
keyframes 完成 ──→ caption 启动             ← 和 frame_encode 同时
caption 完成 ──→ summary 启动
caption 完成 ──→ text_encode 启动
detection + frame_encode 完成 → track_encode 启动 ← 等两个上游都完成
```

---

## 3. 实现：信号驱动的调度器

### 3.1 核心概念

```python
class EventDrivenScheduler:
    """每个 operation 注册一个 asyncio.Event → 上游完成后 set() → 下游唤醒。"""

    def __init__(self, operations, pctx, tracker):
        self.ops = {op.name: op for op in operations}
        self.pctx = pctx
        self.tracker = tracker
        self._done: dict[str, asyncio.Event] = {}  # op.name → event
        self._embedder_lock = asyncio.Lock()        # embedder 并发保护

    async def run(self) -> None:
        """启动所有 op，每个 op 内部先等依赖完成，再执行。"""
        for name in self.ops:
            self._done[name] = asyncio.Event()

        tasks = [
            asyncio.create_task(self._run_op(name))
            for name in self.ops
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            raise PipelineError(f"{len(errors)} operations failed") from errors[0]

    async def _run_op(self, name: str) -> None:
        op = self.ops[name]

        # 等待所有依赖 (被过滤的依赖不在 self._done 中 → 直接跳过)
        for dep_name in op.depends_on:
            event = self._done.get(dep_name)
            if event is not None:
                await event.wait()

        # 执行
        await op.runner.run(self.pctx)

        # 信号: 我完成了
        self._done[name].set()
```

### 3.2 不变项

| 组件 | 改动 |
|------|:---:|
| `Operation` 声明 | 零改动 |
| `OperationRunner.run(pctx)` | 零改动 |
| `StatusTracker` | 零改动 |
| `PipelineContext` | 加一个 `embedder_lock: asyncio.Lock` |
| `_persist()` | 零改动（调度器跑完后统一 persist） |
| `_load_plugins()` | 零改动 |
| `_set_processing()` / `mark_completed()` / `mark_failed()` | 零改动 |

### 3.3 engine.run() 变化

```python
# 旧:
batches = topological_batches(enabled)
for batch in batches:
    await asyncio.gather(*[op.runner.run(pctx) for op in batch])
await self._persist()

# 新:
scheduler = EventDrivenScheduler(enabled, pctx, tracker)
await scheduler.run()
await self._persist()
```

---

## 4. 资源竞争：embedder 并发保护

三个 runner 使用共享 embedder：`frame_encode`、`text_encode`、`track_encode`。

```
问题: 事件驱动后三者可能同时运行 → 多个 asyncio.to_thread → 同时 GPU forward
     → PyTorch 内部 CUDA stream 竞争 → OOM 或结果正确但慢

方案: PipelineContext 加 asyncio.Lock
  embedder_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

  使用端:
    async with pctx.embedder_lock:
        emb = await embedder.encode_image(frame)
```

改动范围：`core/interfaces.py`（PipelineContext 加字段）、使用 embedder 的 3 个 runner 方法内包裹 `async with pctx.embedder_lock:`。

---

## 5. 错误处理

```
_do_run_op 失败:
  → done_events[name] 仍然 set() (避免下游永久等待)
  → 异常被 gather(return_exceptions=True) 捕获
  → 调度器汇总所有异常, raise 第一个
  → engine.run() 的 except 块捕获 → mark_failed
```

---

## 6. 增量处理兼容

`run_incremental()` 只跑子集操作。事件驱动同样适用——`ops` 列表只有需要跑的那几个，依赖关系自动处理。

---

## 7. 进度条

StatusTracker 的权重计算基于传进来的 operations 列表。事件驱动后权重不变——操作顺序变了但 total_weight 和每个 op 的权重占比没变。

但进度条范围不再"有序"。当前：
```
duration 0.0-0.04 → segmentation 0.04-0.33 → keyframes 0.33-0.62 → ...
进度条从左到右 = 操作执行顺序
```

新调度器下，detection 和 keyframes 同时跑。它们占据的进度范围是预先分配的，前端看到的是两条独立的子进度条在各自的范围内推进。StatusTracker 的 `sub_progress` 机制天然支持——每个 op 在自己分配的区间内独立推进，前端看到的进度条是累计效果。

**不需要改动 StatusTracker。**

---

## 8. 文件变更清单

| 文件 | 改动 |
|------|------|
| `pipeline/engine.py` | 删除 `topological_batches`，新增 `EventDrivenScheduler` 类，`run()` 调用它 |
| `core/interfaces.py` | `PipelineContext` 加 `embedder_lock: asyncio.Lock` |
| `pipeline/runners/frame_encode.py` | `encode_image` 调用处包裹 `async with pctx.embedder_lock` |
| `pipeline/runners/text_encode.py` | `encode_text` 调用处包裹 `async with pctx.embedder_lock` |
| `pipeline/runners/track_encode.py` | `encode_image[s]_batch` 调用处包裹 `async with pctx.embedder_lock` |

**不需要改动:** `operations.py`、`StatusTracker`、所有其他 runner、`_persist()`、前端。

---

## 9. 效果对比 (137s 视频, 20fps detection)

```
旧 DAG (静态批次):
  Batch 0: duration (0.5s)
  Batch 1: segmentation (2s)
  Batch 2: keyframes(3s) + detection(80s) → 等 80s
  Batch 3: frame_encode(5s) → 又等 5s
  Batch 4: track_encode(0.2s)
  ─────────────────────────────────────
  搜索可用: 88s    检测可用: 88s

新 DAG (事件驱动):
  duration (0.5s)
    → segmentation (2s)
      → keyframes (3s)
        → frame_encode (5s)            ← 不等 detection!
      → detection (80s)                ← 和 frame_encode 并行
  frame_encode + detection 都完成
    → track_encode (0.2s)
  ─────────────────────────────────────
  搜索可用: 8s     检测可用: 80s     跟踪嵌入: 80s
```

---

## 10. 未来扩展：零摩擦

```
新增 OCR runner:
  1. 写 OCRRunner 类
  2. 注册 Operation(name="ocr", depends_on=["keyframes"], ...)
  3. 完成

引擎自动:
  - OCR 在 keyframes 完成后自动启动 → 和 caption/detection 并行
  - 不手动调依赖链
  - 不碰 engine.py
```
