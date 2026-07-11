# Cerno final_0.1

通用视频分析平台。目标硬件：8GB ~ 32GB 显存皆可。
核心功能：语义搜索、视频摘要、动态画面盘查、视频导出。

---

## 零、架构规范

### 抽象接口层

所有 AI 算法模块定义为抽象接口，`core/interfaces.py`：

| 接口 | 职责 | 输入→输出 |
|---|---|---|
| `BaseQC` | 视频质量检测 | 视频流 → {is_valid, estimated_duration, 黑屏/静音标记} |
| `BaseTranscriber` | 语音转录 | 音频流 → word[]（含时间戳） |
| `BaseSegmenter` | 镜头分割 | 帧序列 → Scene[] |
| `BaseDetector` | 物体检测 | 单帧 → Entity[]（label, bbox, time） |
| `BaseOCR` | 文字提取 | 单帧 → str |
| `BaseCaptioner` | 画面描述 | 帧 + 上下文 → 文本描述 |
| `BaseEmbedder` | 向量编码 | 文本/图像 → 固定维度向量 |
| `BaseSummarizer` | 摘要生成 | Scene[] + transcript → 结构化摘要 |
| `BaseGrounding` | 开放词汇目标定位 | 帧 + 查询文本 → BBox[] |

### 数据传递：VideoContext

```
VideoContext:
  video_id, file_path, duration
  scenes: List[Scene]
  transcript: str               # 全局转录全文（备用）
  summary: dict
  qc_result: dict                # 质检结果

Scene:
  scene_id, start_sec, end_sec
  keyframe: np.ndarray
  ocr_text: str                  # 关键帧上的文字
  aligned_transcript: str        # 切分到本场景的语音文本
  caption: str                   # 含上下文的深度描述
  embedding: list[float]
  entities: list[dict]           # 检测物 + 时间区间
  prev_caption: str              # 上一场景的描述（记忆传递用）
```

### 插件化：工厂模式

```python
pipeline_engine:
  qc           = load_plugin(config, "qc")
  segmenter    = load_plugin(config, "segmenter")
  transcriber  = load_plugin(config, "transcriber")
  detector     = load_plugin(config, "detector")
  ocr          = load_plugin(config, "ocr")
  captioner    = load_plugin(config, "captioner")
  embedder     = load_plugin(config, "embedder")
  summarizer   = load_plugin(config, "summarizer")
  grounding    = load_plugin(config, "grounding")   # 搜索时调用
```

**切换模型只需改 config.yaml，不改一行代码。**

---

## 一、Pipeline（五阶段认知工作流）

每一阶段依赖前一阶段的产出，各阶段内部模块可并行。

### Phase 1：前置质检与拆解

```
上传视频
  │
  ├── BaseQC
  │     ├── 检测黑屏/过曝/静音 → 标记异常段
  │     ├── 黑屏段跳过后续视觉处理
  │     └── 静音段跳过后续转录
  │
  ├── FFmpeg 抽取音频 → BaseTranscriber → word[]（字词级时间戳）
  │
  └── FFmpeg 内存抽帧 + BaseSegmenter → Scene 列表（含起止时间）
```

### Phase 2：独立模态感知（可并行）

```
对每个场景取代表帧后，三条线并行：

  ┌── BaseDetector → Scene.entities（label, bbox, 时间区间）
  │
  ├── BaseOCR → Scene.ocr_text（PPT文字、字幕、车牌号）
  │
  └── （转录已在 Phase 1 完成，等待对齐）
```

### Phase 3：模态交叉对齐

```
  ┌── 空间对齐：将 entities 和 ocr_text 挂载到对应 Scene
  │
  └── 时序对齐：根据字词级时间戳，
        把 BaseTranscriber 输出的 word[] 切分到对应场景
        → Scene.aligned_transcript
        
  此时每个 Scene 拥有完整信息：[画面 + 实体 + 文字 + 对应台词]
```

### Phase 4：带上下文的深度理解

