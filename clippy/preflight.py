"""Friendly preflight checks.

Surface common setup problems in plain English *before* a run starts — each with
a concrete fix — instead of letting them blow up as a traceback (or a silent
ffmpeg failure) partway through. All checks run and report together so the user
can fix everything in one pass.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Issue:
    """A single preflight finding."""

    level: str  # "error" (blocks the run) or "warning" (proceed, but degraded)
    title: str
    fix: str


def _binary_available(path: str) -> bool:
    """True if *path* is a runnable executable (absolute path or found on PATH)."""
    if not path:
        return False
    if os.path.isabs(path) or os.sep in path or (os.altsep and os.altsep in path):
        return os.path.isfile(path)
    return shutil.which(path) is not None


#: Where to point someone who needs to install a binary by hand.
_BINARY_SOURCE = {
    "ffmpeg": "https://ffmpeg.org/download.html",
    "ffprobe": "https://ffmpeg.org/download.html",
    "yt-dlp": "https://github.com/yt-dlp/yt-dlp",
}


def _check_binaries() -> List[Issue]:
    from clippy import config as _cfg

    issues: List[Issue] = []
    for name, path in (
        ("ffmpeg", _cfg.ffmpeg),
        ("ffprobe", _cfg.ffprobe),
        ("yt-dlp", _cfg.youtubeDl),
    ):
        if not _binary_available(path):
            issues.append(
                Issue(
                    "error",
                    f"{name} not found ({path!r})",
                    f"Run 'clippy deps' to download {name} into ./bin, or install it yourself "
                    f"and put it on your PATH. Source: {_BINARY_SOURCE[name]}",
                )
            )
    if not issues and _cfg.ffmpeg:
        from clippy.ffmpeg import detect_encoder

        if detect_encoder(_cfg.ffmpeg) != "h264_nvenc":
            issues.append(
                Issue(
                    "warning",
                    "NVENC (h264_nvenc) not available — encoding will use libx264 on the CPU",
                    "This works but is slower. Needs an NVIDIA GPU plus an ffmpeg build "
                    "compiled with --enable-nvenc. Use --preset cpu_only to make it explicit.",
                )
            )
    return issues


def _check_credentials(discord_mode: bool) -> List[Issue]:
    issues: List[Issue] = []
    if discord_mode:
        if not os.getenv("DISCORD_TOKEN"):
            issues.append(
                Issue(
                    "error",
                    "Discord bot token missing (DISCORD_TOKEN)",
                    "Add DISCORD_TOKEN to .env (or run 'clippy setup'). Create a bot at "
                    "https://discord.com/developers/applications and enable the Message Content intent.",
                )
            )
        return issues

    if not os.getenv("TWITCH_CLIENT_ID") or not os.getenv("TWITCH_CLIENT_SECRET"):
        issues.append(
            Issue(
                "error",
                "Twitch credentials missing",
                "Run 'clippy setup', or set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET in .env. "
                "Create an app at https://dev.twitch.tv/console/apps",
            )
        )
    return issues


def _check_transitions() -> List[Issue]:
    from clippy.config import get_config
    from clippy.utils import resolve_transitions_dir

    issues: List[Issue] = []
    tdir = resolve_transitions_dir()
    static_name = get_config().assets.static
    static_path = os.path.join(tdir, static_name)
    if not os.path.isdir(tdir):
        issues.append(
            Issue(
                "error",
                f"Transitions folder not found: {tdir}",
                f"Run 'clippy deps' to fetch {static_name}, or create the folder yourself "
                "and add one (or pass --transitions-dir / set TRANSITIONS_DIR).",
            )
        )
    elif not os.path.isfile(static_path):
        issues.append(
            Issue(
                "error",
                f"Required file missing: {static_name} in {tdir}",
                f"Run 'clippy deps' to fetch the default {static_name}, or add your own "
                "(import one with scripts/import_media.py --type transition).",
            )
        )
    return issues


def _check_overlay_font() -> List[Issue]:
    from clippy.config import get_config

    cfg = get_config()
    if not cfg.behavior.enable_overlay:
        return []
    font = cfg.assets.fontfile
    if font and not os.path.isfile(font):
        return [
            Issue(
                "warning",
                f"Overlay font not found: {font}",
                "Creator-credit text may fail to render. Set assets.fontfile to a valid .ttf, "
                "or disable the overlay with --no-overlay.",
            )
        ]
    return []


def _check_output_writable() -> List[Issue]:
    from clippy.config import get_config

    out = get_config().paths.output
    try:
        os.makedirs(out, exist_ok=True)
        probe = os.path.join(out, ".clippy_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        return [
            Issue(
                "error",
                f"Output folder is not writable: {out}",
                f"Choose a writable location with --output-dir, or fix permissions ({e}).",
            )
        ]
    return []


def run_preflight(
    *,
    discord_mode: bool = False,
    require_credentials: bool = True,
    require_transitions: bool = True,
) -> List[Issue]:
    """Run all applicable checks and return the collected issues (errors + warnings)."""
    issues: List[Issue] = []
    issues += _check_binaries()
    if require_credentials:
        issues += _check_credentials(discord_mode)
    if require_transitions:
        issues += _check_transitions()
    issues += _check_overlay_font()
    issues += _check_output_writable()
    return issues


def report(issues: List[Issue], log: Optional[callable] = None) -> bool:
    """Print issues grouped by severity. Return True if any are errors (caller should abort)."""
    if log is None:
        from clippy.utils import log as _default_log

        log = _default_log

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    for issue in warnings:
        log("Heads up: " + issue.title, 2)
        log("  Fix: " + issue.fix, 1)

    for issue in errors:
        log(issue.title, 5)
        log("  Fix: " + issue.fix, 1)

    if errors:
        log(
            f"Preflight found {len(errors)} problem(s) to fix before running.",
            5,
        )
    return bool(errors)
