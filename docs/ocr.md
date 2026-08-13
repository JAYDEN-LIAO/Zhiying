# OCR 模块设计（v0.34 候选）

> 视频画面文字提取：从视频抽取高清帧 → PaddleOCR 识别文字 → 独立表落库 → 精确文字检索 → 前端展示/定位。
> 设计定稿于 2026-08-12（讨论基于 v0.33 代码现状 + 服务器 NVDEC 实测调查）。
> 相关文档：`docs/arch.md`（架构）、`CLAUDE.md`（项目说明）。

## 概述

OCR 是**独立感知模块**（与 detection/face/plate 同层），从视频画面提取可见文字（字幕/标题/屏幕文字/监控叠加等），落独立表 `ocr_detections`，提供**精确文字检索**（第 8 路搜索）与前端展示/定位。

```
独立高清帧 → PaddleOCR(CPU) → ocr_detections 表 → 精确检索 / 前端展示
```

**核心定位**：OCR 的价值是"精确读出画面里的具体字符"（编号/型号/标题/字幕），搜索以**精确串匹配**（ILIKE + 编辑距离）为主，语义向量为辅。

## 一、背景与决策依据

### 1.1 现状盘点（OCR 骨架已就位）

| 层 | 现状 |
|---|---|
| 参数开关 | `ocr_enabled` 全链路通（4 级 L2，前端 ParameterPanel 已渲染"文字识别"开关 + 场景预设 `text_recognition`） |
| 数据落点 | `scenes.ocr_text` 列存在（v0.33 前 text_encode 会拼接，现依赖待定，见 1.3） |
| 接口定义 | `BaseOCR.extract(frame) -> str`（需升级，见 §3） |
| 插件注册 | `factory.py` `IMPL_CLASS_MAP["ocr"] = "PaddleOCRExtractor"` 已预留 |
| 配置占位 | `config.yaml` `plugins.ocr.backend: null` |

真正要写的：插件实现 + `OcrRunner` + operations.py 一个 Operation 条目 + `ocr_detections` 表 + 检索 + 前端。

### 1.2 v0.33 之后：OCR 必须独立于摘要路径

v0.33（摘要链路根治重构）改变了两个前提，**"OCR 绑摘要路径"被否决**：

- **keyframe 抽帧统一 resize 到编码预设分辨率**（`keyframe.py` 传 `output_width/height`，取消原分辨率帧驻留）→ 摘要帧池不再是高清
- **`max_scenes` 场景数上限（默认 6）**（`segmentation.py`）→ 长视频最多 6 个场景，绑摘要 = 最多 6 次 OCR，字幕/屏幕文字全部漏光

结论：**OCR 必须像 detection/face/plate 一样完全独立于摘要路径**。gate 只受 `ocr_enabled + config backend` 双门控，`depends_on=["duration"]`。

### 1.3 帧源：自抽帧（不复用现有流）

现有三条 NVDEC/cv2 流全是"给视觉模型用"的低分辨率帧：

| 流 | 分辨率 | 为什么不能用 |
|---|---|---|
| detection（`detection.py:150`） | 640×384 | 字符只 ~10-15px 高，OCR 读不出 |
| keyframes（v0.33 后） | 编码预设 336~672 宽 | 同上 |
| search_encode | 编码预设 | 同上 |

**原因**：OCR 是唯一"读具体字符"的模块，需要**像素级清晰**（1080p 字幕字符高 50-80px，640×384 下只剩 ~15px）；而缩放发生在 ffmpeg GPU 端（`scale_cuda`），**信息不可逆**，"复用后放大"救不回来。所以 OCR 必须**自抽帧**——独立流输出原分辨率（或上限 1280 宽）。

**采样策略**：低采样率（默认 `fps=0.33`，每 3 秒一帧，可配）——CPU 识别慢（每帧 100-300ms），文字连续出现数秒，3 秒采样不丢关键内容。10 分钟视频 ≈ 200 帧 ≈ 30-60s CPU。

### 1.4 引擎选型：PaddleOCR（CPU）

- `paddlepaddle>=2.6.0` + `paddleocr>=2.7.0` 已在 requirements（为车牌备选后端装的），**环境零新增**
- `paddle_plate.py` 已验证老 API 可用（踩过 RGB→BGR / asyncio.to_thread / use_gpu 的坑）
- 用 **CPU**（`use_gpu=False`）：不占 gpu_lock，不参与 embedder/YOLO 的 GPU 串行队列
- 模型 PP-OCRv4（检测 + 识别）合计 ~20MB，内存占用小

