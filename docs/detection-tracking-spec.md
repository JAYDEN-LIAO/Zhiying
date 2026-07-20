# Object Detection & Playback Tracking — Detailed Specification (v2)

> **Goal**: Add object detection (YOLO11) + cross-frame tracking (ByteTrack) to the pipeline, store results in two new DB tables + scenes.entities aggregation, and render smooth bounding boxes over the video player during playback with click-to-select interaction.
>
> **Design Principle**: Zero impact on existing pipeline operations (caption, summary, search, encoding). Pure additive — detection gates on both `config.yaml` (server-level) and `detection_enabled` parameter (per-video).

---

## 0. Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| Detection model | **YOLO11s** (~22MB) | 成熟稳定，Ultralytics 官方推荐服务端场景，比 YOLOv10 新，比 YOLO26 稳 |
| Tracking algorithm | **ByteTrack** | 1265 FPS，无 GPU 需求，精度仅差 StrongSORT 0.37 HOTA，速度是后者 75x |
| DB architecture | **独立表 + scenes.entities 双写** | 独立表支持前端 O(1) 逐帧查询，entities 聚合让已有 `_label_search` 零改动 |
| Parameter control | **双重门控** | `config.yaml` 控制服务器能力 + L2 `detection_enabled` 控制每视频开关 |
| Detection default | **默认关闭** (`default=False`) | 增强功能，类比 audio/ocr 的默认值 |
| ABC interface | **改为批量接口** | GPU batching amortize kernel launch overhead，且现有 ABC 无任何实现类 |
| Frame pool access | **遍历 `scene.keyframes` + `scene.frame_timestamps`** | 帧按 scene 存储，不在单个 `ctx.scenes[0].frame_pool` |
| Smooth bboxes | **前端 track 级线性插值** | 相邻帧匹配 track_id → 按 currentTime 比例插值 bbox 坐标 |

---

## 1. High-Level Data Flow

```
Pipeline Execution (offline batch):
  keyframe runner → per-scene frame pool (scene.keyframes: list[np.ndarray], 1fps)
                      ↓
  detection runner (NEW, in parallel with caption + frame_encode):
    ├─ Collect all frames + timestamps across scenes (flatten)
    ├─ YOLO11 batch inference (batch_size=8, asyncio.to_thread)
    ├─ ByteTrack association → track_id across frames
    ├─ Write to ctx.frame_detections + ctx.tracks (for engine._persist)
    └─ Aggregate per scene → ctx.scenes[i].entities (for label search)

  engine._persist():
    ├─ bulk_insert_frame_detections(session, rows)
    ├─ bulk_insert_tracks(session, rows)
    └─ (existing) bulk_insert_scenes(session, video_id, scenes_data)
        → scenes.entities written via existing path

Video Playback (frontend):
  on video open:
    GET /api/v1/videos/{id}/detection/data
      → returns {tracks: [...], detections: {timestamp_str: [bbox...]}}
  on playback (requestAnimationFrame loop):
    Read video.currentTime → round to floor/ceil timestamps
    → match track_ids across adjacent frames
    → linear interpolate bbox coordinates → draw on canvas
  on click:
    hit-test interpolated bboxes at currentTime → highlight track
```

---

## 2. File Changes (Complete List)

### 2.1 New Files

| # | File | Purpose |
|---|---|---|
| 1 | `plugins/detector/yolo.py` | YOLO11 detector implementation (fill the existing stub) |
| 2 | `pipeline/runners/detection.py` | Detection + ByteTrack tracking Operation runner |
| 3 | `api/detection_routes.py` | API endpoint for frontend to fetch detection data |
| 4 | `frontend/src/components/DetectionOverlay.tsx` | Canvas overlay with interpolated bboxes on video |

### 2.2 Modified Files

