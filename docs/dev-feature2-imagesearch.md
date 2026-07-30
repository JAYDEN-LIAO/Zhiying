# Dev Doc: 通用图搜视频

> 目标：在已有的「人脸图片搜索」（ArcFace 512d）之外，新增一个「通用图搜」按钮。上传任意图片 → Qwen3-VL-Embedding 2048-dim → 与 `frame_embeddings` 表向量匹配 → 返回最相似帧的时间点。

## 现状分析

### 已有搜索路径对比

| 特性 | 人脸搜索（已有） | 通用图搜（新建） |
|---|---|---|
| **编码器** | ARC Face R50 (512-dim) | Qwen3-VL-Embedding (2048-dim) |
| **目标表** | `face_identities` | `frame_embeddings`（已就绪） |
| **检测步骤** | 图片中检测人脸 → 裁切 → 编码 | 无检测，整图直接编码 |
| **结果** | 人物身份 + 出现时间段 | 帧级精确时间戳（秒） |
| **API** | `POST /search/face` | `POST /search/image` (新建) |

### 已就绪的基础设施

1. **Qwen Embedder 已启动时预加载** — `app.state.embedder` 在 `main.py` lifespan 中初始化，`encode_image()` 接受任意 `np.ndarray` 图片返回 2048-dim 向量
2. **`SearchEngine.search()` 已支持 `image_vec` 参数** — 见 `pipeline/search_engine.py:47`，当 `image_vec` 非空时跳过文本编码，直接使用传入向量
3. **`frame_embeddings` 表已就绪** — Pipeline 自动填充 1fps 帧向量
4. **`frame_vector_search()` 已支持按 video_id 过滤** — `core/search.py:27-47`
5. **前端已有的搜索卡片组件** — `VideoSearchCard.tsx` 已有人脸搜索按钮，样式和流程可复用

## 后端设计

### 新增 API: `POST /api/v1/search/image`

```python
@router.post("/search/image")
async def search_image(
    file: UploadFile = File(...),
    video_ids: str | None = None,
    search_types: str | None = None,
    top_k: int = 20,
    min_similarity: float = 0.3,
    request: Request = None,
) -> APIResponse[list[dict]]:
```

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | UploadFile | ✅ | 图片文件 (JPEG/PNG/WebP) |
| `video_ids` | str (query) | ❌ | 逗号分隔的 UUID，限定搜索范围 |
| `search_types` | str (query) | ❌ | 逗号分隔，默认 `"frame,track"` |
| `top_k` | int | ❌ | 返回条数上限，默认 20 |
| `min_similarity` | float | ❌ | 最低相似度，默认 0.3 |

#### 流程图

```
用户上传图片
  → api/search_routes.py search_image()
  → PIL Image.open() → np.ndarray (RGB)
  → app.state.embedder.encode_image(image_array)  # Qwen 2048-dim
  → SearchEngine.search(image_vec=vec, search_types=["frame","track"], ...)
    → _frame_search (frame_embeddings 余弦相似度)
    → _track_search (track_embeddings 余弦相似度) [可选]
  → 去重、聚类、补全 scene 信息（已有逻辑）
  → 返回格式化结果
```

#### 返回格式

复用 `SemanticSearchRequest` 同一套 `SearchResultItem` 格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "results": [
      {
        "video_id": "uuid",
        "scene_index": 5,
        "precise_start": 42.0,
        "precise_end": null,
        "precision_level": "frame",
        "match_paths": ["frame"],
        "similarity": 0.87,
        "thumbnail_url": "/api/v1/videos/uuid/thumbnail/5",
        "caption": "..."
      }
    ],
    "total": 3,
    "query_time_ms": 234.5
  }
}
```

**关键区别**：和人脸搜索不同的是，通用图搜返回 `SearchResultItem` 格式（带 `precise_start` 精确时间戳），而不是 `FaceSearchResult` 格式。所以前端可以直接用已有的搜索结果卡片渲染逻辑。

### SearchEngine 改动

`SearchEngine.search()` 的 `image_vec` 参数已经支持。只需添加：

```python
# 在 search_image endpoint 中
se = getattr(request.app.state, "_searcher", None)
# ... 或在构造后传参
results = await se.search(
    image_vec=vec,                    # ← 直接传图片向量
    video_ids=vid_list,
    search_types=st_list,             # ["frame", "track"]
    top_k=top_k,
    min_similarity=min_similarity,
)
```

图片搜索不传 `query`，只传 `image_vec`，所以 `_text_search`、`_label_search`、`_plate_search` 不会触发（它们依赖 query 字符串）。只有 `_frame_search` 和 `_track_search`（需向量）会走。

## 前端设计

### VideoSearchCard.tsx — 新增「通用图搜」按钮

在人脸搜索按钮**右侧**再加一个图片按钮：

```tsx
// 在搜索输入栏中
<div className="src-wrap">
  {/* ... 已有搜索 input ... */}
  <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={handleFaceFile} className="hidden" />
  <button className="src-face" onClick={() => fileInputRef.current?.click()} disabled={faceSearching} title="人脸搜索">
    {/* face icon */}
  </button>
  { /* ★ 新增：通用图搜按钮 */ }
  <input ref={imageInputRef} type="file" accept="image/jpeg,image/png,image/webp" onChange={handleImageSearch} className="hidden" />
  <button className="src-image" onClick={() => imageInputRef.current?.click()} disabled={imageSearching} title="以图搜图">
    {/* image icon */}
  </button>
