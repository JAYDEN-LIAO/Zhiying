# Zhiying Architecture

> 版本: 0.9.0（统一版本号） | Framework: FastAPI + SQLAlchemy async | Database: PostgreSQL 17 + pgvector
> 核心能力：16-op DAG · 4 编码路径 · YOLO11/BoT-SORT 双层 ReID · 人脸/车牌/OCR · 8 路搜索+图搜 · 图片素材库（人脸/通用图搜分轨检索）· 智能参数系统 · 全局任务队列 · 云智接入 · 桌面端 · Windows 安装器（一体化安装+首启模型兜底）· 软件管家 License 校验

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

智能参数系统:
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
摘要默认关闭：摘要耗时长且非核心，所有路径默认 summary_enabled=false
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
       出现段 = 该身份主 person track 的 [first_seen, last_seen]（track_to_identity 同源，非采样点）
任务队列: PipelineQueue FIFO + N worker + pipeline_tasks 表持久化
任务日志: task_logs(seq/level/created_at, (task_id,seq) 索引)——失败 traceback 批量单次落库；
          delete_video 显式清(无 FK)；孤儿/超期 90 天随 maintenance/sweep 清理(TASK_LOG_RETENTION_DAYS)
文件库: videos.file_id+version_no 版本链；批量解析仅处理 pending 视频
案例素材: case_assets 表（图片等归档素材，不参与管道；图片上传已退役，仅保留视频）
素材库: image_subjects + subject_photos + subject_photo_embedding（分轨向量）
        检索: /search/subjects 上传图片 → person ArcFace 512 / other Qwen3-VL → 命中底库目标
        沉淀: 检测 track「+」/ 图搜「+」→ AddSubjectDrawer → 底图 + 编码入库
              保存后仅关抽屉停留当前页；已选目标列表随抽屉整体滚动
重解析: completed/failed 视频参数改动走 POST /reanalyze 新建版本行（版本链 version_no+1）
        PUT /params 仅保留 L3 开关（摘要/搜索索引）增量补跑；pending 走 PUT 启动全量管道
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
            跨页搜索同步: 全局搜索→openWorkbench 带 searchQuery/faceFile/imageFile + 目标视频 id + tick；
            卡片寄存意图等 videoId 落到目标才搜索（常驻挂载下旧视频 id 过渡帧不动作、不被重置清空）
智能筛选推荐: POST /search/suggest-filter 文本相似度预判——事件/动作类→画面定位(frame)、单物体类→物体定位(track)；手动选择优先（autoFilterActive）；车牌/文字模式不参与
搜索结果时间范围: 点击结果自动播放到 end 时间后暂停（autoPauseEndRef + timeupdate 监听）
```

## Database Schema

| Table | 关键列 | 用途 |
|---|---|---|
| `video_groups` | id, name, number/owner | 视频分组/案例 |
| `videos` | status/progress, summary, 开关/参数, source_owned, file_id+version_no, suggested_*, task_hidden(任务删除隐藏) | 主表 |
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
| `pipeline_tasks` | status, dedup_key | 任务队列持久化；delete_video 显式清行（防僵尸）；终态行 90 天保留 |
| `task_logs` | seq, level, message | 任务生命周期日志；delete_video 显式清（无 FK）；孤儿/超期随 sweep 清理 |

向量列 `EmbedVector()`（8b=4096 / 2b=2048）；人脸 `Vector(512)`。

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/videos/upload` · `/upload/batch` | 上传（单个/批量建组） |
| POST | `/api/v1/videos/suggest-params` | 智能场景参数推荐（9 场景分类，**自动落库**到 videos.suggested_* 4 字段） |
| PATCH | `/api/v1/videos/{id}/toggles` | **抽屉轻量持久化**：仅 6 核心开关，不入队管道 |
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
| DELETE | `/api/v1/tasks/{id}` | 删除任务（仅失败；清 pipeline_tasks/task_logs，task_hidden=true 隐藏，不删视频/文件） |
| GET/POST | `/api/v1/videos/{id}/export/*`（clip/track/thumbnails） | 导出片段/单帧/轨迹 zip/缩略图 zip |
| GET | `/api/v1/videos/{id}/export/summary` · `/export/ocr` · `/export/plates` | **摘要/画面文字/车牌 txt 导出**（未生成时 404，前端下拉置灰） |
| GET | `/api/v1/tasks/{id}/report` · `POST /tasks/export-batch` | 任务报告导出（基本信息/分析结果/视频产出=智能摘要+OCR+车牌全量清单/处理日志） |
| GET/POST | `/api/v1/maintenance/storage` · `/maintenance/sweep` | 存储用量/清扫 |
| POST | `/internal/yunzhi/jobs` | 云智异步任务（202+回调+幂等） |

