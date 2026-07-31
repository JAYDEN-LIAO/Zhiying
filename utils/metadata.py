"""
utils/metadata.py
═══════════════════════════════════════════════════════════
Video metadata extraction — technical params + device info.

Three-tier extraction with graceful degradation:
  1. pymediainfo  → full technical metadata (codec, resolution, bitrate, HDR, etc.)
  2. exiftool     → device info (GPS, make/model, creation timestamp)
  3. ffprobe      → fallback for basic format/stream info

All extractors run in try/except — never raises, always returns
whatever data was successfully extracted.

Shared classification functions (classify_container / classify_codec)
are used by FormatService to ensure consistent naming everywhere.
"""

import asyncio
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# Module-level caches
# ═══════════════════════════════════════════════════════════

# Cache metadata results keyed by file_path. Video metadata is
# immutable once extracted (files never change), so no TTL needed.
# Bump this version when the metadata schema or extraction logic changes
# in a way that makes cached data invalid.
_METADATA_CACHE_VERSION = 4  # v4: 来源分析接入文件头魔数嗅探 + 修复 file_name 传递（原为 UUID 存储名）

_metadata_cache: dict[str, dict] = {}

# exiftool availability — checked once per process lifetime
_exiftool_available: bool | None = None


# ═══════════════════════════════════════════════════════════
# Shared classification helpers
# ═══════════════════════════════════════════════════════════

def classify_container(raw: str | None) -> str | None:
    """Normalise ffprobe/pymediainfo format_name to a short identifier.

    Used by both metadata extraction and FormatService so container
    names are consistent across all API surfaces.

    >>> classify_container("mov,mp4,m4a,3gp,3g2,mj2")
    'mov'
    >>> classify_container("matroska,webm")
    'webm'
    """
    if not raw:
        return None
    raw_lower = raw.lower()
    if "mp4" in raw_lower or "mpeg-4" in raw_lower:
        # MOV is ISOBMFF-compatible; distinguish for remux decision
        if "mov" in raw_lower and "mp4" not in raw_lower:
            return "mov"
        return "mp4"
    if "mpegts" in raw_lower:
        return "mpeg_ts"
    if "mpegps" in raw_lower or "mpeg" in raw_lower:
        return "mpeg_ps"
    if "matroska" in raw_lower or "webm" in raw_lower:
        if "webm" in raw_lower:
            return "webm"
        return "mkv"
    if "avi" in raw_lower:
        return "avi"
    if "flv" in raw_lower:
        return "flv"
    if "asf" in raw_lower or "wmv" in raw_lower:
        return "wmv"
    if "ogg" in raw_lower:
        return "ogg"
    if "h264" in raw_lower or "hevc" in raw_lower or "avc" in raw_lower:
        return "raw"
    return raw_lower.split(",")[0].strip()


def classify_codec(raw: str | None) -> str | None:
    """Normalise codec name to a short identifier.

    >>> classify_codec("hevc")
    'hevc'
    >>> classify_codec("h265")
    'hevc'
    """
    if not raw:
        return None
    mapping: dict[str, str] = {
        "h264": "h264",
        "avc": "h264",
        "hevc": "hevc",
        "h265": "hevc",
        "av1": "av1",
        "vp9": "vp9",
        "vp8": "vp8",
        "mpeg4": "mpeg4",
        "msmpeg4v3": "mpeg4",
        "wmv3": "wmv3",
        "wmv2": "wmv3",
        "vc1": "wmv3",
        "prores": "prores",
        "rawvideo": "raw",
    }
    return mapping.get(raw.lower(), raw.lower())


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════

