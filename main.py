"""Standalone entrypoint that bypasses Discord and ingests Twitch clips directly.

Usage (PowerShell):
  $env:TWITCH_CLIENT_ID="xxxxx"; $env:TWITCH_CLIENT_SECRET="yyyyy"
  python main_twitch.py --broadcaster somechannel --max-clips 40 --clips 10 --compilations 2

Optional time window:
  --start 2025-07-01T00:00:00Z --end 2025-07-07T00:00:00Z

Reuses the existing processing pipeline from `main.py` (download, normalize,
overlay, concat) by inserting Helix clip metadata into the existing Messages
table, mapping view_count -> reactions.
"""

from __future__ import annotations

import argparse
import time
import os
import re
import shutil
import sys
from typing import List, Tuple, Optional
from datetime import datetime, timedelta, timezone

from config import *  # noqa: F401,F403
from utils import log, prep_work
import utils as utils_mod
from twitch_ingest import (
    load_credentials,
    get_app_access_token,
    resolve_user,
    fetch_clips,
    build_clip_rows,
    fetch_creator_avatars,
)

# Import processing helpers from existing main module
from pipeline import create_compilations_from, stage_one, stage_two  # DB removed
import pipeline as pipeline_mod


def parse_args():
    class WideHelp(argparse.HelpFormatter):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("max_help_position", 32)
            kwargs.setdefault("width", 110)
            super().__init__(*args, **kwargs)

    p = argparse.ArgumentParser(
        description="Build Twitch clip compilations (no Discord)",
        formatter_class=WideHelp,
    )

    # Required / identity
    g_required = p.add_argument_group("Required")
    g_required.add_argument("--broadcaster", required=True, help="Broadcaster login name (e.g. theflood)")
    g_required.add_argument("--client-id", dest="client_id", help="Twitch Client ID (else TWITCH_CLIENT_ID env)")
    g_required.add_argument("--client-secret", dest="client_secret", help="Twitch Client Secret (else env)")

    # Window and selection
    g_window = p.add_argument_group("Window & selection")
    g_window.add_argument("--start", help="Start date (MM/DD/YYYY). Interpreted as 00:00:00Z of that day.")
    g_window.add_argument("--end", help="End date (MM/DD/YYYY). Interpreted as 23:59:59Z of that day.")
    g_window.add_argument("--min-views", dest="reactionThreshold", type=int, default=reactionThreshold, help="Minimum view count (maps to reactions)")
    g_window.add_argument("--max-clips", type=int, default=100, help="Max clips to fetch before filtering")
    g_window.add_argument("--clips", dest="amountOfClips", type=int, default=amountOfClips, help="Clips per compilation")
    g_window.add_argument("--compilations", dest="amountOfCompilations", type=int, default=amountOfCompilations, help="Number of compilations to create")
    g_window.add_argument("--auto-expand", action="store_true", help="If not enough clips, auto-expand the start date backwards in steps to gather more")
    g_window.add_argument("--expand-step-days", type=int, default=7, help="How many days to extend the lookback per expansion step (default 7)")
    g_window.add_argument("--max-lookback-days", type=int, default=90, help="Maximum total lookback from the end date when auto-expanding (default 90)")
    g_window.add_argument("--seed", type=int, help="Random seed for reproducible intro/outro/transition selection")

    # Output & formatting
    g_output = p.add_argument_group("Output & formatting")
    g_output.add_argument("--quality", choices=["balanced", "high", "max"], help="Quality preset that adjusts bitrate (overridden by --bitrate)")
    g_output.add_argument("--bitrate", help="Override video bitrate target, e.g. 12M")
    g_output.add_argument("--resolution", help="Override output resolution, e.g. 1920x1080 or 1280x720")
    g_output.add_argument("--format", choices=["mp4", "mkv"], help="Container format for final output")
    g_output.add_argument("--fps", type=str, help="Override output framerate, e.g. 60")
    g_output.add_argument("--audio-bitrate", dest="audio_bitrate", type=str, help="Override audio bitrate, e.g. 192k")
    g_output.add_argument("--yt-format", dest="yt_format", type=str, help="yt-dlp --format string override")
    g_output.add_argument("--overwrite-output", action="store_true", help="Overwrite existing files in output (else auto-suffix _1, _2, ...)")

    # Transitions & sequencing
    g_trans = p.add_argument_group("Transitions & sequencing")
    g_trans.add_argument("--intro", type=str, help="Override: single intro filename (transitions/) to force a specific intro for this run")
    g_trans.add_argument("--outro", type=str, help="Override: single outro filename (transitions/) to force a specific outro for this run")
    g_trans.add_argument("--transition", type=str, help="Override: single transition filename used when chosen; static is always placed between segments")
    g_trans.add_argument("--transition-prob", dest="transition_prob", type=float, help="Probability 0..1 to insert a random transition between clips (default from config)")
    g_trans.add_argument("--no-random-transitions", action="store_true", help="Disable random transitions (keeps static-only between clips)")
    g_trans.add_argument("--transitions-dir", dest="transitions_dir", type=str, help="Path to transitions directory (overrides env and defaults)")
    g_trans.add_argument("--rebuild-transitions", action="store_true", help="Force re-encode of transitions assets into cache/_trans")
    g_trans.add_argument("--no-audio-normalize-transitions", action="store_true", help="Disable loudness normalization for transitions normalization")

    # Performance & robustness
    g_perf = p.add_argument_group("Performance & robustness")
    g_perf.add_argument("--max-concurrency", type=int, help="Max workers for download/normalize stage")
    g_perf.add_argument("--skip-bad-clip", action="store_true", help="Skip failed clips instead of aborting")
    g_perf.add_argument("--no-overlay", action="store_true", help="Disable overlay stage for speed")
    g_perf.add_argument("--rebuild", action="store_true", help="Force rebuild even if intermediate files exist")

    # Cache management
    g_cache = p.add_argument_group("Cache management")
    g_cache.add_argument("--cache-dir", dest="cache_dir", type=str, help="Cache directory path")
    g_cache.add_argument("--output-dir", dest="output_dir", type=str, help="Output directory path")
    g_cache.add_argument("--keep-cache", action="store_true", help="Do not delete per-clip cache after finishing")
    g_cache.add_argument("--purge-cache", action="store_true", help="Purge entire cache after run (ignore --keep-cache and cache_preserve_dirs)")

    # Encoder tuning (NVENC)
    g_nvenc = p.add_argument_group("Encoder (NVENC) tuning")
    g_nvenc.add_argument("--cq", type=str, help="NVENC constant quality (lower is higher quality)")
    g_nvenc.add_argument("--preset", dest="nvenc_preset", type=str, choices=["slow","medium","fast","hp","hq","bd","ll","llhq","llhp"], help="NVENC preset")
    g_nvenc.add_argument("--gop", type=str, help="GOP size, e.g. 120")
    g_nvenc.add_argument("--rc-lookahead", type=str, help="NVENC rc-lookahead frames")
    g_nvenc.add_argument("--spatial-aq", type=str, help="NVENC spatial AQ enable (0/1)")
    g_nvenc.add_argument("--temporal-aq", type=str, help="NVENC temporal AQ enable (0/1)")
    g_nvenc.add_argument("--aq-strength", type=str, help="NVENC AQ strength 0-15")

    # Misc
    g_misc = p.add_argument_group("Misc")
    g_misc.add_argument("-y", "--yes", action="store_true", help="Auto-confirm the settings prompt")

    return p.parse_args()