## Frontend Architecture

**双前端共存**：服务器 `frontend/`（Dashboard）+ 桌面 `frontend-desktop/`（5 页管理后台）；**对接层 `frontend-shared/` 一份实现**。

**桌面前端**：
- AppContext 全局状态（视频/任务/进度/树选/案例徽章/素材库跨页跳转）+ 5 页组件；Workbench 与 GlobalSearch 常驻挂载（切页 hide 不卸载，保播放与搜索状态），跨页意图（seek/track 选中/搜索同步）携带目标视频 id、等 vid 落到目标才消费：
  - **FileLibrary**（案例库）：左案例树 + 右内容区；选中案例时正文支持视频拖拽上传与文件夹选择；多版本行=一次解析
  - **Workbench**（视频解析）：SplitPane 视频播放器 + 检测栏 + 视频搜索卡（结果类型筛选下拉：全部/画面定位/物体定位 + 语义/人脸/图搜/车牌/文字 toggle + 搜索框固定 + 搜索结果时间范围自动暂停）+ `SingleAnalyzeDialog` 紧凑弹窗；搜索卡仅限当前视频检索（与全局搜索划清边界）；摘要卡标题随内容自动切换（视频摘要/文字识别），无 tab 按钮
  - **ImageLibrary**（素材库页）：左目标列表 + 右底库照片详情（裁剪/拖拽扩充/溯源）+ 新建目标弹窗 + `AddSubjectDrawer`（检测/图搜一键沉淀）
  - **GlobalSearch**（全局搜索）：左 34% 配置面板（文本/图像 Tab + 人/车/车牌/文本/事件 5 类型 chip 互斥选中，切换即清空文本框 + 各类型专属特征选中才出现（颜色常驻）+ 句式化 token + 人脸/通用图搜分轨）+ 右 66% 结果网格；选图来源统一走 `SubjectPhotoPicker`（素材库底图）
  - **TaskCenter**（任务中心）+ **SettingsPage**（系统设置，4 子 tab）
- TitleBar（frameless 暗色）+ SystemMonitor（底部系统监控）；侧栏 5 业务 + 2 设置入口

**桌面端窗口壳**：pywebview 主窗（frameless, shadow）；启动生命周期 = License 校验（封装态，软件管家激活助手退出码分流）→ 环境检查 → 模型检查（缺失进 MODEL_BOOT 下载面板）→ 起后端 → 开产品窗；SplashApi 窗口控制/系统监控/模型下载引导（start_model_download / get_model_download_status / abort_model_download）；后端 backend_launcher.py（字节码/源码双模式 + 看门狗）。壳 `load_url` 追加 `?v=<version>` 击穿 WebView2 持久化 HTTP 缓存（`private_mode=False`，跨版本复用会显示旧 UI，如素材库消失）。

## Desktop Installer (Windows)

