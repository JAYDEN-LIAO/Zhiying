"""
utils/video_source.py
═══════════════════════════════════════════════════════════
视频来源分析规则引擎 — 来源分类 + 监控品牌判断。

不依赖第三方库、无需 GPU、<10ms 完成。

输入：exiftool 原始 JSON + pymediainfo 流数据 + 文件名
输出：{source_type, source_label, confidence, evidence, surveillance_brand?, surveillance_method?}
"""

from __future__ import annotations

import re
from typing import Any

# ═══════════════════════════════════════════════════════════
# 已知品牌列表
# ═══════════════════════════════════════════════════════════

PHONE_BRANDS: set[str] = {
    "apple", "samsung", "xiaomi", "huawei", "oppo", "vivo", "oneplus",
    "google", "motorola", "lg", "sony", "nokia", "honor", "realme",
    "asus", "lenovo", "htc", "blackberry", "zte", "meizu",
    # 中文名（exiftool 可能输出本地化名称）
    "华为", "小米", "三星", "oppo", "vivo", "荣耀",
}

CAMERA_BRANDS: set[str] = {
    "canon", "nikon", "sony", "fujifilm", "panasonic", "olympus",
    "pentax", "leica", "sigma", "tamron", "zeiss", "gopro",
    "dji", "insta360", "blackmagic", "red", "arri", "phase one",
    "kodak", "casio", "ricoh",
    # 运动相机/无人机
    "gopro", "dji", "insta360",
}

