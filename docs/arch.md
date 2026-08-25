# Zhiying Architecture

> 版本: v0.6（图片素材库 + 搜索统一 + 摘要 UI 重构）· 后端定版 v0.34（OCR） | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector
> 核心能力：16-op DAG · 4 编码路径 · YOLO11/BoT-SORT 双层 ReID · 人脸/车牌/OCR · 8 路搜索+图搜 · 图片素材库（人脸/通用图搜分轨检索）· 智能参数系统 · 全局任务队列 · 云智接入 · 桌面端

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
  L1 场景（9 智能推荐场景 + 5 旧值兼容）: traffic/vehicle_focus/surveillance_people/
       indoor/portrait_focus/document/street_mixed/outdoor_landscape/chat_screen
       （旧值 general/meeting/surveillance/text_recognition/custom 保留兼容历史视频）
  L2 感知模块: vision/audio/ocr/caption/detection/grounding（各开关）
  L3 功能开关: search_index_enabled / summary_enabled（已完成视频可增量）
  L4 高级参数: language/sample_fps/encode_profile/summary_mode(vlm_llm 默认)

智能参数系统（v0.37 核心）:
  ┌─ 持久化层（DB 字段）：
  │   videos.suggested_scene_key / label / confidence / suggested_params(JSONB)
  │   POST /videos/suggest-params 计算后自动落库，关闭弹窗不丢失
  │
  ├─ 抽屉轻量层（PATCH /videos/{id}/toggles）：
  │   仅持久化 6 开关（detection/face/plate/ocr/search_index/summary），
  │   不入队管道、不动版本、不联动组（与 PUT /params 解耦）
  │
  ├─ UI 层（统一 6 开关 + 内容类型场景预设）：
  │   - 抽屉「参数设置」小面板（FileDetailDrawer 内嵌，点击即保存）
  │   - Workbench SingleAnalyzeDialog（460px 紧凑弹窗）
  │   - 案例库 BatchAnalyzeDialog（520px，2 选项：按各视频/统一参数）
  │   - 三场景共用 AnalyzeSettingsPanel（内容类型 + 6 开关）+ buildPipelineParams()
  │
  └─ 智能推荐场景映射（CONTENT_TYPE_PRESETS，与 services/smart_suggest.py SCENE_CLASSES 对齐）：
      每个场景对应一组检测/人脸/车牌/OCR 开关预设；所有场景摘要预设 = false

校验: vision OFF→ocr/caption/detection OFF；caption OFF→summary OFF
门控: detection 双门控(config backend + per-video)；face/plate 三门控
摘要默认关闭（v0.37）：摘要耗时长且非核心，所有路径默认 summary_enabled=false
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
案例素材: case_assets 表（图片等归档素材，不参与管道；图片上传已退役，仅保留视频）
素材库: image_subjects + subject_photos + subject_photo_embedding（分轨向量）
        检索: /search/subjects 上传图片 → person ArcFace 512 / other Qwen3-VL → 命中底库目标
        沉淀: 检测 track「+」/ 图搜「+」→ AddSubjectDrawer → 底图 + 编码入库
```

## Plugin System

```
plugins/factory.py: load_plugin(config, category) → import + 实例化; null backend = 禁用
后端: segmenter(transnetv2) · captioner(qwen_api 默认) · embedder(qwen3_vl_embedding, 档位驱动)
      summarizer(DeepSeek) · detector(yolo) · face(insightface) · plate(hyperlpr)
      ocr(rapidocr=PP-OCRv3 ONNX via DirectML 独立子进程) · grounding(null) 占位
约定: 插件接口异步; 同步模型推理 MUST asyncio.to_thread(); 禁用重复实例化（共享单实例）
     OCR worker 是按路径 spawn 的子进程脚本：封装态（backend_pyc 只留 .pyc）须 `.pyc` 回退（Python 可直接执行 legacy .pyc），
     worker 内项目根定位走 ZHIYING_PROJECT_ROOT（backend_launcher 注入；源码态 __file__ 推导）
