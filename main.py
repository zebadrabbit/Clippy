# ╔════════════════════════════════════════════════════════════════════════════╗
# ║                                                                            ║
# ║   ██████╗██╗     ██╗██████╗ ██████╗ ██╗   ██╗                              ║
# ║  ██╔════╝██║     ██║██╔══██╗██╔══██╗╚██╗ ██╔╝                              ║
# ║  ██║     ██║     ██║██████╔╝██████╔╝ ╚████╔╝                               ║
# ║  ██║     ██║     ██║██╔═══╝ ██╔═══╝   ╚██╔╝                                ║
# ║  ╚██████╗███████╗██║██║     ██║        ██║                                 ║
# ║   ╚═════╝╚══════╝╚═╝╚═╝     ╚═╝        ╚═╝                                 ║
# ║                                                                            ║
# ║      Clippy - Twitch Clip Compilation Tool                                 ║
# ║      Author: Erin Lukens <108551595+zebadrabbit@users.noreply.github.com   ║
# ║                                                                            ║
# ║   Usage:                                                                   ║
# ║     python main.py <clip_url> --clips 5 [other options]                    ║
# ║                                                                            ║
# ║   Requirements:                                                            ║
# ║     - ffmpeg and ffprobe available (in PATH or config.ffmpeg's directory)  ║
# ║     - Python packages: requests, Pillow, yachalk, yt_dlp                   ║
# ║                                                                            ║
# ╚════════════════════════════════════════════════════════════════════════════╝

"""Clippy entrypoint: fetch Twitch clips and build compilations.

Quick start (PowerShell):
    $env:TWITCH_CLIENT_ID="xxxxx"; $env:TWITCH_CLIENT_SECRET="yyyyy"; \
    python .\main.py --broadcaster somechannel --max-clips 40 --clips 10 --compilations 2

Optional time window:
    --start 2025-07-01T00:00:00Z --end 2025-07-07T00:00:00Z

This orchestrates the processing pipeline (download, normalize, optional overlay, concat)
using configuration from config.py and runtime CLI overrides.
"""

from __future__ import annotations
import os
import sys
from typing import List, Tuple, Optional
from datetime import datetime, timedelta, timezone

from clippy.config import *  # noqa: F401,F403
from clippy.utils import log, prep_work
import clippy.utils as utils_mod
from clippy.twitch_ingest import (
    load_credentials,
    get_app_access_token,
    resolve_user,
    fetch_clips,
    build_clip_rows,
    fetch_creator_avatars,
    fetch_clips_by_ids,
)
from clippy.discord_ingest import fetch_recent_clip_ids, load_discord_token

# Import processing helpers from existing main module
from clippy.pipeline import create_compilations_from, stage_one, stage_two  # DB removed
import clippy.pipeline as pipeline_mod
from clippy.cli import parse_args
from clippy.banner import show_banner
from clippy import __version__ as CLIPPY_VERSION
from clippy.window import resolve_date_window, summarize as _summarize
from clippy.naming import sanitize_filename as _sanitize_filename, ensure_unique_names as _ensure_unique_names, finalize_outputs
from clippy.runtime import ensure_twitch_credentials_if_needed, ensure_transitions_static_present
try:
    from clippy.theme import THEME, enable_windows_vt  # type: ignore
except Exception:  # pragma: no cover
    THEME = None  # type: ignore
    def enable_windows_vt():  # type: ignore
        return

