# Cerno 核心代码骨架与目录树设计

> 版本：v0.1 | 设计模式：Factory + Strategy | 框架：FastAPI + SQLAlchemy async

---

## 一、项目目录树

```
cerno/
├── main.py                          # FastAPI 入口, lifespan 事件
├── pyproject.toml                   # 项目元信息与依赖
├── requirements.txt                 # pip 依赖清单
├── docker-compose.yaml              # 部署编排 (app + postgres)
├── Dockerfile                       # 应用镜像
│
├── config/
│   ├── config.yaml                  # ★ 核心配置: 模型选择、路径、端口
│   ├── config_schema.py             # config.yaml 的 Pydantic 校验模型
│   └── prompts.yaml                 # ★ 所有 VLM/LLM 提示词模板
│
├── core/
│   ├── __init__.py
│   ├── interfaces.py                # ★ 抽象接口层 (9 个 Base 类)
│   ├── models.py                    # ★ SQLAlchemy ORM 模型 (Video, Scene, Transcript)
│   ├── db.py                        # 数据库引擎 & session 工厂
│   ├── schemas.py                   # 数据传递对象 (VideoContext, Scene 等 dataclass)
│   ├── config_loader.py             # YAML 配置加载 & 校验
│   ├── prompt_loader.py             # ★ Prompt 模板加载与渲染
│   ├── exceptions.py                # 自定义异常
│   └── status_tracker.py            # 处理状态更新器
│
├── pipeline/
│   ├── __init__.py
│   ├── engine.py                    # ★ PipelineEngine: 五阶段编排
│   ├── phase1_qc.py                 # Phase 1: 质检 + 音频抽取 + 镜头分割
│   ├── phase2_perception.py         # Phase 2: 检测 + OCR (并行调度)
│   ├── phase3_alignment.py          # Phase 3: 模态交叉对齐
│   ├── phase4_caption.py            # Phase 4: 记忆窗口深度描述
│   ├── phase5_summary.py            # Phase 5: 全局升华摘要
│   ├── search_engine.py             # 第一阶段搜索: 多路召回 + RRF 融合
│   └── grounding.py                 # 第二阶段: 动态目标定位
│
├── plugins/
│   ├── __init__.py
│   ├── factory.py                   # ★ PluginFactory: 根据 config 动态加载
│   ├── qc/
│   │   ├── __init__.py
│   │   └── basic_qc.py              # 黑屏/静音检测
│   ├── transcriber/
│   │   ├── __init__.py
│   │   └── faster_whisper.py
│   ├── segmenter/
│   │   ├── __init__.py
│   │   └── transnet_v2.py
│   ├── detector/
│   │   ├── __init__.py
│   │   └── yolo_detector.py
│   ├── ocr/
│   │   ├── __init__.py
│   │   └── paddle_ocr.py
│   ├── captioner/
│   │   ├── __init__.py
│   │   └── qwen_vl_captioner.py     # 本地 VLM 推理
│   ├── embedder/
│   │   ├── __init__.py
│   │   └── qwen_vl_embedder.py
│   ├── summarizer/
│   │   ├── __init__.py
│   │   └── vllm_summarizer.py       # ★ vLLM (port 8010) OpenAI 兼容 API
│   └── grounding/
│       ├── __init__.py
│       └── florence2_grounding.py
│
├── api/
│   ├── __init__.py
│   ├── router.py                    # 路由注册
│   ├── schemas.py                   # ★ Pydantic 请求/响应模型
│   ├── deps.py                      # FastAPI 依赖注入 (DB session, config)
│   ├── video_routes.py              # 视频 CRUD + 上传
│   ├── search_routes.py             # 搜索接口
│   ├── export_routes.py             # 导出接口
│   └── maintenance_routes.py        # 健康检查 / reindex
│
├── services/
│   ├── __init__.py
│   ├── video_service.py             # 视频业务逻辑 (CRUD + pipeline 触发)
│   ├── search_service.py            # 搜索编排 (多路召回 + RRF + 排序)
│   ├── export_service.py            # FFmpeg 导出 / 合并
│   └── grounding_service.py         # Grounding 请求处理
│
├── utils/
│   ├── __init__.py
│   ├── ffmpeg.py                    # FFmpeg 封装 (抽音频/抽帧/切片)
│   ├── video_io.py                  # decord / OpenCV 内存帧读取
│   └── time_utils.py                # 时间格式化工具
│
├── migrations/
│   └── ...                          # Alembic migration 文件
│
├── tests/
│   ├── conftest.py
│   ├── test_interfaces.py
│   ├── test_pipeline.py
│   ├── test_api.py
│   └── test_plugins/
│       └── ...
│
└── data/                            # 运行时数据 (gitignore)
    ├── videos/
    ├── frames/
    └── db/
```

---

## 二、核心配置文件

### 2.1 config/prompts.yaml

