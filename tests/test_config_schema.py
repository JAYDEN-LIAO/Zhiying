"""
config/config_schema.py 测试
═════════════════════════════════════════════════════════════════
验证：完整配置合法解析、缺少必填字段报错、null backend 可解析。
"""
import pytest
from pydantic import ValidationError

from config.config_schema import (
    validate_config,
    AppConfig,
    ServerConfig,
    PluginConfig,
)


class TestValidateConfig:
    """validate_config 合法 / 非法场景。"""

    def test_valid_full_config(self):
        raw = {
            "server": {"host": "127.0.0.1", "port": 9000},
            "database": {"uri": "postgresql+asyncpg://u:p@localhost/db", "pool_size": 10, "max_overflow": 5},
            "storage": {"video_dir": "/data/videos", "artifact_dir": "/data/artifacts"},
            "plugins": {
                "qc": {"backend": "native_qc"},
                "transcriber": {"backend": "faster_whisper", "model_path": "tiny"},
            },
            "pipeline": {"sample_fps": 2.0, "scene_min_duration": 0.5},
        }
        cfg = validate_config(raw)
        assert isinstance(cfg, AppConfig)
        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.port == 9000
        assert cfg.database.pool_size == 10
        assert cfg.pipeline.sample_fps == 2.0
        assert "qc" in cfg.plugins
        assert cfg.plugins["qc"].backend == "native_qc"
        assert cfg.plugins["transcriber"].backend == "faster_whisper"

    def test_invalid_port_type(self):
        """port 应为 int，传入字符串应抛出 ValidationError。"""
        raw = {
            "server": {"host": "0.0.0.0", "port": "eight thousand"},
            "database": {"uri": "postgresql+asyncpg://u:p@localhost/db"},
            "storage": {"video_dir": "/v", "artifact_dir": "/a"},
        }
        with pytest.raises(ValidationError) as exc:
            validate_config(raw)
        # 至少应有一条与 port 相关的校验错误
        errors = exc.value.errors()
        port_errors = [
            e for e in errors
            if any("port" in str(loc) for loc in (e.get("loc") or []))
        ]
        assert len(port_errors) >= 1, f"应报 port 类型错误，实际: {errors}"

    def test_plugin_backend_null(self):
        raw = {
            "server": {"host": "0.0.0.0", "port": 8000},
            "database": {"uri": "postgresql+asyncpg://u:p@localhost/db"},
            "storage": {"video_dir": "/v", "artifact_dir": "/a"},
            "plugins": {
                "custom_plugin": {"backend": None},
            },
        }
        cfg = validate_config(raw)
        assert cfg.plugins["custom_plugin"].backend is None

    def test_partial_config_uses_defaults(self):
        raw = {
            "server": {"host": "0.0.0.0", "port": 8000},
            "database": {"uri": "sqlite:///test.db"},
            "storage": {"video_dir": "/v", "artifact_dir": "/a"},
        }
        cfg = validate_config(raw)
        # pipeline 未提供，使用默认值
        assert cfg.pipeline.sample_fps == 1.0
        assert cfg.pipeline.scene_min_duration == 1.0
        # plugins 未提供，使用空 dict
        assert cfg.plugins == {}


class TestPluginConfig:
    """PluginConfig 额外字段兼容性。"""

    def test_extra_fields_allowed(self):
        pc = PluginConfig(backend="test", custom_field="value", timeout=30)
        assert pc.backend == "test"
        # extra="allow" 确保自定义字段存在
        extra = pc.model_dump()
        assert extra.get("custom_field") == "value"