def main():  # noqa: C901
    global amountOfClips, amountOfCompilations, reactionThreshold
    global bitrate, resolution, container_ext, container_flags
    global fps, audio_bitrate, cache, output, intro, outro, transition
    global enable_overlay, rebuild
    global cq, nvenc_preset, gop, rc_lookahead, spatial_aq, temporal_aq, aq_strength

    # Ensure we have Twitch creds when running a broadcaster ingest
    ensure_twitch_credentials_if_needed()

    # Show banner unless help is requested or non-interactive
    # Peek at argv for -h/--help to avoid printing above help output
    _argv = [a.lower() for a in sys.argv[1:]]
    if not any(a in ('-h', '--help', '--version') for a in _argv):
        try:
            show_banner()
        except Exception:
            pass
        try:
            from yachalk import chalk as _chalk
            print(str(_chalk.gray(f"Version {CLIPPY_VERSION}")))
        except Exception:
            print(f"Version {CLIPPY_VERSION}")
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
        import clippy.config as _cfg
        _cfg.amountOfClips = amountOfClips
        _cfg.amountOfCompilations = amountOfCompilations
        _cfg.reactionThreshold = reactionThreshold
    except Exception:
        pass
    try:
        import clippy.pipeline as _pl
        _pl.amountOfClips = amountOfClips
        _pl.amountOfCompilations = amountOfCompilations
        _pl.reactionThreshold = reactionThreshold
    except Exception:
        pass

    # Resolve simple date window to RFC3339
    window = resolve_date_window(args.start, args.end)
    # Show startup summary only when skipping confirmation to avoid duplication
    if getattr(args, "yes", False):
        _summarize(args, window, globals().get("resolution", None), globals().get("container_ext", "mp4"), globals().get("bitrate", None))
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
            import clippy.config as _cfg
            _cfg.intro = [args.intro] if args.intro else []
        except Exception:
            pass
    if args.outro is not None:
        try:
            import clippy.config as _cfg
            _cfg.outro = [args.outro] if args.outro else []
        except Exception:
            pass
    if args.transition is not None:
        try:
            import clippy.config as _cfg
            if args.transition:
                _cfg.transitions = [args.transition]
        except Exception:
            pass
    if args.transition_prob is not None:
        try:
            import clippy.config as _cfg
            _cfg.transition_probability = max(0.0, min(1.0, float(args.transition_prob)))
        except Exception:
            pass
    if args.no_random_transitions:
        try:
            import clippy.config as _cfg
            _cfg.no_random_transitions = True
        except Exception:
            pass
    if args.skip_bad_clip:
        try:
            import clippy.config as _cfg
            _cfg.skip_bad_clip = True
        except Exception:
            pass
    if args.max_concurrency is not None:
        try:
            import clippy.config as _cfg
            _cfg.max_concurrency = max(1, int(args.max_concurrency))
        except Exception:
            pass
    if args.transitions_dir:
        # Make resolver see the override
        os.environ['TRANSITIONS_DIR'] = args.transitions_dir
        try:
            from clippy.utils import log as _log
            _log("Transitions directory override: " + os.path.abspath(args.transitions_dir), 1)
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
            import clippy.config as _cfg
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
        import clippy.config as _cfg
        if getattr(args, 'rebuild_transitions', False):
            _cfg.transitions_rebuild = True
        if getattr(args, 'no_audio_normalize_transitions', False):
            _cfg.audio_normalize_transitions = False
    except Exception:
        pass

    # If broadcaster not provided via CLI, use default from config if present
    try:
        _def_b = globals().get("default_broadcaster", "")
    except Exception:
        _def_b = ""
    if not getattr(args, "broadcaster", None):
        if _def_b:
            args.broadcaster = _def_b
            log("Using default broadcaster from config: " + str(_def_b), 1)
        else:
            log("No broadcaster provided and no default configured in clippy.yaml (identity.broadcaster)", 5)
            log("Set identity.broadcaster via setup_wizard or provide --broadcaster", 1)
            raise SystemExit(2)

    # Interactive confirmation (default). Use -y/--yes to skip.
    if not getattr(args, "yes", False):
        try:
            # Concise BBS-style panel
            try:
                enable_windows_vt()
            except Exception:
                pass
            try:
                from yachalk import chalk as _chalk
            except Exception:
                class _Plain:
                    def __getattr__(self, name):
                        return lambda s: s
                _chalk = _Plain()  # type: ignore
            title = (THEME.title("Run plan") if THEME else _chalk.cyan_bright("Run plan"))
            bar = (THEME.bar("=" * 56) if THEME else _chalk.gray("=" * 56))
            def L(s: str) -> str:
                # Static labels: darker blue
                return THEME.section(s) if THEME else str(_chalk.blue(s))
            def S(txt: str = " : ") -> str:
                return THEME.sep(txt) if THEME else str(_chalk.gray(txt))
            def V(v: str, accent: bool = False) -> str:
                # Dynamic values: white
                return str(_chalk.white(v))
            # Gather values
            try:
                import clippy.config as _cfg
                _intro_list = getattr(_cfg, 'intro', [])
                _outro_list = getattr(_cfg, 'outro', [])
                _transitions_list = getattr(_cfg, 'transitions', [])
                _tprob = getattr(_cfg, 'transition_probability', 0.35)
                _norand = getattr(_cfg, 'no_random_transitions', False)
            except Exception:
                _intro_list = []; _outro_list = []; _transitions_list = []; _tprob = 0.35; _norand = False
            try:
                _total = int(args.amountOfCompilations) * int(args.amountOfClips)
            except Exception:
                _total = None
            # Panel rendering
            print(bar)
            print(title)
            print(bar)
            print(f"{L('Broadcaster')}{S()}{V(str(args.broadcaster), True)}")
            print(f"{L('Time Window')}{S()}{V(str(window[0] or 'ANY'), True)} {S('->')} {V(str(window[1] or 'NOW'), True)}")
            print(f"{L('Max fetch')}{S()}{V(str(args.max_clips))}")
            print(f"{L('Min views')}{S()}{V(str(reactionThreshold))}")
            print(f"{L('Format')}{S()}{V(container_ext)} {S('(')}{V(container_flags or 'no flags')}{S(')')}")
            print(f"{L('Resolution')}{S()}{V(resolution)}  {L('FPS')}{S()}{V(str(fps))}  {L('Bitrate')}{S()}{V(str(bitrate))}")
            comp_desc = f"{V(str(args.amountOfCompilations))} x {V(str(args.amountOfClips))}"
            if _total is not None:
                comp_desc += f" {S('(')}{V(str(_total))} {V('total')}{S(')')}"
            print(f"{L('Compilations x Clips')}{S()}{comp_desc}")
            print(f"{L('Cache dir')}{S()}{V(str(cache), True)}")
            print(f"{L('Output dir')}{S()}{V(str(output), True)}")
            tr_desc = f"intro={len(_intro_list)}, trans={len(_transitions_list)}, outro={len(_outro_list)}, prob={_tprob}"
            if _norand:
                tr_desc += f" {S('[no-random]')}"
            print(f"{L('Transitions')}{S()}{V(tr_desc)}")
            print(f"{L('Overlay')}{S()}{V('enabled' if enable_overlay else 'disabled')}")
            print(f"{L('Rebuild')}{S()}{V('true' if rebuild else 'false')}")
            print(bar)
            # Prompt
            ans = input("Proceed? [Y/n]: ").strip().lower()
            if ans in ("n", "no"):
                raise SystemExit("Aborted by user")
        except EOFError:
            # If input is not available, fail safe unless --yes provided
            raise SystemExit("Confirmation required but no TTY available. Re-run with -y/--yes.")
    cid, secret = load_credentials(args.client_id, args.client_secret)
    token = get_app_access_token(cid, secret)

    prep_work()

    if getattr(args, "discord", False):
        # Discord mode: read clip IDs from a channel and resolve via Helix
        from clippy.config import DEFAULTS as _CFG_DEFAULTS  # type: ignore
        try:
            import clippy.config as _cfg
            _discord_channel_id = getattr(_cfg, "discord_channel_id", None)
            _discord_limit = getattr(_cfg, "discord_message_limit", 200)
        except Exception:
            _discord_channel_id = None
            _discord_limit = 200
        ch_id = args.discord_channel_id or _discord_channel_id
        if not ch_id:
            raise SystemExit("Discord mode requires --discord-channel-id or clippy.yaml discord.channel_id")
        d_token = load_discord_token(args.discord_token if hasattr(args, 'discord_token') else None)
        import asyncio as _asyncio
        log("Reading Discord channel for clip links", 1)
        clip_ids = _asyncio.run(fetch_recent_clip_ids(d_token, int(ch_id), limit=int(args.discord_limit or _discord_limit)))
        # Dedupe and limit to max_clips
        clip_ids = list(dict.fromkeys(clip_ids))[: args.max_clips]
        if not clip_ids:
            raise SystemExit("No clip links found in the specified Discord channel")
        log("Fetching clips by IDs from Helix", 1)
        clips = fetch_clips_by_ids(clip_ids, cid, token)
        # Broadcaster for naming: use the first clip's broadcaster_name/login if present, else fallback
        try:
            b_name = clips[0].get("broadcaster_name") or clips[0].get("broadcaster_login") or args.broadcaster or "clips"
            args.broadcaster = b_name
        except Exception:
            if not getattr(args, "broadcaster", None):
                args.broadcaster = "clips"
    else:
        user = resolve_user(args.broadcaster, cid, token)
        if not user:
            raise SystemExit("Broadcaster not found")
        broadcaster_id = user["id"]
        log("Resolved broadcaster id: " + str(broadcaster_id), 2)
        log("Fetching clips from Helix", 1)
        clips = fetch_clips(
            broadcaster_id=broadcaster_id,
            client_id=cid,
            token=token,
            started_at=window[0],
            ended_at=window[1],
            max_clips=args.max_clips,
        )
    log("Fetched " + str(len(clips)) + " raw clips", 2)

    # Filter by min views (reactionThreshold proxy)
    filtered = [c for c in clips if int(c.get("view_count", 0)) >= reactionThreshold]
    log("Filtered to " + str(len(filtered)) + " clips (>= " + str(reactionThreshold) + " views)", 2)
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
                    log("Auto-expand: no clips found for segment", 2)
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
                    "Auto-expand: segment "
                    + new_start_iso
                    + " -> "
                    + current_start.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                    + " added "
                    + str(gained)
                    + " clips (total "
                    + str(len(collected))
                    + ")",
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
                "After expand: " + str(len(filtered))
                + " filtered clips (target " + str(target_total) + ")",
                2,
            )
        except Exception as e:
            log("Auto-expand failed: " + str(e), 5)

    avatar_map = fetch_creator_avatars(filtered, cid, token)
    rows = build_clip_rows(filtered, avatar_map)
    comps = create_compilations_from(rows)
    log("Stage 1 (processing clips)", 1)
    stage_one(comps)
    log("Stage 2 (concatenate)", 1)
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
        from clippy.config import container_ext as _ext
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
    _was_interrupted = False
    try:
        stage_two(comps, final_names)
    except KeyboardInterrupt:
        # Cooperative shutdown: signal pipeline to stop and clean up child procs
        try:
            from clippy.pipeline import request_shutdown
            request_shutdown()
        except Exception:
            pass
        _was_interrupted = True
    if _was_interrupted:
        log("Interrupted by user (Ctrl-C). Stopping encoder and cleaning up...", 1)
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
            "version": CLIPPY_VERSION,
            "files": finals,
            "compilations": [[row[0] for row in comp] for comp in comps],
            "created_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        _m_path = _os.path.join(output, "manifest.json")
        with open(_m_path, "w", encoding="utf-8") as f:
            _json.dump(manifest, f, indent=2)
        log("Wrote manifest: " + _m_path, 1)
    except Exception as e:
        log("WARN Failed to write manifest: " + str(e), 2)
    log("Done", 2)


if __name__ == "__main__":  # pragma: no cover
    try:
        main()
    except KeyboardInterrupt:
        # Global catch in case Ctrl-C occurs outside main's guarded block
        try:
            from clippy.pipeline import request_shutdown
            request_shutdown()
        except Exception:
            pass
        try:
            from clippy.utils import log as _log
            _log("Interrupted by user. Exiting.")
        except Exception:
            print("Interrupted by user. Exiting.")
