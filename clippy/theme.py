from __future__ import annotations

import os
import sys

try:
    from yachalk import chalk  # type: ignore
except Exception:  # pragma: no cover
    class _Plain:
        def __getattr__(self, name):
            return lambda s: s
    chalk = _Plain()  # type: ignore


def enable_windows_vt() -> None:
    if os.name != 'nt':
        return
    try:  # pragma: no cover
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


class Theme:
    """Cool 90s BBS-style palette and helpers (cyan/blue/gray)."""

    def __init__(self):
        # Headings & sections
        self.bar = lambda s: chalk.gray(s)
        self.title = lambda s: chalk.cyan_bright(s)
        self.header = lambda s: chalk.cyan_bright(s)
        self.section = lambda s: chalk.blue(s)
        # Body text & accents
        self.text = lambda s: chalk.gray(s)
        self.value = lambda s: chalk.white(s)
        self.path = lambda s: chalk.cyan(s)
        self.success = lambda s: chalk.cyan(s)
        self.warn = lambda s: chalk.magenta(s)
        self.error = lambda s: chalk.magenta(s)
        # Prompt parts
        self.label = lambda s: chalk.cyan(s)
        self.default = lambda s: chalk.blue_bright(s)
        self.sep = lambda s: chalk.gray(s)
        self.choice_default = lambda s: chalk.cyan_bright(s)
        self.choice_other = lambda s: chalk.gray(s)
        # Symbols/indicators accent (bright pink/purple)
        self.symbol = lambda s: chalk.magenta_bright(s)


THEME = Theme()


def paint(text: str, *styles: str) -> str:
    """Best-effort wrapper around chalk styles by name."""
    s = chalk
    for st in styles:
        try:
            s = getattr(s, st)
        except Exception:
            pass
    try:
        return str(s(text))
    except Exception:
        return text


def status_tag(kind: str) -> str:
    kinds = {
        "OK": ("OK", ("cyan", "bold")),
        "WARN": ("WARN", ("magenta", "bold")),
        "MISSING": ("MISSING", ("magenta", "bold")),
        "INFO": ("INFO", ("blue", "bold")),
    }
    text, styles = kinds.get(kind, (kind, ()))
    return paint(f"[{text}]", *styles)
