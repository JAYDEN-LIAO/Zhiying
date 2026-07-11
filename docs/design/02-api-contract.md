# Cerno API 契约文档

> 版本：v0.1 | 协议：RESTful JSON | 认证：暂无（内网部署） | Base URL: `http://{host}:8000/api/v1`

---

## 一、通用规范

### 1.1 请求头

```
Content-Type: application/json          # 非文件上传接口
Accept: application/json
```

### 1.2 统一响应信封

所有接口返回统一格式：

```json
{
  "code": 0,
  "message": "ok",
  "data": { ... }
}
```

- `code=0` 表示成功；非 0 为业务错误。
- `data` 为具体业务数据，可能为 `null`。

### 1.3 通用 Pydantic 模型

```python
# api/schemas.py

from pydantic import BaseModel, Field
from typing import Generic, TypeVar, Any

T = TypeVar("T")

class APIResponse(BaseModel, Generic[T]):
    code: int = Field(default=0, description="业务状态码, 0=成功")
    message: str = Field(default="ok")
    data: T | None = Field(default=None)

class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int
```

### 1.4 错误码枚举

```python
from enum import IntEnum

class ErrorCode(IntEnum):
    # ── 通用 ──
    SUCCESS            = 0
    INVALID_REQUEST    = 1001    # 请求参数校验失败
    NOT_FOUND          = 1002    # 资源不存在
    INTERNAL_ERROR     = 1003    # 服务器内部错误
    UNPROCESSABLE      = 1004    # 语义错误(如重复上传)

    # ── 视频 ──
    VIDEO_NOT_FOUND     = 2001
    VIDEO_PROCESSING    = 2002   # 视频处理中, 不允许操作
    VIDEO_UPLOAD_FAILED = 2003
    VIDEO_DELETE_FAILED = 2004

    # ── 搜索 ──
    SEARCH_QUERY_EMPTY  = 3001   # query 和 image 都为空
    SEARCH_UNSUPPORTED  = 3002   # 搜索类型不支持(如 Grounding 未启用)

    # ── 导出 ──
    EXPORT_RANGE_INVALID   = 4001
    EXPORT_MERGE_TOO_FEW  = 4002   # 合并导出少于 2 个片段
    EXPORT_CLIP_FAILED     = 4003
```

### 1.5 HTTP 状态码映射

| HTTP Status | 场景 |
|---|---|
| 200 | 成功 |
| 400 | 参数校验失败 (ErrorCode 1001) |
| 404 | 资源不存在 (ErrorCode 1002 / 2001) |
| 422 | 语义错误 (ErrorCode 1004 / 4002) |
| 500 | 服务器内部错误 (ErrorCode 1003) |

---

## 二、视频管理 API

### 2.1 上传视频

```
POST /api/v1/videos/upload
Content-Type: multipart/form-data
```

**Request (form-data):**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | Y | 视频文件 |
| `preset` | string | N | `quick` / `standard` / `full` / `custom`, 默认 `standard` |
| `content_type` | string | N | `general` / `meeting` / `surveillance` / `product`, 默认 `general` |
| `language` | string | N | `auto` / `zh` / `en`, 默认 `auto` |
| `audio_enabled` | bool | N | 默认 `true` |
| `vision_enabled` | bool | N | 默认 `true` |
| `ocr_enabled` | bool | N | 默认 `true` |
| `grounding_enabled` | bool | N | 默认 `false` |
| `caption_enabled` | bool | N | 默认 `true` |
| `summary_enabled` | bool | N | 默认 `true` |

**Pydantic 解析 (表单补充字段):**

```python
from pydantic import BaseModel, Field
from fastapi import UploadFile, File, Form

class VideoUploadOptions(BaseModel):
    preset: str = Field(default="standard", pattern="^(quick|standard|full|custom)$")
    content_type: str = Field(default="general", pattern="^(general|meeting|surveillance|product)$")
    language: str = Field(default="auto", pattern="^(auto|zh|en|ja)$")
    audio_enabled: bool = True
    vision_enabled: bool = True
    ocr_enabled: bool = True
    grounding_enabled: bool = False
    caption_enabled: bool = True
    summary_enabled: bool = True
```