async def get_video_metadata(
    video_path: str,
    *,
    use_cache: bool = True,
    verbose: bool = False,
) -> dict:
    """Extract all available metadata from a video file.

    Args:
        video_path: Absolute path to the video file.
        use_cache: If True (default), return cached result for this path.
        verbose: If True, include ``raw`` key with full extractor output.

    Returns a dict suitable for API serialization.  Fields that
    could not be extracted are ``None`` (scalar) or empty list (streams).
    """
    if not os.path.exists(video_path):
        logger.warning("[Metadata] File not found: %s", video_path)
        return _empty_result()

    # ── Check cache ──
    cache_key = os.path.realpath(video_path)
    if use_cache and cache_key in _metadata_cache:
        result = _metadata_cache[cache_key]
        if not verbose:
            result = {**result, "raw": None}
        return result

    # ── Tier 1: pymediainfo (primary) ──
    mediainfo_data = await _extract_mediainfo(video_path)

    # ── Tier 2: exiftool (device / GPS supplement) ──
    exiftool_data = await _extract_exiftool(video_path)

    # ── Tier 3: ffprobe fallback (if pymediainfo returned nothing) ──
    ffprobe_data = None
    if mediainfo_data is None:
        ffprobe_data = await _extract_ffprobe(video_path)

    # ── Merge ──
    result = _build_result(mediainfo_data, exiftool_data, ffprobe_data, video_path)

    # ── Store in cache ──
    if use_cache:
        _metadata_cache[cache_key] = result

    if not verbose:
        result = {**result, "raw": None}

    return result


def clear_metadata_cache(video_path: str | None = None) -> None:
    """Clear the in-memory metadata cache.

    Args:
        video_path: If given, clear only that entry. Otherwise clear all.
    """
    if video_path:
        _metadata_cache.pop(os.path.realpath(video_path), None)
    else:
        _metadata_cache.clear()


# ═══════════════════════════════════════════════════════════
# Tier 1: pymediainfo
# ═══════════════════════════════════════════════════════════

async def _extract_mediainfo(video_path: str) -> dict | None:
    """Extract full technical metadata via pymediainfo (MediaInfo library).

    Runs in a thread because pymediainfo is synchronous.
    """
    try:
        from pymediainfo import MediaInfo

        def _run() -> dict:
            info = MediaInfo.parse(video_path)
            return info.to_data()  # type: ignore[no-any-return]

        raw = await asyncio.to_thread(_run)

        # Parse tracks
        video_streams: list[dict] = []
        audio_streams: list[dict] = []
        subtitle_streams: list[dict] = []
        general: dict = {}

        for track in raw.get("tracks", []):
            track_type = track.get("track_type", "")
            if track_type == "General":
                general = track
            elif track_type == "Video":
                video_streams.append(_parse_video_track(track))
            elif track_type == "Audio":
                audio_streams.append(_parse_audio_track(track))
            elif track_type == "Text":
                subtitle_streams.append(_parse_text_track(track))

        # Container classification — use shared normaliser for consistency.
        # Build a composite hint: MediaInfo format + codec_id to distinguish
        # MOV (codec_id "qt") from MP4 (codec_id "isom"/"mp42") — both report
        # "MPEG-4" as format, but the codec_id reveals the actual container.
        raw_format = general.get("format") or general.get("format_commercial") or ""
        codec_id = general.get("codec_id", "")
        if "qt" in codec_id.lower():
            classify_hint = f"{raw_format} mov"
        else:
            classify_hint = raw_format
        format_name = general.get("format")  # e.g. "MPEG-4"
        container = classify_container(classify_hint)

        # Encoder — try MediaInfo first, exiftool will supplement
        encoder = general.get("encoded_library") or general.get("writing_library")

        # pymediainfo reports duration in MILLISECONDS (int).
        # Confirmed: doctest in pymediainfo __init__.py shows t.duration → 3000 for 3 s.
        # MediaInfo XML always has Duration in ms; pymediainfo's to_data() passes
        # the raw int through without /1000 conversion.
        duration_ms = _to_float(general.get("duration"))
        duration_sec = (duration_ms / 1000.0) if duration_ms is not None else None

        return {
            "container": container,
            "format_name": format_name,
            "duration": duration_sec,
            "file_size": _to_int(general.get("file_size")),
            "overall_bitrate": _to_int(general.get("overall_bit_rate")),
            "video_streams": video_streams,
            "audio_streams": audio_streams,
            "subtitle_streams": subtitle_streams,
            "encoder": str(encoder) if encoder else None,
            "raw_mediainfo": raw,
        }
    except Exception:
        logger.warning("[Metadata] pymediainfo failed for %s", video_path, exc_info=True)
        return None


