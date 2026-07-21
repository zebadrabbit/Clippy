"""Exit codes.

An unattended run needs to be actionable without parsing the log. The important
distinction is between "ran fine, there was simply nothing to build" -- which a
nightly job should shrug off -- and a real failure that wants attention.
"""

from __future__ import annotations

#: Built at least one compilation.
OK = 0

#: Something unexpected went wrong.
ERROR = 1

#: Bad invocation or configuration: unknown broadcaster, missing setup, a
#: prompt that cannot be answered. Also argparse's own code for bad arguments.
USAGE = 2

#: Ran correctly and found nothing to build. Not a failure: an empty week, or a
#: min-views filter nothing cleared. Distinguishing this is the whole point of
#: having codes at all.
NO_CLIPS = 3

#: Credentials missing or rejected by Twitch.
AUTH = 4

#: An external tool failed -- ffmpeg or yt-dlp.
TOOL = 5

#: Interrupted (Ctrl-C, or a shutdown signal).
INTERRUPTED = 130

NAMES = {
    OK: "ok",
    ERROR: "error",
    USAGE: "usage",
    NO_CLIPS: "no-clips",
    AUTH: "auth",
    TOOL: "tool",
    INTERRUPTED: "interrupted",
}


def name(code: int) -> str:
    """Human-readable label for *code*, for logs and JSON output."""
    return NAMES.get(code, "error")
