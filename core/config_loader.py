"""
core/config_loader.py
═══════════════════════════════════════════════════════════
YAML 配置加载器 — 一次性加载、全局缓存。

使用 pyyaml 读取 config/config.yaml，缓存结果。
支持通过环境变量覆写敏感字段（如 API key），避免密钥进入版本控制。
"""

import os
from pathlib import Path
from functools import lru_cache

import yaml

from core.exceptions import ConfigurationError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 部署时可用 CERNO_CONFIG 环境变量指定备选配置文件（如 config/config.windows.yaml）
_DEFAULT_CONFIG_PATH = Path(
    os.environ.get("CERNO_CONFIG", str(_PROJECT_ROOT / "config" / "config.yaml"))
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
