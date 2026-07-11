"""
core/config_loader.py 测试
═════════════════════════════════════════════════════════════════
验证：YAML 加载、ConfigurationError 抛出、lru_cache 缓存生效。
"""
import os
import pytest
import yaml

from core.config_loader import load_config
from core.exceptions import ConfigurationError


class TestLoadConfig:
    """load_config 正常路径与异常路径。"""

    def test_load_valid_yaml(self, tmp_path):
        config_content = {
            "server": {"host": "0.0.0.0", "port": 8000},
            "database": {"uri": "postgresql+asyncpg://test:test@localhost/test"},
        }
        config_file = tmp_path / "config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        result = load_config(config_file)
        assert result == config_content
        assert result["server"]["host"] == "0.0.0.0"
        assert result["server"]["port"] == 8000

        load_config.cache_clear()

    def test_file_not_found(self):
        nonexistent = "/tmp/__nonexistent_config_xyz.yaml"
        with pytest.raises(ConfigurationError, match="Configuration file not found"):
            load_config(nonexistent)

        load_config.cache_clear()

    def test_invalid_yaml_syntax(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{invalid: yaml: unclosed", encoding="utf-8")

        with pytest.raises(ConfigurationError, match="Failed to parse YAML"):
            load_config(bad_file)

        load_config.cache_clear()

    def test_non_dict_root(self, tmp_path):
        non_dict = tmp_path / "scalar.yaml"
        non_dict.write_text("just a string", encoding="utf-8")

        with pytest.raises(ConfigurationError, match="Config root is not a dict"):
            load_config(non_dict)

        load_config.cache_clear()


class TestLRUCache:
    """load_config 的 lru_cache 应返回同一对象。"""

    def test_cache_returns_same_object(self, tmp_path):
        load_config.cache_clear()

        config_content = {"key": "value"}
        config_file = tmp_path / "cached.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_content, f)

        first = load_config(config_file)
        second = load_config(config_file)
        assert first is second, "lru_cache 应返回相同对象"

        load_config.cache_clear()