def _parse_video_track(track: dict) -> dict:
    """Extract key fields from a pymediainfo video track (including HDR)."""
    width = _to_int(track.get("width")) or _to_int(track.get("sampled_width"))
    height = _to_int(track.get("height")) or _to_int(track.get("sampled_height"))
    resolution = f"{width}x{height}" if width and height else None

    # Codec classification for consistency
    codec_raw = track.get("format") or track.get("codec_id")
    codec = classify_codec(codec_raw)

    # HDR & colour metadata
    color_space = track.get("color_space")
    color_primaries = track.get("color_primaries")
    transfer = track.get("transfer_characteristics")
    chroma = track.get("chroma_subsampling")

    # Codec level & tier (e.g. HEVC Main@L4@Main → level=4, tier=Main)
    codec_level = _to_str(track.get("format_level"))
    codec_tier = _to_str(track.get("format_tier"))

    return {
        "codec": codec,
        "codec_profile": track.get("format_profile"),
        "codec_level": codec_level,
        "codec_tier": codec_tier,
        "resolution": resolution,
        "width": width,
        "height": height,
        "fps": _to_float(track.get("frame_rate")),
        "bitrate": _to_int(track.get("bit_rate")),
        # pixel_format is an ffmpeg/ffprobe concept (e.g. "yuv420p").
        # pymediainfo has chroma_subsampling (e.g. "4:2:0") which is a
        # different level of description; keep them separate.
        "pixel_format": _to_str(track.get("pixel_format")),
        "color_space": color_space,
        "color_primaries": color_primaries,
        "transfer_characteristics": transfer,
        "chroma_subsampling": chroma,
        "bit_depth": _to_int(track.get("bit_depth")),
        "display_aspect_ratio": track.get("display_aspect_ratio"),
        "rotation": _to_float(track.get("rotation")),
        "encoder": None,  # filled later from General track or exiftool
    }


def _parse_audio_track(track: dict) -> dict:
    """Extract key fields from a pymediainfo audio track."""
    return {
        "codec": track.get("format") or track.get("codec_id"),
        "channels": _to_int(track.get("channels")),
        "channel_layout": track.get("channel_layout") or track.get("channel_positions"),
        "sample_rate": _to_int(track.get("sampling_rate")),
        "bitrate": _to_int(track.get("bit_rate")),
        "language": track.get("language"),
    }


def _parse_text_track(track: dict) -> dict:
    """Extract key fields from a pymediainfo text/subtitle track."""
    return {
        "format": track.get("format") or track.get("codec_id"),
        "language": track.get("language"),
        "title": track.get("title"),
        "forced": str(track.get("forced", "")).lower() in ("yes", "true", "1"),
    }


# ═══════════════════════════════════════════════════════════
# Tier 2: exiftool
# ═══════════════════════════════════════════════════════════

