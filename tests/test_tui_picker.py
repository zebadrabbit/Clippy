"""Tests for the transitions two-pane picker.

The right pane is the transition pool the pipeline will use, so what these
assert is really "does the screen record what the user sees".

Skipped when the optional ``textual`` dependency is not installed.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

import clippy.tui.screens.transitions as transitions_mod  # noqa: E402
from clippy.tui.app import ClippyApp  # noqa: E402
from clippy.tui.screens.transitions import TransitionsScreen  # noqa: E402

CLIPS = ["transition_01.mp4", "transition_02.mp4", "transition_03.mp4"]


@pytest.fixture(autouse=True)
def _fake_disk(monkeypatch):
    """Three clips on disk, none configured, so the panes start left-heavy."""
    monkeypatch.setattr(transitions_mod, "_discover", lambda path: list(CLIPS))
    monkeypatch.setattr(transitions_mod, "_current_pool", lambda path: [])
    monkeypatch.setattr(transitions_mod, "_resolve_transitions_path", lambda: "/transitions")


def _drive(steps):
    """Mount the picker, run *steps(screen, pilot)*, return the screen."""

    async def run():
        app = ClippyApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = TransitionsScreen()
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()
            await steps(screen, pilot, app)
            return screen, app

    return asyncio.run(run())


class TestInitialState:
    def test_unconfigured_offers_everything_on_the_left(self):
        async def steps(screen, pilot, app):
            pass

        screen, _ = _drive(steps)
        assert screen._available == CLIPS
        assert screen._selected == []

    def test_existing_pool_starts_selected(self, monkeypatch):
        """Opening the picker must not silently change an existing config."""
        monkeypatch.setattr(transitions_mod, "_current_pool", lambda path: CLIPS[:2])

        async def steps(screen, pilot, app):
            pass

        screen, _ = _drive(steps)
        assert screen._selected == CLIPS[:2]
        assert screen._available == [CLIPS[2]]


class TestTransfer:
    def test_right_arrow_selects_the_highlighted_clip(self):
        async def steps(screen, pilot, app):
            screen.query_one("#available-list").focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()

        screen, _ = _drive(steps)
        assert screen._selected == [CLIPS[0]]
        assert CLIPS[0] not in screen._available

    def test_left_arrow_puts_it_back(self):
        async def steps(screen, pilot, app):
            screen.action_select_all()
            await pilot.pause()
            screen.query_one("#selected-list").focus()
            await pilot.pause()
            await pilot.press("left")
            await pilot.pause()

        screen, _ = _drive(steps)
        assert len(screen._selected) == 2
        assert len(screen._available) == 1

    def test_space_moves_from_whichever_pane_has_focus(self):
        async def steps(screen, pilot, app):
            screen.query_one("#available-list").focus()
            await pilot.pause()
            await pilot.press("space")  # -> selected
            await pilot.pause()
            screen.query_one("#selected-list").focus()
            await pilot.pause()
            await pilot.press("space")  # -> back
            await pilot.pause()

        screen, _ = _drive(steps)
        assert screen._selected == []
        assert sorted(screen._available) == sorted(CLIPS)

    def test_select_all_and_none(self):
        async def steps(screen, pilot, app):
            screen.action_select_all()
            await pilot.pause()
            assert screen._available == []
            screen.action_select_none()
            await pilot.pause()

        screen, _ = _drive(steps)
        assert screen._selected == []
        assert sorted(screen._available) == sorted(CLIPS)

    def test_a_clip_is_never_in_both_panes(self):
        async def steps(screen, pilot, app):
            screen.action_select_all()
            await pilot.pause()
            screen.query_one("#selected-list").focus()
            await pilot.pause()
            await pilot.press("left")
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()

        screen, _ = _drive(steps)
        assert not set(screen._available) & set(screen._selected)
        assert sorted(screen._available + screen._selected) == sorted(CLIPS)

    def test_moving_on_an_empty_pane_is_harmless(self):
        async def steps(screen, pilot, app):
            screen.query_one("#selected-list").focus()
            await pilot.pause()
            await pilot.press("left")  # selected is empty
            await pilot.pause()

        screen, _ = _drive(steps)
        assert screen._selected == []
        assert sorted(screen._available) == sorted(CLIPS)


class TestSavedResult:
    def test_saves_the_right_pane_as_an_explicit_pool(self):
        async def steps(screen, pilot, app):
            screen.query_one("#available-list").focus()
            await pilot.pause()
            await pilot.press("right")
            await pilot.pause()
            screen.query_one("#next-btn").press()
            await pilot.pause()
            await pilot.pause()

        _, app = _drive(steps)
        saved = app.workflow["transitions"]
        assert saved["selected_transitions"] == [CLIPS[0]]
        # The pane is the whole answer, so no denylist is needed.
        assert saved["transition_mode"] == "explicit"
        assert saved["transition_exclude"] == []

    def test_advances_to_the_audio_step(self):
        seen = {}

        async def steps(screen, pilot, app):
            screen.query_one("#next-btn").press()
            await pilot.pause()
            await pilot.pause()
            # Read inside the pilot: the screen stack is gone once it exits.
            seen["screen"] = type(app.screen).__name__

        _drive(steps)
        assert seen["screen"] == "AudioScreen"

    def test_probability_and_cooldown_are_bounded(self):
        async def steps(screen, pilot, app):
            screen.query_one("#transition-prob").value = "5.0"
            screen.query_one("#transition-cooldown").value = "-3"
            await pilot.pause()
            screen.query_one("#next-btn").press()
            await pilot.pause()
            await pilot.pause()

        _, app = _drive(steps)
        saved = app.workflow["transitions"]
        assert saved["transition_probability"] == 1.0
        assert saved["transition_cooldown"] == 0
