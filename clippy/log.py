"""Centralized logging for Clippy.

Replaces the ad-hoc ``utils.log()`` with stdlib ``logging``, keeping the
BBS-style theme formatting via a custom ``Formatter``.

Usage (new code)::

    import logging
    logger = logging.getLogger("clippy")
    logger.info("something happened")
    logger.error("something broke")

Usage (migration shim)::

    from clippy.log import log
    log("message", level=0)   # same API as the old utils.log()
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Theme helpers (imported lazily to avoid circular deps at module scope)
# ---------------------------------------------------------------------------

_THEME = None
_VT_ENABLED = False


def _ensure_vt() -> None:
    """Enable Windows VT processing once."""
    global _VT_ENABLED
    if _VT_ENABLED:
        return
    _VT_ENABLED = True
    if os.name == "nt":
        try:
            from clippy.theme import enable_windows_vt

            enable_windows_vt()
        except Exception:
            pass


def _get_theme():
    global _THEME
    if _THEME is None:
        try:
            from clippy.theme import THEME

            _THEME = THEME
        except Exception:
            _THEME = False  # sentinel: don't retry
    return _THEME if _THEME is not False else None


# ---------------------------------------------------------------------------
# Mapping from old numeric levels to stdlib levels
# ---------------------------------------------------------------------------

_OLD_LEVEL_MAP = {
    0: logging.INFO,
    1: logging.INFO,
    2: logging.INFO,
    5: logging.ERROR,
}

# Custom attribute set on LogRecords so the formatter can distinguish sub-levels
_CLIPPY_SUBLEVEL = "clippy_sublevel"


# ---------------------------------------------------------------------------
# BBS-themed Formatter
# ---------------------------------------------------------------------------


class ClippyFormatter(logging.Formatter):
    """Format log records with the BBS color theme.

    Keeps the same visual style as the old ``utils.log()`` function:
    level 0 → indented info, 1 → bullet, 2 → chevron, 5/ERROR → red X.
    """

    def format(self, record: logging.LogRecord) -> str:
        _ensure_vt()
        theme = _get_theme()
        msg = record.getMessage()
        sublevel = getattr(record, _CLIPPY_SUBLEVEL, None)

        # If message already has ANSI, don't re-style
        is_styled = "\x1b[" in msg

        try:
            from clippy.utils import _accent_symbols, _style_label_value
        except Exception:
            _accent_symbols = _style_label_value = None  # type: ignore[assignment]

        def _style(text: str) -> str:
            if is_styled:
                return text
            if _style_label_value is not None:
                try:
                    return _style_label_value(text)
                except Exception:
                    pass
            if theme:
                try:
                    return theme.text(text)
                except Exception:
                    pass
            return text

        def _accent(text: str) -> str:
            if _accent_symbols is not None:
                try:
                    return _accent_symbols(text)
                except Exception:
                    pass
            return text

        body = _accent(_style(msg))

        if record.levelno >= logging.ERROR or sublevel == 5:
            try:
                if theme:
                    if not is_styled:
                        body = theme.error(body)
                    x = theme.error("\u2716")
                else:
                    from yachalk import chalk

                    if not is_styled:
                        body = chalk.red_bright(body)
                    x = chalk.red_bright("\u2716")
            except Exception:
                x = "\u2716"
            return f"{x} {body}"

        if sublevel == 2:
            try:
                chev = theme.symbol("\u203a") if theme else "\u203a"
            except Exception:
                chev = "\u203a"
            return f"{chev} {body}"

        if sublevel == 1:
            try:
                bullet = theme.symbol("\u2022") if theme else "\u2022"
            except Exception:
                bullet = "\u2022"
            return f"{bullet} {body}"

        # sublevel 0 / default
        return f"  {body}"


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

_logger: Optional[logging.Logger] = None


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the ``clippy`` logger. Called once at startup."""
    global _logger
    logger = logging.getLogger("clippy")
    if logger.handlers:
        # Already configured
        _logger = logger
        return logger
    logger.setLevel(level)
    # Force UTF-8 on Windows to avoid cp1252 encoding errors with Unicode symbols
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ClippyFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """Return the clippy logger, setting it up if needed."""
    global _logger
    if _logger is None:
        return setup_logging()
    return _logger


# ---------------------------------------------------------------------------
# Backwards-compatible shim
# ---------------------------------------------------------------------------


def log(msg: object, level: int = 0) -> None:
    """Drop-in replacement for the old ``utils.log(msg, level)`` API.

    Maps the old numeric levels to stdlib levels and preserves the sub-level
    on the record so the ClippyFormatter can apply the correct prefix.
    """
    logger = get_logger()
    stdlib_level = _OLD_LEVEL_MAP.get(level, logging.INFO)
    # Use logger.log with an extra dict to carry the sublevel
    logger.log(stdlib_level, str(msg), extra={_CLIPPY_SUBLEVEL: level})
