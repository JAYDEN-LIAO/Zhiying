"""
core/config_loader.py
═══════════════════════════════════════════════════════════
YAML 配置加载器 — 一次性加载、全局缓存。

使用 pyyaml 读取 config/config.yaml，缓存结果。
支持通过环境变量覆写敏感字段（如 API key），避免密钥进入版本控制。
"""

import logging
import os
from pathlib import Path
from functools import lru_cache

import yaml

from core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 部署时可用 ZHIYING_CONFIG 环境变量指定备选配置文件（如 config/config.windows.yaml）
_DEFAULT_CONFIG_PATH = Path(
    os.environ.get("ZHIYING_CONFIG", str(_PROJECT_ROOT / "config" / "config.yaml"))
)

# 环境变量 → 配置内嵌路径映射
# 键为环境变量名，值为 yaml 加载后的 dict 中要覆盖的逐层 key
_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "DASHSCOPE_API_KEY": ("plugins", "captioner", "params", "api_key"),
    "DEEPSEEK_API_KEY":  ("plugins", "summarizer", "api_key"),
}

# settings.json 中的 key id → 环境变量名
# 前端设置页保存的 key 会被注入为环境变量，从而走 _ENV_OVERRIDES 覆盖配置。
# 与 core/settings_service.py 的 API_KEY_DEFS 保持一致。
_SETTINGS_ENV_KEYS: dict[str, str] = {
    "dashscope": "DASHSCOPE_API_KEY",
    "deepseek":  "DEEPSEEK_API_KEY",
}

# ═══════════════════════════════════════════════════════════
# 管道性能参数规格 — 推荐默认 + 合法范围 + 步进
# 前端设置页 placeholder/min/max/step 与这里的 recommend/min/max/step 保持一致。
# 保存/应用时按此规格钳制，防止乱填越界。
# ═══════════════════════════════════════════════════════════
PIPELINE_NUMERIC_SPEC: dict[str, dict] = {
    "detection_fps":         {"cast": float, "min": 1,   "max": 30,   "step": 1,   "recommend": 10},
    "detector_batch_size":   {"cast": int,   "min": 1,   "max": 512,  "step": 1,   "recommend": 128},
    "yolo_imgsz":            {"cast": int,   "min": 320, "max": 640,  "step": 32,  "recommend": 640},  # YOLO 需 32 倍数
    "confidence_threshold":  {"cast": float, "min": 0.05, "max": 0.95, "step": 0.05, "recommend": 0.4},
    "iou_threshold":         {"cast": float, "min": 0.05, "max": 0.9,  "step": 0.05, "recommend": 0.5},
    "max_concurrent_videos": {"cast": int,   "min": 0,   "max": 16,   "step": 1,   "recommend": 1},
    "max_scenes":            {"cast": int,   "min": 1,   "max": 30,   "step": 1,   "recommend": 6},
    "sample_fps":            {"cast": float, "min": 0.5, "max": 3.0, "step": 0.1, "recommend": 1.0},
    "segment_threshold":     {"cast": float, "min": 0.2, "max": 0.8, "step": 0.1, "recommend": 0.5},
}
# 编码三档模板字段规格（分辨率只钳范围不强制步进，避免破坏 504 等非 16 倍数推荐值）
ENCODE_PROFILE_NUMERIC_SPEC: dict[str, dict] = {
    "encode_width":      {"cast": int, "min": 224,  "max": 960,  "step": 1, "recommend": 0},
    "encode_height":     {"cast": int, "min": 224,  "max": 960,  "step": 1, "recommend": 0},
    "encode_batch_size": {"cast": int, "min": 8,    "max": 1024, "step": 8, "recommend": 0},
}
ENCODE_PROFILE_NAMES = ("fast", "balanced", "precise")


def clamp_param(spec: dict, value) -> float | int | None:
    """把数值钳制到 [min, max] 并按 step 取整；无法转换返回 None。"""
    try:
        v = spec["cast"](value)
    except (TypeError, ValueError):
        return None
    step = spec.get("step", 1)
    v = round(v / step) * step
    v = max(spec["min"], min(spec["max"], v))
    if spec["cast"] is float:
        v = round(v, 4)  # 去掉浮点噪声
    return v


def _load_dotenv() -> None:
    """加载 .env 文件到 os.environ（如已存在同名变量则不覆盖）。

    纯 Python 实现，无 python-dotenv 依赖。
    .env 文件路径为项目根目录下的 .env。
    """
    env_path = _PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip("\"'")
            if key and not os.environ.get(key):
                os.environ[key] = val


