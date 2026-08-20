# Zhiying Architecture

> Version: 0.35 候选（桌面端 UI）· 后端定版 v0.34（OCR） | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector
> 核心能力：16-op DAG · 4 编码路径 · YOLO11/BoT-SORT 双层 ReID · 人脸/车牌/OCR · 8 路搜索+图搜 · 4 级参数+设置/预设 · 全局任务队列 · 云智接入 · 桌面端

## System Data Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                  Client (Browser / React Frontend)                   │
└─────────────┬──────────────────────┬──────────────────┬─────────────┘
              │ POST /videos/upload  │ POST /search     │ GET /videos/
              ▼                      ▼                  ▼
┌────────────────────────┐ ┌────────────────────────┐ ┌────────────────┐
│   FastAPI (main.py)    │ │   SearchEngine         │ │ React Frontend │
│   api/video_routes.py  │ │   7 路并行召回          │ │ video player   │
│   api/search_routes.py │ │   frame/chunk/text/    │ │ pipeline UI    │
│   FormatService        │ │   label/track/plate/ocr│ │ search panel   │
└───────────┬────────────┘ └───────────┬────────────┘ └────────────────┘
            │                          │
            ▼                          ▼
  Pipeline DAG (16 ops)           Embedder (local GPU)
  duration → detection → track_encode → face/plate
  duration → segmentation → keyframes → caption → summary
  duration → ocr(RapidOCR+DirectML 子进程) → ocr_detections
            │
            ▼
    PostgreSQL + pgvector
```

## Parameter System

```
4 级层次控制管道执行:
  L1 场景 (general/meeting/surveillance/text_recognition/custom)
  L2 感知模块: vision/audio/ocr/caption/detection/grounding（各开关）
  L3 功能开关: search_index_enabled / summary_enabled（已完成视频可增量）
  L4 高级参数: language/sample_fps/encode_profile/summary_mode(vlm_llm 默认)

智能场景参数推荐（POST /videos/suggest-params）:
  按视频画面内容分类（services/smart_suggest.py, 9 场景）
  traffic/vehicle_focus/surveillance_people/indoor/portrait_focus/document/
  street_mixed/outdoor_landscape/chat_screen
  每类对应一组检测/人脸/车牌/OCR 开关预设；低置信(≤0.30)回退 _DEFAULT_PARAMS
  批量帧向量按成功解码分组对齐（防跨视频污染）；embedder 缓存键含场景指纹（改场景自动失效）
  例：人流监控→det+face on、plate off；文档/聊天录屏→仅 OCR、不建搜索索引

校验: vision OFF→ocr/caption/detection OFF；caption OFF→summary OFF
      （已废弃"搜索索引/智能摘要/文字识别至少开启一个"——可仅检测+人脸）
门控: detection 双门控(config backend + per-video)；face/plate 三门控
```

## Pipeline Detail

```
DAG 阶段流（16 ops, 每 op 一个 asyncio 任务）:
  duration
    ├─ search_encode（仅摘要关时）— 与 detection 共享 NVDEC, 64 帧一批 → frame_embeddings
    ├─ ocr — 自抽高清帧, RapidOCR(PP-OCRv3 ONNX) DirectML 独立子进程 → ocr_detections
    ├─ detection（10fps, 攒批 128）→ track_encode → face/plate
    └─ segmentation → keyframes(1fps) → caption(vlm_llm) → summary(vlm_llm)
  → _persist() → mark_completed()

GPU 串行: 所有 embedder/detect 前向持 gpu_lock（并发触发驱动故障）
Keyframe 4 消费链: frame_encode/text_encode/chunk_encode/caption
摘要: vlm_llm 默认（Qwen-VL-Max + DeepSeek）; native_video 已退役
人脸路: SCRFD + ArcFace 512d → 护栏式双阈值聚类（同 track 0.30 / 跨 track 0.58）
任务队列: PipelineQueue FIFO + N worker + pipeline_tasks 表持久化
文件库: videos.file_id+version_no 版本链；批量解析仅处理 pending 视频
```

## Plugin System

```
plugins/factory.py: load_plugin(config, category) → import + 实例化; null backend = 禁用
后端: segmenter(transnetv2) · captioner(qwen_api 默认) · embedder(qwen3_vl_embedding, 档位驱动)
      summarizer(DeepSeek) · detector(yolo) · face(insightface) · plate(hyperlpr)
      ocr(rapidocr=PP-OCRv3 ONNX via DirectML 独立子进程) · grounding(null) 占位
