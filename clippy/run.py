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

r"""Clippy orchestration: fetch Twitch clips and build compilations.

This module backs the ``clippy`` command (see :func:`console_main`) and the
legacy ``python main.py`` shim.

Quick start:
    clippy setup                       # guided first-time setup
    clippy --broadcaster somechannel   # build compilations
    clippy tui                         # interactive TUI

Optional time window:
    clippy --broadcaster somechannel --start 2025-07-01T00:00:00Z --end 2025-07-07T00:00:00Z

It orchestrates the processing pipeline (download, normalize, optional overlay,
concat) using the typed ClippyConfig plus runtime CLI overrides.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

# Note on optional Discord dependency: we only import discord-related helpers when
# --discord mode is requested, so Twitch-only flows don't need discord.py installed.
from clippy import __version__ as CLIPPY_VERSION
from clippy import exits
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
from clippy.runtime import _load_env_if_present
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
from clippy.window import resolve_date_window
from clippy.window import summarize as _summarize

logger = logging.getLogger(__name__)

try:
    from clippy.theme import THEME, enable_windows_vt, hi, paint, tx  # type: ignore
except ImportError:  # pragma: no cover
    THEME = None  # type: ignore

    def enable_windows_vt():  # type: ignore
        return

    def hi(value):  # type: ignore
        return str(value)

    def tx(text):  # type: ignore
        return str(text)

    def paint(text, *styles):  # type: ignore
        return str(text)


def _fail(message: str, code: int):
    """Report *message* and exit with a code a scheduler can act on.

    SystemExit(str) prints the message but always exits 1, which makes "nothing
    matched this week" indistinguishable from "ffmpeg died".
    """
    log(message, 5)
    raise SystemExit(code)


def _apply_encoding_preset(encoding, preset_name: str):
    """Fold a named encoding preset into an ``EncodingConfig`` baseline.

    The codec lives on the config module rather than ``ClippyConfig`` (same channel
    the TUI quality screen writes), so ``cpu_only`` sets it there.
    """
    import dataclasses as _dc

    import clippy.config as _cfg
    from clippy.presets import from_preset

    try:
        p = from_preset(preset_name)
    except KeyError as exc:
        log(str(exc), 5)
        raise SystemExit(2) from exc

    _cfg.video_codec = p.video_codec
    return _dc.replace(
        encoding,
        bitrate=p.max_bitrate,
        resolution=p.resolution,
        fps=p.fps,
        audio_bitrate=p.audio_bitrate,
        container_ext=p.container_ext,
        container_flags=p.container_flags,
        nvenc=_dc.replace(encoding.nvenc, preset=p.preset, cq=str(p.cq), gop=str(p.gop)),
    )


def apply_cli_overrides(args):
    """Build the typed ClippyConfig from defaults + CLI args (the single writer).

    Every CLI override flows into one ``set_config()`` call, so the typed config is
    the single source of truth the pipeline and templating read from.  Values not
    modelled on ``ClippyConfig`` (the transitions-dir resolver) are handled as
    explicit side effects at the end.
    """
    import dataclasses as _dc

    import clippy.config as _cfg

    # A profile is a layer under the CLI flags: re-read the file with it applied
    # first, then let the explicit flags below win over whatever it set.
    if getattr(args, "profile", None):
        try:
            _cfg.reload_with_profile(args.profile)
        except Exception as exc:  # a bad profile must not end the run
            log(f"Could not apply profile {args.profile!r}: {exc}", 5)

    cfg = _cfg.get_config()

    # A profile can default to Discord (identity.source: discord); --discord/
    # --no-discord on the CLI always wins when passed explicitly.
    if getattr(args, "discord", None) is None:
        args.discord = cfg.identity.source == "discord"

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
    # A --preset replaces the encoding baseline; individual flags below still win.
    base_encoding = cfg.encoding
    if getattr(args, "encoding_preset", None):
        base_encoding = _apply_encoding_preset(base_encoding, args.encoding_preset)

    qmap = {"balanced": "10M", "high": "12M", "max": "16M"}
    chosen_bitrate = (
        args.bitrate or (qmap.get(args.quality) if args.quality else None) or base_encoding.bitrate
    )
    container_ext = base_encoding.container_ext
    container_flags = base_encoding.container_flags
    if args.format == "mp4":
        container_ext, container_flags = "mp4", "-movflags +faststart"
    elif args.format == "mkv":
        container_ext, container_flags = "mkv", ""
    nvenc = _dc.replace(
        base_encoding.nvenc,
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
        base_encoding,
        bitrate=chosen_bitrate,
        resolution=args.resolution or base_encoding.resolution,
        container_ext=container_ext,
        container_flags=container_flags,
        fps=args.fps or base_encoding.fps,
        audio_bitrate=args.audio_bitrate or base_encoding.audio_bitrate,
        yt_format=args.yt_format or base_encoding.yt_format,
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
        _audio_bitrate = _live.encoding.audio_bitrate
        _silence_static = _live.audio.silence_static
        _norm_clips = _live.audio.audio_normalize_clips
        _norm_trans = _live.audio.audio_normalize_transitions
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
        _source = "Discord" if getattr(args, "discord", False) else "Helix"
        print(f"{L('Source')}{S()}{V(_source)}")
        if getattr(args, "discord", False):
            _ch_id = getattr(args, "discord_channel_id", None) or _live.discord.channel_id
            if _ch_id:
                print(f"{L('Discord channel')}{S()}{V(str(_ch_id))}")
        try:
            import clippy.config as _cfg_mod

            _profile_name = getattr(_cfg_mod, "active_profile", "") or "default"
        except Exception:  # cosmetic; non-fatal
            _profile_name = "default"
        print(f"{L('Profile')}{S()}{V(_profile_name)}")
        print(f"{L('Broadcaster')}{S()}{V(str(args.broadcaster), True)}")

        def _short_date(iso: Optional[str]) -> Optional[str]:
            return iso.split("T", 1)[0] if iso and "T" in iso else iso

        _start_s, _end_s = window
        _span_txt = ""
        try:
            from datetime import datetime as _dt

            if _start_s and _end_s:
                _d0 = _dt.fromisoformat(_start_s.replace("Z", "+00:00"))
                _d1 = _dt.fromisoformat(_end_s.replace("Z", "+00:00"))
                _days = max(1, round((_d1 - _d0).total_seconds() / 86400))
                _span_txt = f" ({_days} day{'s' if _days != 1 else ''})"
        except (ValueError, TypeError):
            _span_txt = ""
        print(
            f"{L('Time Window')}{S()}{V(_short_date(_start_s) or 'ANY', True)} "
            f"{S('->')} {V(_short_date(_end_s) or 'NOW', True)}{S(_span_txt)}"
        )
        print(f"{L('Min views')}{S()}{V(str(_min_views))}")
        print(
            f"{L('Format')}{S()}{V(_container_ext)} {S('(')}{V(_container_flags or 'no flags')}{S(')')}"
        )
        print(
            f"{L('Resolution')}{S()}{V(_resolution)}  {L('FPS')}{S()}{V(str(_fps))}  "
            f"{L('Bitrate')}{S()}{V(str(_bitrate))}  {L('Audio')}{S()}{V(str(_audio_bitrate))}"
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
        print(f"{L('Output dir')}{S()}{V(str(_output), True)}")
        tr_desc = f"intro={len(_intro_list)}, trans={len(_transitions_list)}, outro={len(_outro_list)}, prob={_tprob}"
        if _norand:
            tr_desc += f" {S('[no-random]')}"
        print(f"{L('Transitions')}{S()}{V(tr_desc)}")
        print(f"{L('Overlay')}{S()}{V('enabled' if _overlay else 'disabled')}")
        if not _norm_clips or not _norm_trans or _silence_static:
            notes = []
            if not _norm_clips:
                notes.append("clips not normalized")
            if not _norm_trans:
                notes.append("transitions not normalized")
            if _silence_static:
                notes.append("static.mp4 silenced")
            print(f"{L('Audio notes')}{S()}{V(', '.join(notes))}")
        if _rebuild:
            print(f"{L('Rebuild')}{S()}{V('true')}")
        print(bar)
        # Prompt
        ans = input("Proceed? [Y/n]: ").strip().lower()
        if ans in ("n", "no"):
            _fail("Aborted by user", exits.ERROR)
    except EOFError:
        # If input is not available, fail safe unless --yes provided
        _fail(
            "Confirmation required but no TTY available. Re-run with -y/--yes " "(or --headless).",
            exits.USAGE,
        )


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
            _fail(str(_imp_err), exits.USAGE)
        try:
            import clippy.config as _cfg

            _discord_channel_id = getattr(_cfg, "discord_channel_id", None)
            _discord_limit = getattr(_cfg, "discord_message_limit", 200)
        except (ImportError, AttributeError):
            _discord_channel_id = None
            _discord_limit = 200
        ch_id = args.discord_channel_id or _discord_channel_id
        if not ch_id:
            _fail(
                "Discord mode requires --discord-channel-id or clippy.yaml discord.channel_id",
                exits.USAGE,
            )
        d_token = load_discord_token(args.discord_token if hasattr(args, "discord_token") else None)
        import asyncio as _asyncio

        log("Reading Discord channel for clip links", 1)
        try:
            clip_ids, _channel_disp = _asyncio.run(
                fetch_recent_clip_ids(
                    d_token, int(ch_id), limit=int(args.discord_limit or _discord_limit)
                )
            )
        except ModuleNotFoundError as _imp_err:
            # discord.py is imported lazily inside fetch_recent_clip_ids (so the URL
            # parser works without it installed), so a missing install only surfaces
            # here, not at the top-level `from clippy.discord_ingest import ...`.
            log("Discord mode requires the optional dependency 'discord.py'", 5)
            log("Install it with: pip install discord.py", 1)
            _fail(str(_imp_err), exits.USAGE)
        try:
            if _channel_disp:
                log("Discord channel: " + str(_channel_disp), 2)
        except Exception:  # logging; non-fatal
            pass
        # Dedupe and limit to max_clips
        clip_ids = list(dict.fromkeys(clip_ids))[: args.max_clips]
        if not clip_ids:
            _fail("No clip links found in the specified Discord channel", exits.NO_CLIPS)
        try:
            log(tx("Found ") + hi(len(clip_ids)) + tx(" clip links"), 2)
        except Exception:  # logging; non-fatal
            pass
        log(tx("Fetching clips by IDs from ") + hi("Helix"), 1)
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
            _fail("Broadcaster not found", exits.USAGE)
        broadcaster_id = user["id"]
        log("Resolved broadcaster id: " + str(broadcaster_id), 2)
        log(tx("Fetching clips from ") + hi("Helix"), 1)
        clips = fetch_clips(
            broadcaster_id=broadcaster_id,
            client_id=cid,
            token=token,
            started_at=window[0],
            ended_at=window[1],
            max_clips=args.max_clips,
        )
    log(tx("Fetched ") + hi(len(clips)) + tx(" raw clips"), 2)
    return clips, broadcaster_id


def filter_and_expand(clips, args, cid, token, broadcaster_id, window):
    """Apply view-count filter and auto-expand window if needed. Returns (filtered, window)."""
    from clippy.config import get_config

    min_views = get_config().selection.min_views
    # Filter by min views
    filtered = [c for c in clips if int(c.get("view_count", 0)) >= min_views]
    log(
        tx("Filtered to ") + hi(len(filtered)) + tx(" clips (>= ") + hi(min_views) + tx(" views)"),
        2,
    )

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
            _fail("No clips meet criteria", exits.NO_CLIPS)

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
        # Narrow on purpose: a flaky Helix call or malformed clip data is
        # expected and recoverable, but a TypeError/AttributeError here is a bug
        # and must not be downgraded to a log line that looks like "found nothing".
        except (requests.RequestException, ValueError, KeyError) as e:
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
        except (requests.RequestException, ValueError, KeyError) as e:
            log(f"Nostalgia fetch failed: {e}", 5)

    return filtered, window


def run_pipeline(comps, args, window):
    """Run stage_one, stage_two, finalize outputs, and write manifest."""
    from clippy.config import get_config

    _live = get_config()
    cache = _live.paths.cache
    output = _live.paths.output
    log(paint("Stage 1", "white", "bold") + tx(": Processing clips"), 1)
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
                _fail("No compilations available after concat list generation", exits.TOOL)
    except Exception:
        # Non-fatal: continue and let stage_two handle any missing files
        pass
    log(paint("Stage 2", "white", "bold") + tx(": Concatenating"), 1)
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
        manifest = {
            "broadcaster": args.broadcaster,
            "window": {"start": window[0], "end": window[1]},
            "version": CLIPPY_VERSION,
            "files": finals,
        }
    log("Done", 2)
    return manifest


def main():  # noqa: C901
    # Load .env early so preflight + ingestion see saved credentials.
    _load_env_if_present()

    # Show banner unless help is requested or non-interactive
    # Peek at argv for -h/--help to avoid printing above help output
    _argv = [a.lower() for a in sys.argv[1:]]
    _quiet = any(a in ("-h", "--help", "--version", "--headless", "--json") for a in _argv)
    if not _quiet:
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
                log("Run 'clippy setup' for guided setup, or pass --broadcaster <name>", 1)
                raise SystemExit(2)

    # Preflight: report all setup problems (ffmpeg, credentials, transitions) at once.
    from clippy import preflight as _pf

    if _pf.report(_pf.run_preflight(discord_mode=getattr(args, "discord", False))):
        raise SystemExit(2)

    # Interactive confirmation (default). Use -y/--yes to skip.
    if not getattr(args, "yes", False):
        display_confirmation(args, window)

    cid, secret = load_credentials(args.client_id, args.client_secret)
    try:
        token = get_app_access_token(cid, secret)
    except RuntimeError as exc:
        # Wrong or revoked client id/secret: worth waking someone for, unlike an
        # empty week.
        _fail(str(exc), exits.AUTH)

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

    return run_pipeline(comps, args, window)


def _run_with_shutdown(fn):
    """Run *fn*, converting Ctrl-C into a cooperative pipeline shutdown.

    Returns whatever *fn* returned, or raises SystemExit(INTERRUPTED) so an
    unattended caller can tell a cancelled run from a finished one.
    """
    try:
        return fn()
    except KeyboardInterrupt:
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
        raise SystemExit(exits.INTERRUPTED) from None


def _headless_requested(argv: list[str]) -> bool:
    """True if this invocation must never wait for a human.

    Checked before argparse runs, because the banner and colour setup happen
    first and both want to know.
    """
    return "--headless" in argv


def _emit_json(result: Optional[dict], code: int) -> None:
    """Print the machine-readable result document.

    Always a complete document, even on failure: a scheduler should be able to
    parse one shape regardless of outcome.
    """
    import json as _json

    payload = {
        "status": exits.name(code),
        "exit_code": code,
        "files": (result or {}).get("files", []),
        "broadcaster": (result or {}).get("broadcaster"),
        "window": (result or {}).get("window"),
        "compilations": len((result or {}).get("files", []) or []),
        "version": CLIPPY_VERSION,
    }
    print(_json.dumps(payload, indent=2))


def _is_first_run() -> bool:
    """True when no config exists yet and we're attached to an interactive terminal."""
    try:
        return not os.path.exists("clippy.yaml") and sys.stdin.isatty()
    except Exception:
        return False


