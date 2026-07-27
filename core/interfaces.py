"""
core/interfaces.py
═══════════════════════════════════════════════════════════
所有 AI 算法模块的抽象接口层 — 8 个 ABC（v0.8）。

⚠️  异步 / 同步边界 — 硬性约定
────────────────────────────────────────────────────────
本文件所有接口均为 async def，但具体插件实现（YOLO / PaddleOCR /
faster-whisper 等）的内部模型推理是同步 CPU/GPU 密集型计算。
如果直接在 async 方法中调用同步推理，会阻塞整个 asyncio 事件循环。

实现规范：

  ✅ 正确写法（YOLO 检测器示例）:
      async def detect(self, frames: list[np.ndarray]):
          return await asyncio.to_thread(self._sync_predict, frames)

      def _sync_predict(self, frames: list[np.ndarray]):
          return self.model(frames, conf=0.35, device="cuda", verbose=False)

  ❌ 反例（禁止 — 会卡死事件循环）:
      async def detect(self, frames: list[np.ndarray]):
          return self.model(frames, conf=0.35, device="cuda")   # ← 阻塞!

  例外：VLLMSummarizer（走 AsyncOpenAI HTTP）不需要 to_thread。

  受影响插件清单见 docs/03-core-code-skeleton-and-directory-tree.md → §3.1。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from collections.abc import Callable, Awaitable

import numpy as np


# ═══════════════════════════════════════════════════════════
# 数据传递对象
# ═══════════════════════════════════════════════════════════

@dataclass
class Scene:
    """单个场景的完整信息载体。按 Pipeline 阶段逐步填充。

    填充顺序：分割 → 关键帧 → 对齐 → 描述 → 编码
    """

    # ── 分割阶段（Phase 1）填充 ──
    scene_id: int
    scene_index: int
    start_sec: float
    end_sec: float

    # ── 关键帧阶段填充 ──
    keyframe: np.ndarray | None = None            # (H,W,C) uint8 — 中点代表帧（缩略图用）
    keyframe_path: str | None = None
    keyframes: list[np.ndarray] = field(default_factory=list)      # 1fps 帧池
    frame_timestamps: list[float] = field(default_factory=list)    # 帧池对应时间戳
    caption_frames: list[np.ndarray] | None = None  # vlm_llm 模式: VLM 选中的 3-7 帧（native_video 下为 None）

    # ── 对齐阶段填充 ──
    ocr_text: str | None = None
    aligned_transcript: str | None = None

    # ── 描述阶段填充 ──
    caption: str | None = None
    prev_caption: str | None = None
    structured_caption: dict | None = None         # native_video 模式: 结构化 JSON {description, keywords, objects, actions, scene_type, lighting}

    # ── 编码阶段填充 ──
    # DEPRECATED (v0.8): 不再写入，仅兼容旧数据读取
    embedding: list[float] | None = None
    text_embedding: list[float] | None = None      # Vector(4096) — encode_text(caption+ocr+transcript)，文本语义搜索用

    # ── 预留 ──
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
    summary: dict | None = None
    frame_detections: list[dict] | None = None   # detection runner 产出
    tracks: list[dict] | None = None              # detection runner 产出
    track_best_frames: dict | None = None          # {track_id: {frame, bbox, timestamp, conf}}
    track_embeddings: list[dict] | None = None     # track_encode runner 产出
    face_identities: list[dict] | None = None      # face runner 产出 — 聚类后的人脸身份
    face_detections: list[dict] | None = None      # face runner 产出 — 逐次人脸检出记录
    plate_detections: list[dict] | None = None     # plate runner 产出 — 车牌识别结果

    # 异步进度回调: async def cb(progress: float, phase: str, desc: str)
    progress_callback: Callable[[float, str, str], Awaitable[None]] | None = None


# ═══════════════════════════════════════════════════════════
# 抽象接口
# ═══════════════════════════════════════════════════════════

class BaseTranscriber(ABC):
    """语音转录 — 音频文件 → 带时间戳的全文。"""

    @abstractmethod
    async def transcribe(
        self,
        audio_path: str,
        language: str | None = None,
    ) -> dict:
        """
        对音频文件执行语音识别。

        Args:
            audio_path: 音频文件路径（WAV / MP3）。
            language: 语言提示（None = 自动检测, "zh" / "en" 等）。

        Returns:
            {
                "full_text": str,                           # 转录全文
                "language": str,                             # 检测语言
                "duration": float,                           # 转录覆盖音频时长(秒)
                "words": [{"word": str, "start": float, "end": float, "confidence": float}],
            }
        """
        ...


class BaseSegmenter(ABC):
    """镜头分割 — 视频 → 场景时间片段列表。"""

    @abstractmethod
    async def segment(
        self,
        video_path: str,
        sample_fps: float = 1.0,
    ) -> list[dict]:
        """
        将视频按镜头切换切分为场景片段。

        Args:
            video_path: 视频文件路径。
            sample_fps: 抽帧频率（帧/秒），影响分割精度与速度的平衡。

        Returns:
            [
                {
                    "scene_index": int,                      # 场景序号，0-based
                    "start_sec": float,                      # 开始秒数
                    "end_sec": float,                        # 结束秒数
                    "keyframe": np.ndarray | None,           # 代表帧 (H,W,C) uint8
                },
            ]
        """
        ...


class BaseDetector(ABC):
    """物体检测 — 批量帧 → 批量检测物列表。

    GPU 推理受益于批量处理（amortize kernel launch overhead）。
    时间范围和跟踪 ID 由上层（ByteTrack / runner）负责，检测器只回答
    "这幅图里有什么物体"。
    """

    @abstractmethod
    async def detect(self, frames: list[np.ndarray]) -> list[list[dict]]:
        """
        对一批帧执行物体检测。

        Args:
            frames: RGB 图像列表 (H, W, 3) uint8，长度通常为 batch_size（8）。

        Returns:
            与 frames 等长的列表。每个元素是该帧的检测物列表::

                [
                    {
                        "bbox": [x1, y1, x2, y2],   # 归一化 0-1 坐标
                        "confidence": float,         # 置信度 (0~1)
                        "class_name": str,          # COCO 类别名
                    },
                ]
        """
        ...


class BaseFaceRecognizer(ABC):
    """人脸检测与识别 — SCRFD 检测 + ArcFace R50 嵌入 (512-dim)。

    GPU 推理密集，实现必须通过 asyncio.to_thread 包裹同步调用。
    接受 person crop 图像列表，返回人脸 bbox + embedding。
    """

    @abstractmethod
    async def extract(self, crops: list[np.ndarray]) -> list[list[dict]]:
        """批量处理 person crops，检测人脸并提取 512 维嵌入向量。

        Args:
            crops: person crop 图像列表 (H, W, 3) uint8。

        Returns:
            与 crops 等长的列表。每个元素是该 crop 中检测到的所有人脸::

                [
                    {
                        "bbox": {"x1": float, "y1": float, "x2": float, "y2": float},
                        "quality": float,       # 人脸质量分数 (0~1)
                        "embedding": [float],   # ArcFace R50 512 维归一化向量
                    },
                ]
        """
        ...


class BasePlateRecognizer(ABC):
    """车牌检测与识别 — PaddleOCR 检测车牌区域 + 字符识别。

    GPU 推理密集，实现必须通过 asyncio.to_thread 包裹同步调用。
    接受 vehicle crop 图像列表，返回车牌文本 + 元数据。
    """

    @abstractmethod
    async def recognize(self, crops: list[np.ndarray]) -> list[list[dict]]:
        """批量处理 vehicle crops，检测并识别车牌。

        Args:
            crops: vehicle crop 图像列表 (H, W, 3) uint8。

        Returns:
            与 crops 等长的列表。每个元素是该 crop 中检测到的所有车牌::

                [
                    {
                        "plate_text": str,              # 车牌号文本
                        "plate_type": str,              # blue/yellow/green/white
                        "char_confidences": [float],    # 逐字符置信度
                        "bbox": {"x1": float, "y1": float, "x2": float, "y2": float},
                        "confidence": float,            # 整体检测置信度
                    },
                ]
        """
        ...


class BaseOCR(ABC):
    """文字提取 — 单帧 → 可见文字。"""

    @abstractmethod
    async def extract(self, frame: np.ndarray) -> str:
        """
        对关键帧执行 OCR 文字提取。

        Args:
            frame: 单帧图像 (H, W, C) uint8。

        Returns:
            提取到的文字内容（多行文本用换行分隔）。
        """
        ...


class BaseCaptioner(ABC):
    """画面描述 (VLM) — 多帧序列 + 文本 prompt → 自然语言描述。"""

    @abstractmethod
    async def caption(
        self,
        keyframes: list[np.ndarray],
        prompt: str,
        max_new_tokens: int = 256,
    ) -> str:
        """
        对一组关键帧生成深度画面描述（多帧时序输入）。

        Args:
            keyframes: 关键帧序列，每帧 (H, W, C) uint8。
            prompt: 由 prompt_loader 渲染好的完整提示词。
            max_new_tokens: 生成最大 token 数。

        Returns:
            自然语言描述文本。
        """
        ...


class BaseEmbedder(ABC):
    """向量编码 — 图像 / 文本 → 4096 维嵌入向量。"""

    @abstractmethod
    async def encode_image(self, image: np.ndarray) -> list[float]:
        """
        将图像编码为嵌入向量。

        Args:
            image: 输入图像 (H, W, C) uint8。

        Returns:
            4096 维 float 向量（Qwen3-VL-Embedding-2B 输出维度）。
        """
        ...

    @abstractmethod
    async def encode_text(self, text: str) -> list[float]:
        """
        将文本编码为嵌入向量（用于文本查询的向量化）。

        Args:
            text: 输入文本。

        Returns:
            4096 维 float 向量（Qwen3-VL-Embedding-2B 输出维度）。
        """
        ...

    @abstractmethod
    async def encode_video(
        self, video_path: str, fps: float = 1.0, max_frames: int = 32,
    ) -> list[float]:
        """原生视频编码 — 接受视频文件路径，模型内部处理帧提取与时序融合。

        通过 qwen_vl_utils.process_vision_info 处理视频，
        将视频帧与文本映射到同一语义空间。

        Args:
            video_path: 视频文件路径。
            fps: 提取帧率（帧/秒）。
            max_frames: 最大帧数。

        Returns:
            4096 维归一化 float 向量。
        """
        ...


class BaseSummarizer(ABC):
    """摘要生成 (LLM) — 视频剧本 → 结构化摘要。"""

    @abstractmethod
    async def summarize(
        self,
        script: str,
        system_prompt: str,
        user_prompt: str,
    ) -> dict:
        """
        根据视频剧本生成结构化摘要。

        Args:
            script: 按时间排列的完整视频剧本。
            system_prompt: 系统角色提示词。
            user_prompt: 用户提示词（已包含 script 占位符）。

        Returns:
            {
                "one_liner": str,                            # 一句话概括
                "scenes_summary": [                          # 场景摘要列表
                    {
                        "scene_index": int,
                        "start_sec": float,
                        "end_sec": float,
                        "description": str,
                        "keywords": [str],
                    },
                ],
                "tags": [str],                               # 标签
                "main_topics": [str],                        # 核心主题
                "main_entities": [str],                      # 主要实体
            }
        """
        ...


class BaseGrounding(ABC):
    """开放词汇目标定位 — 单帧 + 查询文本 → 边界框列表。"""

    @abstractmethod
    async def locate(
        self,
        frame: np.ndarray,
        query: str,
    ) -> list[dict]:
        """
        在帧画面中定位查询文本描述的物体。

        Args:
            frame: 单帧图像 (H, W, C) uint8。
            query: 查询文本，如"猫"、"红色的车"。

        Returns:
            [
                {
                    "label": str,                            # 物体标签
                    "bbox": [x1, y1, x2, y2],                # 边界框坐标
                    "confidence": float,                     # 置信度 (0~1)
                },
            ]
        """
        ...
