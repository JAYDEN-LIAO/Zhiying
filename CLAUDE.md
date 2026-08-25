# Zhiying Project Context for AI Agents

## Overview

智影 (Zhiying) 是**视频分析引擎**：上传视频（单个/批量分组/多版本解析）→ 声明式 DAG 管道（16 ops）→ 4 条编码路径 + YOLO11/BoT-SORT 检测跟踪（双层 ReID）+ 人脸/车牌/OCR 识别 → 8 路语义搜索 + 图搜 + 图片素材库（人脸/通用图搜分轨检索）→ FastAPI + PostgreSQL/pgvector 对外服务。当前版本 **v0.6**（图片素材库 + 搜索统一 + 摘要 UI 重构）；后端定版 v0.34（OCR RapidOCR+DirectML 子进程）。

**关键锚点**：
- **生产部署**：10.0.0.176（systemd `zhiying.service`，8011）；发版 `./bump` → 服务器 `bash deploy.sh v<tag>`
- **配置**：`config/config.yaml` 机器相关 gitignored；运行时覆盖走 `data/settings.json`（保存即生效）+ 共享预设 `config/presets.json`（入 git）
- **双前端**：服务器 `frontend/` + 桌面 `frontend-desktop/`（5 页管理后台，pywebview 壳）；对接层 `frontend-shared/` 一份实现
- **模型档位**：`embedding_profile` 8b=4096 维（默认）/ 2b=2048 维（低显存平替）；人脸固定 512（ArcFace）
- **摘要**：vlm_llm（API，默认）；native_video 已退役
- 架构细节见 `docs/arch.md`

## Core Flow

```
上传 → 参数 → 管道 → 搜索:
  POST /videos/upload(/upload/batch) → 存盘 → probe → 建记录(pending) → 异步 remux/proxy
  POST /videos/suggest-params → 按画面内容推荐参数（9 场景分类, 低置信兜底默认）
  PUT /videos/{id}/params → 校验 → 入队 → PipelineEngine.run()(pending) / run_incremental()(completed)
  PATCH /videos/{id}/toggles（v0.37）→ 仅持久化 6 核心开关，不入队管道（抽屉「参数设置」专用）
  PipelineEngine 事件驱动 DAG(16 ops):
    duration → detection(生产者-消费者, 共享 NVDEC) → track_encode → face/plate
    duration → segmentation → keyframes → caption → summary → frame/text/chunk_encode
    duration → ocr(RapidOCR+DirectML 独立子进程) → ocr_detections
  搜索 7 路并行 + 图搜：frame/chunk/text/label/track/plate/ocr
  素材库检索（v0.6）：/search/subjects 上传图片 → person 走 ArcFace 512 / other 走 Qwen3-VL → 命中底库目标
  沉淀：检测 track「+」/ 图搜「+」→ AddSubjectDrawer → 底库照片 + 编码入库
```

## Key Conventions