| # | File | Change |
|---|---|---|
| 5 | `core/models.py` | Add `FrameDetection` + `Track` ORM models; add `detection_enabled` column to `Video` |
| 6 | `core/schemas.py` | Add `detection_enabled: bool` to `PipelineParams` + `VideoResponse`; add validator rule |
| 7 | `core/interfaces.py` | Change `BaseDetector.detect()` from single-frame to batch interface |
| 8 | `core/repository.py` | Add `bulk_insert_frame_detections()` + `bulk_insert_tracks()` |
| 9 | `pipeline/operations.py` | Register `detection` operation in `ALL_OPERATIONS` |
| 10 | `pipeline/engine.py` | Add detection + tracks persistence to `_persist()` |
| 11 | `pipeline/runners/base.py` | Add `frame_detections` + `tracks` fields to `PipelineContext` |
| 12 | `config/config.yaml` | Set `plugins.detector.backend: yolo` + add model/confidence/iou params |
| 13 | `plugins/factory.py` | Add `_MODULE_OVERRIDES` + `_CLASS_OVERRIDES` entries for detector |
| 14 | `api/router.py` | Mount `detection_routes` under `/api/v1` |
| 15 | `api/schemas.py` | Add `has_detection: bool` to video detail response (or status response) |
| 16 | `frontend/src/Dashboard.tsx` | Add `<DetectionOverlay>` next to `<video>` element |
| 17 | `frontend/src/services/api.ts` | Add `fetchDetectionData(videoId)` function |
| 18 | `frontend/src/types/index.ts` | Add `DetectionData`, `Track`, `Detection` TypeScript types |
| 19 | `frontend/src/components/ParameterPanel.tsx` | Remove hardcoded grayed-out detection toggle; wire to real `detection_enabled` |
| 20 | `core/db.py` | Incremental migration: `ALTER TABLE videos ADD COLUMN IF NOT EXISTS detection_enabled` |

---

## 3. Database Schema

### 3.1 New Table: `frame_detections`

Per-frame, per-detection rows. Indexed for O(1) timestamp lookup during playback.

```python
class FrameDetection(Base):
    __tablename__ = "frame_detections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    track_id: Mapped[int] = mapped_column(index=True)
    timestamp_sec: Mapped[float]                           # seconds from video start (1fps grid)
    class_name: Mapped[str]                                # "person", "car", etc. (COCO 80)
    confidence: Mapped[float]                              # YOLO confidence 0-1
    bbox: Mapped[dict] = mapped_column(JSONB)              # {x1, y1, x2, y2} normalized 0-1
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_frame_detections_video_ts", "video_id", "timestamp_sec"),
    )
```

### 3.2 New Table: `tracks`

One row per unique track (ByteTrack track_id). Used for click-to-highlight and track-level queries.

```python
class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    video_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    track_id: Mapped[int]                                  # ByteTrack internal ID
    class_name: Mapped[str]                                # majority class across frames
    first_seen: Mapped[float]                              # first frame timestamp (seconds)
    last_seen: Mapped[float]                               # last frame timestamp (seconds)
    frame_count: Mapped[int]                               # how many frames this track appears in
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("video_id", "track_id", name="uq_track_video"),
    )
```

### 3.3 Existing: `scenes.entities` (Populated by Aggregation)

Already exists at `core/models.py:255`. The detection runner writes per-scene aggregated entities here:

```python
# Structure matches existing comment on the column:
# [{label, bbox, confidence, start_sec, end_sec, track_id}, ...]
# Aggregated: deduplicated by track_id within the scene's time range
```

This means the existing `_label_search` (`search_engine.py:148`) works with **zero changes**.

### 3.4 Existing: `videos` Table — New Column

```python
detection_enabled: Mapped[bool] = mapped_column(
    default=False, server_default=text("false"),
    comment="L2 perception switch: run YOLO detection pipeline"
)
```

Added via incremental migration in `core/db.py` (following existing `ALTER TABLE ADD COLUMN IF NOT EXISTS` pattern).

---

## 4. Plugin: YOLO11 Detector (`plugins/detector/yolo.py`)

### 4.1 Interface Contract (Updated — Batch Interface)

Change `BaseDetector` in `core/interfaces.py` from single-frame to batch:

