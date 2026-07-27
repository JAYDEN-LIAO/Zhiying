"""
config/config_schema.py
═══════════════════════════════════════════════════════════
config.yaml 的 Pydantic v2 校验模型。

提供 validate_config() 函数，将原始 dict 转换为强类型 AppConfig。
"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Any


# ═══════════════════════════════════════════════════════════
# 嵌套配置段
# ═══════════════════════════════════════════════════════════

class ServerConfig(BaseModel):
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)


class DatabaseConfig(BaseModel):
    uri: str = Field(default="postgresql+asyncpg://cerno:cerno@localhost:5432/cerno")
    pool_size: int = Field(default=20, ge=1)
    max_overflow: int = Field(default=10, ge=0)


class StorageConfig(BaseModel):
    video_dir: str = Field(default="/home/cerno/data/videos")
    artifact_dir: str = Field(default="/home/cerno/data/artifacts")


class PluginConfig(BaseModel):
    """单个插件配置。允许每个插件携带自定义参数。"""
    model_config = ConfigDict(extra="allow")

    backend: str | None = Field(default=None, description="插件后端标识")


class PipelineConfig(BaseModel):
    sample_fps: float = Field(default=1.0, gt=0.0)
    scene_min_duration: float = Field(default=1.0, ge=0.0)
    chunk_encoding: bool = Field(default=False, description="chunk 编码开关（需较好 GPU）")
    encode_batch_size: int = Field(default=64, ge=1, description="帧编码批大小（按 GPU VRAM 调整）")
    use_nvdec: bool = Field(default=False, description="NVDEC 硬件解码（需 NVIDIA GPU + FFmpeg CUDA）")


# ═══════════════════════════════════════════════════════════
# 顶层配置
# ═══════════════════════════════════════════════════════════

class AppConfig(BaseModel):
    """应用完整配置的强类型视图。"""
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    plugins: dict[str, PluginConfig] = Field(default_factory=dict)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)


# ═══════════════════════════════════════════════════════════
# 校验入口
# ═══════════════════════════════════════════════════════════

def validate_config(raw: dict[str, Any]) -> AppConfig:
    """将原始 dict 校验为 AppConfig 实例。

    Args:
        raw: yaml.safe_load() 输出的原始字典。

    Returns:
        校验通过的 AppConfig 强类型对象。

    Raises:
        pydantic.ValidationError: 配置结构不符合 schema。
    """
    return AppConfig.model_validate(raw)