def summarize(cfg, resolved_window: Tuple[Optional[str], Optional[str]]):
    start_iso, end_iso = resolved_window
    log("{@green}Broadcaster:{@reset} {@cyan}" + str(cfg.broadcaster), 1)
    if start_iso or end_iso:
        log("{@green}Time Window:{@reset} {@yellow}" + (start_iso or 'ANY') + "{@reset} {@white}->{@reset} {@yellow}" + (end_iso or 'NOW'), 1)
    else:
        log("{@green}Time Window:{@reset} {@yellow}ANY", 1)
    log("{@green}Max Clips Fetch:{@reset} {@white}" + str(cfg.max_clips), 1)
    try:
        _tot = int(getattr(cfg, "amountOfCompilations")) * int(getattr(cfg, "amountOfClips"))
    except Exception:
        _tot = None
    msg = "{@green}Compilations:{@reset} {@white}" + str(cfg.amountOfCompilations) + "{@reset} {@green}| Clips each:{@reset} {@white}" + str(cfg.amountOfClips)
    if _tot is not None:
        msg += " {@green}({@white}" + str(_tot) + "{@green} total)"
    log(msg, 1)
    log("{@green}Min Views:{@reset} {@yellow}" + str(cfg.reactionThreshold), 1)
    # Show selected resolution/format/bitrate
    try:
        log("{@green}Resolution:{@reset} {@white}" + str(globals().get("resolution", "")), 1)
        log("{@green}Format:{@reset} {@white}" + str(globals().get("container_ext", "mp4")), 1)
        log("{@green}Bitrate:{@reset} {@white}" + str(globals().get("bitrate", "")), 1)
    except Exception:
        pass
    try:
        if getattr(cfg, "auto_expand", False):
            log("{@green}Auto-expand:{@reset} {@cyan}enabled", 1)
            log("{@green}Expand step:{@reset} {@white}" + str(getattr(cfg, "expand_step_days", 7)) + "{@reset} {@green}days", 1)
            log("{@green}Max lookback:{@reset} {@white}" + str(getattr(cfg, "max_lookback_days", 90)) + "{@reset} {@green}days", 1)
    except Exception:
        pass


