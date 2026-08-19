# Zhiying Architecture

> Version: 0.34 候选 | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector
> Frontend: React 19 + Vite 6 + Tailwind CSS 4（双前端：frontend/ 服务器 + frontend-desktop/ 桌面，共享 frontend-shared/ 对接层）
> 核心能力：16-op 声明式 DAG · 4 编码路径 · YOLO11/BoT-SORT 双层 ReID · 人脸/车牌/OCR · 8 路搜索+图搜 · 存储卫生 · 4 级参数+设置/预设 · 全局任务队列 · 文件库/多版本/任务中心 · 云智接入 · 桌面端（pywebview 壳 + 4 页管理后台）

## System Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                     Client (CLI/Browser / React Frontend)                        │
└──────────────────┬────────────────────────────┬──────────────────┬───────────────┘
                   │ POST /videos/upload (single)     │ POST /search/semantic │ GET /videos/
                   │ + /upload/batch · PUT /params    │ + /search/face·image   │
                   ▼                            ▼                        ▼
┌─────────────────────────────┐  ┌─────────────────────────────┐  ┌──────────────────┐
│     FastAPI (main.py)       │  │   SearchEngine              │  │  React Frontend  │
│  ┌─ api/video_routes.py ─┐  │  │   ┌─ frame (1fps 精确)     │  │  ┌── video player │
│  │ upload/register/params │  │  │   ├─ chunk (滑动窗口)      │  │  ├── pipeline UI  │
│  │ stream (hevc 路由)     │  │  │   ├─ text (caption 语义)    │  │  ├── search panel │
│  │ delete/metadata       │  │  │   ├─ label (JSONB 精确)     │  │  └── det panel    │
│  └─────────────────────────┘  │  │   └─ track/plate          │  └──────────────────┘
│  ┌─ api/export_routes.py ─┐  │  └──────────┬──────────────────┘
│  │ clip / frames / track  │  │             │
│  │ thumbnails (GET+POST)  │  │  ┌──────────▼──────────────────┐
│  └─────────────────────────┘  │  │   Embedder (local GPU)      │
│  ┌─ api/tasks/groups ─────┐  │  │   encode_text("query")      │
│  │ 任务中心 / 文件库        │  │  │   encode_image(frame)       │
│  └───────────┬────────────┘  │  └──────────────────────────────┘
│  ┌─ FormatService ──────────┐ │
│  │ probe → remux → proxy    │ │  StorageManager（删除清盘/孤儿清扫）
│  │ (按需, 异步)              │ │  SettingsService + PresetsService（运行时生效, 预设入仓库随 git）
│  └──────────────────────────┘ └───── VideoService → PipelineEngine（DAG, 任务队列入队）─────
└──────────────┬─────────────┘        │
               ▼                      ▼                PostgreSQL + pgvector
  Pipeline DAG (EventDrivenScheduler): videos/scenes/transcripts/frame_embeddings/
  duration → detection(生产者-消费者, 共享 NVDEC 流) → track_encode → face/plate     chunks/track_embeddings
  duration → segmentation→keyframes→caption→summary→frame/text/chunk_encode         /tracks/detections/
  duration → ocr(自抽高清帧, RapidOCR PP-OCRv3 ONNX, DirectML 独立子进程) → ocr_detections                                  face_identities/face_detections/
  → _persist() → mark_completed()                                                  /ocr_detections
```

## Parameter System

```
4 级层次控制管道执行:
  L1 场景 (general/meeting/surveillance/text_recognition/custom) → 模块默认
  L2 感知模块: vision/audio/ocr/caption/detection/grounding（各开关, 插件禁用时置灰）
  L3 功能开关: search_index_enabled / summary_enabled（已完成的视频可增量重跑这两项）
  L4 高级参数: language/sample_fps/segment_threshold/caption_with_context/summary_detail/
              encode_profile(fast/balanced/precise)/summary_mode(vlm_llm 默认)
校验: vision OFF→ocr/caption/detection 强制 OFF；caption OFF→summary OFF；vision+audio 双 OFF 拒绝；search+summary 双 OFF 拒绝
增量: 仅 L3 可对已完成视频增量；summary_mode 变更需新建记录
门控: detection 双门控(config backend + per-video)；face/plate 三门控(+face_enabled/plate_enabled)
```

## Settings & Presets

```
GET/PUT /settings → data/settings.json（网站运行时生效, 保存即生效除非 quantization）:
  api_keys {dashscope, deepseek}     → 注入 env
  providers {base_url, model}        → 覆盖 captioner/summarizer 配置
  storage {video_dir, artifact_dir}  → 覆盖存储路径
  pipeline {encode_profiles 三档模板, default_encode_profile, detection_fps/batch/imgsz/阈值,
            use_nvdec, chunk_encoding, quantization(需重启), max_concurrent_videos, max_scenes,
            sample_fps, segment_threshold}  → 覆盖 config
  core/config_loader: PIPELINE_NUMERIC_SPEC + clamp_param 钳制；每次 load_config() _apply_settings_overrides 合并