- **异步规则**: 所有接口 async；同步模型推理/cv2 MUST `asyncio.to_thread()`
- **Config-driven**: 插件后端由 `config.yaml` `plugins.{name}.backend` 选，null=禁用；API key 只在 `.env`
- **设置运行时生效**: 上传/FormatService/VideoService 用新鲜 `load_config()`（勿用 app.state.config 快照）
- **全局 GPU 锁**: 所有 embedder/detect 前向必须 `async with gpu_lock`（并发会蓝屏/卡死）；detection 攒批用 **128**；实测 RTX 5090 笔记本 + embedder bnb 8bit 在重 GPU 负载下偶发整机硬冻结（供电瞬变，Event 41 无 bugcheck）——24GB+ 机器建议 embedder `quantization=none`（fp16）规避 bnb 8bit matmul 功耗尖峰
- **OCR DML 隔离**: RapidOCR 必须走**独立子进程**（`plugins/ocr/rapidocr_worker.py`），**绝不**在主进程改全局 onnxruntime；封装态（backend_pyc 只留 .pyc）worker 入口已做 `.pyc` 回退，worker 定位 vendor/ort_dml 走 `ZHIYING_PROJECT_ROOT`（源码态 `__file__` 推导）
- **共享单实例**: embedder + detector 启动预载 app.state（detector 懒加载），禁用 `load_plugin` 重复实例化
- **全局任务队列**: PipelineQueue FIFO + N worker + `pipeline_tasks` 表持久化；重启恢复；幂等
- **向量维度**: `EmbedVector()` 随 embedding_profile（8b=4096 / 2b=2048）；人脸 `Vector(512)`
- **DB 连接**: 环境变量 `POSTGRES_URI` → config.yaml `database.uri` → 兜底 5432；`python run.py` 自动自举数据库（端口已通→直接复用 / 内嵌 vendor/pg / docker compose 回退），与桌面启动器 `desktop/db.py` 同优先级
- **配置模板化**: config.yaml 机器相关 gitignored；新机复制 `config.yaml.example` 自改
- **4 级参数系统**: L1 场景（9 智能推荐场景 + 5 旧值）→ L2 感知模块 → L3 功能开关 → L4 高级参数
- **智能参数系统（v0.37）**: 场景分类与参数预设集中在 `services/smart_suggest.py`（9 类）；低置信兜底 `_DEFAULT_PARAMS`；改场景须加/改 `_scene_fingerprint()` 相关缓存（列表增改自动失效）
  - **持久化**：suggest-params 自动落库到 `videos.suggested_scene_key/label/confidence/params(JSONB)` 4 字段；关闭弹窗不丢
  - **抽屉轻量层**：`PATCH /videos/{id}/toggles` 仅持久化 6 核心开关，不入队管道、不动版本、不联动组
  - **抽屉 UI**：FileDetailDrawer「参数设置」section + Workbench `SingleAnalyzeDialog` + 案例库 `BatchAnalyzeDialog` 三处共用 `AnalyzeSettingsPanel` + `buildPipelineParams()`
  - **摘要默认全关**（v0.37）：模型/上传/场景预设/智能推荐按钮联动 → 都关
  - **caption-summary 联动**（v0.6）：开摘要自动开画面描述（后端校验 caption OFF → summary OFF）
  - **9 场景预设**：traffic/vehicle_focus/surveillance_people/indoor/portrait_focus/document/street_mixed/outdoor_landscape/chat_screen，每个场景对应一组检测/人脸/车牌/OCR 开关预设
- **图片素材库（v0.6）**：关注目标（人/其他）底库照片管理 + 检索分轨
  - **3 表**：`image_subjects`（目标）/ `subject_photos`（底图）/ `subject_photo_embedding`（分轨向量：person→Vector(512) / other→EmbedVector）
  - **15 个 API**：`/subjects` CRUD + 照片 + 合并 + 文件 + `/search/subjects` 图片检索
  - **检索分轨**：person→`face_recognizer.extract_best_embedding`（ArcFace 512）/ other→`embedder.encode_image`（Qwen3-VL）；落盘即编码入库
  - **桌面端第 5 页**：`ImageLibrary`（左列表+右详情+裁剪+拖拽扩充）+ `SubjectPhotoPicker`（替代已退役的 `CaseAssetPicker`，全局搜索/视频搜索卡统一选图来源）+ `AddSubjectDrawer`（检测/图搜一键沉淀，支持新建/已有目标两种模式）
  - **搜索同步**：全局搜索文字/人脸/图搜 → 点击结果跳工作台 → 视频搜索卡片自动填充并搜索
  - **告警红点**：前端空壳保留（`imageLibAlertCount`/侧栏红点），后端本期不做（下一阶段）
  - **案例图片退役**：案例库不再支持图片上传，`images` 恒空；`CaseAssetPicker` 已被 `SubjectPhotoPicker` 替代