def _parse_simple_date(s: str) -> datetime:
    """Parse simple date strings in a few common formats.

    Accepted: MM/DD/YYYY, MM-DD-YYYY, YYYY-MM-DD
    Returns naive datetime (date) which will be assigned UTC.
    """
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid date format: {s}. Use MM/DD/YYYY.")


def resolve_date_window(start_str: Optional[str], end_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Convert simple date inputs to RFC3339 (ISO8601) strings for Helix.

    Start becomes 00:00:00Z; end becomes 23:59:59Z of that date.
    If only start provided, end is current UTC time.
    """
    if not start_str and not end_str:
        # default window: last 3 days up to now (inclusive)
        now = datetime.now(timezone.utc).date()
        start_date = now - timedelta(days=3)
        start_iso = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        end_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return start_iso, end_iso
    start_iso = end_iso = None
    if start_str:
        d = _parse_simple_date(start_str)
        start_iso = d.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    if end_str:
        d2 = _parse_simple_date(end_str)
        # End of day 23:59:59
        d2 = d2 + timedelta(hours=23, minutes=59, seconds=59)
        end_iso = d2.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    elif start_iso:
        # If only start provided, use now as end
        end_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return start_iso, end_iso


def _sanitize_filename(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', s)[:80]

def _ensure_unique_names(base_names: list[str], out_dir: str, overwrite: bool) -> list[str]:
    """Return names unique within out_dir by appending _1, _2, ... before extension.
    If overwrite=True, returns base_names unchanged.
    Ensures uniqueness within this batch and against existing files on disk.
    """
    if overwrite:
        return list(base_names)
    used: set[str] = set()
    try:
        for fname in os.listdir(out_dir):
            used.add(fname.lower())
    except Exception:
        pass
    result: list[str] = []
    for name in base_names:
        if name.lower() not in used and name.lower() not in (n.lower() for n in result):
            result.append(name)
            used.add(name.lower())
            continue
        # split name/ext
        root, ext = os.path.splitext(name)
        k = 1
        while True:
            cand = f"{root}_{k}{ext}"
            low = cand.lower()
            if low not in used and low not in (n.lower() for n in result):
                result.append(cand)
                used.add(low)
                break
            k += 1
    return result


def finalize_outputs(broadcaster: str, window: Tuple[Optional[str], Optional[str]], compilation_count: int, keep_cache: bool, final_names: Optional[List[str]] = None, overwrite_output: bool = False, purge_cache: bool = False) -> List[str]:
    """Move compiled files from cache to output with improved naming then optionally clean cache."""
    from utils import log  # local import to avoid circular
    log("{@green}Finalizing outputs", 1)
    try:
        b_name = _sanitize_filename(broadcaster.lower()) or 'broadcaster'
        start_iso, end_iso = window
        # derive date segment
        def _date_part(iso_str: Optional[str]) -> Optional[str]:
            if not iso_str:
                return None
            return iso_str.split('T', 1)[0]
        date_range = None
        if start_iso or end_iso:
            s_part = _date_part(start_iso) or 'unknown'
            e_part = _date_part(end_iso) or s_part
            date_range = f"{s_part}_to_{e_part}"
        else:
            date_range = datetime.utcnow().strftime('%Y-%m-%d')
        # Build final names in index order
        # Determine container extension used by ffmpeg for cache outputs
        try:
            from config import container_ext as _ext_cfg
        except Exception:
            _ext_cfg = 'mp4'
        # Use provided final names (preferred), else derive from broadcaster/date
        if final_names is None:
            final_names = []
            for i in range(compilation_count):
                if compilation_count == 1:
                    final_names.append(f"{b_name}_{date_range}_compilation.{_ext_cfg}")
                else:
                    final_names.append(f"{b_name}_{date_range}_part{i+1}.{_ext_cfg}")

        moved = 0
        # Move cache outputs to output dir with final names using their index
        for i in range(compilation_count):
            # cache file pattern produced by ffmpegBuildSegments
            # It uses: {cache}/complete_{date}_{idx}.{ext}
            # Recreate the expected cache filename for idx i
            date_str = time.strftime('%d_%m_%y')
            cache_name = f"complete_{date_str}_{i}.{_ext_cfg}"
            src = os.path.join(cache, cache_name)
            if not os.path.exists(src):
                # If file wasn't found (e.g., different date formatting), fallback: scan for matching idx
                for fname in os.listdir(cache):
                    if fname.startswith(f"complete_") and fname.endswith(f"_{i}.{_ext_cfg}"):
                        src = os.path.join(cache, fname)
                        break
            if os.path.exists(src):
                dest = os.path.join(output, final_names[i])
                # If overwrite requested, remove existing file to avoid errors
                if overwrite_output and os.path.exists(dest):
                    try:
                        os.remove(dest)
                    except Exception:
                        pass
                # If still exists and overwrite is False (unexpected if names were uniquified), auto-suffix here as a last resort
                if (not overwrite_output) and os.path.exists(dest):
                    root, ext = os.path.splitext(final_names[i])
                    k = 1
                    while True:
                        cand = f"{root}_{k}{ext}"
                        _new = os.path.join(output, cand)
                        if not os.path.exists(_new):
                            dest = _new
                            # Update name so manifest reports actual file
                            final_names[i] = cand
                            break
                        k += 1
                shutil.move(src, dest)
                moved += 1
        log("{@blue}Moved {@white}" + str(moved) + "{@blue} file(s) to {@cyan}output", 2)
    except Exception as e:  # pragma: no cover
        log("{@redbright}{@bold}Finalize failed:{@reset} {@white}" + str(e), 5)
        return []

    if keep_cache and not purge_cache:
        log('{@green}Cache retained{@reset} ({@cyan}--keep-cache set{@reset})', 0)
        return final_names
    # clean cache except leave directory itself
    log('{@green}Cleaning cache', 1)
    try:
        preserve_set = set()
        if not purge_cache:
            try:
                from config import cache_preserve_dirs as _preserve
            except Exception:
                _preserve = []
            preserve_set = {d.strip().lower() for d in _preserve if isinstance(d, str)}
        for entry in os.listdir(cache):
            # skip preserved directories (relative names)
            if entry.strip().lower() in preserve_set:
                continue
            path = os.path.join(cache, entry)
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
            except OSError:
                pass
        log('{@blue}Cache cleaned', 2)
    except Exception as e:  # pragma: no cover
        log("{@redbright}{@bold}Cache cleanup failed:{@reset} {@white}" + str(e), 5)
    return final_names


def _load_env_if_present():
    """Tiny .env loader: sets env vars from a local .env if they aren't set."""
    try:
        env_path = os.path.join(os.getcwd(), ".env")
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        # best-effort; ignore parse errors
        pass


def ensure_twitch_credentials_if_needed():
    """If run in Twitch mode (e.g., --broadcaster), ensure creds are present.
    Shows a helpful message and exits if missing.
    """
    # Detect Twitch mode by common flags; keeps this check non-invasive.
    args = sys.argv[1:]
    broadcaster_requested = ("--broadcaster" in args) or ("-b" in args)
    if not broadcaster_requested:
        return

    # Populate env from .env if present
    _load_env_if_present()

    try:
        from utils import log  # type: ignore
    except Exception:
        def log(msg, level=0):
            print(msg)

    cid = os.getenv("TWITCH_CLIENT_ID") or ""
    secret = os.getenv("TWITCH_CLIENT_SECRET") or ""

    if not cid or not secret:
        log("{@redbright}{@bold}Twitch credentials missing{@reset}", 5)
        log("ID and Secret needed: {@cyan}https://dev.twitch.tv/console/apps{@reset}", 1)
        log("Provide credentials via one of:", 1)
        log("  - .env file: {@white}TWITCH_CLIENT_ID=<id>{@reset}, {@white}TWITCH_CLIENT_SECRET=<secret>", 1)
        log("  - PowerShell env vars: {@white}$env:TWITCH_CLIENT_ID='...'; $env:TWITCH_CLIENT_SECRET='...'{@reset}", 1)
        log("  - CLI flags (if supported): {@white}--client-id <id> --client-secret <secret>{@reset}", 1)
        raise SystemExit(2)


def ensure_transitions_static_present(transitions_dir: Optional[str] = None):
    """Resolve transitions directory and require static.mp4 to exist; exit with a helpful error if missing."""
    try:
        from utils import resolve_transitions_dir  # type: ignore
    except Exception:
        def resolve_transitions_dir():
            import os
            return os.path.abspath(os.path.join(os.getcwd(), 'transitions'))
    # Allow override via CLI-provided transitions_dir
    if transitions_dir:
        os.environ['TRANSITIONS_DIR'] = transitions_dir
    tdir = resolve_transitions_dir()
    static_path = os.path.join(tdir, 'static.mp4')
    try:
        from utils import log as _log  # type: ignore
    except Exception:
        def _log(msg, level=0):
            print(msg)
    if not os.path.isdir(tdir):
        _log("{@redbright}{@bold}Transitions directory missing:{@reset} {@white}" + tdir, 5)
        _log("Place your clips (intro.mp4, static.mp4, outro.mp4) in this folder or provide --transitions-dir.", 1)
        raise SystemExit(2)
    if not os.path.exists(static_path):
        _log("{@redbright}{@bold}Missing required file:{@reset} {@white}static.mp4 {@reset}in {@white}" + tdir, 5)
        _log("This project requires transitions/static.mp4. Set TRANSITIONS_DIR, use --transitions-dir, or place the file.", 1)
        raise SystemExit(2)


def main():  # noqa: C901
    global amountOfClips, amountOfCompilations, reactionThreshold
    global bitrate, resolution, container_ext, container_flags
    global fps, audio_bitrate, cache, output, intro, outro, transition
    global enable_overlay, rebuild
    global cq, nvenc_preset, gop, rc_lookahead, spatial_aq, temporal_aq, aq_strength

    # Ensure we have Twitch creds when running a broadcaster ingest
    ensure_twitch_credentials_if_needed()

    args = parse_args()
    # Seed randomness if provided early
    if getattr(args, 'seed', None) is not None:
        try:
            import random as _rnd
            _rnd.seed(int(args.seed))
        except Exception:
            pass
    amountOfClips = args.amountOfClips
    amountOfCompilations = args.amountOfCompilations
    reactionThreshold = args.reactionThreshold

    # Propagate requested counts to config and pipeline modules so they don't use defaults
    try:
        import config as _cfg
        _cfg.amountOfClips = amountOfClips
        _cfg.amountOfCompilations = amountOfCompilations
        _cfg.reactionThreshold = reactionThreshold
    except Exception:
        pass
    try:
        import pipeline as _pl
        _pl.amountOfClips = amountOfClips
        _pl.amountOfCompilations = amountOfCompilations
        _pl.reactionThreshold = reactionThreshold
    except Exception:
        pass

    # Resolve simple date window to RFC3339
    window = resolve_date_window(args.start, args.end)
    summarize(args, window)
    # Apply runtime overrides for quality/bitrate/resolution/container
    # Determine desired bitrate from quality unless explicitly provided
    qmap = {"balanced": "10M", "high": "12M", "max": "16M"}
    chosen_bitrate = args.bitrate or (qmap.get(args.quality) if args.quality else None) or bitrate
    chosen_resolution = args.resolution or resolution
    # Container selection
    chosen_ext = container_ext if 'container_ext' in globals() else 'mp4'
    chosen_flags = container_flags if 'container_flags' in globals() else '-movflags +faststart'
    if args.format:
        if args.format == 'mp4':
            chosen_ext = 'mp4'
            chosen_flags = '-movflags +faststart'
        elif args.format == 'mkv':
            chosen_ext = 'mkv'
            chosen_flags = ''

    # Update globals in this module for logging
    bitrate = chosen_bitrate
    resolution = chosen_resolution
    container_ext = chosen_ext
    container_flags = chosen_flags
    # Apply additional overrides
    if args.fps:
        fps = args.fps
    if args.audio_bitrate:
        audio_bitrate = args.audio_bitrate
    if args.cache_dir:
        cache = args.cache_dir
    if args.output_dir:
        output = args.output_dir
    # Runtime overrides: if provided, convert to singleton lists to align with pipeline's list-based selection
    if args.intro is not None:
        try:
            import config as _cfg
            _cfg.intro = [args.intro] if args.intro else []
        except Exception:
            pass
    if args.outro is not None:
        try:
            import config as _cfg
            _cfg.outro = [args.outro] if args.outro else []
        except Exception:
            pass
    if args.transition is not None:
        try:
            import config as _cfg
            if args.transition:
                _cfg.transitions = [args.transition]
        except Exception:
            pass
    if args.transition_prob is not None:
        try:
            import config as _cfg
            _cfg.transition_probability = max(0.0, min(1.0, float(args.transition_prob)))
        except Exception:
            pass
    if args.no_random_transitions:
        try:
            import config as _cfg
            _cfg.no_random_transitions = True
        except Exception:
            pass
    if args.skip_bad_clip:
        try:
            import config as _cfg
            _cfg.skip_bad_clip = True
        except Exception:
            pass
    if args.max_concurrency is not None:
        try:
            import config as _cfg
            _cfg.max_concurrency = max(1, int(args.max_concurrency))
        except Exception:
            pass
    if args.transitions_dir:
        # Make resolver see the override
        os.environ['TRANSITIONS_DIR'] = args.transitions_dir
        try:
            from utils import log as _log
            _log("{@green}Transitions directory override:{@reset} {@cyan}" + os.path.abspath(args.transitions_dir), 1)
        except Exception:
            pass

    if args.no_overlay:
        enable_overlay = False
    if args.rebuild:
        rebuild = True
    if args.cq:
        cq = args.cq
    if args.nvenc_preset:
        nvenc_preset = args.nvenc_preset
    if args.gop:
        gop = args.gop
    if args.rc_lookahead:
        rc_lookahead = args.rc_lookahead
    if args.spatial_aq:
        spatial_aq = args.spatial_aq
    if args.temporal_aq:
        temporal_aq = args.temporal_aq
    if args.aq_strength:
        aq_strength = args.aq_strength
    # Propagate to pipeline and utils modules used for replacements
    try:
        pipeline_mod.bitrate = chosen_bitrate
        pipeline_mod.resolution = chosen_resolution
        pipeline_mod.container_ext = chosen_ext
        pipeline_mod.container_flags = chosen_flags
        pipeline_mod.fps = fps
        pipeline_mod.audio_bitrate = audio_bitrate
        pipeline_mod.cache = cache
        pipeline_mod.output = output
    # no direct single-file intro/outro/transition globals; pipeline reads from config lists at runtime
        pipeline_mod.enable_overlay = enable_overlay
        pipeline_mod.rebuild = rebuild
    except Exception:
        pass
    try:
        utils_mod.bitrate = chosen_bitrate
        utils_mod.resolution = chosen_resolution
        utils_mod.fps = fps
        utils_mod.audio_bitrate = audio_bitrate
        utils_mod.cache = cache
    except Exception:
        pass
    # yt-dlp format override via config string
    if args.yt_format:
        try:
            import config as _cfg
            _cfg.yt_format = args.yt_format
            # Rebuild youtubeDlOptions string if present
            if hasattr(_cfg, 'youtubeDlOptions'):
                _cfg.youtubeDlOptions = _cfg.youtubeDlOptions.replace("{yt_format}", _cfg.yt_format)
        except Exception:
            pass
    # Fail fast if required transition is missing
    ensure_transitions_static_present(getattr(args, 'transitions_dir', None))

    # Apply transitions controls to config (used by pipeline write_concat_file)
    try:
        import config as _cfg
        if getattr(args, 'rebuild_transitions', False):
            _cfg.transitions_rebuild = True
        if getattr(args, 'no_audio_normalize_transitions', False):
            _cfg.audio_normalize_transitions = False
    except Exception:
        pass

    # Interactive confirmation (default). Use -y/--yes to skip.
    if not getattr(args, "yes", False):
        try:
            log("{@cyan}Confirmation preview:{@reset}", 1)
            log("  {@green}Broadcaster{@reset}: {@white}" + str(args.broadcaster), 1)
            log("  {@green}Time Window{@reset}: {@yellow}" + str(window[0] or 'ANY') + "{@reset} {@white}->{@reset} {@yellow}" + str(window[1] or 'NOW'), 1)
            log("  {@green}Max Clips Fetch{@reset}: {@white}" + str(args.max_clips), 1)
            try:
                _totc = int(args.amountOfCompilations) * int(args.amountOfClips)
            except Exception:
                _totc = None
            _line = "  {@green}Compilations x Clips{@reset}: {@white}" + str(args.amountOfCompilations) + " x " + str(args.amountOfClips)
            if _totc is not None:
                _line += " {@green}({@white}" + str(_totc) + "{@green} total)"
            log(_line, 1)
            log("  {@green}Min Views{@reset}: {@white}" + str(reactionThreshold), 1)
            if getattr(args, "auto_expand", False):
                log("  {@green}Auto-expand{@reset}: {@cyan}enabled{@reset} {@white}(step {@yellow}" + str(args.expand_step_days) + "{@reset} {@white}day(s), max lookback {@yellow}" + str(args.max_lookback_days) + "{@reset} {@white}day(s))", 1)
            else:
                log("  {@green}Auto-expand{@reset}: {@cyan}disabled", 1)
            log("  {@green}Cache dir{@reset}: {@white}" + str(cache), 1)
            log("  {@green}Output dir{@reset}: {@white}" + str(output), 1)
            log("  {@green}FFmpeg{@reset}: {@white}bitrate=" + str(bitrate) + ", fps=" + str(fps) + ", res=" + str(resolution), 1)
            log("  {@green}Format{@reset}: {@white}" + str(container_ext) + " {@gray}(" + (container_flags or 'no extra flags') + ")", 1)
            try:
                import config as _cfg
                _intro_list = getattr(_cfg, 'intro', [])
                _outro_list = getattr(_cfg, 'outro', [])
                _transitions_list = getattr(_cfg, 'transitions', [])
                _tprob = getattr(_cfg, 'transition_probability', 0.35)
                _norand = getattr(_cfg, 'no_random_transitions', False)
                log("  {@green}Transitions{@reset}: {@white}static.mp4 required, intro choices=" + str(len(_intro_list)) + ", transitions choices=" + str(len(_transitions_list)) + ", outro choices=" + str(len(_outro_list)) + ", prob=" + str(_tprob) + (" {@gray}(random transitions disabled)" if _norand else ""), 1)
            except Exception:
                pass
            log("  {@green}Keep cache{@reset}: {@white}" + ("true" if args.keep_cache else "false"), 1)
            log("  {@green}Overlay{@reset}: {@white}" + ("enabled" if enable_overlay else "disabled"), 1)
            log("  {@green}Rebuild{@reset}: {@white}" + ("true" if rebuild else "false"), 1)
            # No strict intro/outro checks now; static is required and verified earlier.
            ans = input("Proceed? [Y/n]: ").strip().lower()
            if ans in ("n", "no"):
                raise SystemExit("Aborted by user")
        except EOFError:
            # If input is not available, fail safe unless --yes provided
            raise SystemExit("Confirmation required but no TTY available. Re-run with -y/--yes.")
    cid, secret = load_credentials(args.client_id, args.client_secret)
    token = get_app_access_token(cid, secret)
    user = resolve_user(args.broadcaster, cid, token)
    if not user:
        raise SystemExit("Broadcaster not found")
    broadcaster_id = user["id"]
    log("{@blue}Resolved broadcaster id:{@reset} {@cyan}" + str(broadcaster_id), 2)

    prep_work()

    log("{@green}Fetching clips from {@cyan}Helix", 1)
    clips = fetch_clips(
        broadcaster_id=broadcaster_id,
        client_id=cid,
        token=token,
        started_at=window[0],
        ended_at=window[1],
        max_clips=args.max_clips,
    )
    log("{@blue}Fetched {@white}" + str(len(clips)) + "{@blue} raw clips", 2)

    # Filter by min views (reactionThreshold proxy)
    filtered = [c for c in clips if int(c.get("view_count", 0)) >= reactionThreshold]
    log("{@blue}Filtered to {@white}" + str(len(filtered)) + "{@blue} clips (>= {@yellow}" + str(reactionThreshold) + "{@blue} views)", 2)
    if not filtered:
        # If auto-expand is off and we got none, stop here early.
        if not getattr(args, "auto_expand", False):
            raise SystemExit("No clips meet criteria")

    # Auto-expand: extend the start date backwards until we reach target clips or max lookback
    target_total = int(args.amountOfClips) * int(args.amountOfCompilations)
    if getattr(args, "auto_expand", False) and len(filtered) < target_total:
        try:
            # Helper to parse ISO8601 Z to aware datetime
            def _parse_iso_z(s: Optional[str]) -> Optional[datetime]:
                if not s:
                    return None
                try:
                    return datetime.fromisoformat(s.replace("Z", "+00:00"))
                except Exception:
                    return None

            step_days = max(1, int(getattr(args, "expand_step_days", 7)))
            max_look = max(1, int(getattr(args, "max_lookback_days", 90)))
            end_dt = _parse_iso_z(window[1]) or datetime.now(timezone.utc)
            start_dt = _parse_iso_z(window[0])
            if not start_dt:
                # if start missing, begin step from end - step
                start_dt = end_dt - timedelta(days=step_days)

            collected = list(filtered)
            seen_ids = {c.get("id") for c in collected if c.get("id")}
            current_start = start_dt
            initial_start = start_dt
            lookback_limit = end_dt - timedelta(days=max_look)

            while len(collected) < target_total and current_start > lookback_limit:
                new_start = current_start - timedelta(days=step_days)
                new_start_iso = new_start.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                # Fetch only the earlier segment to reduce overlap
                seg_clips = fetch_clips(
                    broadcaster_id=broadcaster_id,
                    client_id=cid,
                    token=token,
                    started_at=new_start_iso,
                    ended_at=current_start.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
                    max_clips=args.max_clips,
                )
                if not seg_clips:
                    log("{@cyan}Auto-expand:{@reset} no clips found for segment", 2)
                # Filter and dedupe
                seg_filtered = [c for c in seg_clips if int(c.get("view_count", 0)) >= reactionThreshold]
                before = len(collected)
                for c in seg_filtered:
                    cid_ = c.get("id")
                    if cid_ and cid_ not in seen_ids:
                        seen_ids.add(cid_)
                        collected.append(c)
                gained = len(collected) - before
                log(
                    "{@cyan}Auto-expand:{@reset} {@green}segment {@yellow}"
                    + new_start_iso
                    + "{@reset} -> {@yellow}"
                    + current_start.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                    + "{@reset} {@blue}added {@white}"
                    + str(gained)
                    + "{@blue} clips (total {@white}"
                    + str(len(collected))
                    + "{@blue})",
                    2,
                )
                if gained == 0:
                    # No new clips; expand again; if repeated 0s, loop will still progress on time bounds
                    pass
                current_start = new_start

            # Update filtered and window start
            filtered = collected
            # update window to reflect earliest start used (for logging / naming)
            try:
                window = (
                    current_start.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
                    window[1],
                )
            except Exception:
                pass
            log(
                "{@blue}After expand:{@reset} {@white}" + str(len(filtered))
                + "{@blue} filtered clips (target {@white}" + str(target_total) + "{@blue})",
                2,
            )
        except Exception as e:
            log("{@redbright}{@bold}Auto-expand failed:{@reset} {@white}" + str(e), 5)

    avatar_map = fetch_creator_avatars(filtered, cid, token)
    rows = build_clip_rows(filtered, avatar_map)
    comps = create_compilations_from(rows)
    log("{@blue}Stage 1{@reset} {@green}(processing clips)", 1)
    stage_one(comps)
    log("{@blue}Stage 2{@reset} {@green}(concatenate)", 1)
    # Build the final filenames for display during compilation
    b_name = _sanitize_filename(args.broadcaster.lower()) or 'broadcaster'
    start_iso, end_iso = window
    def _date_part(iso_str: Optional[str]) -> Optional[str]:
        if not iso_str:
            return None
        return iso_str.split('T', 1)[0]
    if start_iso or end_iso:
        s_part = _date_part(start_iso) or 'unknown'
        e_part = _date_part(end_iso) or s_part
        date_range = f"{s_part}_to_{e_part}"
    else:
        date_range = datetime.utcnow().strftime('%Y-%m-%d')
    try:
        from config import container_ext as _ext
    except Exception:
        _ext = 'mp4'
    base_names = []
    for i in range(len(comps)):
        if len(comps) == 1:
            base_names.append(f"{b_name}_{date_range}_compilation.{_ext}")
        else:
            base_names.append(f"{b_name}_{date_range}_part{i+1}.{_ext}")
    # Ensure names are unique upfront unless overwrite requested
    final_names = _ensure_unique_names(base_names, output, getattr(args, 'overwrite_output', False))
    try:
        stage_two(comps, final_names)
    except KeyboardInterrupt:
        # Cooperative shutdown: signal pipeline to stop and clean up child procs
        try:
            from pipeline import request_shutdown
            request_shutdown()
        except Exception:
            pass
        log("{@yellow}{@bold}Interrupted by user (Ctrl-C). Stopping encoder and cleaning up...", 1)
    finals = finalize_outputs(
        args.broadcaster,
        window,
        len(comps),
        args.keep_cache,
        final_names=final_names,
        overwrite_output=getattr(args, 'overwrite_output', False),
        purge_cache=getattr(args, 'purge_cache', False),
    )
    # Write manifest.json with metadata and clip IDs per compilation
    try:
        import json as _json, os as _os
        manifest = {
            "broadcaster": args.broadcaster,
            "window": {"start": window[0], "end": window[1]},
            "files": finals,
            "compilations": [[row[0] for row in comp] for comp in comps],
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        _m_path = _os.path.join(output, "manifest.json")
        with open(_m_path, "w", encoding="utf-8") as f:
            _json.dump(manifest, f, indent=2)
        log("{@green}Wrote manifest:{@reset} {@cyan}" + _m_path, 1)
    except Exception as e:
        log("{@yellow}{@bold}WARN{@reset} Failed to write manifest: {@white}" + str(e), 2)
    log("{@green}Done", 2)


if __name__ == "__main__":  # pragma: no cover
    try:
        main()
    except KeyboardInterrupt:
        # Global catch in case Ctrl-C occurs outside main's guarded block
        try:
            from pipeline import request_shutdown
            request_shutdown()
        except Exception:
            pass
        try:
            from utils import log as _log
            _log("{@yellow}{@bold}Interrupted by user. Exiting.")
        except Exception:
            print("Interrupted by user. Exiting.")