```python
class BaseDetector(ABC):
    """物体检测 — 批量帧 → 批量检测物列表。"""

    @abstractmethod
    async def detect(self, frames: list[np.ndarray]) -> list[list[dict]]:
        """
        Args:
            frames: list of RGB numpy arrays (H, W, 3), any resolution.
                    Length is batch_size (typically 8).
        Returns:
            list of same length as frames. Each element is a list of detection dicts:
            [{"bbox": [x1, y1, x2, y2], "confidence": float, "class_name": str}, ...]
            bbox is in normalized 0-1 coordinates (relative to frame width/height).
        """
        ...
```

**Rationale**: GPU inference benefits from batching (amortize kernel launch overhead). The existing ABC has zero implementations, so this change is safe.

### 4.2 Implementation

- Use `ultralytics` YOLO11 (`yolov11s.pt`, ~22 MB)
- Load model once in `__init__`
- `detect()` wraps `model.predict(frames, ...)` in `asyncio.to_thread()`
- Strip irrelevant fields, return only `bbox`, `confidence`, `class_name`
- Bbox normalized to 0-1 (YOLO native output format, no conversion needed)

### 4.3 Configuration

```yaml
# config/config.yaml
plugins:
  detector:
    backend: yolo
    model: yolov11s.pt          # or yolov11n.pt (~6MB) / yolov11m.pt (~52MB)
    confidence_threshold: 0.4
    iou_threshold: 0.5
    batch_size: 8               # frames per inference batch
```

### 4.4 Factory Registration

Add missing entries to `plugins/factory.py`:

```python
_MODULE_OVERRIDES[("detector", "yolo")] = "yolo"
_CLASS_OVERRIDES[("detector", "yolo")] = "YoloDetector"
```

Note: `CATEGORY_MAP["detector"]` and `IMPL_CLASS_MAP["detector"]` already exist (lines 28, 40).

---

## 5. Pipeline: Detection Runner (`pipeline/runners/detection.py`)

### 5.1 Runner Contract

```python
class DetectionRunner(OperationRunner):
    """YOLO11 detection + ByteTrack tracking. Runs in parallel with caption + frame_encode."""

    operation_name = "detection"
    label = "物体检测与追踪"

    async def run(self, ctx: PipelineContext) -> None:
        # 1. Collect all frames across all scenes (flatten)
        all_frames = []
        all_timestamps = []
        for scene in ctx.ctx.scenes:
            if scene.keyframes:
                all_frames.extend(scene.keyframes)
                all_timestamps.extend(scene.frame_timestamps)

        # 2. Graceful skip for ultra-short videos
        if len(all_frames) == 0:
            ctx.frame_detections = []
            ctx.tracks = []
            return

        # 3. YOLO11 batch inference
        detector = load_plugin(self.config, "detector")
        batch_size = self.config.get("plugins", {}).get("detector", {}).get("batch_size", 8)
        all_dets = []
        for i in range(0, len(all_frames), batch_size):
            batch = all_frames[i:i + batch_size]
            batch_dets = await detector.detect(batch)
            all_dets.extend(batch_dets)

        # 4. ByteTrack association
        tracker = ByteTrack(...)
        frame_detections = []
        tracks_map = {}  # track_id → {class_name, first_seen, last_seen, frame_count}

        for frame_idx, (timestamp, dets) in enumerate(zip(all_timestamps, all_dets)):
            tracked = tracker.update(dets, frame_idx)
            for t in tracked:
                frame_detections.append({
                    "video_id": ctx.video.id,
                    "track_id": t.track_id,
                    "timestamp_sec": timestamp,
                    "class_name": t.class_name,
                    "confidence": t.confidence,
                    "bbox": t.bbox,  # {x1, y1, x2, y2}
                })
                # Update track summary
                if t.track_id not in tracks_map:
                    tracks_map[t.track_id] = {
                        "video_id": ctx.video.id,
                        "track_id": t.track_id,
                        "class_name": t.class_name,
                        "first_seen": timestamp,
                        "last_seen": timestamp,
                        "frame_count": 1,
                    }
                else:
                    trk = tracks_map[t.track_id]
                    trk["last_seen"] = timestamp
                    trk["frame_count"] += 1
                    trk["class_name"] = majority_class(trk, t.class_name)  # track-level majority vote

        ctx.frame_detections = frame_detections
        ctx.tracks = list(tracks_map.values())

        # 5. Aggregate per-scene entities (for label search, zero changes needed)
        for scene in ctx.ctx.scenes:
            scene_entities = []
            seen_track_ids = set()
            for fd in frame_detections:
                if (scene.start_sec <= fd["timestamp_sec"] <= scene.end_sec
                        and fd["track_id"] not in seen_track_ids):
                    seen_track_ids.add(fd["track_id"])
                    scene_entities.append({
                        "label": fd["class_name"],
                        "bbox": [fd["bbox"]["x1"], fd["bbox"]["y1"],
                                 fd["bbox"]["x2"], fd["bbox"]["y2"]],
                        "confidence": fd["confidence"],
                        "start_sec": fd["timestamp_sec"],
                        "end_sec": fd["timestamp_sec"],
                        "track_id": fd["track_id"],
                    })
            scene.entities = scene_entities if scene_entities else None
```