```yaml
# ── Captioner 提示词 ────────────────────────────────

caption_default: |
  请用简洁的中文描述这张视频关键帧的画面内容。
  包括: 人物、物体、场景环境、正在发生的动作。
  不要添加主观评价。

caption_with_context: |
  前情提要: {prev_caption}
  当前画面中可见的文字: {ocr_text}
  当前场景的台词: {transcript}

  请结合以上信息，用2-3句话描述当前画面发生了什么。
  注意衔接前情，形成连贯的叙事。

# ── Summarizer 提示词 ──────────────────────────────

summary_system: |
  你是一个专业的视频内容分析助手。
  你的任务是根据以下按时间排序的"视频剧本"生成结构化摘要。
  剧本中每一行包含: 时间戳、画面描述、画面文字、对应台词。
  请输出 JSON 格式，确保字段齐全。

summary_user: |
  {script}

  ---
  请按照以下 JSON 格式输出摘要 (不要输出其他内容):

  {{
    "one_liner": "一句话概括整个视频",
    "scenes_summary": [
      {{
        "scene_index": 0,
        "start_sec": 0.0,
        "end_sec": 45.5,
        "description": "该场景内容描述",
        "keywords": ["关键词1", "关键词2"]
      }}
    ],
    "tags": ["标签1", "标签2"],
    "main_topics": ["主题1", "主题2"],
    "main_entities": ["实体1", "实体2"]
  }}

# ── Grounding 提示词 ───────────────────────────────

grounding_caption: |
  在画面中定位: {query}
  返回所有匹配物体的边界框。
```

### 2.2 config/config.yaml

```yaml
# ── 服务配置 ──────────────────────────────────────
server:
  host: "0.0.0.0"
  port: 8000
  workers: 1

# ── 数据库 ────────────────────────────────────────
database:
  uri: "postgresql+asyncpg://cerno:cerno@localhost:5432/cerno"
  pool_size: 20
  max_overflow: 10

# ── 路径 ──────────────────────────────────────────
paths:
  video_dir: "/home/cerno/data/videos"
  frame_dir: "/home/cerno/data/frames"
  model_cache: "/home/cerno/models"

# ── 插件配置 ──────────────────────────────────────
plugins:
  qc:
    backend: basic-check
    params:
      black_threshold: 10        # 黑屏判定阈值(像素值)
      black_min_duration: 0.5    # 最短黑屏时长(秒)
      silent_threshold_db: -40   # 静音判定阈值(dB)

  transcriber:
    backend: faster-whisper
    model: base                   # base / small / medium / large-v3
    device: cpu
    compute_type: int8

  segmenter:
    backend: transnet-v2
    device: cuda

  detector:
    backend: yolo
    model: yolov8n
    device: cuda
    confidence: 0.35
    iou: 0.45

  ocr:
    backend: null                 # 低配跳过 OCR
    # backend: paddle-ocr
    # device: cpu

  captioner:
    backend: qwen2.5-vl-2b-int4
    device: cuda
    with_context: false           # 低配关闭记忆窗口
    max_new_tokens: 256

  embedder:
    backend: qwen3-vl-embedding-2b
    device: cuda

  summarizer:
    backend: vllm-api             # vLLM OpenAI 兼容接口
    base_url: "http://10.0.0.176:8010/v1"
    model_name: "Qwen2.5-7B-Instruct"
    max_tokens: 2048
    temperature: 0.1

  grounding:
    backend: null                 # 低配跳过 Grounding
    # backend: florence-2
    # device: cuda

# ── Pipeline 参数 ─────────────────────────────────
pipeline:
  sample_fps: 1.0                 # 抽帧频率 (帧/秒)
  scene_min_duration: 1.0         # 最短场景时长(秒)
```

---

## 三、core/interfaces.py — 抽象接口层

