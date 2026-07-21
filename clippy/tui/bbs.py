"""Shared BBS-style chrome for the TUI.

The wizard screens all want the same three things: a title bar that names the
step, a dense body, and a two-line status bar at the bottom. The status bar is
what replaces the old per-field help paragraphs -- instead of a sentence under
every input, one line describes whatever field currently has focus. That is the
whole reason the screens used to need a maximized terminal.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static

TOTAL_STEPS = 7


def rule(width: int = 78, char: str = "─") -> str:
    return char * width


class BBSScreen(Screen):
    """A wizard step wearing BBS chrome.

    Subclasses set ``STEP``/``STEP_TITLE`` and fill ``HINTS`` with
    ``{widget_id: one-line description}``. Everything else is handled here.
    """

    STEP: int = 0
    STEP_TITLE: str = ""
    KEYS: str = "[TAB] field   [ENTER] continue   [ESC] back   [Q] quit"

    #: widget id -> single-line help shown while that widget has focus
    HINTS: dict[str, str] = {}

    DEFAULT_HINT = "Use TAB to move between fields."

    # -- chrome -------------------------------------------------------------

    def title_bar(self) -> Static:
        """``CLIPPY ── STEP 3 OF 6 ── CLIP SETTINGS ───────────────``"""
        label = f" CLIPPY ── STEP {self.STEP} OF {TOTAL_STEPS} ── {self.STEP_TITLE.upper()} "
        return Static(label, classes="bbs-titlebar")

    def progress_bar(self) -> Static:
        """A blocky ``▓▓▓░░░`` step meter, the one bit of pure decoration."""
        filled = int(round(28 * self.STEP / TOTAL_STEPS))
        meter = "▓" * filled + "░" * (28 - filled)
        return Static(f"{meter}  step {self.STEP}/{TOTAL_STEPS}", classes="bbs-progress")

    def status_bar(self) -> ComposeResult:
        # markup=False: the key bar is full of [TAB]/[ESC], which Textual would
        # otherwise parse as style tags and swallow entirely.
        yield Static(self.DEFAULT_HINT, id="hint", classes="bbs-hint", markup=False)
        yield Static(self.KEYS, classes="bbs-keys", markup=False)

    # -- contextual help ----------------------------------------------------

    def on_descendant_focus(self, event) -> None:
        """Swap the hint line to match the focused field."""
        widget_id = getattr(event.widget, "id", None)
        self._set_hint(self.HINTS.get(widget_id, self.DEFAULT_HINT))

    def _set_hint(self, text: str) -> None:
        try:
            self.query_one("#hint", Static).update(text)
        except Exception:
            # The hint line is optional chrome; never let it break a screen.
            pass