**Response (201):**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "video_id": "b3f1a2c4-...-8d9e",
    "status": "pending",
    "file_name": "meeting_2024_Q3.mp4",
    "created_at": "2026-07-10T10:30:00Z"
  }
}
```

**说明**: 上传立即返回 `video_id`，后台异步启动 pipeline。前端通过 `GET /status` 轮询进度。

---

### 2.2 查询视频列表

```
GET /api/v1/videos/?page=1&page_size=20&status=completed&sort=-created_at
```

**Query Params:**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `page` | int | 1 | 页码 |
| `page_size` | int | 20 | 每页条数 (max 100) |
| `status` | string | - | 筛选: pending / processing / completed / failed |
| `sort` | string | `-created_at` | 排序: `-created_at` / `+duration` / `+file_name` |
| `content_type` | string | - | 筛选内容类型 |

**Response:**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "video_id": "b3f1a2c4-...-8d9e",
        "status": "completed",
        "file_name": "meeting_2024_Q3.mp4",
        "duration": 3600.0,
        "preset": "standard",
        "content_type": "meeting",
        "scene_count": 42,
        "summary_one_liner": "Q3财报会议, 讨论了营收增长和成本控制",
        "progress": 1.0,
        "created_at": "2026-07-10T10:30:00Z",
        "updated_at": "2026-07-10T10:45:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20,
    "pages": 1
  }
}
```

**Pydantic 模型:**

```python
class VideoListItem(BaseModel):
    video_id: str
    status: str
    file_name: str
    duration: float | None
    preset: str
    content_type: str
    scene_count: int | None
    summary_one_liner: str | None
    progress: float
    created_at: str
    updated_at: str
```

---

### 2.3 获取视频详情

```
GET /api/v1/videos/{video_id}
```

**Response:**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "video_id": "b3f1a2c4-...-8d9e",
    "status": "completed",
    "progress": 1.0,
    "file_name": "meeting_2024_Q3.mp4",
    "file_size": 524288000,
    "duration": 3600.0,
    "preset": "standard",
    "content_type": "meeting",
    "language": "zh",
    "config": {
      "audio_enabled": true,
      "vision_enabled": true,
      "ocr_enabled": true,
      "grounding_enabled": false,
      "caption_enabled": true,
      "summary_enabled": true
    },
    "qc_result": {
      "is_valid": true,
      "estimated_duration": 3600.0,
      "black_segments": [],
      "silent_segments": []
    },
    "summary": {
      "one_liner": "Q3财报会议, 讨论了营收增长和成本控制",
      "tags": ["财报", "会议", "Q3"],
      "main_topics": ["营收增长15%", "成本控制", "Q4展望"],
      "main_entities": ["张三", "李四", "财务部"]
    },
    "scene_count": 42,
    "created_at": "2026-07-10T10:30:00Z",
    "updated_at": "2026-07-10T10:45:00Z"
  }
}
```

**Pydantic 模型:**

```python
class VideoConfig(BaseModel):
    audio_enabled: bool
    vision_enabled: bool
    ocr_enabled: bool
    grounding_enabled: bool
    caption_enabled: bool
    summary_enabled: bool

class VideoDetail(BaseModel):
    video_id: str
    status: str
    progress: float
    file_name: str
    file_size: int
    duration: float | None
    preset: str
    content_type: str
    language: str
    config: VideoConfig
    qc_result: dict | None
    summary: dict | None
    scene_count: int | None
    created_at: str
    updated_at: str
```

---

### 2.4 查询处理状态 (轮询)

```
GET /api/v1/videos/{video_id}/status
```

**Response:**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "video_id": "b3f1a2c4-...-8d9e",
    "status": "processing",
    "progress": 0.35,
    "current_phase": "phase_2_vision",
    "phase_description": "物体检测中...",
    "error_message": null,
    "updated_at": "2026-07-10T10:32:30Z"
  }
}
```

**Pydantic 模型:**

```python
class VideoStatusResponse(BaseModel):
    video_id: str
    status: str                # pending / processing / completed / failed
    progress: float            # 0.0 ~ 1.0
    current_phase: str | None  # phase_1_qc / phase_2_audio / phase_2_vision / phase_2_ocr / phase_3_align / phase_4_caption / phase_5_summary
    phase_description: str | None
    error_message: str | None
    updated_at: str
```

**轮询建议**: 前端每 2~5 秒轮询一次，`status == "completed"` 或 `"failed"` 时停止。

---

### 2.5 删除视频

```
DELETE /api/v1/videos/{video_id}
```