```
遍历场景，引入记忆滑动窗口：

  for i, scene in enumerate(scenes):
    context = scenes[i-1].caption if i > 0 else ""
    
    prompt = f"前情：{context}\n画面文字：{scene.ocr_text}\n台词：{scene.aligned_transcript}\n请描述当前画面"
    
    scene.caption = BaseCaptioner(keyframe, prompt)
    scene.embedding = BaseEmbedder.encode_image(keyframe)
```

### Phase 5：全局升华

```
BaseSummarizer 输入：按时间排列的完整剧本
  [00:15] 画面：XX | 文字：XX | 台词：XX
  [00:30] 画面：XX | 文字：XX | 台词：XX
  ...

  输出：结构化摘要
    - one_liner
    - 场景列表（含时间、描述、关键信息）
    - 标签
    - 主要主题/实体
```

### 全流程一览

```
Phase 1                    Phase 2               Phase 3               Phase 4                  Phase 5
┌──────────┐          ┌──────────────┐     ┌──────────────┐     ┌──────────────┐          ┌──────────────┐
│ QC 质检   │          │ BaseDetector │     │ 空间+时序对齐  │     │ 记忆窗口     │          │ BaseSummarizer│
│ 音频抽取  │──→ 场景  │ BaseOCR      │──→  │ (实体/文字/   │──→  │ 上下文描述   │──→ 摘要  │              │
│ 镜头分割  │   列表   │ BaseSegmenter│     │  台词挂载)    │     │ 场景向量     │          │ 结构化输出   │
└──────────┘          └──────────────┘     └──────────────┘     └──────────────┘          └──────────────┘
                         ↑ 可并行
```

### 存储

| 表 | 行数/视频 | 用途 |
|---|---|---|
| `scenes` | ~30-100 | 场景时间范围、向量、OCR、转录片段、实体、含上下文描述 |
| `transcripts` | 1 | 全视频转录全文（字词级时间戳） |
| `videos` | 1 | 元数据、质检结果、摘要 |

全程不写临时图片文件。帧通过 decord/FFmpeg pipe 读入内存。
唯一落盘数据：原始视频 + 数据库记录。

### 数据库规范

| 字段 | 类型 | 说明 |
|---|---|---|
| `scenes.entities` | **JSONB** | 复杂字典结构，SQLAlchemy 中定义为 JSONB |
| `scenes.embedding` | **vector(768)** | pgvector 向量字段，建 **HNSW 索引**（几万场景下毫秒级检索） |
| `scenes.caption / ocr_text / aligned_transcript` | **tsvector 全文索引** | GIN 索引用于全文检索 |

---

## 二、语义搜索（两阶段）

### 第一阶段：粗排召回

```
用户查询（文本或图片）
  │
  ├── BaseEmbedder.encode_text / encode_image → 向量
  │
  ├── 向量路：pgvector <=> scenes.embedding
  ├── 文本路：全文检索 scenes.caption + scenes.ocr_text + scenes.aligned_transcript
  ├── 标签路：精确匹配 scenes.entities.label
  │
  └── RRF 融合（k=60，空路自动归零）
```

### 第二阶段：动态定位

```
用户暂停视频或点击搜索结果跳转
  │
  GET /api/v1/videos/{id}/grounding?frame=N&query={user_query}
  │
  └── BaseGrounding → 实时推理 → {bbox, label, confidence}[]

前端 Canvas 绘制框 + 标签
```

### 搜索返回结构

```json
{
  "scene_id": 3,
  "scene_range": {"start": 120, "end": 160},
  "precise_range": {"start": 130, "end": 138},
  "precision_source": "entities / grounding",
  "caption": "画面中一只猫从桌上跳下，碰翻了装有水的玻璃杯，水洒在桌面上",
  "ocr_text": "Q3营收报告",
  "transcript_snippet": "我们看到猫把水杯打翻了...",
  "entities": [{"label": "cat", "bbox": [400,200,600,350]}],
  "similarity": 0.74,
  "thumbnail": "/thumbnails/xxx/scene_03.jpg"
}
```

**OCR 和含上下文的 caption 让"猫打碎水杯"、"Q3财报营收"这类查询能被精确命中。**