参数预设 /settings/presets → config/presets.json（命名快照, 入仓库随 git 迁移, 不含存储路径/API key）:
  套用 = 写回 settings.json pipeline 覆盖区 → 运行时生效
档位感知: GET /settings/pipeline 返回 embedding_profile(8b/2b) + embedding_profiles(维度) + 生效 encode 配置
  2b 档自动套用轻量编码/量化默认（_2B_ENCODE_DEFAULTS: balanced 448×224/256, precise 448×336/128, quantization none）;
  _ENCODING_OVERRIDDEN 字段级让位用户设置页保存值
```

## Pipeline Detail

```
DAG 阶段流（16 ops, 每 op 一个 asyncio 任务等待上游事件）:
  duration
    ├─ search_encode（仅摘要关时）— 与 detection 共享单 NVDEC 流, 64 帧一批 → frame_embeddings
    ├─ ocr（v0.34 独立感知模块）— 自抽高清帧, RapidOCR(PP-OCRv3 ONNX) 走 DirectML 独立子进程, 内容去重/固定文字抑制/模糊合并 → ocr_detections
    ├─ detection（10fps 生产者-消费者, 攒批 128）→ track_encode（读检测缓存 crop mean pool）→ face/plate
    └─ segmentation（TransNetV2 / 时长固定段, max_scenes 上限）
         → keyframes（1fps, 抽帧统一 resize 到编码预设分辨率）→ caption（vlm_llm API 并发限流+失败降级）→ summary（vlm_llm, 输入预算截断）
  → _persist() → mark_completed()
GPU 串行: 所有 embedder encode_* / YOLO detect 前向持 core/gpu_lock 全局锁（并发前向触发驱动硬故障; detection 攒批 128 防饿死 embedder）
并发: max_concurrent_videos → PipelineQueue worker 池（0/未设=1 串行 FIFO, 防批量并发 OOM）
Keyframe 4 消费链: frame_encode → frame_embeddings · chunk_encode → chunks(滑窗, 默认关) · text_encode → scenes.text_embedding · caption → scene.caption
摘要: vlm_llm 默认（Qwen-VL-Max 看图 + DeepSeek 摘要, 并发限流+失败重试降级+预算截断）; native_video 已置灰退役（代码保留兼容历史）
人脸路: detection 收尾升级 person/vehicle best 帧为全分辨率 → FACEFRAME 多帧采样 → SCRFD 提脸 + ArcFace 512d → 护栏式双阈值聚类
       （同 track 0.30 宽松合并, 跨 track 0.58 保守合并）→ face_identities(最典型脸主锚 + 均值兜底) + face_detections
任务队列 (core/pipeline_queue.py): FIFO + N worker + pipeline_tasks 表持久化
  所有管道触发点统一入队；重启恢复（queued 重入队 / running yunzhi 续跑 / running pipeline 标失败）；幂等（dedup_key）
文件库/多版本/任务中心:
  videos.file_id+version_no 版本链（一次解析=一个版本行, 产物按 video_id 隔离, (file_id,version_no) 唯一索引）
  日志生命周期统一 repository.append_task_log（task_logs 表）；耗时 = updated_at − processing_started_at（排队不计入）
  批量解析 POST /videos/analyze-batch（精确勾选, 不走组同步）；文件/素材重命名 PUT /files/{id} + /groups/{id}/assets/{id}
```

## Plugin System

```
plugins/factory.py: load_plugin(config, category) → import + 实例化; null backend = 禁用
  CATEGORY_MAP / IMPL_CLASS_MAP / _MODULE_OVERRIDES / _CLASS_OVERRIDES
后端: segmenter(transnetv2) · captioner(qwen_api 默认 / qwen3_vl 本地可选) · embedder(qwen3_vl_embedding, 档位驱动)
      summarizer(vllm=DeepSeek) · transcriber(null) · detector(yolo) · face(insightface) · plate(hyperlpr/paddle)
      ocr(rapidocr=PP-OCRv3 ONNX via DirectML 独立子进程) · grounding(null) 占位