### 1.5 NVDEC 与服务器调查结论（2026-08-12 实测）

- 本机 `use_nvdec=true`：NVDEC 硬解。OCR 自抽帧 = 第三路 NVDEC session（单视频最多 2 路现有流 + OCR = 3 路），可接受（项目已有两路独立流先例）
- **服务器（10.0.0.176）`use_nvdec=false`**：实测服务器 ffmpeg（/usr/bin/ffmpeg 6.1.1）**未编译 CUDA 支持**——`ffmpeg -hwaccels` 只有 `vdpau/vaapi/drm/opencl`，无 `cuda`；无 `cuvid` 解码器、无 `nvenc` 编码器。`-hwaccel cuda` 必然失败 → `video_util.py` 自动 fallback cv2。运维在 `settings.json` 显式 `use_nvdec: false` 避免每次白试
- 服务器画像：GPU 紧张（GPU1 已被 vLLM 占 ~30G/46G）、**CPU 极富余（80 核 / 503G 内存）** → 保持 cv2 软解是正确选择，**不建议开 NVDEC**
- **对 OCR 的含义**：服务器走 cv2 软解 + CPU 识别，无 NVDEC session 竞争，80 核完全扛得住。OCR 成本形态跟随 `use_nvdec` 开关自适应（开硬解机器吃 GPU 解码器，关硬解机器吃 CPU，两端可控）

## 二、架构（完整链路）

```
①帧生产               ②OCR 处理               ③落库              ④消费
stream_frames(video,   PaddleOCRExtractor   ocr_detections 表   ┌─ 搜索: POST /search/semantic
  fps=0.33,              .extract(frame)     (每帧每文字框一行)   │   search_types=["ocr"]
  原分辨率/上限1280,     → [{text, bbox,                         │   → ocr_text_search (ILIKE+编辑距离)
  use_nvdec=按config)     confidence}]         可选: scenes.ocr_text  └─ 前端: 搜索命中文字 / 文字清单 /
                           CPU, 不占 gpu_lock   语义增强(第二版)        文字框定位(第二版)
```

- 完全独立于摘要路径 / 检测路径，并行执行互不干扰
- `engine.py` 零改动（operations.py 声明式驱动）
- 不依赖 scene（无 scene 概念），按时间戳存储

## 三、插件设计

### 3.1 BaseOCR 接口升级

```python
# core/interfaces.py — 从 str 升级为结构化（接口一次到位，避免以后返工）
class BaseOCR(ABC):
    @abstractmethod
    async def extract(self, frame: np.ndarray) -> list[dict]:
        """对单帧执行 OCR，返回该帧识别出的全部文字行:
        [
            {"text": str,              # 文字内容
             "bbox": {"x1","y1","x2","y2"},   # 归一化 0-1（照 plate_detections.bbox）
             "confidence": float},     # 置信度 0~1
        ]
        """
```

### 3.2 PaddleOCRExtractor（plugins/ocr/paddleocr.py）

- 类名 `PaddleOCRExtractor`（`factory.py:43` 已写死），`backend: "paddleocr"` → 模块 `plugins/ocr/paddleocr.py`（无 override，零 factory 改动）
- 老 API（照 `paddle_plate.py`）：`PaddleOCR(use_angle_cls=True, lang="ch", use_gpu=False)` → `ocr(frame, cls=True)` → 解析 `result[0]` 每行 `[bbox_points, (text, confidence)]`
- **同步推理用 `asyncio.to_thread` 包裹**（项目铁律）
- 参数从 config `plugins.ocr.params` 传入：`lang`(默认 ch)、`use_gpu`(默认 false)、`det_db_thresh`、`rec_thresh` 等
- 过滤：置信度阈值（默认 0.5）+ 空文本跳过；四点坐标 → 归一化 bbox

## 四、Runner 设计（pipeline/runners/ocr.py）

