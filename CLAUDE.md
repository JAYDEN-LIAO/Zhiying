# Zhiying Project Context for AI Agents

## Overview

智影 (Zhiying) 是**视频分析引擎**：上传视频（单个/批量分组/多版本解析）→ 声明式 DAG 管道（16 ops）→ 4 条编码路径 + YOLO11/BoT-SORT 检测跟踪（双层 ReID）+ 人脸/车牌/OCR 识别 → 8 路语义搜索 + 图搜 + 图片素材库（人脸/通用图搜分轨检索）→ FastAPI + PostgreSQL/pgvector 对外服务。当前版本 **0.90**（两段式版本号：`core/version.py` 与三前端 package.json 同步）。

**关键锚点**：
- **本机两个入口（定版约定）**：快速看最新效果 → 双击根目录 **`desktop.bat`**（源码模式，改码重启即生效，License 跳过）；打包出货 → 双击 **`update_build.bat`**（dist → 壳 exe 到 `dist\智影桌面端\` → `build\` 安装包 + `build\green` 打包材料，发版前先 `./bump`）。根目录不落地 exe（iss 直接取 dist 产物）；根 exe 是封装态（跑烧进的 backend_pyc，非源码），仅用于模拟客户机
- **生产部署**：10.0.0.176（systemd `zhiying.service`，8011）；发版 `./bump`（可尾链一键构建安装包 + 打包材料目录）→ 服务器 `bash deploy.sh v<tag>`
- **SVN 双仓备份**：`python scripts/svn_sync.py source product`——源码镜像 `AI_Ying/trunk`（git ls-files 精确镜像），产品材料 `AI_Ying_TestVersion/trunk/v<版本>/`（=build\green 全量，已存在需 --force）；凭证 `config/svn.local.json`（gitignored）；svn add 必须 `--no-ignore`（默认忽略 *.pyc 会漏 backend_pyc）
- **配置**：`config/config.yaml` 机器相关 gitignored；运行时覆盖走 `data/settings.json`（保存即生效）+ 共享预设 `config/presets.json`（入 git）
- **三前端**：服务器 `frontend/`（**已废弃保留**，待退役）+ 桌面 `frontend-desktop/`（5 页管理后台，pywebview 壳）+ 新 web `frontend-web/`（轻量解析工作台，api 复用 frontend-shared，自带 mock 演示降级；暂未挂载到后端静态托管，与旧端并存）；对接层 `frontend-shared/` 一份实现
- **Windows 安装器**：`zhiying.iss`（Inno Setup 6）→ `build\视频快速智能检索平台 Ver <版本>.exe`（gitignored）；一体化安装（环境 + 内嵌 PG + 25GB 模型在安装段内完成；首启 MODEL_BOOT 兜底续传，`desktop/model_bootstrap.py` 跑 `deploy/download_models.py`，档位写回 config.yaml）；交付走 `desktop/make_green.ps1` 装配 `build\green\` 打包材料目录（zhiying.iss 就位，可直接 ISCC 编译；`-Zip` 可选压 zip 交外部打包方）
- **License 校验（软件管家）**：封装态启动即验、开发态跳过（`desktop/license_check.py`）——调软件管家 `software_center.exe 1 A5300`，退出码 0=试用通过 / 1=失败弹窗退出 / 2=正式版自校验 SuperDog 加密狗（`SuperDog_x64.dll` 与壳同级）
- **模型档位**：`embedding_profile` 8b=4096 维（默认）/ 2b=2048 维（低显存平替）；人脸固定 512（ArcFace）
- **摘要**：vlm_llm（API，默认）；native_video 已退役
- 架构细节见 `docs/arch.md`

## Core Flow

```
上传 → 参数 → 管道 → 搜索:
  POST /videos/upload(/upload/batch) → 存盘 → probe → 建记录(pending) → 异步 remux/proxy
  POST /videos/suggest-params → 按画面内容推荐参数（9 场景分类, 低置信兜底默认）
  PUT /videos/{id}/params → 校验 → 入队 → PipelineEngine.run()(pending) / run_incremental()(completed)
  PATCH /videos/{id}/toggles → 仅持久化 6 核心开关，不入队管道（抽屉「参数设置」专用）
  PipelineEngine 事件驱动 DAG(16 ops):
    duration → detection(生产者-消费者, 共享 NVDEC) → track_encode → face/plate
    duration → segmentation → keyframes → caption → summary → frame/text/chunk_encode
    duration → ocr(RapidOCR+DirectML 独立子进程) → ocr_detections
  搜索 7 路并行 + 图搜：frame/chunk/text/label/track/plate/ocr
  素材库检索：/search/subjects 上传图片 → person 走 ArcFace 512 / other 走 Qwen3-VL → 命中底库目标
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
- **DB 连接**: 环境变量 `POSTGRES_URI` → config.yaml `database.uri` → 兜底 5432；`python run.py` 自动自举数据库（内嵌 vendor/pg / docker compose 回退），与桌面启动器 `desktop/db.py` 同优先级
- **DB 实例隔离**: 内嵌 PG 端口**每实例终身固定**（`data/db_port.txt`：config 端口空闲才用，被其它程序/其他 Zhiying 安装占用则自动让位空闲端口并落盘；后端经 `POSTGRES_URI` env 注入实例 URI）——杜绝多安装同抢 5432 串库（8b/2b 表维度不同，串库=向量维度错配炸管道）；桌面壳退出即停**本实例**内嵌 PG（`pg_ctl status` 只认自己 pgdata，不碰别人的 PG）
- **配置模板化**: config.yaml 机器相关 gitignored；新机复制 `config.yaml.example` 自改
- **4 级参数系统**: L1 场景（9 智能推荐场景 + 5 旧值）→ L2 感知模块 → L3 功能开关 → L4 高级参数
- **智能参数系统**: 场景分类与参数预设集中在 `services/smart_suggest.py`（9 类）；低置信兜底 `_DEFAULT_PARAMS`；改场景须加/改 `_scene_fingerprint()` 相关缓存（列表增改自动失效）
  - **持久化**：suggest-params 自动落库到 `videos.suggested_scene_key/label/confidence/params(JSONB)` 4 字段；关闭弹窗不丢
  - **抽屉轻量层**：`PATCH /videos/{id}/toggles` 仅持久化 6 核心开关，不入队管道、不动版本、不联动组
  - **抽屉 UI**：FileDetailDrawer「参数设置」section + Workbench `SingleAnalyzeDialog` + 案例库 `BatchAnalyzeDialog` 三处共用 `AnalyzeSettingsPanel` + `buildPipelineParams()`
  - **摘要默认全关**：模型/上传/场景预设/智能推荐按钮联动 → 都关
  - **caption-summary 联动**：开摘要自动开画面描述（后端校验 caption OFF → summary OFF）
  - **9 场景预设**：traffic/vehicle_focus/surveillance_people/indoor/portrait_focus/document/street_mixed/outdoor_landscape/chat_screen，每个场景对应一组检测/人脸/车牌/OCR 开关预设