约定: 插件接口异步; 同步模型推理 MUST asyncio.to_thread(); 禁用 load_plugin("detector"/"embedder") 重复实例化（共享单实例）
人脸/车牌推理 ONNX（x86 装 onnxruntime-gpu, ARM64 自动 CPU）
```

## Search Architecture

```
Semantic Search: query → embedder.encode_text() 一次 → 7 路并行召回:
  frame(1fps 精确) / chunk(滑窗, 默认关) / text(caption+ocr+transcript) / label(JSONB @>) / track(crop 跨模态) / plate(Levenshtein+ILIKE+归一化) / ocr(画面文字精确串匹配, ILIKE+编辑距离, v0.34)
图搜: /search/face（ArcFace 512d → face_identities, GREATEST(最典型脸, 均值) 双锚）· /search/image（Qwen3-VL → frame_embeddings, 独立 search_image_only 路径帧不聚类）
合并去重: 帧簇(间隔≤4s)优先, chunk/text 与帧重叠丢弃; plate/ocr/track 独立去重（无 scene 概念, 各自按 track/时间戳唯一）; confidence = 相似度 × 路径权重（frame 1.0/track 0.9/plate 0.95/ocr 0.95/text 0.85/chunk 0.7）
范围过滤: video_ids 空列表 → 空(fail-closed); None=全库; ⚠️ search/face + /search/image 参数必须 Form(...) 声明（防 query 取 None 全库泄漏）
返回: precision_level / precise_start/end / match_paths / thumbnail_url / track_id? / bbox? / confidence?
core/search.py: frame_vector_search · chunk_vector_search · text_vector_search · track_vector_search · plate_text_search · ocr_text_search · face_identity_search
```

## Database Schema

| Table | 关键列 | 用途 |
|---|---|---|
| `video_groups` | id, name, number/owner(案例编号/负责人) | 视频分组/案例 |
| `videos` | id, status/progress, summary(JSONB), summary_mode, 感知/功能开关, 高级参数, 格式字段, **source_owned**, **group_id**, **external_file_id**(平台 id), **file_id+version_no**(版本链), **processing_started_at**(耗时), metadata_json, source_analysis | 主表 |
| `scenes` | scene_index, start/end_sec, **text_embedding**(EmbedVector), caption, ocr_text, aligned_transcript, entities(JSONB) | 搜索主粒度 |
| `transcripts` | full_text, words(JSONB) | 字幕 |
| `frame_embeddings` | timestamp_sec, embedding(EmbedVector), is_keyframe | 1fps 帧向量 |
| `chunks` | chunk_index, start/end_sec, embedding(EmbedVector) | 滑窗向量 |
| `frame_detections` | track_id, timestamp_sec, class_name, confidence, bbox(JSONB) | YOLO 逐帧检测 |
| `tracks` | track_id, class_name, first/last_seen, frame_count, segments(JSONB) | 轨迹摘要 |
| `track_embeddings` | track_id, embedding(EmbedVector), timestamp_sec, bbox(JSONB) | 轨迹 crop 向量 |
| `face_identities` | identity_label, **face_embedding**(512 均值) + **best_face_embedding**(512 最典型脸), best_track_id, first/last_seen, avg_quality, best_face_bbox | 聚类身份 |
| `face_detections` | identity_id(FK), track_id, timestamp_sec, bbox(JSONB), quality_score, face_embedding(512) | 逐帧人脸 |
| `plate_detections` | track_id, plate_text, plate_type, char_confidences(JSONB), bbox, detection_confidence | 车牌 |
| `ocr_detections` | timestamp_sec, text, bbox(JSONB), confidence | 画面文字（第 8 路精确检索） |
| `pipeline_tasks` | type, dedup_key, video_id, payload_json, status, error | 任务队列持久化 |
| `task_logs` | task_id(=版本行 id), seq, level, message, created_at | 任务生命周期日志 |

向量列 = `EmbedVector()`（维度随 embedding_profile 8b=4096 / 2b=2048）；人脸固定 `Vector(512)`。无 pgvector HNSW（4096 超 2000 上限，demo 规模全扫描 <1ms）。`init_db()` 增量迁移（ADD COLUMN IF NOT EXISTS）。

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/videos/upload` · `/upload/batch` | 上传（单个/批量建组, 不启动管道） |
| POST | `/api/v1/videos/register-external` | 平台共享文件就地引用（source_owned=false） |
| GET | `/api/v1/videos/external/{file_id}` | 平台文件 id 查找（自动跳转目标） |
| PUT | `/api/v1/videos/{id}/params` | 设置参数 + 启动管道 |
| POST | `/api/v1/videos/reuse` · `/{id}/reanalyze` · `/analyze-batch` | 复用文件新建 / 重新解析建版本行 / 批量解析 |
| GET | `/api/v1/videos/` · `/{id}` · `/{id}/status` · `/{id}/metadata` | 列表 / 详情 / 状态 / 元数据+来源分析 |
| GET | `/api/v1/videos/{id}/stream` · `/thumbnail/{scene}` · `/versions` | 播放(HEVC 路由) / 场景缩略图 / 版本链 |
| DELETE | `/api/v1/videos/{id}` | 删除（级联+清盘, 处理中可删优雅中止） |
| GET/PUT | `/api/v1/settings` · `/settings/pipeline` | 系统设置 / 生效管道配置（含档位） |
| GET/POST/PUT/DELETE | `/api/v1/settings/presets` · `/{id}/apply` | 参数预设 CRUD + 套用 |
| GET | `/api/v1/pipeline/operations` | 启用的操作列表 |
| GET | `/api/v1/videos/{id}/detection/tracks` · `/detections` · `/thumbnail` | 检测轨迹 / 时间窗检测框 / 缩略图 |
| GET | `/api/v1/videos/{id}/face/data` · `/face/thumbnail` | 人脸数据 / 缩略图 |
| GET | `/api/v1/videos/{id}/plate/data` · `/plate/thumbnail` | 车牌数据 / 缩略图 |
| GET | `/api/v1/videos/{id}/ocr/data` | OCR 画面文字清单（按时间戳，桌面前端「文字」标签页） |
| GET/POST | `/api/v1/videos/{id}/export/clip` · `/frames` · `/track/{tid}` · `/thumbnails` | 导出片段/帧/轨迹/缩略图 |
| POST | `/api/v1/search/semantic` · `/search/face` · `/search/image` | 语义（含 OCR 第 8 路 search_types=["ocr"]）/ 人脸图搜 / 通用图搜 |
| GET/POST | `/api/v1/files` · `/files/{file_id}` | 文件库列表 / 重命名 |
| GET/POST | `/api/v1/groups` · `/groups/{id}` · `/groups/{id}/assets` | 案例 CRUD / 素材 |
| GET/POST | `/api/v1/tasks` · `/{id}/log` · `/{id}/retry` · `/{id}/report` · `/export-batch` | 任务中心 |
| POST | `/api/v1/maintenance/sweep` · GET `/maintenance/storage` | 存储清扫 / 用量 |
| POST | `/internal/yunzhi/jobs` | 云智异步任务（根路径, 202+回调+幂等） |

