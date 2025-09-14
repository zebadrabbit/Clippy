from __future__ import annotations

import os
import sys
from typing import Optional

try:
    from yachalk import chalk
except Exception:  # fallback if chalk not available
    class _Plain:
        def __getattr__(self, name):
            return lambda s: s
    chalk = _Plain()  # type: ignore


_VT_ENABLED = False


def _enable_windows_vt():
    global _VT_ENABLED
    if _VT_ENABLED:
        return
    if os.name != 'nt':
        _VT_ENABLED = True
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        _VT_ENABLED = True
    except Exception:
        _VT_ENABLED = False


def show_banner(force: bool = False):
    """Print a hacker-style ASCII banner once at program start.

    Respects:
      - CLIPPY_NO_BANNER=1 to disable
      - Skips if stdout is not a TTY unless force=True
    """
    if os.environ.get('CLIPPY_NO_BANNER', '').strip() in ('1', 'true', 'yes'):
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
    neon = chalk.green_bright
    accent = chalk.cyan
    dim = chalk.gray

    for i, line in enumerate(lines):
        if i <= 5:
            print(neon(line))
        elif line.strip():
            print(accent(line))
        else:
            print("")
    # Accent underline
    print(dim("=" * 56))