```
构建链: build_backend_pyc.py（无源字节码包）→ build_exe.ps1 -Deploy（壳 exe + _internal）
        → 本地出包: build_installer.ps1 → ISCC zhiying.iss → Bin\视频快速智能检索平台 Ver <版本>.exe
        | 交付打包方: make_green.ps1 → 打包材料 zip（安装器 [Files] 完整输入集）→ 对方放入 zhiying.iss → ISCC 编译 → 签名
向导流: 选目录（默认 D:\Zhiying，磁盘预检 40GB）→ 档位页（8B/2B 在线下载 | 自备模型导入：路径校验 Qwen 子目录 + robocopy 前置复制，不依赖环境安装成败）
        → 代理页（预填 http://127.0.0.1:，只补端口）→ 安装 → 完成
安装期: 一体化安装——隐藏跑 setup_windows.ps1 全量（环境+内嵌 PG+25GB 模型安装段内下载；非交互参数 -Quiet
        -EmbeddingProfile/-Proxy/-ProgressLog/-DoneMarker/-OutputLog）
        进度 = setup 离散标记（models 段解析 download_models.py [progress] N% 插值）+ Inno 侧蠕动平滑（~2.5s +1 到阶段上限）
        等待循环在 UI 线程：每轮 ProcessMessages 泵消息防窗口假死；超时 = 30 分钟无任何新输出判卡死 + 12h 总兜底（模型在安装段内下载，不能按总时长掐）；powershell 启动失败立即报错
        快捷方式延后到环境安装成功后由代码创建（[Icons] 段早于环境安装执行，装一半失败不留无效图标）
首启兜底: 安装段模型下载失败/中断 → 首启 check_models 缺失 → State.MODEL_BOOT → model_bootstrap.py 后台跑 download_models.py
        （断点续传；档位写回 config.yaml 保证向量维度一致；代理经 data/proxy.txt 记忆）
License: 封装态启动即验（开发态跳过）——desktop/license_check.py 注册表定位拓界软件管家 →
        software_center.exe "1" "A5300" <license.dat>，退出码 0=试用通过 / 1=失败弹窗退出 /
        2=正式版客户端自校验 SuperDog 加密狗（SuperDog_x64.dll 与壳同级）；iss 安装器不校验
交付面: 客户机无明文后端源码（backend_pyc）；装完删安装耗材（requirements.txt / setup_windows.ps1 / desktop\db.py；
        download_models.py 例外保留供首启引导）
        卸载 [UninstallRun] stop_runtime.ps1 停壳+停 pg → [UninstallDelete] 清 .venv/vendor，保留 data/models（用户数据/自备模型）
```

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
| 工作台常驻挂载 + 意图门控 | Workbench/GlobalSearch 切页 hide 不卸载保播放/搜索状态；跨页意图带目标视频 id，等 vid 落到目标才执行/消费（防旧视频 id 过渡帧误搜/误重置） |
| 重解析建新版本 | completed/failed 参数改动走 POST /reanalyze（版本链复制文件信息）；PUT /params 仅摘要/索引开关增量——抽屉开关 PATCH /toggles 先行持久化，PUT 新旧比对必然一致 |
| 删除三层保证 | 路由显式清盘 → FK CASCADE → sweep 兜底；task_logs/pipeline_tasks 无 FK 由 delete_video 显式清，删视频连队列行一起清 |
| 图片素材纳入 sweep | subject_photos/case_assets 文件级引用集 + 600s mtime 保护（上传崩溃窗口可回收）；路径一律 StorageManager 绝对落库，历史相对行读取侧归一化 |
| 队列僵尸治理 | 重启恢复时视频已删的 queued 任务标 failed 不重入队；executor 缺视频抛错标 failed（不再假 completed）；终态队列行 90 天保留清理 |
| 安装器一体化安装 | 环境+内嵌 PG+25GB 模型全在安装段内完成（setup_windows.ps1 全量跑），装完即可用；超时按「无新输出」判定而非总时长（大文件下载期合法静默） |
| 首启模型兜底 | 安装段下载失败/中断不阻断交付——首启 check_models 缺失进 MODEL_BOOT 后台断点续传，档位写回 config.yaml 防维度错配 |
| 安装器单进度条 + 蠕动平滑 | 解压/环境安装复用同一进度条；pip 非终端无进度可解析，离散真实标记 + Inno 侧定时蠕动，条不再长时间死住 |
| 启动 License 校验 | 软件管家生态交付——封装态启动即验（激活助手退出码分流：试用通过/失败/正式版 SuperDog 加密狗），开发态跳过；校验在壳不在安装器（iss 只定 ProductCode A5300） |
| 安装耗材交付面清理 | requirements/setup 脚本/db 引导/平台清单装完即删，客户机只留运行必需；卸载清 .venv/vendor（安装产物），data/models 有意保留 |

## Current Status

核心链路全部可用（系统边界与实现见上文章节）；已知未完成：Chunk 编码（默认关）· OCR 导出/增强（预留）· Grounding(Florence-2 占位) · 素材库告警红点（前端空壳）。

> 变更历史查 git log。

## 版本发布

版本唯一来源 `core/version.py`；发版 `./bump`；后端+服务器前端改动必须发版；部署 `bash deploy.sh v<tag>`。