约定: 插件接口异步; 同步模型推理 MUST asyncio.to_thread(); 禁用重复实例化（共享单实例）
```

## Search Architecture

```
Semantic Search: query → embedder.encode_text() 一次 → 7 路并行召回:
  frame(1fps) / chunk(滑窗) / text(caption+ocr+transcript) / label(JSONB)
  / track(crop 跨模态) / plate(Levenshtein+ILIKE) / ocr(精确串匹配)
图搜: /search/face（ArcFace 512d, 双锚）· /search/image（Qwen3-VL, 独立路径）
合并去重: 帧簇(≤4s)优先; confidence = 相似度 × 路径权重
范围过滤: video_ids 空→空; None=全库; face/image 参数必须 Form(...) 声明
```

## Database Schema

| Table | 关键列 | 用途 |
|---|---|---|
| `video_groups` | id, name, number/owner | 视频分组/案例 |
| `videos` | status/progress, summary, 开关/参数, source_owned, file_id+version_no | 主表 |
| `scenes` | text_embedding(EmbedVector), caption, ocr_text, entities | 搜索主粒度 |
| `frame_embeddings` / `chunks` | embedding(EmbedVector) | 1fps 帧向量 / 滑窗向量 |
| `frame_detections` / `tracks` | track_id, class_name, bbox | YOLO 检测 / BoT-SORT 轨迹 |
| `track_embeddings` | embedding(EmbedVector) | 轨迹 crop 向量 |
| `face_identities` / `face_detections` | face_embedding(512) | 聚类身份 / 逐帧人脸 |
| `plate_detections` | plate_text | 车牌识别 |
| `ocr_detections` | text, bbox, confidence | 画面文字（第 8 路） |
| `pipeline_tasks` | status, dedup_key | 任务队列持久化 |
| `task_logs` | seq, level, message | 任务生命周期日志 |

向量列 `EmbedVector()`（8b=4096 / 2b=2048）；人脸 `Vector(512)`。

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/videos/upload` · `/upload/batch` | 上传（单个/批量建组） |
| POST | `/api/v1/videos/suggest-params` | 智能场景参数推荐（9 场景分类） |
| POST | `/api/v1/videos/register-external` | 平台文件就地引用 |
| PUT | `/api/v1/videos/{id}/params` | 设置参数 + 启动管道 |
| POST | `/api/v1/videos/reuse` · `/{id}/reanalyze` · `/analyze-batch` | 新建/重解析(pending)/批量解析 |
| GET | `/api/v1/videos/{id}` · `/status` · `/stream` · `/thumbnail` | 详情/状态/播放/缩略图 |
| DELETE | `/api/v1/videos/{id}` | 删除（级联+清盘） |
| GET/PUT | `/api/v1/settings` · `/settings/pipeline` | 系统设置 |
| GET/POST/PUT/DELETE | `/api/v1/settings/presets` · `/{id}/apply` | 参数预设 CRUD |
| GET | `/api/v1/videos/{id}/face/data` · `/plate/data` · `/ocr/data` | 人脸/车牌/OCR 数据 |
| POST | `/api/v1/search/semantic` · `/search/face` · `/search/image` | 语义/人脸/图搜 |
| GET/POST | `/api/v1/files` · `/groups` · `/tasks` | 文件库/案例/任务中心 |
| POST | `/api/v1/maintenance/sweep` | 存储清扫 |
| POST | `/internal/yunzhi/jobs` | 云智异步任务（202+回调+幂等） |

## Frontend Architecture