```

## Search Architecture

```
Semantic Search: query → embedder.encode_text() 一次 → 7 路并行召回:
  frame(1fps) / chunk(滑窗) / text(caption+ocr+transcript) / label(JSONB)
  / track(crop 跨模态) / plate(Levenshtein+ILIKE) / ocr(精确串匹配)
图搜: /search/face（ArcFace 512d, 双锚）· /search/image（Qwen3-VL, 独立路径）
素材库检索: /search/subjects（上传图片, person→ArcFace 512 / other→Qwen3-VL, 分轨比对底库向量）
合并去重: 帧簇(≤4s)优先; confidence = 相似度 × 路径权重
范围过滤: video_ids 空→空; None=全库; face/image 参数必须 Form(...) 声明
视频搜索卡: 严格限定当前视频（video_ids=[currentVideoId]）；支持 search_types 结果类型筛选（全部/画面/物体）
智能筛选推荐: POST /search/suggest-filter 文本相似度预判——事件/动作类→画面定位(frame)、单物体类→物体定位(track)；手动选择优先（autoFilterActive）；车牌/文字模式不参与
搜索结果时间范围: 点击结果自动播放到 end 时间后暂停（autoPauseEndRef + timeupdate 监听）
```

## Database Schema

| Table | 关键列 | 用途 |
|---|---|---|
| `video_groups` | id, name, number/owner | 视频分组/案例 |
| `videos` | status/progress, summary, 开关/参数, source_owned, file_id+version_no, suggested_* | 主表 |
| `scenes` | text_embedding(EmbedVector), caption, ocr_text, entities | 搜索主粒度 |
| `frame_embeddings` / `chunks` | embedding(EmbedVector) | 1fps 帧向量 / 滑窗向量 |
| `frame_detections` / `tracks` | track_id, class_name, bbox | YOLO 检测 / BoT-SORT 轨迹 |
| `track_embeddings` | embedding(EmbedVector) | 轨迹 crop 向量 |
| `face_identities` / `face_detections` | face_embedding(512) | 聚类身份 / 逐帧人脸 |
| `plate_detections` | plate_text | 车牌识别 |
| `ocr_detections` | text, bbox, confidence | 画面文字（第 8 路） |
| `case_assets` | group_id, kind, name, path, file_size | 案例素材（图片等非视频归档） |
| `image_subjects` | id, kind(person/other), name, tags(JSONB), photo_count | 素材库关注目标 |
| `subject_photos` | id, subject_id, file_path, crop(JSONB), is_primary, source, source_video_id | 素材库底库照片 |
| `subject_photo_embedding` | photo_id, kind, face_embedding(512), other_embedding(EmbedVector) | 素材库检索向量（分轨） |
| `pipeline_tasks` | status, dedup_key | 任务队列持久化 |
| `task_logs` | seq, level, message | 任务生命周期日志 |

向量列 `EmbedVector()`（8b=4096 / 2b=2048）；人脸 `Vector(512)`。

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/videos/upload` · `/upload/batch` | 上传（单个/批量建组） |
| POST | `/api/v1/videos/suggest-params` | 智能场景参数推荐（9 场景分类，**自动落库**到 videos.suggested_* 4 字段） |
| PATCH | `/api/v1/videos/{id}/toggles` | **抽屉轻量持久化**：仅 6 核心开关，不入队管道（v0.37） |
| POST | `/api/v1/videos/register-external` | 平台文件就地引用 |
| PUT | `/api/v1/videos/{id}/params` | 设置参数 + 启动管道（pending 入队 / completed 建新版本） |
| POST | `/api/v1/videos/reuse` · `/{id}/reanalyze` · `/analyze-batch` | 新建/重解析(pending)/批量解析（参数可省略=各视频用自身） |
| GET | `/api/v1/videos/{id}` · `/status` · `/stream` · `/thumbnail` · `/metadata` · `/proxy-status` | 详情/状态/播放/缩略图/元数据/代理状态 |
| DELETE | `/api/v1/videos/{id}` | 删除（级联+清盘） |
| GET | `/api/v1/videos/{id}/versions` | 版本链查询 |
| GET | `/api/v1/files` | 文件库（逻辑文件列表，含当前版本状态） |
| PUT | `/api/v1/files/{id}` · `DELETE /files/{id}` | 重命名文件 / 删除文件（全版本链+磁盘） |
| GET/PUT | `/api/v1/settings` · `/settings/pipeline` | 系统设置 |
| GET/POST/PUT/DELETE | `/api/v1/settings/presets` · `/{id}/apply` | 参数预设 CRUD |
| GET | `/api/v1/videos/{id}/face/data` · `/plate/data` · `/ocr/data` | 人脸/车牌/OCR 数据 |
| POST | `/api/v1/search/semantic` · `/search/face` · `/search/image` | 语义/人脸/图搜 |
| POST | `/api/v1/search/suggest-filter` | **搜索结果智能筛选推荐**（文本相似度预判画面定位/物体定位） |
| POST | `/api/v1/search/subjects` | **素材库图片检索**（上传图片, person→ArcFace / other→Qwen3-VL） |
| GET | `/api/v1/pipeline/operations` | 当前视频已启用管道操作+进度区间（PipelineBar） |
| GET/POST | `/api/v1/files` · `/groups` · `/tasks` | 文件库/案例/任务中心 |
| GET/POST | `/api/v1/groups/{id}/assets` · `DELETE /assets/{id}` · `PUT /assets/{id}` | 案例素材 CRUD |
| GET | `/api/v1/groups/{id}/assets/{id}/file` | 案例素材文件预览 |
| GET/POST/PUT/DELETE | `/api/v1/subjects` · `/{id}` | **素材库关注目标 CRUD** |
| GET/POST | `/api/v1/subjects/{id}/photos` · `/{photoId}` | **素材库底库照片**（上传/裁剪/设主图/删除） |
| POST | `/api/v1/subjects/{id}/photos/import-case-asset` | **案例库图片转存为底图** |
| POST | `/api/v1/subjects/merge` | **手动合并两目标** |
| GET | `/api/v1/subjects/{id}/primary-photo` · `/{photoId}/file` | **素材库图片文件服务** |
| GET | `/api/v1/tasks/{id}/log` · `POST /{id}/retry` | 任务日志/重试 |
| GET | `/api/v1/tasks/{id}/report` · `POST /tasks/export-batch` | 任务报告导出/批量导出 |
| GET/POST | `/api/v1/maintenance/storage` · `/maintenance/sweep` | 存储用量/清扫 |
| POST | `/internal/yunzhi/jobs` | 云智异步任务（202+回调+幂等） |

