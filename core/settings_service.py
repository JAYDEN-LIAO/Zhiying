"""
core/settings_service.py
═══════════════════════════════════════════════════════════
设置管理服务 — 持久化 API Key 等配置。

存储为 data/settings.json，从 config.yaml 读取初始默认值。
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

# 已知的 API key 定义
API_KEY_DEFS = [
    {"id": "dashscope", "label": "DashScope (描述生成)", "env": "DASHSCOPE_API_KEY"},
    {"id": "deepseek",  "label": "DeepSeek (摘要生成)",  "env": "DEEPSEEK_API_KEY"},
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


def get_current_keys() -> dict:
    """返回各 API key 的状态（脱敏显示）。"""
    # 1. 从 config.yaml 读默认值
    config = load_config()
    config_keys: dict[str, str | None] = {}
    for kdef in API_KEY_DEFS:
        env_var = kdef["env"]
        config_key = kdef["id"]

        # 环境变量优先
        env_val = os.environ.get(env_var)
        if env_val:
            config_keys[config_key] = env_val
            continue

        # 从 config.yaml 读取
        if config_key == "dashscope":
            val = config.get("plugins", {}).get("captioner", {}).get("params", {}).get("api_key")
        elif config_key == "deepseek":
            val = config.get("plugins", {}).get("summarizer", {}).get("api_key")
        else:
            val = None

        if val and val != "placeholder":
            config_keys[config_key] = val
        else:
            config_keys[config_key] = None

    # 2. settings.json 中的覆盖值
    saved = _read_all().get("api_keys", {})

    result = {}
    for kdef in API_KEY_DEFS:
        kid = kdef["id"]
        effective = saved.get(kid) or config_keys.get(kid)
        result[kid] = {
            "id": kid,
            "label": kdef["label"],
            "configured": effective is not None,
            "masked_value": _mask_key(effective),
        }
    return result


def update_keys(keys: dict[str, str]) -> bool:
    """更新 API key 值。key=空字符串视为删除。"""
    data = _read_all()
    api_keys = data.setdefault("api_keys", {})

    for kid, value in keys.items():
        value = value.strip()
        if value:
            api_keys[kid] = value
        else:
            api_keys.pop(kid, None)

    _write_all(data)
    logger.info("[Settings] API keys updated: %s", list(keys.keys()))
    return True
