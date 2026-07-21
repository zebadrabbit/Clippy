"""The TUI must fit an 80x24 terminal.

The screens used to require a maximized window: every field carried a help
paragraph underneath it, so Clip Settings alone wanted 37 rows of content in a
24-row viewport. The BBS redesign moved that text to a single contextual status
line. These tests keep it that way -- adding a help paragraph back under a field
will fail here rather than in someone's terminal.

Skipped when the optional ``textual`` dependency is not installed.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from clippy.tui.app import ClippyApp  # noqa: E402
from clippy.tui.screens.audio import AudioScreen  # noqa: E402
from clippy.tui.screens.clip_settings import ClipSettingsScreen  # noqa: E402
from clippy.tui.screens.credentials import CredentialsScreen  # noqa: E402
from clippy.tui.screens.quality import QualityScreen  # noqa: E402
from clippy.tui.screens.review import ReviewScreen  # noqa: E402
from clippy.tui.screens.source import SourceScreen  # noqa: E402
from clippy.tui.screens.transitions import TransitionsScreen  # noqa: E402

# The classic terminal. Anything that does not fit here is a regression.
TERMINAL = (80, 24)

WIZARD_SCREENS = [
    SourceScreen,
    CredentialsScreen,
    ClipSettingsScreen,
    QualityScreen,
    TransitionsScreen,
    AudioScreen,
    ReviewScreen,
]


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    """Credentials screen reads the environment while composing."""
    monkeypatch.setenv("TWITCH_CLIENT_ID", "x")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "y")


def _run(coro_factory):
    """Run a Textual pilot coroutine.

    Deliberately not pytest-asyncio: these are the only async tests in the
    suite, and asyncio.run keeps it a zero-dependency check.
    """
    return asyncio.run(coro_factory())


def _on_screen(screen_cls, probe):
    """Mount *screen_cls* in an 80x24 app and hand that screen to *probe*.

    The probe gets the screen we pushed, not ``app.screen``: CredentialsScreen
    auto-advances when credentials are already in the environment, so
    ``app.screen`` would be the *next* step by the time we look.
    """

    async def run():
        app = ClippyApp()
        async with app.run_test(size=TERMINAL) as pilot:
            await pilot.pause()
            screen = screen_cls()
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()
            return await probe(screen, pilot)

    return _run(lambda: run())


@pytest.mark.parametrize("screen_cls", WIZARD_SCREENS, ids=lambda c: c.__name__)
def test_screen_fits_an_80x24_terminal(screen_cls):
    async def probe(screen, pilot):
        return screen.query_one(".screen-container").virtual_size.height

    height = _on_screen(screen_cls, probe)
    assert height <= TERMINAL[1], (
        f"{screen_cls.__name__} needs {height} rows in a {TERMINAL[1]}-row terminal. "
        "Keep per-field guidance in the HINTS status line, not under the field."
    )


@pytest.mark.parametrize("screen_cls", WIZARD_SCREENS, ids=lambda c: c.__name__)
def test_no_help_paragraphs_under_fields(screen_cls):
    """The old layout's vertical bloat came entirely from these."""

    async def probe(screen, pilot):
        return len(screen.query(".help-text"))

    assert _on_screen(screen_cls, probe) == 0


def test_hint_line_follows_focus():
    """Focusing a field replaces the status line with that field's guidance."""
    from textual.widgets import Static

    async def probe(screen, pilot):
        seen = {}
        for field in ("min-views", "broadcaster"):
            screen.query_one(f"#{field}").focus()
            await pilot.pause()
            seen[field] = str(screen.query_one("#hint", Static).content)
        return seen

    seen = _on_screen(ClipSettingsScreen, probe)
    assert "min views" in seen["min-views"]
    assert "broadcaster" in seen["broadcaster"]


@pytest.mark.parametrize("screen_cls", WIZARD_SCREENS, ids=lambda c: c.__name__)
def test_every_hint_targets_a_real_widget(screen_cls):
    """A HINTS key with no matching id is dead text nobody will ever see."""
    hints = getattr(screen_cls, "HINTS", {})
    if not hints:
        pytest.skip("no hints on this screen")

    async def probe(screen, pilot):
        return {w.id for w in screen.query("*") if w.id}

    present = _on_screen(screen_cls, probe)
    # Discord-only fields are absent in the default Twitch flow.
    optional = {"discord-token", "discord-channel-id"}
    missing = set(hints) - present - optional
    assert not missing, f"{screen_cls.__name__} hints target no widget: {missing}"


def test_wizard_steps_are_numbered_consistently():
    """Every screen's STEP must be unique, in order, and within TOTAL_STEPS."""
    from clippy.tui.bbs import TOTAL_STEPS

    steps = [s.STEP for s in WIZARD_SCREENS]
    assert steps == sorted(steps), f"screens out of order: {steps}"
    assert len(set(steps)) == len(steps), f"duplicate step numbers: {steps}"
    assert max(steps) == TOTAL_STEPS, f"last step {max(steps)} != TOTAL_STEPS {TOTAL_STEPS}"