## Frontend Architecture

**双前端共存**：服务器 `frontend/`（v0.28 云智嵌入 UI，Dashboard 主工作台 + 19 组件 + 云智 Bridge SDK）+ 桌面独立 `frontend-desktop/`（v0.34 浅蓝 4 页管理后台）——UI 层各自演进不共享；**对接层 `frontend-shared/`（api/types/labels/helpers）一份实现，双端 services/api.ts 等是再导出指针**。

**桌面前端（frontend-desktop/）**：App.tsx 壳 + AppContext（跨页导航/共享视频列表轮询/上传删除编排）+ 4 页组件（FileLibrary / Workbench[视频解析, SplitPane 工作台] / TaskCenter / SettingsPage）+ TitleBar（frameless 自绘标题栏, 手动拖拽, 最近更新下拉, 太阳/月亮暗色主题）+ Sidebar + SystemMonitor(psutil 真机监控)。页面卡片空隙靠 `app-main-flat` 透明 + 根容器透明透出渐变；暗色=CSS 变量调色板重映射（`html.dark`）。与服务器前端完全隔离。

**桌面端窗口壳（desktop/）**：pywebview 主窗 `frameless=True, shadow=True`；SplashApi 窗口控制（minimize/toggle_maximize/is_maximized 读真实 WindowState/move/quit）+ 系统监控 + git 最近提交；SPLASH_HTML 毛玻璃启动页（模型加载段按日志 tqdm `Loading weights: X%` 实时推进, 高清图标 base64 内嵌, 右上角 × 终止启动=停后端+关窗）；后端生命周期 = backend_launcher.py（封装字节码/源码双模式 + 父进程句柄看门狗免疫 PID 复用）；数据库双模式 `desktop/db.py`（vendor/pg 内嵌便携 PostgreSQL 优先, start_db 幂等 pg_isready 探测复用, 无则 docker）；check_models 读 config embedding_profile 传 verify；`build_exe.ps1 -Deploy` 打纯壳 exe（部署前幂等停内嵌 postgres, 后端编译为 .pyc 字节码包藏源码）。