---

## 三、搜索结果交互

### 搜索卡片

```
┌──────────────────────────────────────────────────────┐
│  场景 3 · 00:02:00 - 00:02:40            相似度 0.74 │
│                                                      │
│  一只猫跳下桌子碰翻了玻璃杯，水洒在桌面上               │
│  Q3营收报告（OCR）  "...猫把水杯打翻了..."（转录）      │
│                                                      │
│  [▶ 跳转]  [✂ 导出]  [📋 加入列表]  [📏 调整时间]     │
└──────────────────────────────────────────────────────┘
```

### 视频播放 + 画框

- 播放时：纯净画面
- 暂停时：请求 Grounding → 实时画框
- 恢复播放：清除画布

### 批量导出

```
📋 待导出列表
  □ 场景 3 · 猫打碎水杯 · 00:02:10 - 00:02:18
  □ 场景 7 · Q3财报讨论 · 00:05:30 - 00:06:15
──────────────────────────────
  [📥 全部导出]  [🔗 合并为一个视频]
```

---

## 四、配置层

### 上传弹窗

```
预设模式：
  ○ 快速     ● 标准     ○ 全面     ○ 自定义

  快速：仅转录 + 检测，跳过 VLM、OCR、Grounding
  标准：全链路
  全面：全链路 + 增强描述 + 深度摘要

内容类型（影响参数）：
  ○ 通用    ● 会议/演讲   ○ 户外/监控   ○ 产品展示

语言覆盖：[自动检测 / 中文 / 英文]

### Prompt 模板管理

所有提示词集中管理，不硬编码在 Python 代码中。位置：`config/prompts.yaml`

```yaml
caption_default: "请详细描述这张画面，包括人物、物体、场景、动作。"
caption_with_context: "前情：{prev_caption}\n画面文字：{ocr_text}\n台词：{transcript}\n请结合以上信息描述当前画面。"
summary_system: "你是一个视频分析助手。根据以下按时间排序的剧本生成结构化摘要..."
summary_user: "{script}"
```

新增 prompt 或微调话术只需改 yaml，不改代码。
```

### 三条感知线路独立开关

上传弹窗内以三栏卡片呈现，每栏独立勾选：

```
┌──────────────────┬──────────────────┬──────────────────┐
│  🔊 音频感知     │  👁️ 视觉感知     │  📝 文本感知      │
│  ☑ 语音转录      │  ☑ 物体检测      │  ☑ OCR 文字提取   │
│  faster-whisper  │  YOLO / 其他     │  PP-OCR / 其他   │
│  影响：可搜语音   │  影响：可搜物体   │  影响：可搜屏幕字  │
│  时长：+30-60s   │  时长：+20s      │  时长：+10s      │
│  费用：$0        │  费用：$0        │  费用：$0        │
└──────────────────┴──────────────────┴──────────────────┘
```

三条线路**无依赖关系**，可任意开/关。
未勾选的线路在 Phase 2 中直接跳过，pipeline 对应步骤不执行。

### 模块依赖

| 模块 | 依赖 | 说明 |
|---|---|---|
| 语音转录 | 无 | 🔊 音频感知线，独立 |
| 物体检测 | 无 | 👁️ 视觉感知线，独立 |
| OCR | 无 | 📝 文本感知线，独立 |
| 属性识别 | 依赖物体检测 | 检测关则属性强制关 |
| 场景描述 | 无 | 受三条线输出增强（OCR文本/转录/实体作为 prompt 上下文） |
| 全文摘要 | 至少一个语义输入 | 否则自动拦截 |
| Grounding | 无 | 可选，无则第二阶段跳过 |
| QC | 无 | 前置，不影响后续模块开关 |


## 五、配置与兼容性

### 同一套代码，任意配置组合

接口不变。通过 config.yaml 选择当前硬件适用的模型组合。

**低配示例（4060 8GB，跳过 OCR 和复杂 VLM）：**

