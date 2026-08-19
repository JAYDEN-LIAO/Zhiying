"""
core/settings_service.py
═══════════════════════════════════════════════════════════
设置管理服务 — 持久化 API 密钥 / 服务商端点与模型 / 存储路径 / 管道性能。

存储为 data/settings.json，从 config.yaml 读取初始默认值。
settings.json 中的值优先于 config.yaml，运行时保存即生效（清 config 缓存）。

data/settings.json 结构：
{
  "api_keys":   { "dashscope": "sk-...", "deepseek": "sk-..." },
  "providers":  { "dashscope": {"base_url": "...", "model": "..."},
                  "deepseek":  {"base_url": "...", "model": "..."} },
  "storage":    { "video_dir": "...", "artifact_dir": "..." },
  "pipeline":   { "encode_batch_size": 64, "encode_width": 336, "encode_height": 224,
                  "default_encode_profile": "fast", "detection_fps": 5,
                  "detector_batch_size": 32, "confidence_threshold": 0.4, "iou_threshold": 0.5,
                  "use_nvdec": true, "chunk_encoding": false }
}
"""

import os
import json
import logging

from core.config_loader import (
    load_config,
    PIPELINE_NUMERIC_SPEC,
    ENCODE_PROFILE_NUMERIC_SPEC,
    ENCODE_PROFILE_NAMES,
    OCR_NUMERIC_SPEC,
    OCR_LANGS,
    clamp_param,
)

logger = logging.getLogger(__name__)

from core.paths import project_root

SETTINGS_FILE = str(project_root() / "data" / "settings.json")

# 已知的 API key 定义（env 变量注入插件）
API_KEY_DEFS = [
    {"id": "dashscope", "label": "DashScope (描述生成)", "env": "DASHSCOPE_API_KEY"},
    {"id": "deepseek",  "label": "DeepSeek (摘要生成)",  "env": "DEEPSEEK_API_KEY"},
]

# 已知的 API 服务商配置（端点 + 模型名 → 覆盖 config.yaml 对应插件）
# config_path: 指向插件配置存放 base_url/model_name 的位置
API_PROVIDER_DEFS = [
    {
        "id": "dashscope",
        "label": "DashScope（画面描述 qwen-vl）",
        "config_path": ("plugins", "captioner", "params"),
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-vl-max",
    },
    {
        "id": "deepseek",
        "label": "DeepSeek（摘要生成）",
        "config_path": ("plugins", "summarizer"),
        "default_base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
    },
]


def _ensure_file():
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"api_keys": {}}, f)


def _read_all() -> dict:
    _ensure_file()
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {"api_keys": {}}


def _write_all(data: dict):
    _ensure_file()
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _mask_key(key: str | None) -> str | None:
    """将 API key 脱敏显示，仅显示末 4 位。"""
    if not key:
        return None
    if len(key) <= 4:
        return "••••"
    return "••••••••" + key[-4:]


def _config_get(config: dict, path: tuple[str, ...], key: str, default=None):
    """沿路径取 config 值；缺失返回 default。"""
    node = config
    for p in path:
        node = node.get(p) if isinstance(node, dict) else None
        if node is None:
            return default
    return node.get(key, default) if isinstance(node, dict) else default


def _invalidate() -> None:
    """同步 API key 到环境变量 + 清 config 缓存 → 运行时即时生效。"""
    data = _read_all()
    api_keys = data.get("api_keys", {})
    for kdef in API_KEY_DEFS:
        env_var, kid = kdef["env"], kdef["id"]
        if kid in api_keys and api_keys[kid]:
            os.environ[env_var] = str(api_keys[kid]).strip()
        else:
            os.environ.pop(env_var, None)
    try:
        load_config.cache_clear()
    except Exception:
        pass


def get_current_keys() -> dict:
    """返回各 API key 的状态（脱敏显示）— 兼容旧接口。"""
    return get_current_settings()["api_keys"]


def update_keys(keys: dict[str, str]) -> bool:
    """更新 API key 值。key=空字符串视为删除。（兼容部署脚本 / 旧接口）"""
    return update_settings({"api_keys": keys})