## Key Design Decisions

| Decision | Rationale |
|---|---|
| Plugin + Factory | config.yaml 换后端零代码改动 |
| pgvector over 独立向量库 | 部署简单、事务一致 |
| 本地 GPU Embedder | 每帧 4096 维编码，API 延迟不可接受 |
| 共享 embedder (app.state) | 避免每视频重载 ~4GB 模型 |
| 单 NVDEC 流共享 + 生产者-消费者 | detection 与 search_encode 共享解码流，消灭双流解码竞争 |
| NVDEC MJPEG pipe | ~100KB/帧 替代 raw NV12(3.1MB), pipe I/O 减 30× |
| 三档速度预设 (fast/balanced/precise) | 控制分辨率 + 批量权衡 |
| 搜索/摘要路径解耦 | 帧搜索不等 caption |
| 2 层格式兼容 + 懒代理 | remux(-c copy) 即时 + proxy(NVENC h264) 按需, HEVC 浏览器零处理 |
| 全局 GPU 锁 | 24GB 机 YOLO 卷积 + 8bit matmul 并发触发驱动硬故障 → 串行所有 GPU 前向；detection 攒批 128 防饿死 embedder |
| 全局任务队列 (PipelineQueue) | FIFO + worker 池 + 表持久化；批量并发防 OOM；重启恢复 + 幂等 + 排队回调 |
| 平台共享文件 source_owned | register-external 就地引用不复制；删视频绝不 unlink 源文件（所有权归平台） |
| 人脸聚类护栏式双阈值 | 单一阈值是"跷跷板"：0.60 拆碎同人 / 0.40 并错不同人 → 同 track 0.30 宽松 + 跨 track 0.58 保守 |
| 检索锚点最典型脸 | 与均值最接近的单脸（非质量分最高），防角度偏导致搜索漏检；GREATEST(最典型脸, 均值) 双锚 |
| 搜索数据隔离 | search/face+image 改 Form(...) 声明修全库泄漏；单视频搜索严格过滤 |
| embedding 档位化 (8b/2b) | 低显存机器平替：档位联动模型路径+向量维度；2b 自动套轻量编码/量化默认 |
| 参数预设随 git 迁移 | config/presets.json 入仓库，部署/换机开箱复用 |
| OCR 独立感知模块（v0.34） | 自抽高清帧（读具体字符需像素清晰，复用检测低分辨率帧不可逆）→ **RapidOCR(PP-OCRv3 ONNX) + DirectML EP**（中文精度第一梯队）+ 独立表 + 精确串检索（第 8 路）。**DML 隔离走独立子进程**：onnxruntime 与 onnxruntime-directml 共用 `import onnxruntime` 名，进程内只能一份——为不破坏人脸/车牌依赖的全局 onnxruntime-gpu(CUDA)，RapidOCR 放子进程前置 `vendor/ort_dml` 加载 DML。OCR 文本去重：全局合并 + 固定文字抑制 + 模糊合并 + 阅读序。「OCR 独立模式」= text_recognition 场景关 search_index + 校验器放行仅 OCR 第三态 |

## Current Status
**核心链路全部 ✅**：Pipeline DAG(16 ops) / 4 编码路径 / 双层 ReID / 8 路搜索+图搜 / 人脸+车牌+OCR / 双模式摘要(vlm_llm 默认) / 多格式 / 存储卫生 / 4 级参数+增量 / 设置+预设 / GPU 锁+共享实例 / 任务队列 / 文件库+多版本+任务中心 / 批量解析+重命名 / 档位感知设置 / 云智嵌入 / 桌面端重构 / 生产部署。详见 README「Development Status」。

**非完全状态**：Chunk 编码（config 控制默认关）· OCR 导出/文字框裁剪/语义增强（预留）· Grounding（Florence-2 占位）· Reindex（待办）。AI 生成检测已移除（列保留恒 not_run）。

## 版本发布
见 README「版本号与发布」（`./bump` 联动 core/version.py + frontend/package.json + tag 强绑定 v<__version__>；后端 + 服务器前端/共享层改动必须发版）。