</div>
```

#### 新状态

```typescript
const [imageSearching, setImageSearching] = useState(false);
const imageInputRef = useRef<HTMLInputElement>(null);
```

#### 新处理函数

```typescript
const handleImageSearch = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
  const file = e.target.files?.[0]; if (!file) return;
  setImageSearching(true); setError(null);
  try {
    const data = await api.searchImage(file, {
      video_ids: currentVideoId ? [currentVideoId] : undefined,
    });
    setResults(data.results ?? []);
    setHasSearched(true);
  } catch (err) {
    setError(err instanceof Error ? err.message : "图搜失败");
  } finally {
    setImageSearching(false);
    if (imageInputRef.current) imageInputRef.current.value = "";
  }
}, [currentVideoId]);
```

**设计决策**：图搜结果直接写入 `results` 状态（和非搜索文本结果相同），共用已有的结果卡片渲染。不单独建 `imageResults` 状态。如果有文本搜索结果或人脸搜索结果，点击图搜按钮时**清空**前面两种结果。

### api.ts — 新增 `searchImage` 方法

```typescript
searchImage(file: File, options?: {
  video_ids?: string[];
  top_k?: number;
  min_similarity?: number;
}) {
  const form = new FormData();
  form.append("file", file);
  if (options?.video_ids?.length) form.append("video_ids", options.video_ids.join(","));
  if (options?.top_k != null) form.append("top_k", String(options.top_k));
  if (options?.min_similarity != null) form.append("min_similarity", String(options.min_similarity));
  return request<SearchResults>(`${BASE}/search/image`, { method: "POST", body: form });
}
```

#### types/index.ts — 无需新增类型

通用图搜结果复用 `SearchResultItem` 类型，与语义搜索结果格式一致。

## 改动清单

### 后端

| 文件 | 改动 |
|---|---|
| `api/search_routes.py` | 新增 `search_image()` 端点 (`POST /search/image`) |
| `api/schemas.py` | 可能不需要改（复用 SearchResultItem） |

### 前端

| 文件 | 改动 |
|---|---|
| `frontend/src/components/VideoSearchCard.tsx` | 新增图搜按钮、文件输入、`handleImageSearch`、loading 状态；结果渲染复用已有逻辑 |
| `frontend/src/services/api.ts` | 新增 `searchImage()` 方法 |
| `frontend/src/types/index.ts` | 无需改动 |

## 设计决策记录

1. **不检测/不切割图片内容** — 整图直接 Qwen 编码，不依赖检测模型（和人脸搜索不同）。用户想搜什么就把什么放进图片
2. **结果复用 `SearchResultItem`** — 和人脸搜索结果格式不同，但和图搜意图一致（搜帧），直接复用语义搜索的结果卡片渲染
3. **搜索路径默认为 frame+track** — 图片不能搜文本/标签/车牌，但可以搜物体（track）。如果需要更精确可以切到 `["frame"]` 只搜帧
4. **不存在 embedding 缓存** — 图片不像文本 query 那样可以缓存（理论上每张图片都不同），所以每次都重新编码
5. **前端显示"以图搜图"结果时，不清除同屏文本搜索的人脸搜索的历史** — 但用户同时只能看到一类结果（按点击顺序覆盖）