- **图片素材库**：关注目标（人/其他）底库照片管理 + 检索分轨
  - **3 表**：`image_subjects`（目标）/ `subject_photos`（底图）/ `subject_photo_embedding`（分轨向量：person→Vector(512) / other→EmbedVector）
  - **15 个 API**：`/subjects` CRUD + 照片 + 合并 + 文件 + `/search/subjects` 图片检索
  - **检索分轨**：person→`face_recognizer.extract_best_embedding`（ArcFace 512）/ other→`embedder.encode_image`（Qwen3-VL）；落盘即编码入库
  - **桌面端第 5 页**：`ImageLibrary`（左列表+右详情+裁剪+拖拽扩充）+ `SubjectPhotoPicker`（全局搜索/视频搜索卡统一选图来源）+ `AddSubjectDrawer`（检测/图搜一键沉淀，支持新建/已有目标两种模式；保存后仅关抽屉停留当前页面，已选目标列表随抽屉整体滚动无内滚视口）
  - **搜索同步**：全局搜索文字/人脸/图搜 → 点击结果跳工作台 → 视频搜索卡片自动填充并搜索。跨页意图带目标视频 id（`pendingSearchVideoId`）+ 递增 tick；Workbench 常驻挂载后卡片与消费方都等 vid 落到目标视频才执行/消费，防止拿旧视频 id 搜索或被 stale 重置清空
  - **全局搜索目标类型**：人/车/车牌/文本/事件 5 类型 chip 互斥选中；各类型专属特征面板选中才出现（颜色常驻）；切换类型自动清空搜索文本框与已选 token
  - **案例库重新分析**：抽屉「参数设置」开关点击即 PATCH /toggles 持久化 → completed/failed 视频「重新分析」必须走 POST /reanalyze 建新版本（PUT /params 会因新旧一致被「参数未改变」拦截）；pending 视频仍走 PUT /params
  - **视频搜索卡智能筛选推荐**：`POST /search/suggest-filter` 文本相似度预判——事件/动作/语义类（求婚、打架、两车相撞…）自动画面定位（frame）；单物体类（黑色车辆、戴口罩的人…）自动物体定位（track）；手动选择优先（`autoFilterActive` 状态，用户手动切下拉后置 false）；车牌/文字模式不参与；`skipFilterReseachRef` 抑制自动改筛选触发的重复搜索
  - **告警红点**：前端空壳保留（`imageLibAlertCount`/侧栏红点），后端本期不做（下一阶段）
  - **案例库图片边界**：案例库不支持图片上传，`images` 恒空；选图统一走素材库
