"""
api/settings_routes.py
═══════════════════════════════════════════════════════════
系统设置端点 — API key 管理。
"""

from fastapi import APIRouter

from api.schemas import APIResponse, SettingsKeysRequest

router = APIRouter()


@router.get("/settings")
async def get_settings() -> APIResponse[dict]:
    """获取系统设置（API key 状态等）。"""
    from core.settings_service import get_current_keys
    keys = get_current_keys()
    return APIResponse(data={"api_keys": keys})


@router.put("/settings")
async def update_settings(
    payload: SettingsKeysRequest,
) -> APIResponse[dict]:
    """更新系统设置（API key 等）。"""
    from core.settings_service import update_keys, get_current_keys
    update_keys(payload.api_keys)
    keys = get_current_keys()
    return APIResponse(data={"api_keys": keys})


@router.get("/settings/pipeline")
async def get_pipeline_config() -> APIResponse[dict]:
    """获取 pipeline 配置（编码预设等全局默认值）。"""
    from core.config_loader import load_config
    config = load_config()
    pipeline_cfg = config.get("pipeline", {})
    return APIResponse(data={
        "default_encode_profile": pipeline_cfg.get("default_encode_profile", "balanced"),
        "encode_profiles": pipeline_cfg.get("encode_profiles", {}),
        "use_nvdec": pipeline_cfg.get("use_nvdec", False),
        "chunk_encoding": pipeline_cfg.get("chunk_encoding", False),
    })
