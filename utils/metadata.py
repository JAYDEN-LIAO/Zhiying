"""
utils/metadata.py
═══════════════════════════════════════════════════════════
Video metadata extraction — technical params + device info.

Three-tier extraction with graceful degradation:
  1. pymediainfo  → full technical metadata (codec, resolution, bitrate, etc.)
  2. exiftool     → device info (GPS, make/model, creation timestamp)
  3. ffprobe      → fallback for basic format/stream info

All extractors run in try/except — never raises, always returns
whatever data was successfully extracted.
"""

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)


async def get_video_metadata(video_path: str) -> dict:
    """Extract all available metadata from a video file.

    Returns a flat dict suitable for API serialization.  Fields that
    could not be extracted are ``None`` (scalar) or empty list (streams).

    Returns::

        {
            "container": "MP4",
            "duration": 120.5,
            "file_size": 52428800,
            "video_streams": [{codec, resolution, fps, bitrate, ...}],
            "audio_streams": [{codec, channels, sample_rate, bitrate, ...}],
            "device": {make, model, software, gps_* } | None,
            "timestamps": {created, modified} | None,
            "raw": {...},
        }
    """
    if not os.path.exists(video_path):
        logger.warning("[Metadata] File not found: %s", video_path)
        return _empty_result()

    # ── Tier 1: pymediainfo (primary) ──
    mediainfo_data = await _extract_mediainfo(video_path)

    # ── Tier 2: exiftool (device / GPS supplement) ──
    exiftool_data = await _extract_exiftool(video_path)

    # ── Tier 3: ffprobe fallback (if pymediainfo returned nothing) ──
    ffprobe_data = None
    if mediainfo_data is None:
        ffprobe_data = await _extract_ffprobe(video_path)

    # ── Merge ──
    return _build_result(mediainfo_data, exiftool_data, ffprobe_data, video_path)


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
        general: dict = {}

        for track in raw.get("tracks", []):
            track_type = track.get("track_type", "")
            if track_type == "General":
                general = track
            elif track_type == "Video":
                video_streams.append(_parse_video_track(track))
            elif track_type == "Audio":
                audio_streams.append(_parse_audio_track(track))

        return {
            "container": general.get("format") or general.get("format_commercial"),
            "duration": _to_float(general.get("duration")),
            "file_size": _to_int(general.get("file_size")),
            "overall_bitrate": _to_int(general.get("overall_bit_rate")),
            "video_streams": video_streams,
            "audio_streams": audio_streams,
            "raw_mediainfo": raw,
        }
    except Exception:
        logger.warning("[Metadata] pymediainfo failed for %s", video_path, exc_info=True)
        return None


def _parse_video_track(track: dict) -> dict:
    """Extract key fields from a pymediainfo video track."""
    width = _to_int(track.get("width")) or _to_int(track.get("sampled_width"))
    height = _to_int(track.get("height")) or _to_int(track.get("sampled_height"))
    resolution = f"{width}x{height}" if width and height else None

    return {
        "codec": track.get("format") or track.get("codec_id"),
        "codec_profile": track.get("format_profile"),
        "resolution": resolution,
        "width": width,
        "height": height,
        "fps": _to_float(track.get("frame_rate")),
        "bitrate": _to_int(track.get("bit_rate")),
        "pixel_format": track.get("pixel_format") or track.get("chroma_subsampling"),
        "color_space": track.get("color_space"),
        "bit_depth": _to_int(track.get("bit_depth")),
        "display_aspect_ratio": track.get("display_aspect_ratio"),
        "rotation": _to_float(track.get("rotation")),
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


# ═══════════════════════════════════════════════════════════
# Tier 2: exiftool
# ═══════════════════════════════════════════════════════════

async def _extract_exiftool(video_path: str) -> dict | None:
    """Extract EXIF / GPS / device metadata via exiftool subprocess.

    Returns ``None`` if exiftool is not installed or fails.
    """
    # Quick check if exiftool is available
    try:
        proc = await asyncio.create_subprocess_exec(
            "exiftool", "-ver",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode != 0:
            logger.debug("[Metadata] exiftool not available")
            return None
    except FileNotFoundError:
        logger.debug("[Metadata] exiftool not installed")
        return None
    except PermissionError:
        logger.debug("[Metadata] exiftool not available (permission denied)")
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
    """Parse exiftool JSON output into structured device/timestamps dict."""
    device: dict = {}
    timestamps: dict = {}
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
            "pix_fmt,channels,sample_rate,bit_rate",
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

        video_streams: list[dict] = []
        audio_streams: list[dict] = []

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

                video_streams.append({
                    "codec": s.get("codec_name"),
                    "resolution": f"{w}x{h}" if w and h else None,
                    "width": w,
                    "height": h,
                    "fps": fps,
                    "pixel_format": s.get("pix_fmt"),
                    "bitrate": _to_int(s.get("bit_rate")),
                })
            elif codec_type == "audio":
                audio_streams.append({
                    "codec": s.get("codec_name"),
                    "channels": _to_int(s.get("channels")),
                    "sample_rate": _to_int(s.get("sample_rate")),
                    "bitrate": _to_int(s.get("bit_rate")),
                })

        return {
            "container": fmt.get("format_name"),
            "duration": _to_float(fmt.get("duration")),
            "file_size": _to_int(fmt.get("size")),
            "overall_bitrate": _to_int(fmt.get("bit_rate")),
            "video_streams": video_streams,
            "audio_streams": audio_streams,
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
    raw: dict = {}

    if exiftool:
        device = exiftool.get("device")
        timestamps = exiftool.get("timestamps")
        if exiftool.get("exif_raw"):
            raw["exiftool"] = exiftool["exif_raw"]
        if exiftool.get("extra"):
            raw["vendor_hints"] = exiftool["extra"]

    if mediainfo and "raw_mediainfo" in mediainfo:
        raw["mediainfo"] = mediainfo["raw_mediainfo"]

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
        "duration": tech.get("duration"),
        "file_size": tech.get("file_size"),
        "overall_bitrate": tech.get("overall_bitrate"),
        "video_streams": tech.get("video_streams", []),
        "audio_streams": tech.get("audio_streams", []),
        "device": device,
        "timestamps": timestamps,
        "raw": raw if raw else None,
    }


def _empty_result() -> dict:
    return {
        "container": None,
        "duration": None,
        "file_size": None,
        "overall_bitrate": None,
        "video_streams": [],
        "audio_streams": [],
        "device": None,
        "timestamps": None,
        "raw": None,
    }


# ═══════════════════════════════════════════════════════════
# Type coercion helpers
# ═══════════════════════════════════════════════════════════

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
