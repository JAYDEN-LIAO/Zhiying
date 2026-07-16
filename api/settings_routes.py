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