- **三前端**: UI 各自演进；对接层 `frontend-shared/` 一份实现，改后端接口只改一处；桌面壳 `load_url` 必须带缓存键（`desktop/app.py _cache_bust_url`）击穿 WebView2 持久化缓存（`private_mode=False` 跨版本复用旧缓存会显示旧 UI）——封装态键=版本号、开发态键=dist/index.html mtime（仅改桌面前端不 bump 也取新）
- **多格式**: remux(-c copy) + proxy(NVENC h264, 按需)；管道优先读 remuxed
- **ReID 双层**: 在线 BoT-SORT with_reid + 全局 tracklet 缝合（cosine ≥0.85）
- **人脸双阈值**: 同 track 0.30 宽松合并，跨 track 0.58 保守合并；检索锚点最典型脸
- **人脸出现段**: 检测栏人脸展开显示该身份的**主 person track**（`track_to_identity`，时间轴同源）的 `[first_seen, last_seen]`/`segments`，排除"搭车"长 track；人脸搜索 `appearances` 仅保留主身份 track；点击结果从首段自动播放并逐段跳过，当前段黄框高亮（前端 `timeupdate` 判 `currentTime` 落段）
- **弹窗/抽屉 portal**: 桌面前端所有 modal/drawer 必须 `createPortal(document.body)` + `onMouseDown` 遮罩关闭（`e.target===currentTarget`）；`DetectionOverlay` 用真实事件目标 `container.contains` 判定防穿透/遮挡关不掉
- **安装器约定**: Inno 等待循环跑 UI 线程——每轮必须 ProcessMessages 泵消息（否则窗口假死）；超时 = 30 分钟无任何新输出判卡死 + 12h 总兜底（模型 25GB 在安装段内下载，不能按总时长掐）；进度 = setup 离散标记 + Inno 侧蠕动平滑（pip 接管道非 TTY 无进度条可解析）；pip 走清华镜像、torch 官方源走代理失败回退阿里云 find-links 直连；自备模型复制前置（不依赖环境安装成败）+ 路径校验（models\Qwen 为锚）；快捷方式延后到环境安装成功后由代码创建（[Icons] 段早于环境安装执行）；装完删安装耗材（requirements.txt/setup_windows.ps1/desktop/db.py；download_models.py 保留供首启引导），卸载 [UninstallDelete] 清 .venv/vendor、保留 data/models
- **工作台常驻挂载**: 桌面端 Workbench/GlobalSearch 切页 hide 不卸载（保播放与搜索状态）；跨页意图（seek/track 选中/搜索同步）一律携带目标视频 id，等 vid 落到目标才消费
- **搜索隔离**: search/face 与 search/image 参数必须 `Form(...)` 声明（防全库泄漏）
- **版本号**: `core/version.py` `__version__` 唯一来源（两段式 X.Y，与软件管家平台格式一致）；后端+服务器前端改动必须 `./bump`（联动三前端 package.json/lock + zhiying.iss 兜底版本，GUI 直编不拿旧版本号）；发版手动触发（多次 commit 不发版，bump 才发版）
- **关于弹窗/检查升级**: TitleBar「关于」→ AboutDialog；检查升级走软件管家 `software_center.exe` **模式 2**（`"2" "<产品号>" "<license.dat>" "<当前版本>"`，升级检查/下载由软件管家自带 UI 完成，壳只调起等待）；服务截止时间读 license.dat 过期字段；开发态（非 frozen）置灰
- **删除三层保证**: 路由显式清盘 → DB FK CASCADE → `maintenance/sweep` 兜底；
  task_logs / pipeline_tasks 无 FK（bootstrap 手建表），由 delete_video **显式清除**
  （删视频连队列行一起清，重启恢复不复活僵尸任务；恢复时发现视频已删的排队任务标 failed，
  executor 缺视频抛错而非静默 completed）
