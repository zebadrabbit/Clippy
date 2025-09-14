from __future__ import annotations

import argparse
from typing import Optional
from . import __version__
from config import reactionThreshold, amountOfClips, amountOfCompilations


def parse_args() -> argparse.Namespace:
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
    g_required.add_argument("--broadcaster", help="Broadcaster login name (e.g. theflood). If omitted, uses identity.broadcaster from clippy.yaml if set.")
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
    g_misc.add_argument("--version", action="version", version=f"Clippy {__version__}")

    return p.parse_args()
