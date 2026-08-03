"""
core/settings_service.py
═══════════════════════════════════════════════════════════
设置管理服务 — 持久化 API 密钥 / 服务商端点与模型 / 存储路径。

存储为 data/settings.json，从 config.yaml 读取初始默认值。
settings.json 中的值优先于 config.yaml，运行时保存即生效（清 config 缓存）。

data/settings.json 结构：
{
  "api_keys":   { "dashscope": "sk-...", "deepseek": "sk-..." },
  "providers":  { "dashscope": {"base_url": "...", "model": "..."},
                  "deepseek":  {"base_url": "...", "model": "..."} },
  "storage":    { "video_dir": "...", "artifact_dir": "..." }
}
"""

import os
import json
import logging

from core.config_loader import load_config

logger = logging.getLogger(__name__)

SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "settings.json",
)

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

    return {
        "api_keys": api_keys_result,
        "providers": providers_result,
        "storage": storage_result,
    }


def update_settings(payload: dict) -> bool:
    """保存设置。payload 可含 api_keys / providers / storage，保存后运行时生效。

    - api_keys  {id: value}：value 为空字符串视为删除
    - providers {id: {base_url, model}}：空值忽略
    - storage   {video_dir, artifact_dir}：空值忽略
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

    _write_all(data)
    _invalidate()
    logger.info("[Settings] Updated: %s", list(payload.keys()))
    return True
