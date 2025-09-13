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
    p = argparse.ArgumentParser(description="Build Twitch clip compilations (no Discord)")
    p.add_argument("--broadcaster", required=True, help="Broadcaster login name (e.g. theflood)")
    p.add_argument("--client-id", dest="client_id", help="Twitch Client ID (else TWITCH_CLIENT_ID env)")
    p.add_argument("--client-secret", dest="client_secret", help="Twitch Client Secret (else env)")
    p.add_argument("--start", help="Start date (MM/DD/YYYY). Interpreted as 00:00:00Z of that day.")
    p.add_argument("--end", help="End date (MM/DD/YYYY). Interpreted as 23:59:59Z of that day.")
    p.add_argument("--min-views", dest="reactionThreshold", type=int, default=reactionThreshold, help="Minimum view count (maps to reactions)")
    p.add_argument("--max-clips", type=int, default=100, help="Max clips to fetch before filtering")
    p.add_argument("--clips", dest="amountOfClips", type=int, default=amountOfClips, help="Clips per compilation")
    p.add_argument("--compilations", dest="amountOfCompilations", type=int, default=amountOfCompilations, help="Number of compilations to create")
    p.add_argument("--keep-cache", action="store_true", help="Do not delete per-clip cache after finishing")
    p.add_argument(
        "--quality",
        choices=["balanced", "high", "max"],
        help="Quality preset that adjusts bitrate (overridden by --bitrate)",
    )
    p.add_argument(
        "--bitrate",
        help="Override video bitrate target, e.g. 12M",
    )
    p.add_argument(
        "--resolution",
        help="Override output resolution, e.g. 1920x1080 or 1280x720",
    )
    p.add_argument(
        "--format",
        choices=["mp4", "mkv"],
        help="Container format for final output",
    )
    p.add_argument(
        "--auto-expand",
        action="store_true",
        help="If not enough clips, auto-expand the start date backwards in steps to gather more",
    )
    p.add_argument(
        "--expand-step-days",
        type=int,
        default=7,
        help="How many days to extend the lookback per expansion step (default 7)",
    )
    p.add_argument(
        "--max-lookback-days",
        type=int,
        default=90,
        help="Maximum total lookback from the end date when auto-expanding (default 90)",
    )
    p.add_argument(
        "-y", "--yes",
        action="store_true",
    help="Auto-confirm the settings prompt",
    )
    # Additional overrides for robustness and convenience
    p.add_argument("--fps", type=str, help="Override output framerate, e.g. 60")
    p.add_argument("--audio-bitrate", dest="audio_bitrate", type=str, help="Override audio bitrate, e.g. 192k")
    p.add_argument("--cache-dir", dest="cache_dir", type=str, help="Cache directory path")
    p.add_argument("--output-dir", dest="output_dir", type=str, help="Output directory path")
    p.add_argument("--intro", type=str, help="Intro clip filename in transitions dir (e.g., intro.mp4 or empty to disable)")
    p.add_argument("--outro", type=str, help="Outro clip filename in transitions dir (e.g., outro.mp4 or empty to disable)")
    p.add_argument("--transition", type=str, help="Transition clip between items (default static.mp4)")
    p.add_argument("--no-overlay", action="store_true", help="Disable overlay stage for speed")
    p.add_argument("--rebuild", action="store_true", help="Force rebuild even if intermediate files exist")
    p.add_argument("--yt-format", dest="yt_format", type=str, help="yt-dlp --format string override")
    # Encoder tuning
    p.add_argument("--cq", type=str, help="NVENC constant quality (lower is higher quality)")
    p.add_argument("--preset", dest="nvenc_preset", type=str, choices=["slow","medium","fast","hp","hq","bd","ll","llhq","llhp"], help="NVENC preset")
    p.add_argument("--gop", type=str, help="GOP size, e.g. 120")
    p.add_argument("--rc-lookahead", type=str, help="NVENC rc-lookahead frames")
    p.add_argument("--spatial-aq", type=str, help="NVENC spatial AQ enable (0/1)")
    p.add_argument("--temporal-aq", type=str, help="NVENC temporal AQ enable (0/1)")
    p.add_argument("--aq-strength", type=str, help="NVENC AQ strength 0-15")
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