- **双前端**: UI 各自演进；对接层 `frontend-shared/` 一份实现，改后端接口只改一处；桌面壳 `load_url` 必须带版本号（`desktop/app.py _cache_bust_url`）击穿 WebView2 持久化缓存（`private_mode=False` 跨版本复用旧缓存会显示旧 UI）
- **多格式**: remux(-c copy) + proxy(NVENC h264, 按需)；管道优先读 remuxed
- **ReID 双层**: 在线 BoT-SORT with_reid + 全局 tracklet 缝合（cosine ≥0.85）
- **人脸双阈值**: 同 track 0.30 宽松合并，跨 track 0.58 保守合并；检索锚点最典型脸
- **搜索隔离**: search/face 与 search/image 参数必须 `Form(...)` 声明（防全库泄漏）
- **版本号**: `core/version.py` `__version__` 唯一来源；后端+服务器前端改动必须 `./bump`
- **存储卫生**: 删除必须 `repository.delete_video`；新落盘路径登记进 `storage_manager.py`

## Database (19 tables)

| Table | Purpose |
|---|---|
| `video_groups` | 批量上传自动分组（案例） |
| `videos` | 主表：status/progress/summary/开关/参数/格式/source_owned/file_id+version_no/processing_started_at/suggested_* |
| `scenes` | 搜索主粒度：text_embedding/caption/ocr_text/transcript/entities |
| `transcripts` | 完整字幕 + words |
| `frame_embeddings` / `chunks` | 1fps 帧向量 / 滑动窗口向量 |
| `frame_detections` / `tracks` / `track_embeddings` | YOLO 逐帧检测 / BoT-SORT 轨迹 / 轨迹向量 |
| `face_identities` / `face_detections` | 聚类身份(512d) + 逐帧人脸 |
| `plate_detections` | HyperLPR3 车牌 |
| `ocr_detections` | 画面文字（第 8 路精确检索） |
| `case_assets` | 案例素材（图片等非视频归档素材，不参与管道） |
| `image_subjects` | 素材库关注目标（人/其他，kind 两态） |
| `subject_photos` | 素材库底库照片（crop/source/source_video_id） |
| `subject_photo_embedding` | 素材库检索向量（分轨：person→Vector(512) / other→EmbedVector） |
| `pipeline_tasks` | 全局任务队列持久化 |
| `task_logs` | 任务生命周期日志 |

向量列用 `EmbedVector()`（8b=4096 / 2b=2048）；人脸 `Vector(512)`。

## Agent Instructions

1. **Don't modify `.env`** — contains API keys, gitignored
2. **Don't delete empty `__init__.py` / 占位** — plugins/grounding/ 是故意占位
3. **新感知模块** = `pipeline/runners/` 新 runner + `pipeline/operations.py` 一个 Operation
4. **Sync vs Async**: 插件接口全 async；同步模型推理必须 `asyncio.to_thread()`
5. **向量维度**: 向量列用 `EmbedVector()`；人脸 `Vector(512)`
6. **新依赖**: 加 `requirements.txt` AND `Dockerfile`
7. **改后端接口/字段** → 只改 `frontend-shared/`
8. **Detection gate**: 可选感知模块遵循双门控（config backend + per-video toggle）
9. **cv2/sync calls MUST use asyncio.to_thread()**
10. **Storage hygiene**: 删除必须 `repository.delete_video`；新落盘路径登记进 `core/storage_manager.py`
11. **commit / tag / push / 部署必须事前征得用户明确同意**
12. **改前端先确认哪端**: 服务器 `frontend/`（需 bump）vs 桌面 `frontend-desktop/`（独立）；`frontend-shared/` 双端共用

## Python Environment

Python 3.13 · FastAPI + SQLAlchemy async + asyncpg + pgvector · transformers/torch(CUDA)/modelscope · bitsandbytes(量化) · onnxruntime-gpu(x86/Windows; ARM64 CPU) · openai/httpx/Pillow · pytest/pytest-asyncio
