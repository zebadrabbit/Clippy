"""Encoding presets for common use-cases.

Each preset is a frozen ``EncoderParams`` instance that can be used directly
or customized via ``EncoderParams.with_overrides()``.  The TUI quality
screen and ``--preset`` CLI flag both consume these.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from clippy.ffmpeg import EncoderParams


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

PRESETS: Dict[str, EncoderParams] = {
    "youtube_1080p60": EncoderParams(
        video_codec="h264_nvenc",
        cq=19,
        max_bitrate="12M",
        buf_size="12M",
        gop=120,
        preset="slow",
        resolution="1920x1080",
        fps="60",
        audio_bitrate="192k",
        container_ext="mp4",
        container_flags="-movflags +faststart",
        name="youtube_1080p60",
        description="YouTube 1080p60 — balanced quality and file size",
    ),
    "discord_friendly": EncoderParams(
        video_codec="h264_nvenc",
        cq=23,
        max_bitrate="8M",
        buf_size="8M",
        gop=60,
        preset="medium",
        resolution="1280x720",
        fps="30",
        audio_bitrate="128k",
        container_ext="mp4",
        container_flags="-movflags +faststart",
        name="discord_friendly",
        description="Discord-friendly — targets <100 MB for ~2 min clips",
    ),
    "archive_hq": EncoderParams(
        video_codec="h264_nvenc",
        cq=16,
        max_bitrate="20M",
        buf_size="20M",
        gop=120,
        preset="slow",
        resolution="1920x1080",
        fps="60",
        audio_bitrate="256k",
        container_ext="mkv",
        container_flags="",
        name="archive_hq",
        description="Archive high quality — best visual fidelity, larger files",
    ),
    "quick_preview": EncoderParams(
        video_codec="h264_nvenc",
        cq=28,
        max_bitrate="4M",
        buf_size="4M",
        gop=60,
        preset="fast",
        resolution="1280x720",
        fps="30",
        audio_bitrate="128k",
        container_ext="mp4",
        container_flags="-movflags +faststart",
        name="quick_preview",
        description="Quick preview — fast encode, lower quality for review",
    ),
    "cpu_only": EncoderParams(
        video_codec="libx264",
        cq=19,
        max_bitrate="12M",
        buf_size="12M",
        gop=120,
        preset="medium",
        resolution="1920x1080",
        fps="60",
        audio_bitrate="192k",
        container_ext="mp4",
        container_flags="-movflags +faststart",
        name="cpu_only",
        description="CPU encoding (libx264) — no GPU required",
    ),
}


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def from_preset(name: str) -> EncoderParams:
    """Return a copy of the named preset.

    Raises ``KeyError`` if the name is not recognized.
    """
    if name not in PRESETS:
        available = ", ".join(sorted(PRESETS.keys()))
        raise KeyError(f"Unknown preset '{name}'. Available: {available}")
    # Return a fresh copy so callers can mutate via with_overrides
    return PRESETS[name].with_overrides()


def list_presets() -> List[Tuple[str, str]]:
    """Return ``(name, description)`` pairs for all presets."""
    return [(name, p.description) for name, p in PRESETS.items()]


def preset_names() -> List[str]:
    """Return just the preset name strings."""
    return list(PRESETS.keys())