def finalize_outputs(broadcaster: str, window: Tuple[Optional[str], Optional[str]], compilation_count: int, keep_cache: bool) -> List[str]:
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
        try:
            from config import container_ext as _ext
        except Exception:
            _ext = 'mp4'
        final_names: List[str] = []
        for i in range(compilation_count):
            if compilation_count == 1:
                final_names.append(f"{b_name}_{date_range}_compilation.{_ext}")
            else:
                final_names.append(f"{b_name}_{date_range}_part{i+1}.{_ext}")

        moved = 0
        # Move cache outputs to output dir with final names using their index
        for i in range(compilation_count):
            # cache file pattern produced by ffmpegBuildSegments
            # It uses: {cache}/complete_{date}_{idx}.{ext}
            # Recreate the expected cache filename for idx i
            date_str = time.strftime('%d_%m_%y')
            cache_name = f"complete_{date_str}_{i}.{_ext}"
            src = os.path.join(cache, cache_name)
            if not os.path.exists(src):
                # If file wasn't found (e.g., different date formatting), fallback: scan for matching idx
                for fname in os.listdir(cache):
                    if fname.startswith(f"complete_") and fname.endswith(f"_{i}.{_ext}"):
                        src = os.path.join(cache, fname)
                        break
            if os.path.exists(src):
                dest = os.path.join(output, final_names[i])
                shutil.move(src, dest)
                moved += 1
        log("{@blue}Moved {@white}" + str(moved) + "{@blue} file(s) to {@cyan}output", 2)
    except Exception as e:  # pragma: no cover
        log("{@redbright}{@bold}Finalize failed:{@reset} {@white}" + str(e), 5)
        return []

    if keep_cache:
        log('{@green}Cache retained{@reset} ({@cyan}--keep-cache set{@reset})', 0)
    return final_names

    # clean cache except leave directory itself
    log('{@green}Cleaning cache', 1)
    try:
        for entry in os.listdir(cache):
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


def main():  # noqa: C901
    global amountOfClips, amountOfCompilations, reactionThreshold
    global bitrate, resolution, container_ext, container_flags
    global fps, audio_bitrate, cache, output, intro, outro, transition
    global enable_overlay, rebuild
    global cq, nvenc_preset, gop, rc_lookahead, spatial_aq, temporal_aq, aq_strength

    # Ensure we have Twitch creds when running a broadcaster ingest
    ensure_twitch_credentials_if_needed()

    args = parse_args()
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
    if args.intro is not None:
        intro = args.intro or ''
    if args.outro is not None:
        outro = args.outro or ''
    if args.transition is not None:
        transition = args.transition or transition
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
        pipeline_mod.intro = intro
        pipeline_mod.outro = outro
        pipeline_mod.transition = transition
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
            log("  {@green}Transitions{@reset}: {@white}intro=" + str(intro or 'none') + ", transition=" + str(transition) + ", outro=" + str(outro or 'none'), 1)
            log("  {@green}Keep cache{@reset}: {@white}" + ("true" if args.keep_cache else "false"), 1)
            log("  {@green}Overlay{@reset}: {@white}" + ("enabled" if enable_overlay else "disabled"), 1)
            log("  {@green}Rebuild{@reset}: {@white}" + ("true" if rebuild else "false"), 1)
            # Verify intro/outro presence if configured (empty disables)
            try:
                from config import intro as _cfg_intro, outro as _cfg_outro  # type: ignore
            except Exception:
                _cfg_intro, _cfg_outro = intro, outro
            import os as _os
            _warnings: list[str] = []
            _t_dir = _os.path.join('.', 'transitions')
            if _cfg_intro:
                if not _os.path.exists(_os.path.join(_t_dir, _cfg_intro)):
                    _warnings.append(f"Intro file missing: transitions/{_cfg_intro}")
            if _cfg_outro:
                if not _os.path.exists(_os.path.join(_t_dir, _cfg_outro)):
                    _warnings.append(f"Outro file missing: transitions/{_cfg_outro}")
            if _warnings:
                for w in _warnings:
                    log("{@yellow}{@bold}WARN{@reset} " + w, 1)
                log("{@cyan}You can continue without intro/outro or place the files and rerun.", 1)
                ans = input("Proceed anyway? [y/N]: ").strip().lower()
                if ans in ("n", "no", ""):
                    raise SystemExit("Aborted by user (missing intro/outro)")
                # User chose to proceed: disable whichever are missing so pipeline will skip them
                try:
                    if _cfg_intro and not _os.path.exists(_os.path.join(_t_dir, _cfg_intro)):
                        log("{@cyan}Proceeding without intro clip (will be skipped)", 1)
                        intro = ''
                        pipeline_mod.intro = ''
                    if _cfg_outro and not _os.path.exists(_os.path.join(_t_dir, _cfg_outro)):
                        log("{@cyan}Proceeding without outro clip (will be skipped)", 1)
                        outro = ''
                        pipeline_mod.outro = ''
                except Exception:
                    pass
            else:
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
    final_names = []
    for i in range(len(comps)):
        if len(comps) == 1:
            final_names.append(f"{b_name}_{date_range}_compilation.{_ext}")
        else:
            final_names.append(f"{b_name}_{date_range}_part{i+1}.{_ext}")
    stage_two(comps, final_names)
    finalize_outputs(args.broadcaster, window, len(comps), args.keep_cache)
    log("{@green}Done", 2)


if __name__ == "__main__":  # pragma: no cover
    main()
