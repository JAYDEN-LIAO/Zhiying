"""
api/settings_routes.py
═══════════════════════════════════════════════════════════
系统设置端点 — API key / 管道性能 / 模型参数 / 参数预设。
"""

from fastapi import APIRouter, HTTPException, Request

from api.schemas import APIResponse, SettingsKeysRequest, PresetCreate, PresetRename

router = APIRouter()


@router.get("/settings")
async def get_settings() -> APIResponse[dict]:
    """获取系统设置（API 密钥 + 服务商端点/模型 + 存储路径）。"""
    from core.settings_service import get_current_settings
    return APIResponse(data=get_current_settings())


@router.put("/settings")
async def update_settings(
    request: Request,
    payload: SettingsKeysRequest,
) -> APIResponse[dict]:
    """更新系统设置（API 密钥 / 服务商 / 存储路径），保存即运行时生效。"""
    from core.settings_service import update_settings as _update, get_current_settings
    _update(payload.model_dump(exclude_none=True))
    # 并发上限运行时变更 → 队列 worker 数同步调整（v0.32）
    pipeline_queue = getattr(request.app.state, "pipeline_queue", None)
    if pipeline_queue is not None:
        from core.config_loader import load_config
        mcv = int((load_config().get("pipeline", {}) or {}).get("max_concurrent_videos", 0) or 1)
        pipeline_queue.configure(mcv)
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

    # 当前 vector embedding 档位（8b=4096 / 2b=2048）——前端设置页据此显示档位徽标 + 按档推荐
    embedding_profile = str(config.get("embedding_profile", "8b")).strip().lower()

    # OCR 生效参数（v0.34）：settings.json pipeline.ocr 覆盖已并入 plugins.ocr.params
    ocr_params = plugins_cfg.get("ocr", {}).get("params", {}) or {}

    return APIResponse(data={
        "embedding_profile": embedding_profile,
        "embedding_profiles": config.get("embedding_profiles", {}),
        "default_encode_profile": pipeline_cfg.get("default_encode_profile", "balanced"),
        "encode_profiles": pipeline_cfg.get("encode_profiles", {}),
        "use_nvdec": pipeline_cfg.get("use_nvdec", False),
        "chunk_encoding": pipeline_cfg.get("chunk_encoding", False),
        "default_summary_mode": pipeline_cfg.get("default_summary_mode", "vlm_llm"),
        "plugins": plugin_available,
        "ocr": {
            "backend": (plugins_cfg.get("ocr") or {}).get("backend"),
            "params": ocr_params,
        },
    })


# ═══════════════════════════════════════════════════════════
# 参数预设 — 多套命名参数快照，一键套用
# ═══════════════════════════════════════════════════════════

@router.get("/settings/presets")
async def get_presets() -> APIResponse[list]:
    """列出全部参数预设。"""
    from core.presets_service import list_presets
    return APIResponse(data=list_presets())


@router.post("/settings/presets", status_code=201)
async def create_preset(payload: PresetCreate) -> APIResponse[dict]:
    """创建参数预设：快照当前生效的管道参数。"""
    from core.presets_service import create_preset as _create
    try:
        return APIResponse(data=_create(payload.name))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/settings/presets/{preset_id}")
async def rename_preset(preset_id: str, payload: PresetRename) -> APIResponse[dict]:
    """重命名参数预设。"""
    from core.presets_service import rename_preset as _rename
    try:
        return APIResponse(data=_rename(preset_id, payload.name))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/settings/presets/{preset_id}")
async def delete_preset(preset_id: str) -> APIResponse[dict]:
    """删除参数预设。"""
    from core.presets_service import delete_preset as _delete
    try:
        _delete(preset_id)
        return APIResponse(data={"deleted": preset_id})
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/settings/presets/{preset_id}/apply")
async def apply_preset(preset_id: str) -> APIResponse[dict]:
    """套用参数预设：写入 settings.json 覆盖区，运行时生效。"""
    from core.presets_service import apply_preset as _apply
    try:
        return APIResponse(data=_apply(preset_id))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