def get_current_settings() -> dict:
    """返回当前生效的设置：{api_keys, providers, storage}。

    取值优先级：settings.json 覆盖 > 环境变量 > config.yaml 默认。
    """
    config = load_config()
    saved = _read_all()
    saved_keys = saved.get("api_keys", {}) or {}
    saved_providers = saved.get("providers", {}) or {}
    saved_storage = saved.get("storage", {}) or {}

    # ── API keys（脱敏）──
    api_keys_result: dict[str, dict] = {}
    for kdef in API_KEY_DEFS:
        kid = kdef["id"]
        effective = (
            os.environ.get(kdef["env"])
            or saved_keys.get(kid)
            or _config_get(config, ("plugins", "captioner", "params") if kid == "dashscope" else ("plugins", "summarizer"), "api_key")
        )
        if effective == "placeholder":
            effective = None
        api_keys_result[kid] = {
            "id": kid,
            "label": kdef["label"],
            "configured": bool(effective),
            "masked_value": _mask_key(effective),
        }

    # ── 服务商（端点 + 模型名）──
    providers_result: dict[str, dict] = {}
    for pdef in API_PROVIDER_DEFS:
        pid = pdef["id"]
        saved_p = saved_providers.get(pid) or {}
        base_url = (
            saved_p.get("base_url")
            or _config_get(config, pdef["config_path"], "base_url")
            or pdef["default_base_url"]
        )
        model = (
            saved_p.get("model")
            or _config_get(config, pdef["config_path"], "model_name")
            or pdef["default_model"]
        )
        providers_result[pid] = {
            "id": pid,
            "label": pdef["label"],
            "base_url": base_url,
            "model": model,
        }

    # ── 存储路径 ──
    storage_cfg = config.get("storage", {}) or {}
    storage_result = {
        "video_dir": saved_storage.get("video_dir") or storage_cfg.get("video_dir", "data/videos"),
        "artifact_dir": saved_storage.get("artifact_dir") or storage_cfg.get("artifact_dir", "data/artifacts"),
    }

    # ── 管道性能（编码三档模板 + 检测参数 + 全局开关 + 模型参数）──
    saved_pipeline = saved.get("pipeline", {}) or {}
    pipeline_cfg = config.get("pipeline", {}) or {}
    config_profiles = pipeline_cfg.get("encode_profiles", {}) or {}
    saved_profiles = saved_pipeline.get("encode_profiles") or {}
    default_profile = pipeline_cfg.get("default_encode_profile", "balanced")
    det_cfg = config.get("plugins", {}).get("detector", {}) or {}

    # 编码三档生效值：settings.json 逐档覆盖 > config 模板
    profiles_result: dict[str, dict] = {}
    for prof_name in ENCODE_PROFILE_NAMES:
        base = config_profiles.get(prof_name, {}) or {}
        ov = saved_profiles.get(prof_name) or {}
        profiles_result[prof_name] = {
            "encode_width": ov.get("encode_width") or base.get("encode_width", 336),
            "encode_height": ov.get("encode_height") or base.get("encode_height", 224),
            "encode_batch_size": ov.get("encode_batch_size") or base.get("encode_batch_size", 512),
        }

    pipeline_result = {
        # 编码三档模板 + 默认档
        "encode_profiles": profiles_result,
        "default_encode_profile": saved_pipeline.get("default_encode_profile") or default_profile,
        # 物体检测
        "detection_fps": saved_pipeline.get("detection_fps") or det_cfg.get("detection_fps", 10),
        "detector_batch_size": saved_pipeline.get("detector_batch_size") or det_cfg.get("batch_size", 128),
        "confidence_threshold": saved_pipeline.get("confidence_threshold") or det_cfg.get("confidence_threshold", 0.4),
        "iou_threshold": saved_pipeline.get("iou_threshold") or det_cfg.get("iou_threshold", 0.5),
        # 全局开关（布尔：显式覆盖，None 回退 config）
        "use_nvdec": saved_pipeline.get("use_nvdec") if saved_pipeline.get("use_nvdec") is not None
                     else pipeline_cfg.get("use_nvdec", True),
        "chunk_encoding": saved_pipeline.get("chunk_encoding") if saved_pipeline.get("chunk_encoding") is not None
                          else pipeline_cfg.get("chunk_encoding", False),
        # 模型参数
        "quantization": saved_pipeline.get("quantization")
                        or (config.get("plugins", {}).get("embedder", {}).get("params", {}) or {}).get("quantization", "none"),
        "yolo_imgsz": saved_pipeline.get("yolo_imgsz") or det_cfg.get("imgsz", 640),
        "max_concurrent_videos": saved_pipeline.get("max_concurrent_videos")
                                 if saved_pipeline.get("max_concurrent_videos") is not None
                                 else pipeline_cfg.get("max_concurrent_videos", 0),
        # 场景分割参数（v0.33 起全局设置；or 模式天然支持空串回退 config 默认）
        "sample_fps": saved_pipeline.get("sample_fps") or pipeline_cfg.get("sample_fps", 1.0),
        "segment_threshold": saved_pipeline.get("segment_threshold") or pipeline_cfg.get("segment_threshold", 0.5),
    }

    # ── OCR 参数（v0.34）：settings.json pipeline.ocr 覆盖 > config plugins.ocr.params ──
    ocr_cfg = config.get("plugins", {}).get("ocr", {}).get("params", {}) or {}
    saved_ocr = saved_pipeline.get("ocr") or {}
    saved_max_width = saved_ocr.get("max_width")
    pipeline_result["ocr"] = {
        "sample_fps": saved_ocr.get("sample_fps") or ocr_cfg.get("sample_fps", 1.0),
        "conf_thresh": saved_ocr.get("conf_thresh") or ocr_cfg.get("conf_thresh", 0.5),
        "max_width": saved_max_width if saved_max_width is not None
                     else ocr_cfg.get("max_width"),
        "scale": saved_ocr.get("scale") or ocr_cfg.get("scale", 1.0),
        "lang": saved_ocr.get("lang") or ocr_cfg.get("lang", "ch"),
    }

    return {
        "api_keys": api_keys_result,
        "providers": providers_result,
        "storage": storage_result,
        "pipeline": pipeline_result,
    }