## Frontend Architecture

**双前端共存**：服务器 `frontend/`（Dashboard）+ 桌面 `frontend-desktop/`（4 页管理后台）；**对接层 `frontend-shared/` 一份实现**。

**桌面前端**：
- AppContext 全局状态（视频/任务/进度/树选/案例徽章/素材库跨页跳转）+ 5 页组件：
  - **FileLibrary**（案例库）：左案例树 + 右内容区；选中案例时正文支持视频拖拽上传（图片上传已退役）；多版本行=一次解析
  - **Workbench**（视频解析）：SplitPane 视频播放器 + 检测栏 + 视频搜索卡（结果类型筛选下拉：全部/画面定位/物体定位 + 语义/人脸/图搜/车牌/文字 toggle + 搜索框固定 + 搜索结果时间范围自动暂停）+ `SingleAnalyzeDialog` 紧凑弹窗；搜索卡仅限当前视频检索（与全局搜索划清边界）；摘要卡标题随内容自动切换（视频摘要/文字识别），无 tab 按钮
  - **ImageLibrary**（素材库，v0.6 新增）：左目标列表 + 右底库照片详情（裁剪/拖拽扩充/溯源）+ 新建目标弹窗 + `AddSubjectDrawer`（检测/图搜一键沉淀）
  - **GlobalSearch**（全局搜索）：左 34% 配置面板（文本/图像 Tab + 4 类型 chip 互斥选中 + 句式化 token + 人脸/通用图搜分轨）+ 右 66% 结果网格；选图来源统一走 `SubjectPhotoPicker`（素材库底图）
  - **TaskCenter**（任务中心）+ **SettingsPage**（系统设置，4 子 tab）
