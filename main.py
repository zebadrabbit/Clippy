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

r"""Clippy entrypoint: fetch Twitch clips and build compilations.

Quick start (PowerShell):
    $env:TWITCH_CLIENT_ID="xxxxx"; $env:TWITCH_CLIENT_SECRET="yyyyy"; \
    python .\main.py --broadcaster somechannel --max-clips 40 --clips 10 --compilations 2

Optional time window:
    --start 2025-07-01T00:00:00Z --end 2025-07-07T00:00:00Z

This orchestrates the processing pipeline (download, normalize, optional overlay, concat)
using configuration from config.py and runtime CLI overrides.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from clippy.twitch_ingest import (
    build_clip_rows,
    fetch_clips,
    fetch_clips_by_ids,
    fetch_creator_avatars,
    get_app_access_token,
    load_credentials,
    resolve_user,
)
from clippy.utils import log, prep_work

"""
Note on optional Discord dependency:
We only import discord-related helpers when --discord mode is requested.
This lets users run Twitch-only flows without installing discord.py.
"""

# Import processing helpers from existing main module
from clippy import __version__ as CLIPPY_VERSION
from clippy.banner import show_banner
from clippy.cli import parse_args
from clippy.naming import (
    ensure_unique_names as _ensure_unique_names,
)
from clippy.naming import (
    finalize_outputs,
)
from clippy.naming import (
    sanitize_filename as _sanitize_filename,
)
from clippy.pipeline import create_compilations_from, stage_one, stage_two  # DB removed
from clippy.runtime import ensure_transitions_static_present, ensure_twitch_credentials_if_needed
from clippy.window import resolve_date_window
from clippy.window import summarize as _summarize

logger = logging.getLogger(__name__)

try:
    from clippy.theme import THEME, enable_windows_vt  # type: ignore
except ImportError:  # pragma: no cover
    THEME = None  # type: ignore

    def enable_windows_vt():  # type: ignore
        return


def apply_cli_overrides(args):
    """Build the typed ClippyConfig from defaults + CLI args (the single writer).

    Every CLI override flows into one ``set_config()`` call, so the typed config is
    the single source of truth the pipeline and templating read from.  Values not
    modelled on ``ClippyConfig`` (the transitions-dir resolver) are handled as
    explicit side effects at the end.
    """
    import dataclasses as _dc

    import clippy.config as _cfg

    cfg = _cfg.get_config()

    # Discord prefill: borrow the configured broadcaster for nicer summaries.
    if getattr(args, "discord", False) and not getattr(args, "broadcaster", None):
        if cfg.identity.broadcaster:
            args.broadcaster = cfg.identity.broadcaster

    # --- Selection ---
    selection = _dc.replace(
        cfg.selection,
        clips_per_compilation=args.amountOfClips,
        compilations=args.amountOfCompilations,
        min_views=args.reactionThreshold,
    )

    # --- Encoding ---
    qmap = {"balanced": "10M", "high": "12M", "max": "16M"}
    chosen_bitrate = (
        args.bitrate or (qmap.get(args.quality) if args.quality else None) or cfg.encoding.bitrate
    )
    container_ext = cfg.encoding.container_ext
    container_flags = cfg.encoding.container_flags
    if args.format == "mp4":
        container_ext, container_flags = "mp4", "-movflags +faststart"
    elif args.format == "mkv":
        container_ext, container_flags = "mkv", ""
    nvenc = _dc.replace(
        cfg.encoding.nvenc,
        **{
            k: str(v)
            for k, v in {
                "cq": args.cq,
                "preset": args.nvenc_preset,
                "gop": args.gop,
                "rc_lookahead": args.rc_lookahead,
                "spatial_aq": args.spatial_aq,
                "temporal_aq": args.temporal_aq,
                "aq_strength": args.aq_strength,
            }.items()
            if v
        },
    )
    encoding = _dc.replace(
        cfg.encoding,
        bitrate=chosen_bitrate,
        resolution=args.resolution or cfg.encoding.resolution,
        container_ext=container_ext,
        container_flags=container_flags,
        fps=args.fps or cfg.encoding.fps,
        audio_bitrate=args.audio_bitrate or cfg.encoding.audio_bitrate,
        yt_format=args.yt_format or cfg.encoding.yt_format,
        nvenc=nvenc,
    )

    # --- Paths ---
    paths = _dc.replace(
        cfg.paths,
        cache=args.cache_dir or cfg.paths.cache,
        output=args.output_dir or cfg.paths.output,
    )

    # --- Assets (single-file intro/outro/transition overrides) ---
    assets = cfg.assets
    if args.intro is not None:
        assets = _dc.replace(assets, intro=[args.intro] if args.intro else [])
    if args.outro is not None:
        assets = _dc.replace(assets, outro=[args.outro] if args.outro else [])
    if args.transition:
        assets = _dc.replace(assets, transitions=[args.transition])

    # --- Sequencing ---
    sequencing = cfg.sequencing
    if args.transition_prob is not None:
        try:
            sequencing = _dc.replace(
                sequencing,
                transition_probability=max(0.0, min(1.0, float(args.transition_prob))),
            )
        except (TypeError, ValueError):
            pass
    if args.no_random_transitions:
        sequencing = _dc.replace(sequencing, no_random_transitions=True)

    # --- Audio ---
    audio = cfg.audio
    if getattr(args, "no_audio_normalize_transitions", False):
        audio = _dc.replace(audio, audio_normalize_transitions=False)
    if getattr(args, "no_normalize_clips", False):
        audio = _dc.replace(audio, audio_normalize_clips=False)

    # --- Behavior ---
    behavior = _dc.replace(
        cfg.behavior,
        enable_overlay=False if args.no_overlay else cfg.behavior.enable_overlay,
        rebuild=True if args.rebuild else cfg.behavior.rebuild,
        skip_bad_clip=True if args.skip_bad_clip else cfg.behavior.skip_bad_clip,
        max_concurrency=(
            max(1, int(args.max_concurrency))
            if args.max_concurrency is not None
            else cfg.behavior.max_concurrency
        ),
        transitions_rebuild=(
            True
            if getattr(args, "rebuild_transitions", False)
            else cfg.behavior.transitions_rebuild
        ),
        keep_clips=True if getattr(args, "keep_clips", False) else cfg.behavior.keep_clips,
        cache_ttl_days=(
            int(args.cache_ttl_days)
            if getattr(args, "cache_ttl_days", 0)
            else cfg.behavior.cache_ttl_days
        ),
        cache_max_size_mb=(
            int(args.cache_max_size_mb)
            if getattr(args, "cache_max_size_mb", 0)
            else cfg.behavior.cache_max_size_mb
        ),
    )

    _cfg.set_config(
        cfg.replace(
            selection=selection,
            encoding=encoding,
            paths=paths,
            assets=assets,
            sequencing=sequencing,
            audio=audio,
            behavior=behavior,
        )
    )

    # --- Side effects for values not modelled on ClippyConfig ---
    if args.transitions_dir:
        os.environ["TRANSITIONS_DIR"] = args.transitions_dir
        _cfg.transitions_dir = args.transitions_dir
        try:
            from clippy.utils import log as _log

            _log("Transitions directory override: " + os.path.abspath(args.transitions_dir), 1)
        except ImportError:
            pass

    # Fail fast if the required static transition is missing.
    ensure_transitions_static_present(getattr(args, "transitions_dir", None))


def display_confirmation(args, window):
    """Show BBS-style confirmation panel and prompt user to proceed."""
    try:
        # Concise BBS-style panel
        try:
            enable_windows_vt()
        except Exception:  # cosmetic; non-fatal
            pass
        try:
            from yachalk import chalk as _chalk
        except ImportError:

            class _Plain:
                def __getattr__(self, name):
                    return lambda s: s

            _chalk = _Plain()  # type: ignore
        title = THEME.title("Run plan") if THEME else _chalk.cyan_bright("Run plan")
        bar = THEME.bar("=" * 56) if THEME else _chalk.gray("=" * 56)

        def L(s: str) -> str:
            # Static labels: darker blue
            return THEME.section(s) if THEME else str(_chalk.blue(s))

        def S(txt: str = " : ") -> str:
            return THEME.sep(txt) if THEME else str(_chalk.gray(txt))

        def V(v: str, accent: bool = False) -> str:
            # Dynamic values: white
            return str(_chalk.white(v))

        # Gather values from the typed config (single source of truth)
        from clippy.config import get_config

        _live = get_config()
        _intro_list = _live.assets.intro
        _outro_list = _live.assets.outro
        _transitions_list = _live.assets.transitions
        _tprob = _live.sequencing.transition_probability
        _norand = _live.sequencing.no_random_transitions
        _min_views = _live.selection.min_views
        _container_ext = _live.encoding.container_ext
        _container_flags = _live.encoding.container_flags
        _resolution = _live.encoding.resolution
        _fps = _live.encoding.fps
        _bitrate = _live.encoding.bitrate
        _cache = _live.paths.cache
        _output = _live.paths.output
        _overlay = _live.behavior.enable_overlay
        _rebuild = _live.behavior.rebuild
        try:
            _total = int(args.amountOfCompilations) * int(args.amountOfClips)
        except (ValueError, TypeError):
            _total = None
        # Panel rendering
        print(bar)
        print(title)
        print(bar)
        print(f"{L('Broadcaster')}{S()}{V(str(args.broadcaster), True)}")
        print(
            f"{L('Time Window')}{S()}{V(str(window[0] or 'ANY'), True)} {S('->')} {V(str(window[1] or 'NOW'), True)}"
        )
        print(f"{L('Max fetch')}{S()}{V(str(args.max_clips))}")
        print(f"{L('Min views')}{S()}{V(str(_min_views))}")
        print(
            f"{L('Format')}{S()}{V(_container_ext)} {S('(')}{V(_container_flags or 'no flags')}{S(')')}"
        )
        print(
            f"{L('Resolution')}{S()}{V(_resolution)}  {L('FPS')}{S()}{V(str(_fps))}  {L('Bitrate')}{S()}{V(str(_bitrate))}"
        )
        comp_desc = f"{V(str(args.amountOfCompilations))} x {V(str(args.amountOfClips))}"
        if _total is not None:
            comp_desc += f" {S('(')}{V(str(_total))} {V('total')}{S(')')}"
        target_dur = getattr(args, "target_duration", 0) or 0
        if target_dur > 0:
            comp_desc = f"{V(str(args.amountOfCompilations))} x ~{V(str(target_dur))} min"
        print(f"{L('Compilations')}{S()}{comp_desc}")
        if getattr(args, "auto_expand", False) and not getattr(args, "no_auto_expand", False):
            print(f"{L('Auto-expand')}{S()}{V('enabled')}")
        if getattr(args, "nostalgia", False):
            print(f"{L('Nostalgia mode')}{S()}{V('enabled')}")
        print(f"{L('Cache dir')}{S()}{V(str(_cache), True)}")
        print(f"{L('Output dir')}{S()}{V(str(_output), True)}")
        tr_desc = f"intro={len(_intro_list)}, trans={len(_transitions_list)}, outro={len(_outro_list)}, prob={_tprob}"
        if _norand:
            tr_desc += f" {S('[no-random]')}"
        print(f"{L('Transitions')}{S()}{V(tr_desc)}")
        print(f"{L('Overlay')}{S()}{V('enabled' if _overlay else 'disabled')}")
        print(f"{L('Rebuild')}{S()}{V('true' if _rebuild else 'false')}")
        print(bar)
        # Prompt
        ans = input("Proceed? [Y/n]: ").strip().lower()
        if ans in ("n", "no"):
            raise SystemExit("Aborted by user")
    except EOFError:
        # If input is not available, fail safe unless --yes provided
        raise SystemExit("Confirmation required but no TTY available. Re-run with -y/--yes.")


def ingest_clips(args, cid, token, window):
    """Fetch clips from Discord or Twitch. Returns (clips, broadcaster_id)."""
    broadcaster_id = None
    if getattr(args, "discord", False):
        # Discord mode: read clip IDs from a channel and resolve via Helix
        try:
            from clippy.discord_ingest import (  # type: ignore
                fetch_recent_clip_ids,
                load_discord_token,
            )
        except ImportError as _imp_err:
            log("Discord mode requires the optional dependency 'discord.py'", 5)
            log("Install it with: pip install discord.py", 1)
            raise SystemExit(_imp_err)
        try:
            import clippy.config as _cfg

            _discord_channel_id = getattr(_cfg, "discord_channel_id", None)
            _discord_limit = getattr(_cfg, "discord_message_limit", 200)
        except (ImportError, AttributeError):
            _discord_channel_id = None
            _discord_limit = 200
        ch_id = args.discord_channel_id or _discord_channel_id
        if not ch_id:
            raise SystemExit(
                "Discord mode requires --discord-channel-id or clippy.yaml discord.channel_id"
            )
        d_token = load_discord_token(args.discord_token if hasattr(args, "discord_token") else None)
        import asyncio as _asyncio

        log("Reading Discord channel for clip links", 1)
        clip_ids, _channel_disp = _asyncio.run(
            fetch_recent_clip_ids(
                d_token, int(ch_id), limit=int(args.discord_limit or _discord_limit)
            )
        )
        try:
            if _channel_disp:
                log("Discord channel: " + str(_channel_disp), 2)
        except Exception:  # logging; non-fatal
            pass
        # Dedupe and limit to max_clips
        clip_ids = list(dict.fromkeys(clip_ids))[: args.max_clips]
        if not clip_ids:
            raise SystemExit("No clip links found in the specified Discord channel")
        try:
            log("Found " + str(len(clip_ids)) + " clip links", 2)
        except Exception:  # logging; non-fatal
            pass
        log("Fetching clips by IDs from Helix", 1)
        clips = fetch_clips_by_ids(clip_ids, cid, token)
        # Broadcaster for naming: use the first clip's broadcaster_name/login if present, else fallback
        try:
            b_name = (
                clips[0].get("broadcaster_name")
                or clips[0].get("broadcaster_login")
                or args.broadcaster
                or "clips"
            )
            args.broadcaster = b_name
        except (IndexError, KeyError):
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
    return clips, broadcaster_id


def filter_and_expand(clips, args, cid, token, broadcaster_id, window):
    """Apply view-count filter and auto-expand window if needed. Returns (filtered, window)."""
    from clippy.config import get_config

    min_views = get_config().selection.min_views
    # Filter by min views
    filtered = [c for c in clips if int(c.get("view_count", 0)) >= min_views]
    log("Filtered to " + str(len(filtered)) + " clips (>= " + str(min_views) + " views)", 2)

    # Compute target total — use duration estimate if --target-duration is set
    target_duration_min = getattr(args, "target_duration", 0) or 0
    if target_duration_min > 0:
        # Estimate ~30s avg clip duration to figure out how many clips we need
        est_clips = max(1, int((target_duration_min * 60) / 30))
        target_total = est_clips * int(args.amountOfCompilations)
    else:
        target_total = int(args.amountOfClips) * int(args.amountOfCompilations)

    # Determine if auto-expand is active
    do_auto_expand = getattr(args, "auto_expand", False)
    if getattr(args, "no_auto_expand", False):
        do_auto_expand = False

    if not filtered:
        # If auto-expand is off and we got none, stop here early.
        if not do_auto_expand:
            raise SystemExit("No clips meet criteria")

    # Auto-expand: extend the start date backwards until we reach target clips or max lookback
    if do_auto_expand and len(filtered) < target_total:
        try:
            # Helper to parse ISO8601 Z to aware datetime
            def _parse_iso_z(s: Optional[str]) -> Optional[datetime]:
                if not s:
                    return None
                try:
                    return datetime.fromisoformat(s.replace("Z", "+00:00"))
                except (ValueError, TypeError):
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
            lookback_limit = end_dt - timedelta(days=max_look)

            while len(collected) < target_total and current_start > lookback_limit:
                new_start = current_start - timedelta(days=step_days)
                new_start_iso = (
                    new_start.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
                )
                # Fetch only the earlier segment to reduce overlap
                seg_clips = fetch_clips(
                    broadcaster_id=broadcaster_id,
                    client_id=cid,
                    token=token,
                    started_at=new_start_iso,
                    ended_at=current_start.replace(tzinfo=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    max_clips=args.max_clips,
                )
                if not seg_clips:
                    log("Auto-expand: no clips found for segment", 2)
                # Filter and dedupe
                seg_filtered = [c for c in seg_clips if int(c.get("view_count", 0)) >= min_views]
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
            except Exception:  # non-fatal window update
                pass
            log(
                "After expand: "
                + str(len(filtered))
                + " filtered clips (target "
                + str(target_total)
                + ")",
                2,
            )
        except Exception as e:  # auto-expand is best-effort
            log("Auto-expand failed: " + str(e), 5)

    # Nostalgia mode: mix in random older clips (>6 months old)
    if getattr(args, "nostalgia", False) and filtered:
        import random as _rng

        log("Nostalgia mode: fetching older clips (>6 months)...", 1)
        six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
        one_year_ago = six_months_ago - timedelta(days=180)
        try:
            old_clips = fetch_clips(
                broadcaster_id=broadcaster_id,
                client_id=cid,
                token=token,
                started_at=one_year_ago.isoformat().replace("+00:00", "Z"),
                ended_at=six_months_ago.isoformat().replace("+00:00", "Z"),
                max_clips=50,
            )
            old_filtered = [c for c in old_clips if int(c.get("view_count", 0)) >= min_views]
            seen_ids = {c.get("id") for c in filtered}
            old_unique = [c for c in old_filtered if c.get("id") not in seen_ids]
            if old_unique:
                n_nostalgia = max(1, target_total // 5)
                n_nostalgia = min(n_nostalgia, len(old_unique))
                picks = _rng.sample(old_unique, n_nostalgia)
                log(f"Mixing in {len(picks)} nostalgia clip(s)", 2)
                result = list(filtered[: target_total - n_nostalgia])
                for p in picks:
                    pos = _rng.randint(0, len(result))
                    result.insert(pos, p)
                filtered = result
            else:
                log("No unique nostalgia clips found (>6 months old)", 2)
        except Exception as e:  # nostalgia is best-effort
            log(f"Nostalgia fetch failed: {e}", 5)

    return filtered, window


def run_pipeline(comps, args, window):
    """Run stage_one, stage_two, finalize outputs, and write manifest."""
    from clippy.config import get_config

    _live = get_config()
    cache = _live.paths.cache
    output = _live.paths.output
    log("Stage 1 (processing clips)", 1)
    stage_one(comps)
    # Verify concat lists were written for each expected compilation index.
    # If any concat file is missing, log and drop that compilation to avoid surprise.
    try:
        missing = []
        present = []
        import os as _os

        for i in range(len(comps)):
            concat_path = _os.path.join(cache, f"comp{i}")
            if not _os.path.exists(concat_path):
                missing.append(i)
            else:
                present.append(i)
        if missing:
            try:
                log(
                    f"WARN: Missing concat lists for indices: {', '.join(str(m) for m in missing)}; these compilations will be skipped",
                    2,
                )
            except Exception:  # logging; non-fatal
                pass
            # Filter out missing comps in order
            comps = [c for idx, c in enumerate(comps) if idx in present]
            if not comps:
                raise SystemExit("No compilations available after concat list generation")
    except Exception:
        # Non-fatal: continue and let stage_two handle any missing files
        pass
    log("Stage 2 (concatenate)", 1)
    # Build the final filenames for display during compilation
    b_name = _sanitize_filename(args.broadcaster.lower()) or "broadcaster"
    start_iso, end_iso = window

    def _date_part(iso_str: Optional[str]) -> Optional[str]:
        if not iso_str:
            return None
        return iso_str.split("T", 1)[0]

    if start_iso or end_iso:
        s_part = _date_part(start_iso) or "unknown"
        e_part = _date_part(end_iso) or s_part
        date_range = f"{s_part}_to_{e_part}"
    else:
        date_range = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _ext = _live.encoding.container_ext
    base_names = []
    for i in range(len(comps)):
        if len(comps) == 1:
            base_names.append(f"{b_name}_{date_range}_compilation.{_ext}")
        else:
            base_names.append(f"{b_name}_{date_range}_part{i+1}.{_ext}")
    # Ensure names are unique upfront unless overwrite requested
    final_names = _ensure_unique_names(base_names, output, getattr(args, "overwrite_output", False))
    _was_interrupted = False
    try:
        stage_two(comps, final_names)
    except KeyboardInterrupt:
        # Cooperative shutdown: signal pipeline to stop and clean up child procs
        try:
            from clippy.pipeline import request_shutdown

            request_shutdown()
        except Exception:  # best-effort shutdown
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
        overwrite_output=getattr(args, "overwrite_output", False),
        purge_cache=getattr(args, "purge_cache", False),
        keep_clips=getattr(args, "keep_clips", False),
        cache_ttl_days=getattr(args, "cache_ttl_days", 0),
        cache_max_size_mb=getattr(args, "cache_max_size_mb", 0),
    )
    # Write manifest.json with metadata and clip IDs per compilation
    try:
        import json as _json
        import os as _os

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
        try:
            _disp_path = _m_path.replace("\\", "/")
        except (TypeError, AttributeError):
            _disp_path = _m_path
        log("Wrote manifest: " + _disp_path, 1)
    except (OSError, TypeError, ValueError) as e:
        log("WARN Failed to write manifest: " + str(e), 2)
    log("Done", 2)


def main():  # noqa: C901
    # Ensure we have Twitch creds when running a broadcaster ingest
    ensure_twitch_credentials_if_needed()

    # Show banner unless help is requested or non-interactive
    # Peek at argv for -h/--help to avoid printing above help output
    _argv = [a.lower() for a in sys.argv[1:]]
    if not any(a in ("-h", "--help", "--version") for a in _argv):
        try:
            show_banner()
        except Exception:  # cosmetic; non-fatal
            pass
        try:
            from yachalk import chalk as _chalk

            print(str(_chalk.gray(f"Version {CLIPPY_VERSION}")))
        except Exception:  # cosmetic; non-fatal
            print(f"Version {CLIPPY_VERSION}")
    args = parse_args()

    # Launch TUI if requested
    if getattr(args, "tui", False):
        from clippy.tui.app import run_tui

        run_tui()
        return

    # Seed randomness if provided early
    if getattr(args, "seed", None) is not None:
        try:
            import random as _rnd

            _rnd.seed(int(args.seed))
        except (ValueError, TypeError):
            pass

    apply_cli_overrides(args)

    # Resolve simple date window to RFC3339
    window = resolve_date_window(args.start, args.end)
    # Show startup summary only when skipping confirmation to avoid duplication
    if getattr(args, "yes", False):
        from clippy.config import get_config

        _enc = get_config().encoding
        _summarize(
            args,
            window,
            _enc.resolution,
            _enc.container_ext,
            _enc.bitrate,
        )

    # If not in Discord mode, require a broadcaster (CLI or config). In Discord mode, we'll infer later.
    if not getattr(args, "discord", False):
        try:
            from clippy.config import get_config

            _def_b = get_config().identity.broadcaster
        except Exception:  # defensive fallback
            _def_b = ""
        if not getattr(args, "broadcaster", None):
            if _def_b:
                args.broadcaster = _def_b
                log("Using default broadcaster from config: " + str(_def_b), 1)
            else:
                log(
                    "No broadcaster provided and no default configured in clippy.yaml (identity.broadcaster)",
                    5,
                )
                log("Set identity.broadcaster via setup_wizard or provide --broadcaster", 1)
                raise SystemExit(2)

    # Interactive confirmation (default). Use -y/--yes to skip.
    if not getattr(args, "yes", False):
        display_confirmation(args, window)

    cid, secret = load_credentials(args.client_id, args.client_secret)
    token = get_app_access_token(cid, secret)

    # Save credentials to .env if requested
    if getattr(args, "save_env", False):
        try:
            from clippy.runtime import save_env

            env_vals = {"TWITCH_CLIENT_ID": cid, "TWITCH_CLIENT_SECRET": secret}
            if getattr(args, "discord_token", None):
                env_vals["DISCORD_TOKEN"] = args.discord_token
            if getattr(args, "discord_channel_id", None):
                env_vals["DISCORD_CHANNEL_ID"] = str(args.discord_channel_id)
            save_env(env_vals)
            log("Credentials saved to .env", 1)
        except Exception as e:  # non-fatal
            log(f"Failed to save .env: {e}", 5)

    prep_work()

    clips, broadcaster_id = ingest_clips(args, cid, token, window)
    filtered, window = filter_and_expand(clips, args, cid, token, broadcaster_id, window)

    avatar_map = fetch_creator_avatars(filtered, cid, token)
    rows = build_clip_rows(filtered, avatar_map)

    # Duration-based or count-based compilation splitting
    target_duration_min = getattr(args, "target_duration", 0) or 0
    target_duration_secs = target_duration_min * 60 if target_duration_min > 0 else 0
    comps = create_compilations_from(rows, target_duration_secs=target_duration_secs)

    run_pipeline(comps, args, window)


if __name__ == "__main__":  # pragma: no cover
    try:
        main()
    except KeyboardInterrupt:
        # Global catch in case Ctrl-C occurs outside main's guarded block
        try:
            from clippy.pipeline import request_shutdown

            request_shutdown()
        except Exception:  # best-effort shutdown
            pass
        try:
            from clippy.utils import log as _log

            _log("Interrupted by user. Exiting.")
        except ImportError:
            print("Interrupted by user. Exiting.")