```yaml
qc:
  backend: basic-check               # 仅检查黑屏静音

transcription:
  backend: faster-whisper
  model: base
  device: cpu

detection:
  backend: yolo
  model: yolov8n

caption:
  backend: qwen2.5-vl-2b-int4        # ~3GB

embedding:
  backend: qwen3-vl-embedding-2b      # ~3GB

summary:
  backend: qwen2.5-vl-2b-int4         # 复用 captioner

ocr:
  backend: null                        # 跳过

grounding:
  backend: null                        # 第二阶段不启用
```

**高配示例（5090 32GB，全链路开）：**

```yaml
qc:
  backend: basic-check

transcription:
  backend: faster-whisper
  model: large-v3
  device: cpu

detection:
  backend: yolo
  model: yolov8n

ocr:
  backend: paddle-ocr                  # PPT、字幕文字提取
  device: cpu

caption:
  backend: qwen2.5-vl-7b-int4         # ~6GB
  with_context: true                    # 开启记忆滑动窗口

embedding:
  backend: qwen3-vl-embedding-8b       # ~8GB

summary:
  backend: qwen2.5-vl-7b-int4

grounding:
  backend: florence-2                  # ~4GB
```

**模型替换示例：**

```yaml
caption:
  backend: llava-video-7b               # 换成另一套 VLM
  # 或
  backend: api-qwen-vl                   # 切回云端
  api_key: sk-...
```

**原则**：接口锁定，模型名是配置值。增删改模块只需操作 config.yaml + plugins/ 目录。

---

## 六、API 表面

```
视频管理：
  POST   /api/v1/videos/upload                    ← 立刻返回 {video_id, status:"pending"}，后台异步处理
  GET    /api/v1/videos/
  GET    /api/v1/videos/{id}
  GET    /api/v1/videos/{id}/status               ← 轮询处理进度（前端用）
  DELETE /api/v1/videos/{id}

搜索与浏览：
  POST   /api/v1/search                    ← query 与 image 二选一
  GET    /api/v1/videos/{id}/scenes
  GET    /api/v1/videos/{id}/transcript

交互：
  GET    /api/v1/videos/{id}/grounding?frame=N&query=   ← 第二阶段画框

导出：
  GET    /api/v1/videos/{id}/export/clip?start=&end=
  GET    /api/v1/videos/{id}/export/json
  GET    /api/v1/videos/{id}/export/markdown
  POST   /api/v1/export/merge

维护：
  POST   /api/v1/videos/{id}/reindex
  GET    /health
```

---

## 七、开发优先级

```
P0（架构 + 核心链路 MVP）
  ├── core/interfaces.py + core/models.py（含 Scene 完整字段）
  ├── PipelineEngine + config.yaml 加载
  ├── QC 基础质检（黑屏/静音检测）
  ├── 实现基础 Plugin 套件（Whisper + YOLO + TransNetV2 + Embedding）
  ├── 跑通简化版 pipeline（Phase 1→2→4→5，跳过 OCR 和记忆）
  ├── 音频-场景时序对齐（Phase 3 基础版）
  ├── 存 scenes 表
  ├── 第一阶段搜索 + RRF
  ├── 前端搜索卡片 + 跳转 + 导出 + 暂停画框
  └── 配置层预设/内容类型

P1（增强认知链路）
  ├── BaseOCR 插件（PP-OCR / 其他）
  ├── 记忆滑动窗口（caption 间上下文传递）
  ├── OCR + 转录 + 实体 → caption 增强 prompt
  ├── 以图搜图
  ├── Grounding 第二阶段插件
  ├── 多视频搜索
  └── 批量导出合并

P2（优化）
  ├── 插件生态扩展
  └── 性能调优
```

---

## 八、部署方案（面向 10.0.0.176）

### 环境总览

