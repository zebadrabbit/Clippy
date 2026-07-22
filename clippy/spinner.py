"""A spinner glyph and a text progress bar for long-running CLI steps.

Off when stdout isn't a real terminal (piped/redirected output, e.g. headless
runs logging to a file) since \\r-redraws would just corrupt a log.
"""

from __future__ import annotations

import sys

_SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner_char(counter: list) -> str:
    """Next spinner glyph, advancing *counter[0]* each call."""
    if not sys.stdout.isatty():
        return ""
    ch = _SPIN_FRAMES[counter[0] % len(_SPIN_FRAMES)]
    counter[0] += 1
    return ch + " "


def progress_bar(pct: int, width: int = 18) -> str:
    filled = max(0, min(width, round(width * pct / 100)))
    return "[" + ("#" * filled) + ("-" * (width - filled)) + f"] {pct:3d}%"