> **插件实现者注意**: 以下所有接口均为 `async def`。在实现具体插件时，所有同步耗时调用（模型推理、`subprocess.run` 等）**必须**通过 `asyncio.to_thread()` 或 `asyncio.create_subprocess_exec()` 包装，严禁直接阻塞事件循环。详见 [§3.1 插件实现强制规范](#31-插件实现强制规范异步与同步边界)。

```python
"""
core/interfaces.py
═══════════════════════════════════════════════════════════
所有 AI 算法模块的抽象接口。
每个接口 = 一个策略 (Strategy Pattern)。
具体实现放在 plugins/ 目录下，通过 factory.py 注入。

⚠️ 实现约定: 接口为 async, 插件内部同步耗时调用必须用
   asyncio.to_thread() 或 run_in_threadpool() 包裹。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import numpy as np
from typing import Protocol

# ═══════════════════════════════════════════════════════
# VideoContext — 数据传递对象
# ═══════════════════════════════════════════════════════

@dataclass
class Scene:
    """单个场景的完整信息载体。在 Pipeline 各阶段逐步填充。"""
    scene_id: int
    scene_index: int
    start_sec: float
    end_sec: float
    keyframe: np.ndarray | None = None          # 代表帧 (H, W, C) uint8
    keyframe_path: str | None = None
    ocr_text: str | None = None
    aligned_transcript: str | None = None
    caption: str | None = None
    prev_caption: str | None = None
    embedding: list[float] | None = None        # Vector(768)
    entities: list[dict] = field(default_factory=list)


@dataclass
class VideoContext:
    """Pipeline 全流程数据载体。各阶段读写此对象传递信息。"""
    video_id: str
    file_path: str
    duration: float | None = None
    scenes: list[Scene] = field(default_factory=list)
    transcript_full: str | None = None
    transcript_words: list[dict] = field(default_factory=list)
    qc_result: dict = field(default_factory=dict)
    summary: dict | None = None

    # 处理元信息
    progress_callback: "callable | None" = None  # async def cb(progress: float, phase: str, desc: str)


# ═══════════════════════════════════════════════════════
# 抽象接口
# ═══════════════════════════════════════════════════════

class BaseQC(ABC):
    """视频质量检测"""
    @abstractmethod
    async def check(self, ctx: VideoContext) -> dict:
        """
        输入: VideoContext (含 file_path)
        输出: {
            "is_valid": bool,
            "estimated_duration": float,
            "black_segments": [{"start_sec":, "end_sec":}],
            "silent_segments": [...],
            "overexposed_segments": [...]
        }
        """
        ...


class BaseTranscriber(ABC):
    """语音转录"""
    @abstractmethod
    async def transcribe(self, audio_path: str, language: str | None = None) -> dict:
        """
        输入: 音频文件路径
        输出: {
            "full_text": str,
            "language": str,
            "duration": float,
            "words": [{"word": str, "start": float, "end": float, "confidence": float}]
        }
        """
        ...


class BaseSegmenter(ABC):
    """镜头分割"""
    @abstractmethod
    async def segment(self, video_path: str, sample_fps: float = 1.0) -> list[dict]:
        """
        输入: 视频路径 + 抽帧频率
        输出: [
            {"scene_index": 0, "start_sec": 0.0, "end_sec": 5.2, "keyframe": np.ndarray},
            ...
        ]
        keyframe 可为 None (后续由 engine 统一抽)
        """
        ...


class BaseDetector(ABC):
    """物体检测"""
    @abstractmethod
    async def detect(self, frame: np.ndarray, start_sec: float, end_sec: float) -> list[dict]:
        """
        输入: 单帧图像 + 场景时间区间
        输出: [
            {"label": "cat", "bbox": [x1,y1,x2,y2], "confidence": 0.92,
             "start_sec": 130.0, "end_sec": 138.0, "track_id": 1}
        ]
        """
        ...


class BaseOCR(ABC):
    """文字提取"""
    @abstractmethod
    async def extract(self, frame: np.ndarray) -> str:
        """单帧 → 提取文字"""
        ...


class BaseCaptioner(ABC):
    """画面描述 (VLM)"""
    @abstractmethod
    async def caption(
        self,
        keyframe: np.ndarray,
        prompt: str,                    # 由 prompt_loader 渲染好的完整 prompt
        max_new_tokens: int = 256
    ) -> str:
        """帧 + 文本 prompt → 自然语言描述"""
        ...


class BaseEmbedder(ABC):
    """向量编码"""
    @abstractmethod
    async def encode_image(self, image: np.ndarray) -> list[float]:
        """图像 → Vector(768)"""
        ...

    @abstractmethod
    async def encode_text(self, text: str) -> list[float]:
        """文本 → Vector(768)"""
        ...


class BaseSummarizer(ABC):
    """摘要生成"""
    @abstractmethod
    async def summarize(self, script: str, system_prompt: str, user_prompt: str) -> dict:
        """
        输入: 按时间排列的完整剧本 + system/user prompt
        输出: {
            "one_liner": str,
            "scenes_summary": [{"scene_index":, "start_sec":, "end_sec":, "description":, "keywords": []}],
            "tags": [],
            "main_topics": [],
            "main_entities": []
        }
        """
        ...


class BaseGrounding(ABC):
    """开放词汇目标定位"""
    @abstractmethod
    async def locate(self, frame: np.ndarray, query: str) -> list[dict]:
        """
        输入: 单帧 + 查询文本
        输出: [{"label": str, "bbox": [x1,y1,x2,y2], "confidence": float}]
        """
        ...
```

---

### 3.1 插件实现强制规范：异步与同步边界

> **这是本项目的唯一硬性约定，违反将导致线上事故。**

**问题**: `core/interfaces.py` 中所有接口都是 `async def`，但本地模型推理（YOLOv8 `model.predict()`、PaddleOCR `ocr.ocr()`、faster-whisper `model.transcribe()` 等）是同步 CPU/GPU 密集型计算。如果在 FastAPI 主事件循环中直接调用同步推理，会阻塞整个 asyncio 事件循环，导致所有 API 请求（包括 `/status` 轮询）全部超时。

**规则**: 所有插件的同步耗时调用，**必须**通过 `asyncio.to_thread()` 或 `run_in_threadpool()` 扔进线程池执行。

**标准写法 (以 YOLO 检测器为例):**

```python
"""
plugins/detector/yolo_detector.py
═══════════════════════════════════════════════════════════
YOLO 物体检测器 — 演示正确的 async/sync 边界处理。

关键约定:
  - model.predict() 是同步耗时调用, 绝不能直接在 async 上下文中调用
  - 必须使用 asyncio.to_thread() 将同步代码发到线程池
  - 输入/输出转换 (numpy ↔ dict) 可以在 async 上下文中进行(轻量操作)
"""

import asyncio
import numpy as np
from ultralytics import YOLO
from core.interfaces import BaseDetector


class YoloDetector(BaseDetector):

    def __init__(self, model: str = "yolov8n", device: str = "cuda",
                 confidence: float = 0.35, iou: float = 0.45, **kwargs):
        # 模型加载在 __init__ 中完成 (同步, 发生在 import 阶段, 不阻塞事件循环)
        self.model = YOLO(f"{model}.pt")
        self.device = device
        self.confidence = confidence
        self.iou = iou

    async def detect(self, frame: np.ndarray, start_sec: float, end_sec: float) -> list[dict]:
        """
        async 接口 — 内部用 asyncio.to_thread() 包裹同步推理。
        """
        # ✅ 正确: 将同步的 model.predict() 扔进线程池, 不阻塞事件循环
        results = await asyncio.to_thread(
            self._sync_predict, frame
        )
        # 输出转换是轻量 CPU 操作, 可以直接在 async 上下文中做
        return self._parse_results(results, start_sec, end_sec)

    def _sync_predict(self, frame: np.ndarray):
        """同步推理 — 在线程池中执行, 可以放心阻塞。"""
        return self.model(
            frame,
            conf=self.confidence,
            iou=self.iou,
            device=self.device,
            verbose=False,
        )

    def _parse_results(self, results, start_sec: float, end_sec: float) -> list[dict]:
        entities = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                entities.append({
                    "label": r.names[int(box.cls[0])],
                    "bbox": [x1, y1, x2, y2],
                    "confidence": float(box.conf[0]),
                    "start_sec": start_sec,
                    "end_sec": end_sec,
                })
        return entities
```

**反例 (禁止):**

```python
# ❌ 错误: 在 async 方法中直接调用同步推理 — 会阻塞整个事件循环!
async def detect(self, frame, start_sec, end_sec):
    results = self.model(frame, conf=0.35, device="cuda")  # ← 卡死!
    return self._parse_results(results, start_sec, end_sec)
```

**需要遵守此规范的插件:**

| 插件 | 同步阻塞调用 | 规避方式 |
|---|---|---|
| `YoloDetector` | `model.predict()` | `asyncio.to_thread()` |
| `PaddleOCRExtractor` | `ocr.ocr()` | `asyncio.to_thread()` |
| `FasterWhisperTranscriber` | `model.transcribe()` | `asyncio.to_thread()` |
| `TransNetV2Segmenter` | `model.predict_frames()` | `asyncio.to_thread()` |
| `QwenVLCaptioner` | `model.generate()` | `asyncio.to_thread()` |
| `QwenVLEmbedder` | `model.encode()` | `asyncio.to_thread()` |
| `Florence2Grounding` | `model.generate()` | `asyncio.to_thread()` |
| `BasicQC` (FFmpeg) | `subprocess.run()` | `asyncio.create_subprocess_exec()` |

> **注意**: `VLLMSummarizer` 和 `BasicQC` 是仅有的两个例外 — vLLM 走 HTTP (AsyncOpenAI 自带异步)，FFmpeg 用 `asyncio.create_subprocess_exec()`，不阻塞。

---

## 四、core/prompt_loader.py — Prompt 管理

```python
"""
core/prompt_loader.py
═══════════════════════════════════════════════════════════
所有 VLM/LLM 提示词从 YAML 加载，不在业务代码中硬编码。
"""

import yaml
from pathlib import Path
from functools import lru_cache

PROMPT_FILE = Path(__file__).parent.parent / "config" / "prompts.yaml"


class PromptLoader:
    """提示词模板加载器。应用启动时加载一次，全局单例。"""

    def __init__(self, prompt_path: Path = PROMPT_FILE):
        with open(prompt_path, "r", encoding="utf-8") as f:
            self._templates: dict[str, str] = yaml.safe_load(f)

    def get(self, name: str, **kwargs) -> str:
        """获取并渲染模板。"""
        template = self._templates.get(name)
        if template is None:
            raise KeyError(f"Prompt template '{name}' not found in prompts.yaml")
        return template.format(**kwargs) if kwargs else template

    def get_raw(self, name: str) -> str:
        """获取原始模板 (不做 format)。"""
        return self._templates[name]


# 全局单例
@lru_cache(maxsize=1)
def get_prompt_loader() -> PromptLoader:
    return PromptLoader()
```

**业务代码使用示例:**

```python
# 在 Phase 4 caption 阶段:
pl = get_prompt_loader()

# 带上下文的描述 prompt
prompt = pl.get("caption_with_context",
    prev_caption=scenes[i-1].caption or "无",
    ocr_text=scene.ocr_text or "无",
    transcript=scene.aligned_transcript or "无"
)
scene.caption = await captioner.caption(scene.keyframe, prompt)

# 不带上下文的默认 prompt
prompt = pl.get("caption_default")
```

---

## 五、plugins/factory.py — 插件工厂

```python
"""
plugins/factory.py
═══════════════════════════════════════════════════════════
插件工厂: 根据 config.yaml 动态加载策略实现。
切换模型只需改 config.yaml，不改一行业务代码。

约定:
  - 每个插件的入口模块为 plugins/{category}/{backend}.py
  - 模块内必须暴露一个与接口同名的实现类
  - 如: plugins/transcriber/faster_whisper.py → class BaseTranscriber(ABC)
"""

import importlib
import logging

logger = logging.getLogger(__name__)

# 接口 → 插件目录 映射
CATEGORY_MAP = {
    "qc":           "plugins.qc",
    "transcriber":  "plugins.transcriber",
    "segmenter":    "plugins.segmenter",
    "detector":     "plugins.detector",
    "ocr":          "plugins.ocr",
    "captioner":    "plugins.captioner",
    "embedder":     "plugins.embedder",
    "summarizer":   "plugins.summarizer",
    "grounding":    "plugins.grounding",
}

# 接口 → 实现类名 映射
IMPL_CLASS_MAP = {
    "qc":           "BasicQC",
    "transcriber":  "FasterWhisperTranscriber",
    "segmenter":    "TransNetV2Segmenter",
    "detector":     "YoloDetector",
    "ocr":          "PaddleOCRExtractor",
    "captioner":    "QwenVLCaptioner",
    "embedder":     "QwenVLEmbedder",
    "summarizer":   "VLLMSummarizer",
    "grounding":    "Florence2Grounding",
}


async def load_plugin(config: dict, category: str):
    """
    根据配置动态加载插件。

    Args:
        config: 完整配置字典 (config.yaml 加载后)
        category: 插件类别, 如 "transcriber" / "detector" / ...

    Returns:
        插件实例, 或 None (如果 backend 为 null 或 "")
    """
    plugin_cfg = config.get("plugins", {}).get(category, {})
    backend = plugin_cfg.get("backend")

    # ----- backend 为空 → 跳过 -----
    if not backend:
        logger.info(f"[Factory] {category}: backend is null → skipped")
        return None

    # ----- 构建模块路径 -----
    if category not in CATEGORY_MAP:
        raise ValueError(f"Unknown plugin category: {category}")

    module_path = f"{CATEGORY_MAP[category]}.{backend}"
    class_name = IMPL_CLASS_MAP.get(category)

    if class_name is None:
        raise ValueError(f"No implementation class mapped for: {category}")

    # ----- 动态导入 -----
    try:
        module = importlib.import_module(module_path)
        impl_class = getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise ImportError(
            f"Failed to load plugin '{category}' from '{module_path}.{class_name}': {e}"
        )

    # ----- 实例化 (传入插件专属 params) -----
    params = plugin_cfg.get("params", {})
    instance = impl_class(**params)
    logger.info(f"[Factory] {category}: {module_path}.{class_name} loaded")
    return instance
```

**使用示例 (PipelineEngine 中):**

```python
class PipelineEngine:
    def __init__(self, config: dict):
        self.qc          = await load_plugin(config, "qc")
        self.segmenter   = await load_plugin(config, "segmenter")
        self.transcriber = await load_plugin(config, "transcriber")
        self.detector    = await load_plugin(config, "detector")
        self.ocr         = await load_plugin(config, "ocr")
        self.captioner   = await load_plugin(config, "captioner")
        self.embedder    = await load_plugin(config, "embedder")
        self.summarizer  = await load_plugin(config, "summarizer")
        self.grounding   = await load_plugin(config, "grounding")

        # 可能为 None 的模块在调用时检查
```

---

## 六、core/status_tracker.py — 状态追踪

```python
"""
core/status_tracker.py
═══════════════════════════════════════════════════════════
Pipeline 执行期间更新 videos 表的 status / progress / current_phase。
"""

import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import Video, VideoStatus


class StatusTracker:
    """异步状态更新器。Pipeline 各阶段调用以报告进度。"""

    PHASE_WEIGHTS = {
        "phase_1_qc":       0.0,    # 起始
        "phase_1_audio":    0.10,
        "phase_1_segment":  0.15,
        "phase_2_vision":   0.20,
        "phase_2_ocr":      0.30,
        "phase_3_align":    0.40,
        "phase_4_caption":  0.50,
        "phase_4_embed":    0.75,
        "phase_5_summary":  0.85,
        "completed":        1.0,
    }

    PHASE_DESCRIPTIONS = {
        "phase_1_qc":       "质量检测中...",
        "phase_1_audio":    "音频抽取与转录中...",
        "phase_1_segment":  "镜头分割中...",
        "phase_2_vision":   "物体检测中...",
        "phase_2_ocr":      "文字提取中...",
        "phase_3_align":    "模态对齐中...",
        "phase_4_caption":  "深度理解中...",
        "phase_4_embed":    "向量编码中...",
        "phase_5_summary":  "摘要生成中...",
    }

    def __init__(self, video_id: str, db_session_factory):
        self.video_id = video_id
        self.db_session_factory = db_session_factory

    async def update(self, phase: str, progress: float | None = None, description: str | None = None):
        """更新 videos 表进度。"""
        if progress is None:
            progress = self.PHASE_WEIGHTS.get(phase, 0.0)
        if description is None:
            description = self.PHASE_DESCRIPTIONS.get(phase, phase)

        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video_id)
                .values(
                    progress=progress,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await session.commit()

    async def mark_completed(self):
        await self._set_status(VideoStatus.COMPLETED, progress=1.0)

    async def mark_failed(self, error: str):
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video_id)
                .values(
                    status=VideoStatus.FAILED,
                    error_message=error,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            await session.commit()

    async def _set_status(self, status: VideoStatus, progress: float):
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video)
                .where(Video.id == self.video_id)
                .values(status=status, progress=progress, updated_at=datetime.now(timezone.utc))
            )
            await session.commit()
```

---

## 七、pipeline/engine.py — PipelineEngine

```python
"""
pipeline/engine.py
═══════════════════════════════════════════════════════════
五阶段认知 Pipeline 编排器。
作为后台任务被 FastAPI 调用 (BackgroundTasks.add_task)。
"""

import asyncio
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from core.interfaces import VideoContext, Scene
from core.schemas import VideoContext
from core.status_tracker import StatusTracker
from core.prompt_loader import get_prompt_loader
from core.models import Video, VideoStatus
from plugins.factory import load_plugin
from pipeline.phase1_qc import Phase1QC
from pipeline.phase2_perception import Phase2Perception
from pipeline.phase3_alignment import Phase3Alignment
from pipeline.phase4_caption import Phase4Caption
from pipeline.phase5_summary import Phase5Summary

logger = logging.getLogger(__name__)


class PipelineEngine:
    """
    五阶段认知工作流编排器。

    设计原则:
      - 每一阶段依赖前一阶段的产出
      - 各阶段内部模块可并行
      - 阶段之间通过 VideoContext 传递数据
      - 每阶段完成时调用 StatusTracker 更新进度
    """

    def __init__(
        self,
        config: dict,
        db_session_factory,
        video: Video,
    ):
        self.config = config
        self.db_session_factory = db_session_factory
        self.video = video
        self.tracker = StatusTracker(video.id, db_session_factory)
        self.prompt_loader = get_prompt_loader()

        # 上下文
        self.ctx = VideoContext(
            video_id=str(video.id),
            file_path=video.file_path,
        )

        # 插件: 异步加载, 可能为 None
        self.plugins: dict = {}

    async def initialize(self):
        """加载所有插件。"""
        for category in ["qc", "transcriber", "segmenter", "detector",
                          "ocr", "captioner", "embedder", "summarizer", "grounding"]:
            self.plugins[category] = await load_plugin(self.config, category)

    async def run(self):
        """入口: 按顺序执行五阶段。"""
        try:
            await self._set_processing()
            await self.initialize()

            # ── Phase 1: 前置质检与拆解 ──
            await self._phase1()

            # ── Phase 2: 独立模态感知 (可并行) ──
            await self._phase2()

            # ── Phase 3: 模态交叉对齐 ──
            await self._phase3()

            # ── Phase 4: 带上下文的深度理解 ──
            await self._phase4()

            # ── Phase 5: 全局升华 ──
            await self._phase5()

            # ── 持久化 ──
            await self._persist()

            await self.tracker.mark_completed()
            logger.info(f"[Pipeline] video {self.video.id} completed")

        except Exception as e:
            logger.exception(f"[Pipeline] video {self.video.id} failed: {e}")
            await self.tracker.mark_failed(str(e))

    async def _set_processing(self):
        """标记为处理中。"""
        from sqlalchemy import update
        async with self.db_session_factory() as session:
            await session.execute(
                update(Video).where(Video.id == self.video.id).values(status=VideoStatus.PROCESSING)
            )
            await session.commit()

    # ──────────────────────────────────────────────────
    # Phase 1: 质检 + 音频抽取 + 镜头分割
    # ──────────────────────────────────────────────────

    async def _phase1(self):
        """Phase 1: 前置质检与拆解"""
        engine = Phase1QC(self.ctx, self.plugins, self.config, self.tracker)
        await engine.execute()

    # ──────────────────────────────────────────────────
    # Phase 2: 检测 + OCR (并行)
    # ──────────────────────────────────────────────────

    async def _phase2(self):
        """Phase 2: 独立模态感知"""
        engine = Phase2Perception(self.ctx, self.plugins, self.config, self.tracker, self.video)
        await engine.execute()

    # ──────────────────────────────────────────────────
    # Phase 3: 时序对齐
    # ──────────────────────────────────────────────────

    async def _phase3(self):
        """Phase 3: 模态交叉对齐"""
        engine = Phase3Alignment(self.ctx, self.plugins, self.config, self.tracker)
        await engine.execute()

    # ──────────────────────────────────────────────────
    # Phase 4: 记忆窗口深度描述 + 向量编码
    # ──────────────────────────────────────────────────

    async def _phase4(self):
        """Phase 4: 带上下文的深度理解"""
        engine = Phase4Caption(self.ctx, self.plugins, self.config, self.tracker, self.prompt_loader)
        await engine.execute()

    # ──────────────────────────────────────────────────
    # Phase 5: 全局升华摘要
    # ──────────────────────────────────────────────────

    async def _phase5(self):
        """Phase 5: 全局升华"""
        engine = Phase5Summary(self.ctx, self.plugins, self.config, self.tracker, self.prompt_loader)
        await engine.execute()

    # ──────────────────────────────────────────────────
    # 持久化: VideoContext → DB
    # ──────────────────────────────────────────────────

    async def _persist(self):
        """将 VideoContext 中的所有数据写入数据库。"""
        async with self.db_session_factory() as session:
            # 更新 Video
            from sqlalchemy import update
            await session.execute(
                update(Video)
                .where(Video.id == self.video.id)
                .values(
                    duration=self.ctx.duration,
                    qc_result=self.ctx.qc_result,
                    summary=self.ctx.summary,
                )
            )

            # 写入 Scenes
            from core.models import Scene as SceneModel
            for s in self.ctx.scenes:
                scene_row = SceneModel(
                    video_id=self.video.id,
                    scene_index=s.scene_index,
                    start_sec=s.start_sec,
                    end_sec=s.end_sec,
                    keyframe_path=s.keyframe_path,
                    ocr_text=s.ocr_text,
                    aligned_transcript=s.aligned_transcript,
                    caption=s.caption,
                    prev_caption=s.prev_caption,
                    embedding=s.embedding,
                    entities=s.entities,
                )
                session.add(scene_row)

            # 写入 Transcript
            if self.ctx.transcript_full:
                from core.models import Transcript as TranscriptModel
                transcript_row = TranscriptModel(
                    video_id=self.video.id,
                    full_text=self.ctx.transcript_full,
                    words=self.ctx.transcript_words,
                )
                session.add(transcript_row)

            await session.commit()
```

---

## 八、pipeline/phase4_caption.py — Phase 4 示例

```python
"""
pipeline/phase4_caption.py
═══════════════════════════════════════════════════════════
Phase 4: 带上下文记忆窗口的深度画面描述 + 向量编码

执行逻辑:
  for each scene:
    1. 构建 prompt (含前情/OCR/转录上下文)
    2. VLM 推理 → caption
    3. Embedder 编码 → embedding
    4. 传递 prev_caption 给下一场景
"""

import asyncio

class Phase4Caption:
    def __init__(self, ctx, plugins, config, tracker, prompt_loader):
        self.ctx = ctx
        self.plugins = plugins
        self.config = config
        self.tracker = tracker
        self.pl = prompt_loader

    async def execute(self):
        captioner = self.plugins.get("captioner")
        embedder = self.plugins.get("embedder")

        if captioner is None:
            return  # caption 被禁用

        with_context = self.config.get("plugins", {}).get("captioner", {}).get("with_context", False)
        max_tokens = self.config.get("plugins", {}).get("captioner", {}).get("max_new_tokens", 256)

        await self.tracker.update("phase_4_caption")
        total = len(self.ctx.scenes)

        for i, scene in enumerate(self.ctx.scenes):
            # ── 构建 prompt ──
            if with_context and i > 0:
                prompt = self.pl.get("caption_with_context",
                    prev_caption=self.ctx.scenes[i-1].caption or "无",
                    ocr_text=scene.ocr_text or "无",
                    transcript=scene.aligned_transcript or "无"
                )
            else:
                prompt = self.pl.get("caption_default")

            # ── VLM 推理 ──
            scene.caption = await captioner.caption(
                scene.keyframe, prompt, max_new_tokens=max_tokens
            )

            # ── 记忆传递 ──
            if i > 0:
                scene.prev_caption = self.ctx.scenes[i-1].caption

            # ── 进度 ──
            await self.tracker.update("phase_4_caption", progress=0.50 + 0.25 * (i / total))

        # ── 向量编码 (可与 caption 交替或在此批量处理) ──
        if embedder is not None:
            await self.tracker.update("phase_4_embed")
            for i, scene in enumerate(self.ctx.scenes):
                if scene.keyframe is not None:
                    scene.embedding = await embedder.encode_image(scene.keyframe)
                await self.tracker.update("phase_4_embed", progress=0.75 + 0.10 * (i / total))
```

---

## 九、plugins/summarizer/vllm_summarizer.py — vLLM 插件

```python
"""
plugins/summarizer/vllm_summarizer.py
═══════════════════════════════════════════════════════════
基于 vLLM (port 8010) OpenAI 兼容 API 的 Summarizer 实现。

vLLM 提供标准 /v1/chat/completions 接口，本插件用 openai 库直接调用。
"""

import json
import logging
from openai import AsyncOpenAI
from core.interfaces import BaseSummarizer

logger = logging.getLogger(__name__)


class VLLMSummarizer(BaseSummarizer):
    """
    通过 OpenAI 兼容 API 调用本地 vLLM 服务。

    config 示例:
      summarizer:
        backend: vllm-api
        base_url: "http://10.0.0.176:8010/v1"
        model_name: "Qwen2.5-7B-Instruct"
        max_tokens: 2048
        temperature: 0.1
    """

    def __init__(
        self,
        base_url: str = "http://10.0.0.176:8010/v1",
        model_name: str = "Qwen2.5-7B-Instruct",
        max_tokens: int = 2048,
        temperature: float = 0.1,
        **kwargs
    ):
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key="not-needed"   # vLLM 内网无需认证
        )
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def summarize(self, script: str, system_prompt: str, user_prompt: str) -> dict:
        """
        Args:
            script: 按时间排列的完整视频剧本
            system_prompt: 系统角色提示词
            user_prompt: 用户提示词 (含 script 占位符已填充)

        Returns:
            结构化摘要 dict
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt.format(script=script)},
        ]

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"},  # vLLM 支持的 JSON mode
            )

            content = response.choices[0].message.content
            return json.loads(content)

        except json.JSONDecodeError:
            logger.warning("vLLM returned non-JSON, attempting to extract...")
            # Fallback: 尝试从文本中提取 JSON
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            return json.loads(content.strip())

        except Exception as e:
            logger.error(f"vLLM summarizer error: {e}")
            raise
```

---

## 十、pipeline/search_engine.py — 多路召回 + RRF

```python
"""
pipeline/search_engine.py
═══════════════════════════════════════════════════════════
第一阶段搜索: 向量路 + 全文检索路 + 标签路 → RRF 融合
"""

import asyncio
from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from core.models import Scene


class SearchEngine:
    """多路召回 + Reciprocal Rank Fusion"""

    RRF_K = 60  # RRF 平滑常数

    def __init__(self, db_session_factory, embedder):
        self.db_session_factory = db_session_factory
        self.embedder = embedder

    async def search(
        self,
        query: str | None = None,
        image_vec: list[float] | None = None,
        video_ids: list[str] | None = None,
        search_types: list[str] | None = None,
        top_k: int = 20,
        min_similarity: float = 0.3,
    ) -> list[dict]:
        """
        多路召回 + RRF 融合。

        三路并行召回:
          1. vector:  pgvector <=> cosine distance
          2. fulltext: ts_rank + ts_query 全文检索
          3. label:    JSONB @> 精确匹配 entities.label
        """
        if search_types is None:
            search_types = ["vector", "fulltext", "label"]

        # ── 对文本查询做向量编码 ──
        if query and "vector" in search_types and self.embedder:
            image_vec = await self.embedder.encode_text(query)

        # ── 三路并行召回 ──
        tasks = []
        if "vector" in search_types and image_vec:
            tasks.append(self._vector_search(image_vec, video_ids, top_k * 2))
        if "fulltext" in search_types and query:
            tasks.append(self._fulltext_search(query, video_ids, top_k * 2))
        if "label" in search_types and query:
            tasks.append(self._label_search(query, video_ids, top_k * 2))

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # ── RRF 融合 ──
        fused = self._rrf_fuse(
            [r for r in results_list if not isinstance(r, Exception) and r],
            k=self.RRF_K
        )

        # ── 过滤低分 + Top-K ──
        filtered = [item for item in fused if item["similarity"] >= min_similarity]
        return filtered[:top_k]

    async def _vector_search(self, vec: list[float], video_ids: list[str] | None, limit: int):
        async with self.db_session_factory() as session:
            query = (
                select(
                    Scene,
                    (1.0 - func.cosine_distance(Scene.embedding, vec)).label("similarity")
                )
                .where(Scene.embedding.isnot(None))
                .order_by(func.cosine_distance(Scene.embedding, vec))
                .limit(limit)
            )
            if video_ids:
                query = query.where(Scene.video_id.in_(video_ids))

            result = await session.execute(query)
            return [self._row_to_dict(row.Scene, row.similarity, "vector") for row in result]

    async def _fulltext_search(self, query: str, video_ids: list[str] | None, limit: int):
        """tsvector 全文检索 + ts_rank 排序"""
        async with self.db_session_factory() as session:
            ts_query = func.plainto_tsquery("simple", query)
            similarity = func.ts_rank(Scene.search_vector, ts_query)

            stmt = (
                select(Scene, similarity.label("similarity"))
                .where(Scene.search_vector.op("@@")(ts_query))
                .order_by(similarity.desc())
                .limit(limit)
            )
            if video_ids:
                stmt = stmt.where(Scene.video_id.in_(video_ids))

            result = await session.execute(stmt)
            return [self._row_to_dict(row.Scene, row.similarity, "fulltext") for row in result]

    async def _label_search(self, query: str, video_ids: list[str] | None, limit: int):
        """JSONB 精确匹配: entities 中 label 包含查询词"""
        async with self.db_session_factory() as session:
            stmt = (
                select(Scene, func.literal(1.0).label("similarity"))
                .where(Scene.entities.op("@>")(f'[{{"label": "{query}"}}]'))
                .limit(limit)
            )
            if video_ids:
                stmt = stmt.where(Scene.video_id.in_(video_ids))

            result = await session.execute(stmt)
            return [self._row_to_dict(row.Scene, row.similarity, "label") for row in result]

    def _rrf_fuse(self, ranked_lists: list[list[dict]], k: int = 60) -> list[dict]:
        """Reciprocal Rank Fusion: 合并多路召回结果"""
        scores: dict[int, tuple[dict, float]] = {}

        for ranked in ranked_lists:
            for rank, item in enumerate(ranked, start=1):
                sid = item["scene_id"]
                rrf_score = 1.0 / (k + rank)
                if sid in scores:
                    existing, prev = scores[sid]
                    scores[sid] = (existing, prev + rrf_score)
                else:
                    scores[sid] = (item, rrf_score)

        # 按融合分降序
        fused = [{"scene_id": sid, **item, "similarity": round(score, 4)}
                 for sid, (item, score) in scores.items()]
        fused.sort(key=lambda x: x["similarity"], reverse=True)
        return fused

    @staticmethod
    def _row_to_dict(scene, similarity: float, source: str) -> dict:
        return {
            "scene_id": scene.id,
            "video_id": str(scene.video_id),
            "scene_index": scene.scene_index,
            "start_sec": scene.start_sec,
            "end_sec": scene.end_sec,
            "caption": scene.caption,
            "ocr_text": scene.ocr_text,
            "aligned_transcript": scene.aligned_transcript,
            "entities": scene.entities or [],
            "similarity": float(similarity),
            "source": source,
        }
```

---

## 十一、main.py — FastAPI 入口

```python
"""
main.py
═══════════════════════════════════════════════════════════
FastAPI 应用入口。
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.db import engine, init_db, AsyncSessionLocal
from core.config_loader import load_config
from core.prompt_loader import get_prompt_loader
from api.router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭生命周期。"""
    # 启动: 加载配置 & 初始化 DB
    app.state.config = load_config()
    app.state.prompt_loader = get_prompt_loader()
    await init_db()
    yield
    # 关闭: 释放资源
    await engine.dispose()


app = FastAPI(
    title="Cerno",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
```

---

## 十二、模块依赖关系图

```
main.py
  └── api/router.py
        ├── api/video_routes.py → services/video_service.py
        │     └── pipeline/engine.py
        │           ├── pipeline/phase1_qc.py
        │           ├── pipeline/phase2_perception.py
        │           ├── pipeline/phase3_alignment.py
        │           ├── pipeline/phase4_caption.py
        │           ├── pipeline/phase5_summary.py
        │           ├── plugins/factory.py → plugins/... (策略实例)
        │           └── core/status_tracker.py → core/models.py → core/db.py
        ├── api/search_routes.py → pipeline/search_engine.py
        ├── api/export_routes.py → services/export_service.py
        └── api/maintenance_routes.py

core/
  ├── interfaces.py     ← 所有插件实现依赖此模块
  ├── models.py         ← pipeline & services 依赖
  ├── db.py             ← 全局数据库引擎
  ├── schemas.py        ← VideoContext, Scene 数据对象
  ├── config_loader.py  ← 启动时加载 config.yaml
  └── prompt_loader.py  ← 业务代码获取 prompt 模板
```