def _auto_fallback_captioner(cfg: dict) -> None:
    """本地 captioner 模型缺失时，自动降级到 qwen_api（DashScope）。

    让一份 config.yaml 同时适用于「有本地 8B 模型的开发机」与「走 API 的部署机」：
    - 配置里 captioner.backend = qwen3_vl，但本地模型目录不存在 → 切成 qwen_api；
    - native_video → vlm_llm 的摘要模式转换由 runners/base.py effective_summary_mode 兜底。
    必须在本函数之后才应用 settings.json 覆盖（_apply_settings_overrides），
    这样降级后的 qwen_api 能继承设置页注入的 base_url / model_name。
    """
    plugins = cfg.setdefault("plugins", {})
    captioner = plugins.get("captioner") or {}
    if captioner.get("backend") != "qwen3_vl":
        return

    local_model = str(captioner.get(
        "params", {},
    ).get("model_name", "models/Qwen/Qwen3-VL-8B-Instruct"))
    model_path = Path(local_model)
    if not model_path.is_absolute():
        model_path = _PROJECT_ROOT / local_model
    if model_path.exists():
        logger.info("[Config] captioner 本地模型在 %s → 保持 qwen3_vl", model_path)
        return

    logger.warning(
        "[Config] captioner 本地模型缺失 (%s) → 自动降级 captioner 为 qwen_api (DashScope)",
        local_model,
    )
    plugins["captioner"] = {
        "backend": "qwen_api",
        "params": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_key": "placeholder",  # 实际值经 env / settings.json 注入
            "model_name": "qwen-vl-max",
            "max_new_tokens": 2048,
            "with_context": False,  # 默认关：caption 并发提速；开则串行（依赖前序场景描述）
        },
    }


def _apply_settings_overrides(cfg: dict) -> None:
    """将 data/settings.json 中保存的设置覆盖进配置。

    前端设置页通过 PUT /settings 写入 data/settings.json；这里在每次
    load_config() 时读取并应用：
      1. API key → 注入环境变量（真实 env 优先级更高），由 _ENV_OVERRIDES 流入插件；
      2. 服务商 base_url / model_name → 直接覆盖 captioner/summarizer 配置；
      3. 存储路径 video_dir / artifact_dir → 覆盖 storage 配置。
    保存后 update_settings 会清空 load_config 缓存，因此运行时保存即生效。
    """
    settings_path = _PROJECT_ROOT / "data" / "settings.json"
    if not settings_path.exists():
        return
    try:
        data = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return
    data = data or {}

    # 1. API keys → env（走 _ENV_OVERRIDES）
    api_keys = data.get("api_keys", {}) or {}
    for kid, env_name in _SETTINGS_ENV_KEYS.items():
        value = api_keys.get(kid)
        if value and not os.environ.get(env_name):
            os.environ[env_name] = str(value).strip()

    # 2. 服务商 base_url / model_name → 直接覆盖插件配置
    providers = data.get("providers", {}) or {}
    cap_params = cfg.setdefault("plugins", {}).setdefault("captioner", {}).setdefault("params", {})
    sum_cfg = cfg.setdefault("plugins", {}).setdefault("summarizer", {})
    dash = providers.get("dashscope") or {}
    deep = providers.get("deepseek") or {}
    if dash.get("base_url"):
        cap_params["base_url"] = str(dash["base_url"]).strip()
    if dash.get("model"):
        cap_params["model_name"] = str(dash["model"]).strip()
    if deep.get("base_url"):
        sum_cfg["base_url"] = str(deep["base_url"]).strip()
    if deep.get("model"):
        sum_cfg["model_name"] = str(deep["model"]).strip()

    # 3. 存储路径 → 覆盖 storage 配置
    storage = data.get("storage", {}) or {}
    scfg = cfg.setdefault("storage", {})
    if storage.get("video_dir"):
        scfg["video_dir"] = str(storage["video_dir"]).strip()
    if storage.get("artifact_dir"):
        scfg["artifact_dir"] = str(storage["artifact_dir"]).strip()

    # 4. 管道性能 → 覆盖编码三档模板 / 检测参数 / 全局开关 / 模型参数
    #    编码三档模板（encode_profiles）逐档覆盖；其余数值参数按 PIPELINE_NUMERIC_SPEC 钳制。
    pipeline = data.get("pipeline", {}) or {}
    pcfg = cfg.setdefault("pipeline", {})
    det = cfg.setdefault("plugins", {}).setdefault("detector", {})
    profiles = pcfg.setdefault("encode_profiles", {}) or {}

    def _coerce_bool(v) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)

    # ── 编码三档模板：逐档覆盖（钳制范围 + 步进取整）──
    saved_profiles = pipeline.get("encode_profiles")
    if isinstance(saved_profiles, dict):
        for prof_name in ENCODE_PROFILE_NAMES:
            vals = saved_profiles.get(prof_name)
            if not isinstance(vals, dict) or prof_name not in profiles:
                continue
            target = profiles[prof_name]
            for field, spec in ENCODE_PROFILE_NUMERIC_SPEC.items():
                if vals.get(field) is None:
                    continue
                v = clamp_param(spec, vals[field])
                if v is not None:
                    target[field] = v

    # ── 默认编码预设（枚举校验）──
    if pipeline.get("default_encode_profile") is not None:
        v = str(pipeline["default_encode_profile"]).strip()
        if v in ENCODE_PROFILE_NAMES:
            pcfg["default_encode_profile"] = v

    # ── 检测参数 / 并发上限（带范围钳制）→ plugins.detector / pipeline ──
    det_map = {
        "detection_fps": "detection_fps",
        "detector_batch_size": "batch_size",
        "confidence_threshold": "confidence_threshold",
        "iou_threshold": "iou_threshold",
        "yolo_imgsz": "imgsz",
    }
    for src_key, det_key in det_map.items():
        if pipeline.get(src_key) is None:
            continue
        v = clamp_param(PIPELINE_NUMERIC_SPEC[src_key], pipeline[src_key])
        if v is not None:
            det[det_key] = v
    if pipeline.get("max_concurrent_videos") is not None:
        v = clamp_param(PIPELINE_NUMERIC_SPEC["max_concurrent_videos"], pipeline["max_concurrent_videos"])
        if v is not None:
            pcfg["max_concurrent_videos"] = v
    if pipeline.get("max_scenes") is not None:
        v = clamp_param(PIPELINE_NUMERIC_SPEC["max_scenes"], pipeline["max_scenes"])
        if v is not None:
            pcfg["max_scenes"] = v

    # ── 场景分割参数（TransNetV2 采样帧率 / 场景切换敏感度，v0.33 起全局设置）──
    for key in ("sample_fps", "segment_threshold"):
        if pipeline.get(key) is not None:
            v = clamp_param(PIPELINE_NUMERIC_SPEC[key], pipeline[key])
            if v is not None:
                pcfg[key] = v

    # ── 全局开关（布尔，含 "false" 字符串兜底）──
    if pipeline.get("use_nvdec") is not None:
        pcfg["use_nvdec"] = _coerce_bool(pipeline["use_nvdec"])
    if pipeline.get("chunk_encoding") is not None:
        pcfg["chunk_encoding"] = _coerce_bool(pipeline["chunk_encoding"])

    # ── 模型参数：量化（枚举）──
    if pipeline.get("quantization") is not None:
        v = str(pipeline["quantization"]).strip().lower()
        if v in ("none", "8bit", "4bit"):
            cfg.setdefault("plugins", {}).setdefault("embedder", {}).setdefault("params", {})["quantization"] = v


