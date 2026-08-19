"""
pipeline/operations.py
═══════════════════════════════════════════════════════════
操作注册表 — 系统的能力声明清单。

engine 通过 ALL_OPERATIONS 发现所有可用操作，
根据 gate 过滤 → 拓扑排序 → 逐批执行。

新增感知模块时，只需在此列表添加一行 Operation(...) 即可。
"""

from pipeline.runners.base import Operation
from pipeline.runners.duration import DurationRunner
from pipeline.runners.segmentation import SegmentRunner
from pipeline.runners.transcription import TranscribeRunner
from pipeline.runners.keyframe import KeyframeRunner
from pipeline.runners.alignment import AlignRunner
from pipeline.runners.caption import CaptionRunner
from pipeline.runners.summary import SummaryRunner
from pipeline.runners.frame_encode import FrameEncodeRunner
from pipeline.runners.chunk_encode import ChunkEncodeRunner
from pipeline.runners.text_encode import TextEncodeRunner
from pipeline.runners.detection import DetectionRunner
from pipeline.runners.track_encode import TrackEncodeRunner
from pipeline.runners.face import FaceRunner
from pipeline.runners.plate import PlateRunner
from pipeline.runners.search_encode import SearchEncodeRunner
from pipeline.runners.ocr import OcrRunner

ALL_OPERATIONS: list[Operation] = [
    Operation(
        name="duration", runner=DurationRunner(),
        label="视频信息", description="读取视频时长与元数据",
        progress_weight=0.02,
    ),

    Operation(
        name="segmentation", runner=SegmentRunner(),
        depends_on=["duration"],
        gate=lambda v, _: v.summary_enabled,
        required_plugins=["segmenter"],
        label="场景分割", description="镜头边界检测中",
        progress_weight=0.15,
    ),

    Operation(
        name="transcription", runner=TranscribeRunner(),
        depends_on=["duration"],
        gate=lambda v, _: v.audio_enabled,
        required_plugins=["transcriber"],
        label="音频转录", description="语音转文字中",
        progress_weight=0.10,
    ),

    Operation(
        name="keyframes", runner=KeyframeRunner(),
        depends_on=["segmentation"],
        gate=lambda v, _: v.vision_enabled and v.summary_enabled,
        label="关键帧抽取", description="1fps 帧池提取中",
        progress_weight=0.15,
    ),

    Operation(
        name="alignment", runner=AlignRunner(),
        depends_on=["segmentation", "transcription"],
        gate=lambda v, _: v.audio_enabled,
        label="模态对齐", description="时间戳分配到场景中",
        progress_weight=0.05,
    ),

    Operation(
        name="detection", runner=DetectionRunner(),
        depends_on=["duration"],  # 仅需时长，不依赖分割；场景聚合在结束时自动有 scenes
        gate=lambda v, cfg: (
            cfg.get("plugins", {}).get("detector", {}).get("backend") is not None
            and getattr(v, "detection_enabled", False)
        ),
        required_plugins=["detector"],
        label="物体检测", description="YOLO11 检测 + BoT-SORT 追踪（独立帧率）",
        progress_weight=0.10,
    ),

    Operation(
        name="caption", runner=CaptionRunner(),
        depends_on=["keyframes"],
        gate=lambda v, _: v.vision_enabled and v.caption_enabled and v.summary_enabled,
        required_plugins=["captioner"],
        label="画面描述", description="VLM 画面描述中",
        progress_weight=0.20,
    ),

    Operation(
        name="summary", runner=SummaryRunner(),
        depends_on=["caption"],
        gate=lambda v, _: v.summary_enabled and v.caption_enabled and v.vision_enabled,
        required_plugins=["summarizer"],
        label="智能摘要", description="结构化摘要生成中",
        progress_weight=0.10,
    ),

    Operation(
        name="frame_encode", runner=FrameEncodeRunner(),
        depends_on=["segmentation"],  # 与 keyframes 并行: 通过 frame_queue 流式消费帧
        gate=lambda v, _: v.search_index_enabled and v.vision_enabled and v.summary_enabled,
        required_plugins=["embedder"],
        label="帧级编码", description="逐帧向量编码中",
        progress_weight=0.08,
    ),

    Operation(
        name="chunk_encode", runner=ChunkEncodeRunner(),
        depends_on=["keyframes"],
        gate=lambda v, cfg: (
            v.search_index_enabled and v.vision_enabled
            and v.summary_enabled
            and cfg.get("pipeline", {}).get("chunk_encoding", False)
        ),
        required_plugins=["embedder"],
        label="片段编码", description="滑动窗口编码中",
        progress_weight=0.05,
    ),

    Operation(
        name="text_encode", runner=TextEncodeRunner(),
        depends_on=["keyframes", "caption"],  # 等 caption 产出的描述文本，避免编码空 caption
        gate=lambda v, _: (
            v.search_index_enabled and v.vision_enabled
            and v.summary_enabled
        ),  # 依赖 caption 产出的 text → 需要 summary 路径
        required_plugins=["embedder"],
        label="文本语义编码", description="文本向量编码中",
        progress_weight=0.07,
    ),

    Operation(
        name="search_encode", runner=SearchEncodeRunner(),
        depends_on=["duration"],
        gate=lambda v, _: (
            v.search_index_enabled
            and v.vision_enabled
            and not v.summary_enabled  # 摘要开启时由 keyframes→frame_encode 负责编码
        ),
        required_plugins=["embedder"],
        label="搜索索引构建", description="1fps 抽帧 + 批量编码中",
        progress_weight=0.23,
    ),

    Operation(
        name="track_encode", runner=TrackEncodeRunner(),
        # 仅依赖 detection（读其内存态 track_crop_cache 做嵌入+缝合）；
        # 阶段二 incremental 不含 frame_encode，去掉该依赖以免语义误导
        depends_on=["detection"],
        gate=lambda v, cfg: (
            v.detection_enabled
            and v.search_index_enabled
            and v.vision_enabled
            and cfg.get("plugins", {}).get("detector", {}).get("backend") is not None
        ),
        required_plugins=["embedder"],
        label="物体语义编码", description="Track 跨模态嵌入 + 全局重识别",
        progress_weight=0.03,
    ),

    Operation(
        name="face", runner=FaceRunner(),
        depends_on=["detection"],
        gate=lambda v, cfg: (
            cfg.get("plugins", {}).get("face", {}).get("backend") is not None
            and getattr(v, "detection_enabled", False)
            and getattr(v, "face_enabled", False)
        ),
        required_plugins=["face"],
        label="人脸识别", description="SCRFD 人脸检测 + ArcFace 身份聚类",
        progress_weight=0.03,
    ),

    Operation(
        name="plate", runner=PlateRunner(),
        depends_on=["detection"],
        gate=lambda v, cfg: (
            cfg.get("plugins", {}).get("plate", {}).get("backend") is not None
            and getattr(v, "detection_enabled", False)
            and getattr(v, "plate_enabled", False)
        ),
        required_plugins=["plate"],
        label="车牌识别", description="PaddleOCR 车牌检测与文字识别",
        progress_weight=0.03,
    ),

    Operation(
        name="ocr", runner=OcrRunner(),
        depends_on=["duration"],  # 独立感知模块：自抽高清帧，与摘要/检测完全解耦
        gate=lambda v, cfg: (
            cfg.get("plugins", {}).get("ocr", {}).get("backend") is not None
            and getattr(v, "ocr_enabled", False)
        ),
        required_plugins=["ocr"],
        label="文字识别", description="画面文字提取中",
        progress_weight=0.05,
    ),

]
