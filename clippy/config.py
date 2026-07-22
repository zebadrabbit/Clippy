"""
Package configuration facade.

Loads user settings via config_loader and exposes familiar module-level globals
used throughout the app (ffmpeg templates, binaries, paths, etc.).

New code should use ``get_config()`` to obtain the typed ``ClippyConfig``
dataclass instead of relying on module-level globals.  The globals are kept
for backwards compatibility during the migration period.

This file lives inside the clippy package; path resolution that previously
assumed repo root is adjusted accordingly.
"""

from __future__ import annotations

import dataclasses
import os
import sys
from typing import Any, Optional

from clippy.models import ClippyConfig

# Load merged config from YAML/env/defaults
try:
    from .config_loader import load_merged_config  # type: ignore

    _merged: dict[str, Any] = load_merged_config()
except Exception:  # broad fallback: config bootstrap must not crash
    _merged = {
        "yt_format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]",
        "bitrate": "12M",
        "audio_bitrate": "192k",
        "fps": "60",
        "resolution": "1920x1080",
        "nvenc_preset": "slow",
        "cq": "19",
        "gop": "120",
        "rc_lookahead": "20",
        "aq_strength": "8",
        "spatial_aq": "1",
        "temporal_aq": "1",
        "cache": "./cache",
        "output": "./output",
        "enable_overlay": True,
        "fontfile": "assets/fonts/Roboto-Medium.ttf",
    }

# Export merged values as module-level globals
globals().update(_merged)

# Ensure essentials exist
yt_format = globals().get(
    "yt_format", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]"
)

# Determine repository root (parent of this package directory)
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.abspath(os.path.join(_PKG_DIR, ".."))

# ffmpeg / downloader binaries (source-only)
# Try repo-level bin/ executables first, then fall back to PATH names.
_bin_ff = os.path.join(_REPO_DIR, "bin", "ffmpeg.exe")
ffmpeg = _bin_ff if os.path.exists(_bin_ff) else "ffmpeg"
_bin_fp = os.path.join(_REPO_DIR, "bin", "ffprobe.exe")
ffprobe = _bin_fp if os.path.exists(_bin_fp) else "ffprobe"
# yt-dlp preferred; fall back to youtube-dl if present in bin/
_bin_ytdlp = os.path.join(_REPO_DIR, "bin", "yt-dlp.exe")
_bin_youtubedl = os.path.join(_REPO_DIR, "bin", "youtube-dl.exe")
if os.path.exists(_bin_ytdlp):
    YTDL_BIN = _bin_ytdlp
elif os.path.exists(_bin_youtubedl):
    YTDL_BIN = _bin_youtubedl
else:
    YTDL_BIN = "yt-dlp"

# The font ships as package data under clippy/assets/fonts/, so an installed
# ``clippy`` finds it even outside the repo directory.
_PACKAGED_FONT = os.path.join(_PKG_DIR, "assets", "fonts", "Roboto-Medium.ttf")
_DEFAULT_FONT = "assets/fonts/Roboto-Medium.ttf"


def resolve_fontfile(value: Any = None) -> str:
    """Turn a configured font path into one that exists on this machine.

    Must run after *every* merge, not just at import: re-reading the config
    (switching profiles, for instance) puts the raw relative path back, and
    preflight then reports the overlay font as missing.
    """
    try:
        candidate = value if isinstance(value, str) and value else _DEFAULT_FONT
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        # A relative path is tried against the repo root first.
        under_repo = os.path.join(_REPO_DIR, candidate)
        if os.path.exists(under_repo):
            return under_repo
        # The packaged font only stands in for the default. A custom path that
        # does not exist is returned as-is so preflight can say so, rather than
        # silently swapping in Roboto and rendering the wrong typeface.
        if os.path.basename(candidate) == os.path.basename(_DEFAULT_FONT):
            if os.path.exists(_PACKAGED_FONT):
                return _PACKAGED_FONT
        return candidate
    except OSError:
        return _DEFAULT_FONT


fontfile = resolve_fontfile(globals().get("fontfile"))

container_ext = globals().get("container_ext", "mp4")
container_flags = globals().get("container_flags", "-movflags +faststart")
# youtube-dl stuff (yt-dlp). Legacy variable names retained.
youtubeDl = YTDL_BIN
youtubeDlOptions = (
    "--no-color --no-check-certificate --quiet --progress --retries 5 --socket-timeout 30 "
    "--ffmpeg-location {ffmpeg_path} "
    "--merge-output-format mp4 "
    "--format {yt_format} "
    "-o {cache}/{message_id}/clip.mp4"
)

# ---------------------------------------------------------------------------
# Typed config singleton (preferred for new code)
# ---------------------------------------------------------------------------

_CONFIG: Optional[ClippyConfig] = None


def get_config() -> ClippyConfig:
    """Return the canonical ClippyConfig singleton.

    Built lazily from the same merged dict that populates the module globals.
    Call ``set_config()`` to replace it (e.g. after CLI override merging).
    """
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = ClippyConfig.from_merged_dict(_merged)
    return _CONFIG


def set_config(cfg: ClippyConfig) -> None:
    """Replace the global config singleton and sync legacy globals."""
    global _CONFIG
    _CONFIG = cfg
    # Keep module-level globals in sync for code that still reads them
    flat = cfg.to_flat_dict()
    # A config built from a fresh merge carries the unresolved font path; never
    # let it overwrite a working one.
    flat["fontfile"] = resolve_fontfile(flat.get("fontfile"))
    globals().update(flat)
    if flat["fontfile"] != cfg.assets.fontfile:
        _CONFIG = dataclasses.replace(
            cfg, assets=dataclasses.replace(cfg.assets, fontfile=flat["fontfile"])
        )


def reload_with_profile(name: Optional[str]) -> ClippyConfig:
    """Re-read clippy.yaml with *name* applied and rebuild the typed config.

    The config module is imported long before argv is parsed, so ``--profile``
    cannot be honoured at import time. Re-running the merge is simpler and more
    predictable than trying to patch the already-built config section by section.
    """
    global _merged
    from .config_loader import load_merged_config

    _merged = load_merged_config(profile=name)
    globals().update(_merged)
    # The merge restores the raw relative font path; resolve it again.
    _merged["fontfile"] = resolve_fontfile(_merged.get("fontfile"))
    globals()["fontfile"] = _merged["fontfile"]
    cfg = ClippyConfig.from_merged_dict(_merged)
    set_config(cfg)
    return cfg


def refresh_from_globals() -> ClippyConfig:
    """Rebuild the typed config singleton from the current module-level globals.

    The legacy CLI path (``apply_cli_overrides``) mutates the module globals in
    place.  Calling this afterwards folds those overrides back into the typed
    ``ClippyConfig`` so the dataclass stays the single source of truth that the
    rest of the app reads from.  Values not modelled on ``ClippyConfig`` (binary
    paths, etc.) are left untouched on the module.
    """
    mod = sys.modules[__name__]
    # The flat dict keys are exactly the legacy global names the dataclass models.
    keys = ClippyConfig().to_flat_dict().keys()
    snapshot: dict[str, Any] = dict(_merged)
    for key in keys:
        if hasattr(mod, key):
            snapshot[key] = getattr(mod, key)
    cfg = ClippyConfig.from_merged_dict(snapshot)
    set_config(cfg)
    return cfg


# Initialise the singleton from the fully-resolved globals (e.g. absolute
# fontfile path) so get_config() is authoritative from the first read.
try:
    refresh_from_globals()
except Exception:  # config bootstrap must never crash the import
    pass