| 约束 | 情况 | 方案 |
|---|---|---|
| GPU | 2× L20 46GB，各剩 ~24G / ~28G | 小模型挂空闲卡，无需独占 |
| 内存 | 503GB，充裕 | 不限 |
| 磁盘 | `/` 69GB 满，`/home` 3.3TB 空 | **全部放 `/home/cerno/`** |
| 网络 | HF 不通，魔塔可达 | 模型从 ModelScope 下载 |
| sudo | 需密码 | 非必要时不用 root |
| docker | 需 sudo | 开发阶段用 conda，部署阶段找 root 协助 |
| 已有 vLLM | port 8010 Qwen2.5-7B-Instruct（GPU 0） | 可用于文本摘要，需先确认 |

### 版本对齐

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | **3.12** | 两边 conda 统一 |
| PyTorch | **2.5.1+cu124** | 本地 4060 和服务 L20 均为 Ada 架构，通用 |
| CUDA toolkit | 12.4（PyTorch 自带） | 本地驱动 596.49 ≥ 535 ✅，服务驱动 570.86 ≥ 535 ✅ |
| transformers | **≥ 4.57.0** | Qwen3-VL-Embedding 最低要求 |
| faster-whisper | 最新 pip | CPU 运行，无冲突 |
| ultralytics | 最新 pip | 版本不敏感 |
| PostgreSQL | **17 + pgvector 0.8** | Docker 镜像固定 |
| modelscope | 最新 pip | 模型下载源 |

### 目录结构

```
/home/cerno/
├── project/              # 项目代码
│   ├── core/
│   ├── plugins/
│   ├── config/
│   ├── requirements.txt
│   └── docker-compose.yaml    # 部署阶段使用
├── env/                  # conda 虚拟环境（独立，不污染系统）
├── models/               # 模型权重（MODELSCOPE_CACHE 指向这里）
├── data/                 # 运行时数据（视频、数据库持久化）
│   ├── videos/
│   ├── frames/
│   └── db/
└── logs/                 # 日志
```

### 虚拟环境

```bash
# conda 装在自己目录下，不依赖系统 /opt/miniconda3/
cd /home/cerno
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p /home/cerno/env/conda
rm Miniconda3-latest-Linux-x86_64.sh

# 创建项目环境
/home/cerno/env/conda/bin/conda create -n cerno python=3.12 -y
source /home/cerno/env/conda/bin/activate cerno
pip install -r /home/cerno/project/requirements.txt
```

### 模型来源

所有模型从 ModelScope 下载，cache 指向项目目录：

```bash
export MODELSCOPE_CACHE=/home/cerno/models

# 下载模型（各约 4GB）
pip install modelscope
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen3-VL-Embedding-2B')"
python -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('Qwen/Qwen2.5-VL-2B-Instruct')"
```

预置配置文件中已指向 ModelScope 源。模型权重只下载一次，Docker 容器通过卷挂载读取，不重复下载。

### GPU 分配策略

```
GPU 0（空闲 ~24GB）：
  └── 已有 vLLM Qwen2.5-7B-Instruct（port 8010）— 不动它，可复用做摘要

GPU 1（空闲 ~28GB）：
  └── Qwen3-VL-Embedding-2B（~3GB，常驻）
  └── Qwen2.5-VL-2B-Instruct（~4GB，caption 时短暂加载）
  └── YOLOv8n（~1GB，检测阶段短暂加载）
  峰值约 8GB，GPU 1 余量充足
```

通过 `CUDA_VISIBLE_DEVICES=1` 将项目进程限定在 GPU 1，不影响 GPU 0 上的 vLLM 服务。

### 复用已有资源

| 资源 | 位置 | 复用方式 |
|---|---|---|
| Qwen2.5-7B-Instruct vLLM | port 8010，OpenAI 兼容接口 | BaseSummarizer 用 `openai` 库直接调，需先确认 |
| bge-reranker-v2-m3 | `/home/model-weights/` | 搜索重排插件可复用 |
| conda 环境命名 | 团队习惯使用 `clip` `ocr` 等命名 | 新环境命名为 `cerno` 避免冲突 |

### 开发与部署

```
开发阶段：
  conda 环境 + 本地运行 + GPU 1
  代码放 /home/cerno/project/

部署阶段：
  root 协助构建 docker 镜像
  docker-compose 编排（app + db）
  模型权重通过卷挂载，不打包进镜像
```