async def _exiftool_is_available() -> bool:
    """Check once whether exiftool is installed (cached at module level)."""
    global _exiftool_available
    if _exiftool_available is not None:
        return _exiftool_available
    try:
        proc = await asyncio.create_subprocess_exec(
            "exiftool", "-ver",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        _exiftool_available = proc.returncode == 0
    except (FileNotFoundError, PermissionError):
        _exiftool_available = False
    if not _exiftool_available:
        logger.debug("[Metadata] exiftool not available")
    return _exiftool_available


async def _extract_exiftool(video_path: str) -> dict | None:
    """Extract EXIF / GPS / device metadata via exiftool subprocess.

    Returns ``None`` if exiftool is not installed or fails.
    """
    if not await _exiftool_is_available():
        return None

    try:
        cmd = [
            "exiftool", "-json", "-g", "-struct",
            "-GPSLatitude", "-GPSLongitude", "-GPSAltitude",
            "-GPSPosition",
            "-Make", "-Model", "-Software",
            "-CreateDate", "-ModifyDate", "-MediaCreateDate", "-MediaModifyDate",
            "-ImageWidth", "-ImageHeight",
            "-CompressorID", "-CompressorName",
            "-HandlerVendorID",
            "-AndroidVersion", "-CameraElevationAngle",
            video_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode(errors="replace")[:300]
            logger.warning("[Metadata] exiftool error: %s", error_msg)
            return None

        data = json.loads(stdout.decode())
        if not data or not isinstance(data, list):
            return None

        entry = data[0]
        return _parse_exiftool(entry)

    except (json.JSONDecodeError, Exception):
        logger.warning("[Metadata] exiftool parse failed for %s", video_path, exc_info=True)
        return None


def _parse_exiftool(entry: dict) -> dict:
    """Parse exiftool JSON output into structured device/timestamps/encoder dict."""
    device: dict = {}
    timestamps: dict = {}
    encoder: str | None = None
    extra: dict = {}

    # GPS
    gps: dict = {}
    for key in ("GPSLatitude", "GPSLongitude", "GPSAltitude", "GPSPosition"):
        val = entry.get(key)
        if val:
            gps[key.lower().replace("gps", "gps_")] = val
    if gps:
        device.update({k.replace("gps_", ""): v for k, v in gps.items()})

    # Device identity — check common EXIF groups
    for group_key in ("EXIF:", "QuickTime:", "XMP:", ""):
        prefix = group_key
        make = entry.get(f"{prefix}Make") or entry.get("Make")
        model = entry.get(f"{prefix}Model") or entry.get("Model")
        software = entry.get(f"{prefix}Software") or entry.get("Software")
        if make or model:
            if make:
                device["make"] = make
            if model:
                device["model"] = model
            if software:
                device["software"] = software
            break

    # Encoder info — prefer CompressorName (e.g. "Lavc60.31.102 libx265")
    for key in ("CompressorName", "CompressorID"):
        val = entry.get(key)
        if val:
            encoder = str(val)
            break

    # Timestamps — prefer media timestamps, fall back to filesystem
    for key in ("MediaCreateDate", "CreateDate", "MediaModifyDate", "ModifyDate"):
        val = entry.get(key)
        if val and "created" not in timestamps and "Create" in key:
            timestamps["created"] = str(val)
        elif val and "modified" not in timestamps and "Modify" in key:
            timestamps["modified"] = str(val)

    # Vendor-specific fields for future parsing
    for key in ("HandlerVendorID", "CompressorID", "CompressorName",
                "AndroidVersion", "CameraElevationAngle"):
        val = entry.get(key)
        if val:
            extra[key] = val

    return {
        "device": device if device else None,
        "timestamps": timestamps if timestamps else None,
        "encoder": encoder,
        "exif_raw": entry,
        "extra": extra if extra else None,
    }


# ═══════════════════════════════════════════════════════════
# Tier 3: ffprobe fallback
# ═══════════════════════════════════════════════════════════

async def _extract_ffprobe(video_path: str) -> dict | None:
    """Extract basic format/stream info via ffprobe (if pymediainfo failed)."""
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration,size,format_name,bit_rate"
            ":stream=codec_name,codec_type,width,height,r_frame_rate,"
            "pix_fmt,channels,sample_rate,bit_rate,color_space,color_primaries,"
            "color_transfer,chroma_location,profile,level",
            "-of", "json",
            video_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode != 0:
            logger.warning("[Metadata] ffprobe failed for %s", video_path)
            return None

        data = json.loads(stdout.decode())

        fmt = data.get("format", {})
        streams = data.get("streams", [])

        raw_format = fmt.get("format_name", "")
        container = classify_container(raw_format)
        format_name = raw_format

        video_streams: list[dict] = []
        audio_streams: list[dict] = []
        subtitle_streams: list[dict] = []

        for s in streams:
            codec_type = s.get("codec_type", "")
            if codec_type == "video":
                w = s.get("width")
                h = s.get("height")
                fps_str = s.get("r_frame_rate", "0/1")
                try:
                    num, den = fps_str.split("/")
                    fps = float(num) / float(den) if float(den) != 0 else None
                except (ValueError, ZeroDivisionError):
                    fps = None

                codec_raw = s.get("codec_name", "")
                codec = classify_codec(codec_raw)

                video_streams.append({
                    "codec": codec,
                    "codec_profile": _to_str(s.get("profile")),
                    "codec_level": _to_str(s.get("level")),
                    "codec_tier": None,
                    "resolution": f"{w}x{h}" if w and h else None,
                    "width": w,
                    "height": h,
                    "fps": fps,
                    "pixel_format": s.get("pix_fmt"),
                    "color_space": s.get("color_space"),
                    "color_primaries": s.get("color_primaries"),
                    "transfer_characteristics": s.get("color_transfer"),
                    "chroma_subsampling": s.get("chroma_location"),
                    "bit_depth": _to_int(s.get("bits_per_raw_sample")),
                    "display_aspect_ratio": s.get("display_aspect_ratio"),
                    "rotation": None,
                    "bitrate": _to_int(s.get("bit_rate")),
                    "encoder": None,
                })
            elif codec_type == "audio":
                audio_streams.append({
                    "codec": s.get("codec_name"),
                    "channels": _to_int(s.get("channels")),
                    "channel_layout": s.get("channel_layout"),
                    "sample_rate": _to_int(s.get("sample_rate")),
                    "bitrate": _to_int(s.get("bit_rate")),
                    "language": s.get("tags", {}).get("language") if s.get("tags") else None,
                })
            elif codec_type == "subtitle":
                tags = s.get("tags", {}) or {}
                subtitle_streams.append({
                    "format": s.get("codec_name"),
                    "language": tags.get("language"),
                    "title": tags.get("title"),
                    "forced": False,
                })

        return {
            "container": container,
            "format_name": format_name,
            "duration": _to_float(fmt.get("duration")),
            "file_size": _to_int(fmt.get("size")),
            "overall_bitrate": _to_int(fmt.get("bit_rate")),
            "video_streams": video_streams,
            "audio_streams": audio_streams,
            "subtitle_streams": subtitle_streams,
            "encoder": None,
        }
    except Exception:
        logger.warning("[Metadata] ffprobe failed for %s", video_path, exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════
# Merge helpers
# ═══════════════════════════════════════════════════════════

def _build_result(
    mediainfo: dict | None,
    exiftool: dict | None,
    ffprobe: dict | None,
    video_path: str,
) -> dict:
    """Merge results from all extractors into the final output dict."""
    tech = mediainfo or ffprobe or {}

    device = None
    timestamps = None
    encoder = tech.get("encoder")  # MediaInfo encoder (may be overridden by exiftool)
    raw: dict = {}

    if exiftool:
        device = exiftool.get("device")
        timestamps = exiftool.get("timestamps")
        # exiftool encoder takes priority (more detailed, e.g. "Lavc60 libx265")
        if exiftool.get("encoder"):
            encoder = exiftool["encoder"]
        if exiftool.get("exif_raw"):
            raw["exiftool"] = exiftool["exif_raw"]
        if exiftool.get("extra"):
            raw["vendor_hints"] = exiftool["extra"]

    if mediainfo and "raw_mediainfo" in mediainfo:
        raw["mediainfo"] = mediainfo["raw_mediainfo"]

    # Inject encoder into first video stream
    video_streams = tech.get("video_streams", [])
    if encoder and video_streams:
        video_streams[0]["encoder"] = encoder

    # Filesystem timestamps as last resort
    if not timestamps:
        try:
            stat = os.stat(video_path)
            from datetime import datetime, timezone
            timestamps = {
                "created": datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        except OSError:
            pass

    return {
        "container": tech.get("container"),
        "format_name": tech.get("format_name"),
        "duration": tech.get("duration"),
        "file_size": tech.get("file_size"),
        "overall_bitrate": tech.get("overall_bitrate"),
        "video_streams": video_streams,
        "audio_streams": tech.get("audio_streams", []),
        "subtitle_streams": tech.get("subtitle_streams", []),
        "device": device,
        "timestamps": timestamps,
        "raw": raw if raw else None,
    }


def _empty_result() -> dict:
    return {
        "container": None,
        "format_name": None,
        "duration": None,
        "file_size": None,
        "overall_bitrate": None,
        "video_streams": [],
        "audio_streams": [],
        "subtitle_streams": [],
        "device": None,
        "timestamps": None,
        "raw": None,
    }


# ═══════════════════════════════════════════════════════════
# Type coercion helpers
# ═══════════════════════════════════════════════════════════

def _to_str(value) -> str | None:
    """Coerce a value to string, returning None for None/empty.

    Handles ffprobe integer levels (e.g. level=120 → "120") and
    pymediainfo string levels (e.g. "4.0").
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        s = str(value)
        return s if s.strip() else None
    except (ValueError, TypeError):
        return None


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None