### 5.2 ByteTrack Integration

- Use `boxmot` package (`pip install boxmot`) — provides clean ByteTrack Python API
- ByteTrack is imported directly (NOT a plugin — it's a tracking utility)
- Add `boxmot` to `requirements.txt` and `Dockerfile`

### 5.3 PipelineContext Changes (`pipeline/runners/base.py`)

```python
@dataclass
class PipelineContext:
    # ... existing fields ...
    frame_detections: list[dict] | None = None   # NEW: for _persist()
    tracks: list[dict] | None = None              # NEW: for _persist()
```

### 5.4 DAG Registration (`pipeline/operations.py`)

```python
Operation(
    name="detection",
    label="物体检测",
    description="YOLO11 逐帧目标检测与 ByteTrack 跨帧追踪",
    gate=lambda video, config: (
        config.get("plugins", {}).get("detector", {}).get("backend") is not None
        and getattr(video, "detection_enabled", False)
    ),
    depends_on=["keyframes"],       # needs scene.keyframes populated
    progress_weight=10,
    required_plugins=["detector"],
)
```

**Gate logic**: Both conditions must be true — server has the model installed (`config.yaml`), AND user opted in for this video (`detection_enabled`).

**Batch placement**: After topo sort, `detection` appears in the same batch as `caption` and `frame_encode` (all depend on `keyframes`). The engine runs them in parallel.

### 5.5 Engine Persistence (`pipeline/engine.py`)

Add to `_persist()`, following the existing truthiness-guard pattern:

```python
# 5. 写入检测数据
if self.ctx.frame_detections:
    async with self.db_session_factory() as session:
        await bulk_insert_frame_detections(session, self.ctx.frame_detections)
        await bulk_insert_tracks(session, self.ctx.tracks)
```

### 5.6 Repository (`core/repository.py`)

Follow existing `bulk_insert_frames` / `bulk_insert_chunks` pattern:

```python
async def bulk_insert_frame_detections(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入逐帧检测结果。rows 已包含全部列 (video_id, track_id, timestamp_sec,
    class_name, confidence, bbox)."""
    if not rows:
        return
    await session.execute(insert(FrameDetection).values(rows))
    await session.commit()


async def bulk_insert_tracks(
    session: AsyncSession,
    rows: list[dict],
) -> None:
    """批量写入追踪轨迹。使用 ON CONFLICT DO NOTHING 防止重跑 duplicate。"""
    if not rows:
        return
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(Track).values(rows).on_conflict_do_nothing(
        constraint="uq_track_video"
    )
    await session.execute(stmt)
    await session.commit()
```

---

## 6. API: Fetch Detection Data (`api/detection_routes.py`)

### 6.1 New Endpoint

```
GET /api/v1/videos/{video_id}/detection/data
```

Response:

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "has_detection": true,
    "tracks": [
      {
        "track_id": 1,
        "class_name": "person",
        "first_seen": 12.0,
        "last_seen": 45.0,
        "frame_count": 34
      }
    ],
    "detections": {
      "0.0": [
        {"bbox": {"x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.8}, "class_name": "car", "track_id": 2}
      ],
      "1.0": [...]
    }
  }
}
```

- `detections` keyed by integer-second timestamp string (e.g. `"3.0"`) for O(1) lookup
- `has_detection: bool` lets frontend decide whether to render overlay without loading full data
- Graceful: if video has no detection data, return `{has_detection: false, tracks: [], detections: {}}`

### 6.2 Router Registration

In `api/router.py`:

```python
from api.detection_routes import router as detection_router
router.include_router(detection_router, prefix="/videos")
```

---

## 7. Frontend

### 7.1 TypeScript Types (`types/index.ts`)

```typescript
interface DetectionData {
  has_detection: boolean;
  tracks: Track[];
  detections: Record<string, Detection[]>;  // keyed by integer timestamp string
}

interface Track {
  track_id: number;
  class_name: string;
  first_seen: number;
  last_seen: number;
  frame_count: number;
}

interface Detection {
  bbox: { x1: number; y1: number; x2: number; y2: number };
  class_name: string;
  track_id: number;
}
```

### 7.2 DetectionOverlay Component

#### Props

```typescript
interface DetectionOverlayProps {
  videoRef: React.RefObject<HTMLVideoElement>;
  videoId: string;
  enabled: boolean;
}
```

#### State Machine

| State | Rendering |
|---|---|
| **Loading** | Canvas hidden, fetch in progress |
| **No data** (`has_detection: false`) | `enabled=false`, overlay not rendered |
| **Playing, no selection** | All bboxes rendered, semi-transparent fill + border, class-specific color |
| **Track selected** (click on a bbox) | Selected track: opaque fill + thick border. Others: dimmed to 15% opacity |
| **Paused** | Bboxes stay visible on the current frame |
| **Seeking** | Re-interpolate on next requestAnimationFrame (handled automatically) |

#### Smooth Interpolation Algorithm (NEW — not in v1 spec)

```typescript
function getInterpolatedDetections(
  detections: Record<string, Detection[]>,
  currentTime: number,
): Detection[] {
  const floor = Math.floor(currentTime);
  const ceil = Math.ceil(currentTime);
  const t = currentTime - floor;  // interpolation factor 0..1

  const floorDets = detections[String(floor)] ?? [];
  const ceilDets = detections[String(ceil)] ?? [];

  // Match by track_id across adjacent frames
  const result: Detection[] = [];
  const floorMap = new Map(floorDets.map(d => [d.track_id, d]));
  const ceilMap = new Map(ceilDets.map(d => [d.track_id, d]));

  for (const [track_id, fDet] of floorMap) {
    const cDet = ceilMap.get(track_id);
    if (cDet) {
      // Both frames have this track → interpolate
      result.push({
        track_id,
        class_name: fDet.class_name,
        bbox: {
          x1: fDet.bbox.x1 + (cDet.bbox.x1 - fDet.bbox.x1) * t,
          y1: fDet.bbox.y1 + (cDet.bbox.y1 - fDet.bbox.y1) * t,
          x2: fDet.bbox.x2 + (cDet.bbox.x2 - fDet.bbox.x2) * t,
          y2: fDet.bbox.y2 + (cDet.bbox.y2 - fDet.bbox.y2) * t,
        },
      });
    } else {
      // Track only in floor frame → show at slightly reduced opacity
      result.push({ ...fDet, opacity: 0.5 });
    }
  }

  return result;
}
```

This gives smooth, fluid bounding box movement between 1fps detection frames.

#### Canvas Rendering Loop

```
requestAnimationFrame loop:
  1. Read video.currentTime
  2. Call getInterpolatedDetections(detections, currentTime)
  3. Clear canvas
  4. Get video.getBoundingClientRect() for coordinate mapping
  5. For each interpolated bbox:
     a. Convert normalized coords (0-1) → canvas pixels
     b. Draw rectangle: CLASS_COLORS[class_name] fill (15% opacity) + border (80% opacity)
     c. Draw small class_name label at top-left of bbox
     d. If track_id === selectedTrackId: draw with full opacity + thick border (#FFD700 gold)
  6. ResizeObserver on video element → update canvas dimensions
```

#### Color Mapping

```typescript
const CLASS_COLORS: Record<string, string> = {
  person: "#FF6B6B",    // warm red
  car: "#4ECDC4",       // teal
  bicycle: "#45B7D1",   // sky blue
  motorcycle: "#F7DC6F", // yellow
  bus: "#96CEB4",       // sage green
  truck: "#DDA0DD",     // plum
  dog: "#FF9F43",       // orange
  cat: "#A29BFE",       // lavender
  // ... all 80 COCO classes, with visually distinct colors
  default: "#95A5A6",   // gray fallback
};
```

#### Click Hit-Testing

```
onClick(e):
  1. Get click position relative to video → normalize to 0-1
  2. Get interpolated detections at currentTime
  3. Hit-test: is click point inside any bbox?
      x1 <= click.x <= x2 AND y1 <= click.y <= y2
  4. If hit on multiple bboxes (overlap): pick smallest area (most specific)
  5. setSelectedTrackId(hit.track_id) OR setSelectedTrackId(null) for empty space
```

### 7.3 ParameterPanel Changes

Remove the three hardcoded guards on the detection toggle:

1. `MODULE_AVAILABLE.detection`: change from `false` to `true`
2. `grayed.detection`: remove the `= true` override, use normal logic (grayed when plugin not loaded)
3. `ModuleKey` type union: add `"detection"` to the type
4. `isOn`: remove `=== "detection" ? false :` hardcode
5. `isGrayed`: remove `=== "detection" ? true :` hardcode
6. `onChange`: remove `!== "detection" &&` guard
7. `hint`: change from "YOLO 插件未实现" to dynamic message (grayed → "检测插件未启用（检查 config.yaml）", active → "开启后将对视频进行逐帧物体检测与追踪")

### 7.4 Dashboard Integration

```tsx
{video && (
  <div style={{ position: "relative" }}>
    <video ref={videoRef} ... />
    <DetectionOverlay
      videoRef={videoRef}
      videoId={video.id}
      enabled={video.detection_enabled}
    />
  </div>
)}
```

Fetch detection data in useEffect when `video.detection_enabled` is true.

---

## 8. Parameter System Integration

### 8.1 PipelineParams (`core/schemas.py`)

```python
class PipelineParams(BaseModel):
    # ... existing fields ...
    # L2
    detection_enabled: bool = Field(default=False)  # NEW
```

### 8.2 Validator Rule

Add to existing `model_validator`:

```python
# detection ON requires vision ON (vision is master switch for frame processing)
if self.detection_enabled and not self.vision_enabled:
    raise ValueError("物体检测需要开启视觉感知模块")
```

### 8.3 Video ORM (`core/models.py`)

```python
detection_enabled: Mapped[bool] = mapped_column(
    default=False, server_default=text("false"),
)
```

### 8.4 VideoResponse (`core/schemas.py`)

```python
class VideoResponse(BaseModel):
    # ... existing fields ...
    detection_enabled: bool  # NEW
```

---

## 9. Search Integration (Label Search — Zero Changes)

The existing `_label_search` method at `search_engine.py:148` already works:

```python
stmt = select(Scene).where(Scene.entities.op("@>")(f'[{{"label": "{query}"}}]'))
```

Since we populate `scenes.entities` during detection runner execution (§5.1 step 5), this search path activates automatically when detection data exists. No code changes needed in the search engine.

---

## 10. Configuration & Gating

### 10.1 Enable Detection (Full)

```yaml
# config/config.yaml
plugins:
  detector:
    backend: yolo
    model: yolov11s.pt
    confidence_threshold: 0.4
    iou_threshold: 0.5
    batch_size: 8
```

**Plus** user must toggle `detection_enabled: true` in the Parameter Panel for each video.

### 10.2 Disable Detection (Server-Level)

```yaml
plugins:
  detector: null
```

All detection toggles in the frontend become grayed (plugin not loaded).

### 10.3 Disable Detection (Per-Video)

`detection_enabled: false` in Parameter Panel → gate returns false → operation skipped for that video even if the server has the plugin.

---

## 11. Dependencies

```
# requirements.txt
ultralytics          # YOLO11
boxmot               # ByteTrack (BoxMOT package)

# Dockerfile — add same packages
```

Also add to `Dockerfile`.

---

## 12. Incremental Migration (`core/db.py`)

Add to `init_db()`:

```python
await session.execute(text(
    "ALTER TABLE videos ADD COLUMN IF NOT EXISTS detection_enabled "
    "BOOLEAN NOT NULL DEFAULT false"
))
```

New tables are auto-created by SQLAlchemy `Base.metadata.create_all`.

---

## 13. Acceptance Criteria

1. **Pipeline**: A video processed with `detector.backend: yolo` + `detection_enabled: true` completes without error. `frame_detections` and `tracks` have rows. `scenes.entities` has aggregated data.
2. **Dual gating**: Setting `detector: null` in config.yaml OR `detection_enabled: false` skips the operation. Existing pipeline behavior unchanged.
3. **API**: `GET /api/v1/videos/{id}/detection/data` returns correctly formatted JSON with `has_detection` flag and timestamp-keyed detections.
4. **Frontend overlay**: Smooth bounding boxes appear on the video during playback, interpolating between detection frames.
5. **Click selection**: Clicking a bounding box highlights that track across all frames with gold border. Clicking empty area clears selection. Selected track info (class_name, track_id) displayed.
6. **Parameter panel**: Detection toggle functional, grayed when plugin disabled server-side, defaults to OFF.
7. **Performance**: Canvas rendering at 60fps, no video playback stutter. Detection data fetch < 500ms for 10-min video.
8. **Existing features untouched**: Semantic search (including label path), summaries, video list/stream — all return identical results regardless of detection state.
9. **Label search**: Querying "person" or "car" returns scenes whose entities contain matching labels (via existing `_label_search`).

---

## 14. Implementation Order

| Phase | Tasks | Depends On | Testable |
|---|---|---|---|
| **1. Backend core** | `yolo.py` plugin, `detection.py` runner, ByteTrack integration, `operations.py` registration, `base.py` context fields | Keyframe runner | ✅ verify rows in DB after pipeline |
| **2. Data layer** | `FrameDetection`/`Track` models, `repository.py` bulk inserts, `engine.py` _persist, `db.py` migration, `models.py` detection_enabled column | Phase 1 | ✅ verify DB schema + curl API |
| **3. Parameter system** | `schemas.py` PipelineParams + VideoResponse + validator, frontend `ParameterPanel.tsx` unfreeze | Phase 1 | ✅ toggle in UI → field in DB |
| **4. API endpoint** | `detection_routes.py`, `api/schemas.py` has_detection, `router.py` mount, frontend `api.ts` + types | Phase 2 | ✅ curl + check JSON shape |
| **5. Frontend overlay** | `DetectionOverlay.tsx` with interpolation, `Dashboard.tsx` integration | Phase 4 | ✅ visual verification in browser |
| **6. Polish** | ResizeObserver, edge cases (<2s video, 0 detections), track info display | Phase 5 | ✅ manual QA |

Phases are independently testable. Phase 5 and 6 can overlap.

---

## 15. Notes & Edge Cases

- **First-run model download**: YOLO11s (~22 MB) downloads on first `YOLODetector.__init__()`. Lighter than TransNetV2 or Qwen models.
- **No detection data for short videos**: <2 second videos have ≤1 frame → gracefully return empty `frame_detections`/`tracks`.
- **Camera motion**: ByteTrack handles moderate camera motion. For fast pans / scene cuts, tracks naturally terminate and new ones start — acceptable.
- **Multiple objects of same class**: Each gets unique track_id. Overlay colors by class_name; selected track gets gold `#FFD700` border to differentiate.
- **Seek during playback**: Canvas reads `video.currentTime` on every animation frame — interpolation handles any timestamp.
- **Responsive video sizing**: Canvas dimensions match `video.getBoundingClientRect()` via ResizeObserver.
- **scenes.entities dedup**: Within a scene, same track_id appears only once (first detection) — prevents label search from returning duplicate results for the same object.
- **Track majority class**: If ByteTrack assigns different class_names to the same track_id across frames (rare but possible with YOLO), the runner uses majority vote for the `tracks.class_name` summary.