def update_settings(payload: dict) -> bool:
    """保存设置。payload 可含 api_keys / providers / storage / pipeline，保存后运行时生效。

    - api_keys  {id: value}：value 为空字符串视为删除
    - providers {id: {base_url, model}}：空值忽略
    - storage   {video_dir, artifact_dir}：空值忽略
    - pipeline  {encode_profiles(三档模板), default_encode_profile, detection_fps,
                  detector_batch_size, yolo_imgsz, confidence_threshold, iou_threshold,
                  use_nvdec, chunk_encoding, quantization, max_concurrent_videos}：
                  未提及(None)=不动，显式空串("")=删除覆盖（回退 config.yaml），布尔为显式开关
    """
    data = _read_all()

    api_keys = payload.get("api_keys") or {}
    for kid, value in api_keys.items():
        value = str(value).strip()
        if value:
            data.setdefault("api_keys", {})[kid] = value
        else:
            data.get("api_keys", {}).pop(kid, None)

    providers = payload.get("providers") or {}
    for pid, cfg in providers.items():
        if not isinstance(cfg, dict):
            continue
        entry = data.setdefault("providers", {}).setdefault(pid, {})
        if cfg.get("base_url"):
            entry["base_url"] = str(cfg["base_url"]).strip()
        if cfg.get("model"):
            entry["model"] = str(cfg["model"]).strip()

    storage = payload.get("storage") or {}
    if isinstance(storage, dict):
        for key in ("video_dir", "artifact_dir"):
            val = storage.get(key)
            if val is None or not str(val).strip():
                data.get("storage", {}).pop(key, None)
            else:
                data.setdefault("storage", {})[key] = str(val).strip()

    pipeline = payload.get("pipeline") or {}
    if isinstance(pipeline, dict):
        # ── 编码三档模板：逐档覆盖（空字段=不覆盖，数值钳制范围+步进取整）──
        saved_profiles = pipeline.get("encode_profiles")
        if isinstance(saved_profiles, dict):
            out_profiles: dict[str, dict] = {}
            for prof_name in ENCODE_PROFILE_NAMES:
                vals = saved_profiles.get(prof_name)
                if not isinstance(vals, dict):
                    continue
                out: dict = {}
                for field, spec in ENCODE_PROFILE_NUMERIC_SPEC.items():
                    val = vals.get(field)
                    if val is None or (isinstance(val, str) and not val.strip()):
                        continue
                    clamped = clamp_param(spec, val)
                    if clamped is None:
                        logger.warning("[Settings] Invalid %s.%s: %r", prof_name, field, val)
                        continue
                    out[field] = clamped
                if out:
                    out_profiles[prof_name] = out
            if out_profiles:
                data.setdefault("pipeline", {})["encode_profiles"] = out_profiles
            else:
                data.get("pipeline", {}).pop("encode_profiles", None)

        # ── 数值字段（范围钳制）：显式空字符串 = 删除覆盖；未提及(None) = 保持现状 ──
        #    每张卡只发自己的字段，未提及的键绝不能清除，否则后保存的卡会抹掉其他卡的值
        for key, spec in PIPELINE_NUMERIC_SPEC.items():
            val = pipeline.get(key)
            if val is None:
                continue  # 该卡未涉及此参数，保持已有覆盖
            if isinstance(val, str) and not val.strip():
                data.get("pipeline", {}).pop(key, None)
                continue
            clamped = clamp_param(spec, val)
            if clamped is None:
                logger.warning("[Settings] Invalid pipeline value for %s: %r", key, val)
            else:
                data.setdefault("pipeline", {})[key] = clamped

        # ── 枚举字段：default_encode_profile / quantization（校验取值）──
        #    同样：未提及(None)=不动，显式空串("")=删除覆盖
        val = pipeline.get("default_encode_profile")
        if val is None:
            pass
        elif isinstance(val, str) and not val.strip():
            data.get("pipeline", {}).pop("default_encode_profile", None)
        else:
            v = str(val).strip()
            if v in ("fast", "balanced", "precise"):
                data.setdefault("pipeline", {})["default_encode_profile"] = v
            else:
                logger.warning("[Settings] Invalid default_encode_profile: %r", val)

        val = pipeline.get("quantization")
        if val is None:
            pass
        elif isinstance(val, str) and not val.strip():
            data.get("pipeline", {}).pop("quantization", None)
        else:
            v = str(val).strip().lower()
            if v in ("none", "8bit", "4bit"):
                data.setdefault("pipeline", {})["quantization"] = v
            else:
                logger.warning("[Settings] Invalid quantization: %r", val)

        # ── 布尔开关：显式 true/false 覆盖；未发送则不处理 ──
        for key in ("use_nvdec", "chunk_encoding"):
            val = pipeline.get(key)
            if isinstance(val, bool):
                data.setdefault("pipeline", {})[key] = val

        # ── OCR 参数（v0.34）：嵌套 `pipeline.ocr`，合并进既有覆盖（不覆盖未发送字段）。
        #    数值按 OCR_NUMERIC_SPEC 钳制；空串或多位=删除该字段覆盖（回退 config 默认）。 ──
        ocr_in = pipeline.get("ocr")
        if isinstance(ocr_in, dict):
            stored_ocr = data.setdefault("pipeline", {}).setdefault("ocr", {})
            for key, spec in OCR_NUMERIC_SPEC.items():
                val = ocr_in.get(key)
                if val is None:
                    continue  # 未发送 → 保持已有覆盖
                if isinstance(val, str) and not val.strip():
                    stored_ocr.pop(key, None)
                    continue
                clamped = clamp_param(spec, val)
                if clamped is None:
                    logger.warning("[Settings] Invalid ocr.%s: %r", key, val)
                    continue
                stored_ocr[key] = clamped
            lang = ocr_in.get("lang")
            if lang is not None:
                v = str(lang).strip().lower()
                if v in OCR_LANGS:
                    stored_ocr["lang"] = v
                elif v:
                    logger.warning("[Settings] Invalid ocr.lang: %r", lang)
            if not stored_ocr:
                data.get("pipeline", {}).pop("ocr", None)

        # ── 兼容清理：旧的扁平编码键（v0.22 前 schema）已废弃，保存时清除 ──
        for legacy in ("encode_batch_size", "encode_width", "encode_height"):
            data.get("pipeline", {}).pop(legacy, None)

        if not data.get("pipeline"):
            data.pop("pipeline", None)

    _write_all(data)
    _invalidate()
    logger.info("[Settings] Updated: %s", list(payload.keys()))
    return True
