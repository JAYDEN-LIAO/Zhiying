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
    """获取系统设置（API 密钥 + 服务商端点/模型 + 存储路径）。"""
    from core.settings_service import get_current_settings
    return APIResponse(data=get_current_settings())


@router.put("/settings")
async def update_settings(
    payload: SettingsKeysRequest,
) -> APIResponse[dict]:
    """更新系统设置（API 密钥 / 服务商 / 存储路径），保存即运行时生效。"""
    from core.settings_service import update_settings as _update, get_current_settings
    _update(payload.model_dump(exclude_none=True))
    return APIResponse(data=get_current_settings())


@router.get("/settings/pipeline")
async def get_pipeline_config() -> APIResponse[dict]:
    """获取 pipeline 配置（编码预设等全局默认值 + 摘要模式默认 + 插件可用性）。"""
    from core.config_loader import load_config
    config = load_config()
    pipeline_cfg = config.get("pipeline", {})
    plugins_cfg = config.get("plugins", {})

    # 插件可用性：backend 非 null/空 → 已启用。前端据此决定开关是否置灰。
    plugin_available = {
        cat: bool((plugins_cfg.get(cat) or {}).get("backend"))
        for cat in ("transcriber", "detector", "face", "plate", "ocr")
    }

    return APIResponse(data={
        "default_encode_profile": pipeline_cfg.get("default_encode_profile", "balanced"),
        "encode_profiles": pipeline_cfg.get("encode_profiles", {}),
        "use_nvdec": pipeline_cfg.get("use_nvdec", False),
        "chunk_encoding": pipeline_cfg.get("chunk_encoding", False),
        "default_summary_mode": pipeline_cfg.get("default_summary_mode", "native_video"),
        "plugins": plugin_available,
    })