```python
class OcrRunner(OperationRunner):
    async def run(self, pctx):
        ocr = pctx.plugins.get("ocr");  if ocr is None: return  # 无插件跳过（照 PlateRunner）
        duration = pctx.ctx.duration
        cfg = pctx.config.get("plugins", {}).get("ocr", {}).get("params", {})
        sample_fps = cfg.get("sample_fps", 0.33)      # 每 3 秒一帧
        max_width  = cfg.get("max_width", None)       # 分辨率上限（默认原分辨率）
        pipeline_cfg = pctx.config.get("pipeline", {})
        use_nvdec   = pipeline_cfg.get("use_nvdec", False)

        # 独立高清流（低采样率）
        async for frame in stream_frames(
            pctx.ctx.file_path, fps=sample_fps,
            use_nvdec=use_nvdec,
            output_width=max_width, output_height=None,  # 保持宽高比（stream_frames 支持传一个?）
            total_frames=int(duration * sample_fps),
        ):
            ts = frame_idx / sample_fps
            rows = await ocr.extract(frame)   # CPU, to_thread
            # 组装 ocr_detections 行（video_id, ts, text, bbox, confidence）
            # 可选去重: 与上一帧文字集合基本相同的静态字幕 → 跳过落库
            frame_idx += 1
            # 每帧独立容错，一帧失败不拖垮管道（照 v0.33 caption 降级思路）

        # 落库
        await bulk_insert_ocr_detections(session, rows)
        await pctx.tracker.update("ocr", sub_progress=1.0)
```

> 注：`stream_frames` 的 `output_width`/`output_height` 需确认是否支持"只传宽度保比例"。若只支持双传，`max_width` 实现为"读首帧尺寸计算高度"或先不开放该参数（默认原分辨率）。

## 五、DAG 注册（operations.py，新增一个 Operation）

```python
Operation(
    name="ocr", runner=OcrRunner(),
    depends_on=["duration"],           # 与 detection 一样，只依赖时长，独立于摘要/检测
    gate=lambda v, cfg: (
        cfg.get("plugins", {}).get("ocr", {}).get("backend") is not None
        and getattr(v, "ocr_enabled", False)
    ),
    required_plugins=["ocr"],
    label="文字识别", description="画面文字提取中",
    progress_weight=0.05,
)
```

## 六、数据模型（core/models.py + 增量迁移）

```python
class OCRDetection(Base):
    __tablename__ = "ocr_detections"
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    timestamp_sec: Mapped[float] = mapped_column(index=True)
    text: Mapped[str]
    bbox: Mapped[dict] = mapped_column(JSONB)   # {x1,y1,x2,y2} 归一化 0-1
    confidence: Mapped[float] = mapped_column(default=0.0)
    created_at: ...
```

- 照 `plate_detections` 写；`init_db()` 增量迁移（`ADD TABLE IF NOT EXISTS`）
- `repository.bulk_insert_ocr_detections` 批量插入
- **数据量估算**：10 分钟视频 ≈ 200 帧 × 1~3 文字框 ≈ 200~600 行，完全可控
- 不做 HNSW/向量列（精确检索走 ILIKE/编辑距离，无需向量）

## 七、搜索集成（第 8 路精确检索）

### 7.1 core/search.py

照 `plate_text_search`（`core/search.py:161-192`）整段抄：

```python
async def ocr_text_search(session, query, limit=20, video_ids=None):
    """OCR 文字精确检索 — 归一化后 ILIKE 子串 + Levenshtein 编辑距离。
    复用 _normalize_plate 的归一化规则（全角→半角/去分隔符/统一大写）。
    相似度 = 1/(1+min(dist,2))，候选跨过 0.3 门槛。
    """
```

- 复用现有 `_normalize_plate` / `_plate_norm_sql`（改名或复用，规则一致）
- 严格按 `video_ids` 过滤（v0.29 泄漏 bug 教训）

### 7.2 pipeline/search_engine.py

- `search_types` 支持 `"ocr"`；`_ocr_search()` 调 `ocr_text_search`
- 结果结构：`{video_id, timestamp_sec, text, confidence, precision_level="ocr", bbox}`
- `_PATH_WEIGHT["ocr"] = 0.95`（照 plate，精确串匹配置信度高）
- **隔离**：语义搜索 body JSON；人脸/图搜 Form——OCR 走 `/search/semantic`（body JSON），沿用语义的隔离路径

### 7.3 明确不做（第一版）

`scenes.ocr_text` 语义增强**不做进第一版**：
- 需要改 text_encode 的 DAG 依赖（text_encode 现 depends_on `["keyframes","caption"]`），引入 OCR→text_encode 时序耦合
- 语义向量对精确字符串先天劣势，OCR 核心价值在精确匹配
- 列为第二版可选（摘要模式下按时间归属写 scenes.ocr_text → text_embedding）

## 八、API 端点

| Method | Path | 用途 | 版本 |
|---|---|---|---|
| POST | /api/v1/search/semantic（search_types=["ocr"]） | OCR 文字精确检索 | 第一步 |
| GET | /api/v1/videos/{id}/ocr/data | 某视频 OCR 文字清单（按时间戳，前端展示） | 第一步 |
| GET | /api/v1/videos/{id}/ocr/thumbnail | 文字框裁剪图 | 第二步 |