- TitleBar（frameless 暗色）+ SystemMonitor（底部系统监控）；侧栏 5 业务 + 2 设置入口

**桌面端窗口壳**：pywebview 主窗（frameless, shadow）；SplashApi 窗口控制/系统监控；后端 backend_launcher.py（字节码/源码双模式 + 看门狗）。壳 `load_url` 追加 `?v=<version>` 击穿 WebView2 持久化 HTTP 缓存（`private_mode=False`，跨版本复用会显示旧 UI，如素材库消失）。

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
| OCR 独立子进程 | DML 隔离不破坏人脸/车牌 CUDA；封装态 worker 仅 .pyc，插件 .pyc 回退 + ZHIYING_PROJECT_ROOT 定位 vendor |
| 参数预设随 git | config/presets.json 部署/换机开箱复用 |
| 桌面壳 URL 版本缓存击穿 | WebView2 持久化缓存（private_mode=False）跨版本复用旧 UI，load_url 带 `?v=<version>` 强制取新 |

## Current Status

**核心链路全部 ✅**：DAG(16 ops) / 4 编码 / 双层 ReID / 8 路搜索+图搜 / 人脸+车牌+OCR / 摘要(vlm_llm, 默认关) / 多格式 / 智能参数系统 / 设置+预设 / GPU 锁 / 任务队列 / 文件库+多版本 / 案例素材 / 任务报告 / 云智 / 桌面端 / 生产部署 / **图片素材库**。

**v0.6 图片素材库 + 搜索统一**：3 表(image_subjects/subject_photos/subject_photo_embedding) + 15 个 /subjects API + 桌面端第 5 页 ImageLibrary + SubjectPhotoPicker（替代 CaseAssetPicker）+ AddSubjectDrawer（检测/图搜沉淀，新建/已有目标双模式）+ 检索分轨(person→ArcFace 512 / other→Qwen3-VL) + 全局搜索关键词/人脸/图搜同步到视频搜索卡片 + 案例图片退役 + VideoSummaryCard 外框标题切换 + caption-summary 联动 + DetectionPanel 跨页自动滚动修复。

**桌面端 UI 优化**：视频搜索卡仅限当前视频检索（退役范围下拉，与全局搜索划清边界）+ 结果类型筛选下拉（全部/画面定位/物体定位，search_types API 过滤）+ **智能筛选推荐**（`POST /search/suggest-filter` 文本相似度预判，事件/动作类→画面定位、单物体类→物体定位，手动选择优先）+ 搜索框固定不随结果滚动 + 搜索结果时间范围自动暂停（timeupdate 监听）+ 摘要卡 tab 按钮删除（标题随内容自动切换）+ 摘要卡嵌套容器精简 + 全局搜索类型 chip 互斥选中 + 物体检测栏进度条删除 + 案例库添加下拉图标尺寸统一。

**v0.37 智能参数系统**：持久化推荐(suggest-params 自动落库 4 字段) + 抽屉轻量面板(PATCH toggles 点击即保存) + AnalyzeSettingsPanel 三处共用 + ContentType 9 场景枚举 + 摘要默认全关 + Workbench 紧凑弹窗 + 批量解析双模式(按各视频/统一参数)。

**非完全**：Chunk 编码（默认关）· OCR 导出/增强（预留）· Grounding(Florence-2 占位) · 素材库告警红点（下一阶段）。

## 版本发布

版本唯一来源 `core/version.py`；发版 `./bump`；后端+服务器前端改动必须发版；部署 `bash deploy.sh v<tag>`。
