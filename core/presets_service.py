"""
core/presets_service.py
═══════════════════════════════════════════════════════════
参数预设服务 — 多套命名参数快照，一键套用。

存储为 config/presets.json（v0.34候选起**入仓库随 git 走**，部署/换机可复用），
与 data/settings.json（当前生效覆盖）分离：
  - create: 把「当前生效」的管道参数快照成一套命名预设
  - apply:  把预设的管道参数写回 settings.json 覆盖区 → 运行时生效（量化需重启）
  - rename / delete: 管理预设

预设只含管道性能/模型参数（编码 + 检测 + 开关 + 量化 + 并发），
不含存储路径与 API 密钥（机器相关，不随参数走）。
历史版本存 data/presets.json（gitignored）→ 首次读取自动搬迁到 config/presets.json。
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone

from core.settings_service import get_current_settings, update_settings
from core.paths import project_root

logger = logging.getLogger(__name__)

# 预设入仓库（config/ 随 git 共享，部署/换机开箱可复用）
PRESETS_FILE = str(project_root() / "config" / "presets.json")
# 历史路径（gitignored）——首次切换时自动迁移
_LEGACY_PRESETS_FILE = str(project_root() / "data" / "presets.json")

# 预设快照的管道参数（与 settings.json pipeline 段一致；encode_profiles 为嵌套三档模板）
PIPELINE_KEYS = [
    "encode_profiles", "default_encode_profile",
    "detection_fps", "detector_batch_size", "confidence_threshold", "iou_threshold",
    "use_nvdec", "chunk_encoding",
    "quantization", "yolo_imgsz", "max_concurrent_videos",
]


def _migrate_from_legacy() -> None:
    """老版本预设存 data/presets.json（gitignored）；首次切换到 config/presets.json 时搬入仓库。"""
    if os.path.exists(PRESETS_FILE) or not os.path.exists(_LEGACY_PRESETS_FILE):
        return
    try:
        with open(_LEGACY_PRESETS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("presets"):
            os.makedirs(os.path.dirname(PRESETS_FILE), exist_ok=True)
            with open(PRESETS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("[Presets] migrated data/presets.json → config/presets.json（%d 预设随 git 共享）", len(data["presets"]))
    except Exception:
        pass


def _read() -> dict:
    _migrate_from_legacy()
    if not os.path.exists(PRESETS_FILE):
        return {"presets": []}
    try:
        with open(PRESETS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"presets": []}


def _write(data: dict) -> None:
    os.makedirs(os.path.dirname(PRESETS_FILE), exist_ok=True)
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_presets() -> list[dict]:
    """返回全部预设（按创建时间顺序）。"""
    return _read().get("presets", [])


def _snapshot_pipeline() -> dict:
    """当前生效的管道参数（settings.json 覆盖 > config 默认）。"""
    pipe = (get_current_settings().get("pipeline") or {})
    return {k: pipe.get(k) for k in PIPELINE_KEYS}


def create_preset(name: str, pipeline: dict | None = None) -> dict:
    """以当前生效参数为快照创建预设；pipeline 传值则使用给定值。"""
    name = str(name or "").strip()
    if not name:
        raise ValueError("预设名称不能为空")
    data = _read()
    presets = data.setdefault("presets", [])
    if any(p["name"] == name for p in presets):
        raise ValueError(f"预设名称已存在: {name}")

    preset = {
        "id": str(uuid.uuid4()),
        "name": name,
        "pipeline": pipeline if pipeline is not None else _snapshot_pipeline(),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    presets.append(preset)
    _write(data)
    logger.info("[Presets] created '%s' (%s)", name, preset["id"])
    return preset


def rename_preset(preset_id: str, name: str) -> dict:
    name = str(name or "").strip()
    if not name:
        raise ValueError("预设名称不能为空")
    data = _read()
    for p in data.get("presets", []):
        if p["id"] == preset_id:
            if any(x["name"] == name and x["id"] != preset_id for x in data["presets"]):
                raise ValueError(f"预设名称已存在: {name}")
            p["name"] = name
            _write(data)
            return p
    raise KeyError(f"预设不存在: {preset_id}")


def delete_preset(preset_id: str) -> None:
    data = _read()
    presets = data.get("presets", [])
    remaining = [p for p in presets if p["id"] != preset_id]
    if len(remaining) == len(presets):
        raise KeyError(f"预设不存在: {preset_id}")
    data["presets"] = remaining
    _write(data)
    logger.info("[Presets] deleted %s", preset_id)


def apply_preset(preset_id: str) -> dict:
    """套用预设：把其管道参数写入 settings.json 覆盖区，运行时生效。"""
    data = _read()
    preset = next((p for p in data.get("presets", []) if p["id"] == preset_id), None)
    if preset is None:
        raise KeyError(f"预设不存在: {preset_id}")
    update_settings({"pipeline": preset.get("pipeline", {})})
    logger.info("[Presets] applied '%s'", preset["name"])
    return preset