## 九、前端（两步）

### 第一步（跑通即展示，后端数据在流里）

- **搜索结果 sr-item 显示命中文字**（后端返回 `text`，现在前端零渲染）
- **"文"搜索模式按钮**（照"牌"模式，`search_types=["ocr"], top_k 拉大`，一个字列出所有相关）
- **视频详情"文字清单"**（按时间戳聚合，类似 Transcript 展示）

### 第二步（定位交互 + 导出）

- `DetectionOverlay` 画文字框（复用多框源渲染器，单独配色；OCR 是稀疏单帧静态框，**不做帧间插值**）
- 点文字框 → seek 到该帧 + 框高亮（单帧静态，比人脸 track 交互简单）
- `DetectionPanel`"文字"视图（按时间聚合文字列表，照人脸视图写）+ 时间轴联动
- 导出：文字清单 CSV/JSON（`时间戳, 文字, 位置, 置信度`）+ 文字框截图（照 track 缩略图导出）

## 十、配置（config.yaml + 模板）

```yaml
plugins:
  ocr:
    backend: "paddleocr"
    params:
      lang: "ch"
      use_gpu: false        # CPU 旁路，不占 gpu_lock
      sample_fps: 0.33      # 每 3 秒一帧
      max_width: null       # 分辨率上限（null=原分辨率，1280 可省 CPU）
      conf_thresh: 0.5      # 文字置信度阈值
```

- `config/config.yaml.example` 同步；服务器/本地 config 各自生效
- PaddleOCR 模型首次运行自动下载（~20MB）→ **登记进 `deploy/download_models.py`** 供离线部署机预置

## 十一、实施步骤

### 第一步：最小闭环（独立模块跑通 + 检索 + 展示）

```
后端:
  core/interfaces.py        BaseOCR.extract 升级为 list[dict]
  plugins/ocr/paddleocr.py  PaddleOCRExtractor
  core/models.py            ocr_detections 表 + init_db 迁移
  core/repository.py        bulk_insert_ocr_detections
  pipeline/runners/ocr.py   OcrRunner（自抽帧 + 采样 + 落库）
  pipeline/operations.py    1 个 Operation 条目
  core/search.py            ocr_text_search
  pipeline/search_engine.py 第 8 路召回 + _PATH_WEIGHT
  api/ocr_routes.py         GET /ocr/data
  config + config.yaml.example
前端:
  搜索 sr-item 显示命中文字 + "文"模式按钮
  视频详情文字清单
```

### 第二步：定位 + 导出 + 语义增强（看价值再上）

```
  DetectionOverlay 文字框渲染 + 点击高亮 + 时间轴
  DetectionPanel "文字"视图
  导出: 文字清单 CSV/JSON + 文字框截图
  (可选) scenes.ocr_text 语义增强
```

## 十二、风险与注意点

1. **分辨率是质量关键**：默认原分辨率，`max_width` 上限需实测（1280 宽 + 0.33fps 是 CPU 友好起点）
2. **PaddleOCR 模型下载**：部署机需预置模型（download_models.py），避免运行时下载
3. **Overlay 稀疏帧不插值**：OCR 框只在有数据的帧显示
4. **文字噪音**：画面无关文字（水印/角标/商品文字）会大量出现 → 置信度阈值 + 可选相邻帧去重
5. **`stream_frames` 单宽传参**：`max_width` 保比例需确认 stream_frames 是否支持（默认先原分辨率）
6. **服务器 CPU 预算**：cv2 软解 + PaddleOCR 识别都在 CPU，80 核富余，但 `max_concurrent_videos>1` 时注意叠加

## 附录：服务器 NVDEC 调查记录（2026-08-12，只读）

- 服务器 ffmpeg 6.1.1 编译配置**无任何 `--enable-cuda/cuvid/nvenc`**
- `ffmpeg -hwaccels` → `vdpau, vaapi, drm, opencl`（无 cuda）；`grep cuvid` / `grep nvenc` 均空
- `settings.json` `use_nvdec: false`（覆盖 config.yaml 的 true，避免每次抽帧白试 NVDEC）
- GPU：2×L20，GPU1 已用 ~30G/46G（vLLM 共享），`CUDA_VISIBLE_DEVICES=1`
- 结论：不开 NVDEC 是服务器硬件画像（GPU 紧张/CPU 富余）下的正确选择；OCR 走 CPU 路径无 NVDEC 竞争
