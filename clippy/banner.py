from __future__ import annotations

import os
import sys

from clippy.theme import THEME, enable_windows_vt  # type: ignore

_VT_ENABLED = False


def _enable_windows_vt():
    global _VT_ENABLED
    if _VT_ENABLED:
        return
    enable_windows_vt()
    _VT_ENABLED = True


def show_banner(force: bool = False):
    """Print a hacker-style ASCII banner once at program start.

    Respects:
      - CLIPPY_NO_BANNER=1 to disable
      - Skips if stdout is not a TTY unless force=True
    """
    if os.environ.get("CLIPPY_NO_BANNER", "").strip() in ("1", "true", "yes"):
        return
    if not force and not sys.stdout.isatty():
        return
    _enable_windows_vt()

    lines = [
        r"       .__  .__                                       ",
        r"  ____ |  | |__|_____ ______ ___.__.    ______ ___.__.",
        r"_/ ___\|  | |  \____ \\____ <   |  |    \____ <   |  |",
        r"\  \___|  |_|  |  |_> >  |_> >___  |    |  |_> >___  |",
        r" \___  >____/__|   __/|   __// ____| /\ |   __// ____|",
        r"     \/        |__|   |__|   \/      \/ |__|   \/     ",
    ]

    # Colorize
    neon = THEME.title
    accent = THEME.path
    dim = THEME.bar

    for i, line in enumerate(lines):
        if i <= 5:
            print(neon(line))
        elif line.strip():
            print(accent(line))
        else:
            print("")
    # Accent underline
    print(dim("=" * 56))