@lru_cache(maxsize=1)
def load_config(config_path: str | Path = _DEFAULT_CONFIG_PATH) -> dict:
    """加载 YAML 配置并返回原始 Python dict。

    结果通过 lru_cache 全局缓存，整个进程只会读取一次。
    如需重新加载（如测试），直接调用 load_config.cache_clear()。

    加载后依次应用 _ENV_OVERRIDES 映射的环境变量覆盖，
    因此 config.yaml 中可填写占位符，实际值通过环境变量注入。

    Args:
        config_path: YAML 配置文件路径，默认项目根目录下的 config/config.yaml。

    Returns:
        配置内容的 Python dict。

    Raises:
        ConfigurationError: 文件不存在、YAML 解析失败等。
    """
    path = Path(config_path)

    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg: dict = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Failed to parse YAML config: {e}") from e
    except OSError as e:
        raise ConfigurationError(f"Failed to read config file: {e}") from e

    if not isinstance(cfg, dict):
        raise ConfigurationError(f"Config root is not a dict, got {type(cfg).__name__}")

    # ── 从 .env 文件加载（如存在） ──
    _load_dotenv()

    # ── 本地 captioner 模型缺失 → 自动降级 qwen_api（先于 settings 覆盖，见函数注释） ──
    _auto_fallback_captioner(cfg)

    # ── 从 data/settings.json 注入设置页保存的 API key / 服务商 / 存储路径 ──
    _apply_settings_overrides(cfg)

    # ── 环境变量覆写（不修改 config.yaml 文件本身） ──
    for var_name, keys in _ENV_OVERRIDES.items():
        value = os.environ.get(var_name)
        if value is None:
            continue
        target = cfg
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value

    return cfg