**Response:**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "video_id": "b3f1a2c4-...-8d9e",
    "deleted": true
  }
}
```

**说明**: 级联删除 scenes、transcripts 及落盘视频文件。

---

## 三、搜索与浏览 API

### 3.1 语义搜索

```
POST /api/v1/search
```

**Request:**

```json
{
  "query": "猫打碎水杯的片段",
  "image": null,
  "video_ids": ["b3f1a2c4-...-8d9e"],
  "search_types": ["vector", "fulltext"],
  "top_k": 20,
  "min_similarity": 0.3
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `query` | string | * | 文本查询 (与 image 二选一) |
| `image` | file / base64 | * | 以图搜图 (与 query 二选一) |
| `video_ids` | string[] | N | 限定视频范围, 为空则全库搜索 |
| `search_types` | string[] | N | 启用哪些检索路: vector / fulltext / label. 默认全部 |
| `top_k` | int | N | 返回条数, 默认 20, max 100 |
| `min_similarity` | float | N | 相似度阈值, 默认 0.3 |

**Pydantic 模型:**

```python
class SearchRequest(BaseModel):
    query: str | None = Field(default=None, description="文本查询")
    image: str | None = Field(default=None, description="Base64 编码图片")
    video_ids: list[str] | None = Field(default=None)
    search_types: list[str] | None = Field(default=None, description="vector / fulltext / label")
    top_k: int = Field(default=20, ge=1, le=100)
    min_similarity: float = Field(default=0.3, ge=0.0, le=1.0)

    def model_post_init(self, __context):
        if not self.query and not self.image:
            raise ValueError("query 和 image 至少提供一个")
```

**Response:**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "results": [
      {
        "scene_id": 3,
        "video_id": "b3f1a2c4-...-8d9e",
        "video_name": "meeting_2024_Q3.mp4",
        "scene_range": {"start": 120.0, "end": 160.0},
        "precise_range": {"start": 130.0, "end": 138.0},
        "precision_source": "entities",
        "caption": "一只猫跳下桌子碰翻了玻璃杯, 水洒在桌面上",
        "ocr_text": "Q3营收报告",
        "aligned_transcript": "我们看到猫把水杯打翻了...",
        "entities": [
          {
            "label": "cat",
            "bbox": [400, 200, 600, 350],
            "confidence": 0.92,
            "start_sec": 130.0,
            "end_sec": 138.0
          }
        ],
        "similarity": 0.74,
        "thumbnail_url": "/api/v1/thumbnails/b3f1a2c4.../scene_03.jpg"
      }
    ],
    "total": 1,
    "query_time_ms": 42,
    "fusion_method": "RRF"
  }
}
```

**Pydantic 模型:**

```python
class SceneRange(BaseModel):
    start: float
    end: float

class EntityResult(BaseModel):
    label: str
    bbox: list[float]     # [x1, y1, x2, y2]
    confidence: float
    start_sec: float | None
    end_sec: float | None

class SearchResultItem(BaseModel):
    scene_id: int
    video_id: str
    video_name: str
    scene_range: SceneRange
    precise_range: SceneRange | None
    precision_source: str | None     # "entities" / "grounding" / null
    caption: str | None
    ocr_text: str | None
    aligned_transcript: str | None
    entities: list[EntityResult]
    similarity: float
    thumbnail_url: str | None
```

---

### 3.2 获取视频所有场景

```
GET /api/v1/videos/{video_id}/scenes?page=1&page_size=50
```

**Response:**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "scene_id": 0,
        "scene_index": 0,
        "start_sec": 0.0,
        "end_sec": 45.5,
        "ocr_text": "2024 Q3 财报会议",
        "aligned_transcript": "大家好, 欢迎参加本次会议...",
        "caption": "会议室中主持人在屏幕前开始介绍Q3财报会议议程",
        "entities": [
          {"label": "person", "bbox": [300, 100, 500, 400], "confidence": 0.95}
        ],
        "thumbnail_url": "/api/v1/thumbnails/b3f1.../scene_00.jpg"
      }
    ],
    "total": 42,
    "page": 1,
    "page_size": 50,
    "pages": 1
  }
}
```

**Pydantic 模型:**

```python
class SceneSummaryItem(BaseModel):
    scene_id: int
    scene_index: int
    start_sec: float
    end_sec: float
    ocr_text: str | None
    aligned_transcript: str | None
    caption: str | None
    entities: list[EntityResult]
    thumbnail_url: str | None
```

---

### 3.3 获取视频完整转录

```
GET /api/v1/videos/{video_id}/transcript
```

**Response:**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "video_id": "b3f1a2c4-...-8d9e",
    "full_text": "大家好, 欢迎参加本次会议... (全文本)",
    "language": "zh",
    "duration_transcribed": 3580.5,
    "words": [
      {"word": "大家", "start": 0.0, "end": 0.5, "confidence": 0.98},
      {"word": "好", "start": 0.5, "end": 0.8, "confidence": 0.99}
    ]
  }
}
```

---

## 四、交互 API

### 4.1 动态 Grounding (暂停画框)

```
GET /api/v1/videos/{video_id}/grounding?frame_sec=135.5&query=猫
```

**Query Params:**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `frame_sec` | float | Y | 暂停帧对应的时间戳(秒) |
| `query` | string | Y | 用户搜索查询文本 |

**Response:**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "frame_sec": 135.5,
    "query": "猫",
    "objects": [
      {
        "label": "cat",
        "bbox": [420, 180, 580, 370],
        "confidence": 0.91
      },
      {
        "label": "cup",
        "bbox": [510, 290, 560, 380],
        "confidence": 0.84
      }
    ],
    "inference_time_ms": 120
  }
}
```