- **素材库/案例库路径**: 底图/案例图落盘一律经 StorageManager（`subject_photo_dir` /
  `case_asset_dir`）存**绝对路径**；历史相对路径行由读取侧归一化兼容，不迁移存量数据
- **清扫范围**: sweep 覆盖视频文件/附属目录/exports TTL/空组 + **subject_photos / case_assets 图片孤儿**
  （引用集 + 600s mtime 保护，覆盖"文件已落盘、DB 未 commit"的崩溃窗口）；yunzhi 平台工作目录有意豁免
- **任务日志**: 失败 traceback 批量单次落库；日志孤儿/超期行与队列终态行按 `TASK_LOG_RETENTION_DAYS`
  （90 天）随 sweep 清理；queued/running 队列行永不清（重启恢复数据源）

## Database (19 tables)

| Table | Purpose |
|---|---|
| `video_groups` | 批量上传自动分组（案例） |
| `videos` | 主表：status/progress/summary/开关/参数/格式/source_owned/file_id+version_no/processing_started_at/suggested_*/task_hidden(任务删除隐藏) |
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
| `pipeline_tasks` | 全局任务队列持久化；delete_video 显式清行（防僵尸）；终态行 90 天保留 |
| `task_logs` | 任务生命周期日志；delete_video 显式清（无 FK）；孤儿/超期随 sweep 清理 |

向量列用 `EmbedVector()`（8b=4096 / 2b=2048）；人脸 `Vector(512)`。

## Agent Instructions

1. **Don't modify `.env`** — contains API keys, gitignored
2. **Don't delete empty `__init__.py` / 占位** — plugins/grounding/ 是故意占位
3. **新感知模块** = `pipeline/runners/` 新 runner + `pipeline/operations.py` 一个 Operation
4. **Sync vs Async**: 插件接口全 async；同步模型推理必须 `asyncio.to_thread()`
5. **向量维度**: 向量列用 `EmbedVector()`；人脸 `Vector(512)`
6. **新依赖**: 加 `requirements.txt`
7. **改后端接口/字段** → 只改 `frontend-shared/`
8. **Detection gate**: 可选感知模块遵循双门控（config backend + per-video toggle）
9. **cv2/sync calls MUST use asyncio.to_thread()**
10. **Storage hygiene**: 删除必须 `repository.delete_video`；新落盘路径登记进 `core/storage_manager.py`
11. **commit / tag / push / 部署必须事前征得用户明确同意**
12. **改前端先确认哪端**: 服务器 `frontend/`（已废弃保留，改动需 bump）/ 桌面 `frontend-desktop/`（独立）/ 新 web `frontend-web/`（暂未挂载上线；挂载替换后需 bump）；`frontend-shared/` 多端共用
13. **文档卫生**: 三份权威文档（README/CLAUDE.md/arch.md）只写**当前事实**——新增功能改写对应章节为现在时态；不追加"某版本做了什么"的改动叙事段，变更历史由 git log 承担

## Python Environment

Python 3.13 · FastAPI + SQLAlchemy async + asyncpg + pgvector · transformers/torch(CUDA)/modelscope · bitsandbytes(量化) · onnxruntime-gpu(x86/Windows; ARM64 CPU) · openai/httpx/Pillow · pytest/pytest-asyncio
