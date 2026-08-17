"""
plugins/factory.py
═══════════════════════════════════════════════════════════
插件工厂 — 根据 config.yaml 动态加载策略实现。

约定:
  - 每个插件的入口模块为 plugins/{category}/{module}.py
  - 模块内必须暴露一个与接口同名的实现类
  - 如: plugins/transcriber/faster_whisper.py → class FasterWhisperTranscriber

用法:
    instance = await load_plugin(config, "transcriber")
    if instance is not None:
        result = await instance.transcribe(...)
"""

import importlib
import logging

from core.exceptions import PluginLoadError

logger = logging.getLogger(__name__)

# 类别 → 插件包路径
CATEGORY_MAP: dict[str, str] = {
    "transcriber":  "plugins.transcriber",
    "segmenter":    "plugins.segmenter",
    "detector":     "plugins.detector",
    "ocr":          "plugins.ocr",
    "captioner":    "plugins.captioner",
    "embedder":     "plugins.embedder",
    "summarizer":   "plugins.summarizer",
    "grounding":    "plugins.grounding",
    "face":         "plugins.face",
    "plate":        "plugins.plate",
}

# 类别 → 预期实现类名
IMPL_CLASS_MAP: dict[str, str] = {
    "transcriber":  "FasterWhisperTranscriber",
    "segmenter":    "TransNetV2Segmenter",
    "detector":     "YoloDetector",
    "ocr":          "PaddleOCRExtractor",
    "captioner":    "Qwen25VLCaptioner",
    "embedder":     "QwenVLEmbedder",
    "summarizer":   "VLLMSummarizer",
    "grounding":    "Florence2Grounding",
    "face":         "InsightFaceRecognizer",
    "plate":        "PaddlePlateRecognizer",
}

# 后端标识 → 实际模块文件名覆盖
# 当 config 中的 backend 值与 .py 文件名不一致时使用。
_MODULE_OVERRIDES: dict[tuple[str, str], str] = {
    ("segmenter", "transnetv2"): "transnet_v2",
    ("captioner", "qwen_api"): "qwen_api_captioner",
    ("captioner", "qwen25_vl"): "qwen25_vl_captioner",
    ("captioner", "qwen3_vl"): "qwen3_vl_captioner",
    ("embedder", "qwen3_vl_embedding"): "qwen_vl_embedder",
    ("embedder", "qwen3_vl_embedding_8b"): "qwen_vl_embedder",
    ("embedder", "qwen3_vl_embedding_2b"): "qwen_vl_embedder",
    ("summarizer", "vllm"): "vllm_summarizer",
    ("detector", "yolo"): "yolo",
    ("face", "insightface"): "insightface_face",
    ("plate", "paddle"): "paddle_plate",
    ("plate", "hyperlpr"): "hyperlpr_plate",
}

# 后端标识 → 实现类名覆盖
# 当 config 中的 backend 要求使用不同的实现类时配置。
_CLASS_OVERRIDES: dict[tuple[str, str], str] = {
    ("captioner", "qwen_api"): "QwenAPICaptioner",
    ("captioner", "qwen25_vl"): "Qwen25VLCaptioner",
    ("captioner", "qwen3_vl"): "Qwen3VLCaptioner",
    ("segmenter", "time_based"): "TimeBasedSegmenter",
    ("detector", "yolo"): "YoloDetector",
    ("face", "insightface"): "InsightFaceRecognizer",
    ("plate", "paddle"): "PaddlePlateRecognizer",
    ("plate", "hyperlpr"): "HyperLPRPlateRecognizer",
}


async def load_plugin(config: dict, category: str):
    """根据配置动态加载插件策略实例。

    Args:
        config: 完整配置字典（load_config 输出）。
        category: 插件类别，如 "transcriber" / "detector" / ...

    Returns:
        插件实例，或 None（backend 为 null / 空字符串）。

    Raises:
        PluginLoadError: 模块不存在、类缺失或实例化异常。
    """
    plugin_cfg = config.get("plugins", {}).get(category, {})
    backend: str | None = plugin_cfg.get("backend")

    # ── backend 为空 → 跳过 ──
    if not backend:
        logger.info("[Factory] %s: backend is null → skipped", category)
        return None

    # ── 校验类别 ──
    if category not in CATEGORY_MAP:
        raise PluginLoadError(f"Unknown plugin category: {category}")

    # ── 构建模块路径 ──
    module_name = _MODULE_OVERRIDES.get((category, backend), backend)
    module_path = f"{CATEGORY_MAP[category]}.{module_name}"
    class_name = _CLASS_OVERRIDES.get(
        (category, backend),
        IMPL_CLASS_MAP.get(category),
    )

    # ── 动态导入 ──
    try:
        module = importlib.import_module(module_path)
        impl_class = getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise PluginLoadError(
            f"Failed to load plugin '{category}': "
            f"module '{module_path}.py' / class '{class_name}' not found — {e}"
        ) from e

    # ── 提取参数并实例化 ──
    # 优先使用 "params" 子段，否则使用 backend 外的所有同级键
    params = plugin_cfg.get("params")
    if params is None:
        params = {k: v for k, v in plugin_cfg.items() if k != "backend"}

    try:
        instance = impl_class(**params)
    except Exception as e:
        raise PluginLoadError(
            f"Failed to instantiate plugin '{category}' "
            f"({module_path}.{class_name}): {e}"
        ) from e

    logger.info(
        "[Factory] %s: %s.%s loaded (params=%s)",
        category, module_path, class_name, params,
    )
    return instance