def console_main(argv: Optional[list[str]] = None) -> None:
    """Entry point for the ``clippy`` command.

    Subcommands:
      clippy setup         Interactive first-run setup (writes clippy.yaml + .env).
      clippy tui           Launch the interactive TUI.
      clippy doctor        Check your setup (ffmpeg, credentials, transitions, ...).
      clippy [options]     Build compilations (the CLI; see ``clippy --help``).
    """
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0].lower() if args else ""

    if cmd in ("setup", "init", "wizard"):
        from clippy.wizard import main as wizard_main

        wizard_main()
        return

    if cmd == "tui":
        from clippy.tui.app import run_tui

        run_tui()
        return

    if cmd in ("doctor", "check"):
        from clippy import preflight as _pf

        _load_env_if_present()
        if _pf.report(_pf.run_preflight()):
            raise SystemExit(1)
        log("All preflight checks passed — you're good to go.", 1)
        return

    if cmd == "version":
        print(f"Clippy {CLIPPY_VERSION}")
        return

    if "--list-profiles" in args:
        from clippy.config_loader import list_profiles
        from clippy.log import get_logger

        get_logger()
        from clippy.config_loader import DEFAULT_PROFILE

        names = list_profiles()
        print("Profiles (use --profile <name>):\n")
        for name in names:
            note = "   base config, transitions root" if name == DEFAULT_PROFILE else ""
            print(f"  {name}{note}")
        if names == [DEFAULT_PROFILE]:
            print("\nRun 'clippy profile' to add one per streamer.")
        return

    if cmd in ("deps", "install-deps"):
        from clippy.deps import (
            ASSETS,
            ASSETS_DEST,
            advice,
            install,
            is_windows,
            missing_assets,
            missing_tools,
        )

        _load_env_if_present()
        if not is_windows():
            log("Automatic download is Windows-only.", 2)
            log(advice(), 1)
            return
        explicit = [a for a in args[1:] if not a.startswith("-")]
        if explicit:
            wanted_tools = [a for a in explicit if a in ("ffmpeg", "yt-dlp")]
            wanted_assets = [a for a in explicit if a in ASSETS]
        else:
            wanted_tools = missing_tools()
            wanted_assets = missing_assets()
        if not wanted_tools and not wanted_assets:
            log("ffmpeg, yt-dlp and static.mp4 are already available.", 1)
            return

        from clippy.spinner import progress_bar, spinner_char

        _spin_i = [0]

        def _dl_progress(name: str, done: int, total: int) -> None:
            spin = spinner_char(_spin_i)
            mb_done = done / (1024 * 1024)
            if total:
                pct = max(0, min(100, int(done / total * 100)))
                mb_total = total / (1024 * 1024)
                sys.stdout.write(
                    f"\r{spin}Downloading {name} {progress_bar(pct)} "
                    f"({mb_done:.1f}/{mb_total:.1f} MB)   "
                )
                if done >= total:
                    sys.stdout.write("\n")
            else:
                sys.stdout.write(f"\r{spin}Downloading {name} ({mb_done:.1f} MB)   ")
            sys.stdout.flush()

        try:
            if wanted_tools:
                install(wanted_tools, log=lambda m: log(m, 1), on_progress=_dl_progress)
            if wanted_assets:
                install(
                    wanted_assets,
                    dest=ASSETS_DEST,
                    specs=ASSETS,
                    log=lambda m: log(m, 1),
                    on_progress=_dl_progress,
                )
        except Exception as exc:
            log(str(exc), 5)
            raise SystemExit(exits.TOOL) from exc
        log("Done. Run 'clippy doctor' to confirm.", 2)
        return

    if cmd in ("profile", "profiles"):
        from clippy.wizard import profile_wizard

        profile_wizard(args[1:])
        return

    if "--list-presets" in args:
        from clippy.log import get_logger
        from clippy.presets import list_presets

        get_logger()  # reconfigures stdout to UTF-8 on Windows (descriptions use em dashes)
        print("Available encoding presets (use --preset <name>):\n")
        for name, desc in list_presets():
            print(f"  {name:<18} {desc}")
        return

    # Friendly nudge on a fresh checkout: suggest the wizard, then continue
    # (the CLI will still require a broadcaster and exit cleanly if none).
    if not args and _is_first_run():
        try:
            log("No clippy.yaml found yet — run 'clippy setup' for guided first-time setup.", 1)
        except Exception:
            pass

    headless = _headless_requested(args)
    want_json = "--json" in args
    if headless:
        # Colour codes and the banner are noise in a log file or a mail body.
        os.environ.setdefault("NO_COLOR", "1")

    result: Optional[dict] = None
    code = exits.OK
    try:
        result = _run_with_shutdown(main)
    except SystemExit as exc:
        raw = exc.code
        code = raw if isinstance(raw, int) else (exits.OK if raw is None else exits.ERROR)
        if isinstance(raw, str):
            # A message-only exit from somewhere not yet converted to a code.
            print(raw, file=sys.stderr)
    if want_json:
        _emit_json(result, code)
    if code:
        raise SystemExit(code)


if __name__ == "__main__":  # pragma: no cover
    console_main()
