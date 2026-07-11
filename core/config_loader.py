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
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "config.yaml"

# 环境变量 → 配置内嵌路径映射
# 键为环境变量名，值为 yaml 加载后的 dict 中要覆盖的逐层 key
_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "DASHSCOPE_API_KEY": ("plugins", "captioner", "params", "api_key"),
    "DEEPSEEK_API_KEY":  ("plugins", "summarizer", "api_key"),
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