**Pydantic 模型:**

```python
class GroundingObject(BaseModel):
    label: str
    bbox: list[float]      # [x1, y1, x2, y2]
    confidence: float

class GroundingResponse(BaseModel):
    frame_sec: float
    query: str
    objects: list[GroundingObject]
    inference_time_ms: int
```

---

## 五、导出 API

### 5.1 导出视频片段

```
GET /api/v1/videos/{video_id}/export/clip?start_sec=130.0&end_sec=138.0
```

**Response:** 二进制视频流 (`Content-Type: video/mp4`)。

**Query Params:**

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `start_sec` | float | Y | 开始秒数 |
| `end_sec` | float | Y | 结束秒数 |
| `format` | string | N | `mp4` / `gif`, 默认 `mp4` |

**错误响应 (422):**

```json
{
  "code": 4001,
  "message": "导出时间范围无效: end_sec(130.0) <= start_sec(138.0)",
  "data": null
}
```

---

### 5.2 合并导出多个片段

```
POST /api/v1/export/merge
```

**Request:**

```json
{
  "clips": [
    {"video_id": "b3f1a2c4...", "start_sec": 130.0, "end_sec": 138.0},
    {"video_id": "b3f1a2c4...", "start_sec": 300.0, "end_sec": 375.0}
  ],
  "output_format": "mp4"
}
```

**Pydantic 模型:**

```python
class ClipSpec(BaseModel):
    video_id: str
    start_sec: float
    end_sec: float

class MergeRequest(BaseModel):
    clips: list[ClipSpec] = Field(..., min_length=2)
    output_format: str = Field(default="mp4", pattern="^(mp4|gif)$")
```

**Response:** 二进制视频流。

---

### 5.3 导出 JSON (结构化数据)

```
GET /api/v1/videos/{video_id}/export/json
```

**Response:** `Content-Type: application/json`, 返回包含所有 scenes、transcript、summary 的完整 JSON。

---

### 5.4 导出 Markdown

```
GET /api/v1/videos/{video_id}/export/markdown
```

**Response:** `Content-Type: text/markdown`, 返回可读的剧本式文档:

```markdown
# meeting_2024_Q3.mp4

> 时长: 01:00:00 | 场景: 42 | 标签: 财报, 会议, Q3

## 摘要
Q3财报会议, 讨论了营收增长和成本控制...

## 场景列表

### 场景 0 · 00:00:00 - 00:00:45
**画面**: 会议室中主持人在屏幕前开始介绍Q3财报会议议程
**OCR**: 2024 Q3 财报会议
**台词**: 大家好, 欢迎参加本次会议...
**物体**: person

---
```

---

## 六、维护 API

### 6.1 重新索引

```
POST /api/v1/videos/{video_id}/reindex
```

**Response:**

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "video_id": "b3f1a2c4-...-8d9e",
    "status": "pending",
    "message": "重新索引已加入后台队列"
  }
}
```

**说明**: 当模型版本升级或索引配置变更时，重新走 Phase 4→5（深度理解 + 摘要），不重跑 QC/检测。

---

### 6.2 健康检查

```
GET /health
```

**Response:**

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "db": "connected",
  "checks": {
    "postgresql": "ok",
    "vllm": "ok"
  }
}
```

---

## 七、API 路由注册一览

```python
# api/router.py

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")

# ── 视频管理 ──
router.add_api_route("/videos/upload",        upload_video,     methods=["POST"])
router.add_api_route("/videos/",              list_videos,      methods=["GET"])
router.add_api_route("/videos/{video_id}",     get_video,        methods=["GET"])
router.add_api_route("/videos/{video_id}",     delete_video,     methods=["DELETE"])
router.add_api_route("/videos/{video_id}/status", get_video_status, methods=["GET"])

# ── 搜索与浏览 ──
router.add_api_route("/search",               search,           methods=["POST"])
router.add_api_route("/videos/{video_id}/scenes",     list_scenes,      methods=["GET"])
router.add_api_route("/videos/{video_id}/transcript", get_transcript,   methods=["GET"])

# ── 交互 ──
router.add_api_route("/videos/{video_id}/grounding",   grounding,       methods=["GET"])

# ── 导出 ──
router.add_api_route("/videos/{video_id}/export/clip",     export_clip,     methods=["GET"])
router.add_api_route("/videos/{video_id}/export/json",     export_json,     methods=["GET"])
router.add_api_route("/videos/{video_id}/export/markdown", export_markdown, methods=["GET"])
router.add_api_route("/export/merge",                      export_merge,    methods=["POST"])

# ── 维护 ──
router.add_api_route("/videos/{video_id}/reindex", reindex,        methods=["POST"])
router.add_api_route("/health",                    health_check,   methods=["GET"])
```