SURVEILLANCE_BRANDS: dict[str, list[str]] = {
    "hikvision": [
        r"ch\d+_\d{14}\.mp4",          # ch01_20240615120000.mp4
        r"\d{14}\.mp4",                 # 20240615120000.mp4（海康最常见模式）
        r"ch\d+_\d{8}\.mp4",            # ch01_20240615.mp4（按日分段）
    ],
    "dahua": [
        r"\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.mp4",  # 2024-06-15 12-00-00.mp4
        r"\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}\.mp4",   # 2024_06_15_12_00_00.mp4
    ],
    "ezviz": [
        r".*ezviz.*\.mp4",              # 文件名含 ezviz
    ],
    "reolink": [
        r"\d{8}_\d{6}_\d+\.mp4",        # 20240615_120000_123.mp4
    ],
}


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _safe_get(metadata: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """安全地从嵌套 dict 中取值。"""
    for key in keys:
        if not isinstance(metadata, dict):
            return default
        metadata = metadata.get(key, {})
    return metadata if metadata is not None else default


def _normalize(value: str | None) -> str | None:
    """规范化字符串：小写、去空格。"""
    if not value:
        return None
    return value.strip().lower()


def _check_surveillance_pattern(file_name: str) -> tuple[str | None, str | None]:
    """通过文件名模式匹配监控品牌。返回 (brand, method)。"""
    for brand, patterns in SURVEILLANCE_BRANDS.items():
        for pat in patterns:
            if re.search(pat, file_name.strip(), re.IGNORECASE):
                return brand, "filename_pattern"
    return None, None


# ═══════════════════════════════════════════════════════════
# 来源分类决策树
# ═══════════════════════════════════════════════════════════

def classify_video_source(
    exif_data: dict[str, Any] | None = None,
    file_name: str = "",
    media_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """视频来源分类主入口。

    Args:
        exif_data: exiftool 原始 JSON 输出的解析 dict（含 Make/Model/GPS/旋转等）。
        file_name: 原始文件名。
        media_info: pymediainfo 提取的流信息（含编码器名、分辨率等）。

    Returns:
        {source_type, source_label, confidence, evidence, surveillance_brand?, surveillance_method?}
    """
    exif_data = exif_data or {}
    media_info = media_info or {}

    evidence: list[str] = []
    file_name_str = file_name or ""

    # ── 提取关键信号 ──
    make = _normalize(_safe_get(exif_data, "Make"))
    model = _normalize(_safe_get(exif_data, "Model"))
    has_gps = bool(
        _safe_get(exif_data, "GPSLatitude")
        or _safe_get(exif_data, "GPSPosition")
        or _safe_get(exif_data, "GPSLatitudeRef")
    )
    rotation = _safe_get(exif_data, "Rotation", default=0)
    handler_vendor = _normalize(_safe_get(exif_data, "HandlerVendorID"))
    compressor = _normalize(_safe_get(exif_data, "CompressorName"))
    encoder = _normalize(_safe_get(exif_data, "Encoder"))

    # 编码器关键词（来自 pymediainfo 或 exiftool）
    encoded_library = _normalize(
        _safe_get(media_info, "encoded_library", default="")
        or _safe_get(media_info, "writing_library", default="")
    )

    width = _safe_get(media_info, "width", default=0)
    height = _safe_get(media_info, "height", default=0)
    has_audio = media_info.get("has_audio", False) is True
    frame_rate = _safe_get(media_info, "frame_rate", default=0) or 0
    video_codec_str = _normalize(_safe_get(media_info, "video_codec", default="") or "")

    # ── P1: Make/Model 高可靠匹配 ──
    if make and model:
        # 相机品牌 → camera
        if make in CAMERA_BRANDS:
            evidence.append(f"Make={exif_data.get('Make')}, Model={exif_data.get('Model')}")
            return _result("camera", "high", evidence)

        # 手机品牌 + Apple 特定 handler → phone
        if make in PHONE_BRANDS:
            evidence.append(f"Make={exif_data.get('Make')}, Model={exif_data.get('Model')}")
            if handler_vendor == "appl":
                evidence.append("HandlerVendorID=appl")
                return _result("phone", "high", evidence)
            # 手机品牌 + GPS + 竖拍
            if has_gps:
                evidence.append("GPS数据存在")
                return _result("phone", "high", evidence)
            if rotation in (90, 270):
                evidence.append(f"旋转角度={rotation}°（竖拍）")
                return _result("phone", "high", evidence)
            return _result("phone", "medium", evidence)

    # ── P1: 软件编码器 → screen_recording（无 Make/Model） ──
    software_keywords = {"lavc", "x264", "x265", "obs", "ffmpeg", "screen", "quicktime",
                         "libx264", "libx265", "lavf", "swf"}
    if not make:
        encoder_text = _concat_encoders(compressor, encoder, encoded_library)
        if encoder_text:
            matched = {kw for kw in software_keywords if kw in encoder_text.lower()}
            if matched:
                evidence.append(f"编码器软件特征: {', '.join(sorted(matched))}")
                return _result("screen_recording", "medium", evidence)

    # ── P1: 监控文件名 → surveillance ──
    brand, method = _check_surveillance_pattern(file_name_str)
    if brand:
        evidence.append(f"文件名匹配 {brand} 模式")
        return _result("surveillance", "medium", evidence, brand, method)

    # ── P2: 手机品牌（次级匹配，无旋转/GPS） ──
    if make in PHONE_BRANDS:
        evidence.append(f"Make={exif_data.get('Make')}（手机品牌，设备元数据较弱）")
        return _result("phone", "medium", evidence)

    # ── P2: 分辨率 + 编码特征 —— 有音频→screen_recording，无音频→surveillance ──
    # 放宽宽高比限制：很多录屏/游戏录像是非标准分辨率（带鱼屏、窗口截取等）
    if width and height and not make and not has_gps and width >= 640:
        is_h264_family = "h264" in (video_codec_str or "") or "hevc" in (video_codec_str or "")
        if has_audio:
            evidence.append(f"分辨率 {width}×{height}，编码 {video_codec_str or '?'}，有音频")
            # 高 fps + 音频 + 非标准分辨率 → 大概率录屏/游戏录制
            if frame_rate and frame_rate > 30:
                evidence.append(f"高帧率 {frame_rate}fps（录屏/游戏典型特征）")
            return _result("screen_recording", "medium", evidence)
        else:
            # 无音频 → 监控（H.264/H.265 + 标准分辨率）
            if is_h264_family and width in {3840, 2560, 1920, 1280, 704, 640}:
                evidence.append(f"分辨率 {width}×{height}，编码 {video_codec_str}，无音频（监控典型）")
                return _result("surveillance", "low", evidence)
            evidence.append(f"分辨率 {width}×{height}，无音频，编码 {video_codec_str or '?'}")
            return _result("surveillance", "low", evidence)

    # ── P3: 非相机来源 ──
    if not make and not model and not has_gps:
        encoder_text = _concat_encoders(compressor, encoder, encoded_library, video_codec_str)
        if encoder_text:
            evidence.append(f"编码器/编码特征: {encoder_text}")
            return _result("non_camera_source", "low", evidence)
        # 没有任何元数据信号，但有分辨率信息
        if width and height:
            evidence.append(f"分辨率 {width}×{height}，无相机元数据/编码器信息")
            return _result("non_camera_source", "low", evidence)
        return _result("unknown", "low", ["全部相机元数据缺失，编码器信息不可用"])

    # ── P4: 兜底 ──
    return _result("unknown", "low", ["信息不足，无法判断"])


def classify_surveillance_brand(
    file_name: str, exif_data: dict[str, Any] | None = None
) -> tuple[str | None, str | None]:
    """判断监控品牌。返回 (brand, method)，未命中则 (None, None)。

    优先级: 文件名模式 > 元数据特征 > 编码器特征。
    """
    # P1: 文件名模式
    brand, method = _check_surveillance_pattern(file_name)
    if brand:
        return brand, method

    # P2: 元数据特征
    exif_data = exif_data or {}
    handler = _normalize(_safe_get(exif_data, "HandlerVendorID"))
    if handler:
        brand_map = {
            "hik": "hikvision",
            "dah": "dahua",
        }
        for prefix, brand_name in brand_map.items():
            if handler.startswith(prefix):
                return brand_name, "metadata"

    return None, None


# ═══════════════════════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════════════════════

_SOURCE_LABELS: dict[str, str] = {
    "phone": "手机视频",
    "camera": "摄像机拍摄",
    "screen_recording": "屏幕录制",
    "surveillance": "监控视频",
    "non_camera_source": "非摄像头拍摄（录屏/重编码/AI生成等）",
    "unknown": "未知",
}

_SURVEILLANCE_BRAND_LABELS: dict[str, str] = {
    "hikvision": "海康威视",
    "dahua": "大华",
    "ezviz": "萤石",
    "reolink": "Reolink",
    "xiaomi": "小米",
    "tplink": "TP-Link",
    "uniview": "宇视",
    "generic_ip": "通用网络摄像头",
    "unknown": "未知",
}


def _result(
    source_type: str,
    confidence: str,
    evidence: list[str],
    surveillance_brand: str | None = None,
    surveillance_method: str | None = None,
) -> dict[str, Any]:
    """构造标准化的来源分析结果。"""
    return {
        "source_type": source_type,
        "source_label": _SOURCE_LABELS.get(source_type, "未知"),
        "confidence": confidence,
        "evidence": evidence,
        "surveillance_brand": surveillance_brand,
        "surveillance_method": surveillance_method,
    }


def _concat_encoders(*args: str | None) -> str:
    """拼接多个编码器字段，去空去重。"""
    seen: set[str] = set()
    parts: list[str] = []
    for a in args:
        if a and a not in seen:
            seen.add(a)
            parts.append(a)
    return " ".join(parts)