**双前端共存**：服务器 `frontend/`（Dashboard）+ 桌面 `frontend-desktop/`（4 页管理后台）；**对接层 `frontend-shared/` 一份实现**。

**桌面前端（v0.35 UI增强）**：
- AppContext 全局状态（视频/任务/进度/树选/案例徽章）+ 4 页组件：
  - **FileLibrary**（案例库）：左案例树 + 右内容区；选中案例时正文支持视频/图片拖拽上传；多版本行=一次解析
  - **Workbench**（视频解析）：SplitPane 视频播放器 + 检测栏（车/物体/人脸/车牌/OCR/画面）+ 视频搜索卡（语义/人脸/图搜/车牌/文字 toggle）+ 智能场景参数推荐弹窗（SmartSuggestDialog，按 scene_key 计数、低置信徽标）
  - **GlobalSearch**（全局搜索，v0.35 重构）：左 34% 配置面板（文本/图像 Tab + 4 类型 chip + 句式化 token + 人脸/通用图搜分轨）+ 右 66% 结果网格
  - **TaskCenter**（任务中心）+ **SettingsPage**（系统设置，4 子 tab：系统/模型参数/参数预设/API 密钥）
- TitleBar（frameless 暗色）+ SystemMonitor（底部系统监控）；侧栏 4 业务 + 2 设置入口（案例库/全局搜索/视频解析/任务中心 + 系统/模型参数）

**桌面端窗口壳**：pywebview 主窗（frameless, shadow）；SplashApi 窗口控制/系统监控；后端 backend_launcher.py（字节码/源码双模式 + 看门狗）。

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Plugin + Factory | config.yaml 换后端零代码改动 |
| pgvector | 部署简单、事务一致 |
| 本地 GPU Embedder | 每帧 4096 维编码，API 延迟不可接受 |
| 共享 embedder (app.state) | 避免每视频重载 ~4GB 模型 |
| 单 NVDEC 流 + 生产者-消费者 | 消灭双流解码竞争 |
| 全局 GPU 锁 | 串行所有 GPU 前向防驱动故障；detection 攒批 128 防饿死 |
| 全局任务队列 (PipelineQueue) | FIFO + worker 池 + 表持久化；批量防 OOM |
| 平台共享文件 source_owned | 就地引用不复制；删视频不删源文件 |
| 人脸聚类双阈值 | 同 track 0.30 宽松 + 跨 track 0.58 保守 |
| 搜索数据隔离 | Form(...) 声明防全库泄漏 |
| OCR 独立子进程 | DML 隔离不破坏人脸/车牌 CUDA |
| 参数预设随 git | config/presets.json 部署/换机开箱复用 |

## Current Status

**核心链路全部 ✅**：DAG(16 ops) / 4 编码 / 双层 ReID / 8 路搜索+图搜 / 人脸+车牌+OCR / 摘要(vlm_llm) / 多格式 / 4 级参数 / 设置+预设 / GPU 锁 / 任务队列 / 文件库+多版本 / 云智 / 桌面端 / 生产部署。

**桌面前端 v0.35 增强（候选）**：全局搜索 4 类型 + 句式化 chip + 人脸/图搜分轨；案例库正文拖拽上传；侧栏顺序优化（案例库 → 全局搜索 → 视频解析 → 任务中心）；持久蓝色描边搜索框。

**后端 v0.35 候选（本次重点）**：智能场景参数推荐（`POST /videos/suggest-params`，9 场景分类 + 低置信兜底 + 批量向量对齐修复 + 场景指纹缓存失效）；废弃"搜索/摘要/OCR 至少开启一个"校验（可仅检测+人脸）；人脸多帧补采收紧（`SHORT_TRACK_SEC=8s` / `LONG_TRACK_SAMPLES=2`）。

**非完全**：Chunk 编码（默认关）· OCR 导出/增强（预留）· Grounding(Florence-2 占位)。

## 版本发布

版本唯一来源 `core/version.py`；发版 `./bump`；后端+服务器前端改动必须发版；部署 `bash deploy.sh v<tag>`。
