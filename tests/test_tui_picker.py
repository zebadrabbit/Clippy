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


class TestDateRange:
    """The date field crashed a run when given 07/01/26; it is a picker now."""

    def _clip_settings(self, steps):
        from clippy.tui.screens.clip_settings import ClipSettingsScreen

        async def run():
            app = ClippyApp()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                screen = ClipSettingsScreen()
                app.push_screen(screen)
                await pilot.pause()
                await pilot.pause()
                screen.query_one("#broadcaster").value = "chan"
                await steps(screen, pilot, app)
                return dict(app.workflow.get("clip_settings", {}))

        return asyncio.run(run())

    def test_custom_fields_are_hidden_until_asked_for(self):
        seen = {}

        async def steps(screen, pilot, app):
            seen["hidden"] = screen.query_one("#custom-dates").has_class("hidden")
            screen.query_one("#date-range").value = "custom"
            await pilot.pause()
            seen["shown"] = not screen.query_one("#custom-dates").has_class("hidden")

        self._clip_settings(steps)
        assert seen["hidden"] and seen["shown"]

    def test_preset_is_resolved_to_rfc3339_before_saving(self):
        """The pipeline should never receive a hand-typed date from a preset."""

        async def steps(screen, pilot, app):
            screen.query_one("#date-range").value = "month"
            await pilot.pause()
            screen._save_and_advance()

        saved = self._clip_settings(steps)
        assert saved["start"].endswith("Z")
        assert saved["end"].endswith("Z")

    def test_everything_leaves_the_start_open(self):
        async def steps(screen, pilot, app):
            screen.query_one("#date-range").value = "everything"
            await pilot.pause()
            screen._save_and_advance()

        saved = self._clip_settings(steps)
        assert saved["start"] == ""

    def test_custom_two_digit_year_survives_the_round_trip(self):
        from clippy.window import resolve_date_window

        async def steps(screen, pilot, app):
            screen.query_one("#date-range").value = "custom"
            await pilot.pause()
            screen.query_one("#start-date").value = "07/01/26"
            await pilot.pause()
            screen._save_and_advance()

        saved = self._clip_settings(steps)
        assert resolve_date_window(saved["start"], None)[0] == "2026-07-01T00:00:00Z"


class TestBulkButtons:
    def test_add_all_button_fills_the_pool(self):
        async def steps(screen, pilot, app):
            screen.query_one("#add-all-btn").press()
            await pilot.pause()

        screen, _ = _drive(steps)
        assert sorted(screen._selected) == sorted(CLIPS)
        assert screen._available == []

    def test_clear_all_button_empties_the_pool(self):
        async def steps(screen, pilot, app):
            screen.action_select_all()
            await pilot.pause()
            screen.query_one("#clear-all-btn").press()
            await pilot.pause()

        screen, _ = _drive(steps)
        assert screen._selected == []
        assert sorted(screen._available) == sorted(CLIPS)

    def test_clearing_all_is_recorded_as_an_empty_pool(self):
        """An empty pool is a legitimate choice; it just must be the user's."""

        async def steps(screen, pilot, app):
            screen.query_one("#clear-all-btn").press()
            await pilot.pause()
            screen.query_one("#next-btn").press()
            await pilot.pause()
            await pilot.pause()

        _, app = _drive(steps)
        assert app.workflow["transitions"]["selected_transitions"] == []


class TestProfileSelector:
    """Picking a profile on step 1 must reach every later screen.

    The wizard screens prefill from ``app.config`` when they compose, and the app
    captures that once at construction -- so the switch has to happen on step 1
    and has to replace app.config, not just the module singleton.
    """

    PROFILES = {
        "identity": {"broadcaster": "basechannel"},
        "selection": {"clips_per_compilation": 12, "compilations": 2, "min_views": 0},
        "profiles": {
            "ninja": {
                "identity": {"broadcaster": "ninja"},
                "selection": {"clips_per_compilation": 7},
            },
        },
    }

    @pytest.fixture(autouse=True)
    def _config(self, tmp_path, monkeypatch):
        import yaml

        from clippy.config_loader import PROFILE_ENV

        (tmp_path / "clippy.yaml").write_text(
            yaml.safe_dump(self.PROFILES, sort_keys=False), encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        # conftest's _isolate_config_module puts clippy.config back afterwards.
        yield

    def _run(self, steps):
        from clippy.tui.app import ClippyApp
        from clippy.tui.screens.source import SourceScreen

        async def run():
            app = ClippyApp()
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                screen = SourceScreen()
                app.push_screen(screen)
                await pilot.pause()
                await pilot.pause()
                return await steps(screen, pilot, app)

        return asyncio.run(run())

    def test_the_builtin_default_is_offered(self):
        from textual.widgets import Select

        async def steps(screen, pilot, app):
            return screen.query_one("#profile-select", Select).value

        assert self._run(steps) == "default"

    def test_choosing_one_switches_the_config(self):
        from textual.widgets import Select

        seen = {}

        async def steps(screen, pilot, app):
            screen.query_one("#profile-select", Select).value = "ninja"
            await pilot.pause()
            screen.query_one("#next-btn").press()
            await pilot.pause()
            await pilot.pause()
            seen["broadcaster"] = app.config.identity.broadcaster
            seen["clips"] = app.config.selection.clips_per_compilation
            seen["workflow"] = app.workflow.get("profile")

        self._run(steps)
        assert seen["broadcaster"] == "ninja"
        assert seen["clips"] == 7
        assert seen["workflow"] == "ninja"

    def test_a_later_screen_prefills_from_the_chosen_profile(self):
        """The whole point: Clip Settings must show the profile's values."""
        from textual.widgets import Input, Select

        from clippy.tui.screens.clip_settings import ClipSettingsScreen

        seen = {}

        async def steps(screen, pilot, app):
            screen.query_one("#profile-select", Select).value = "ninja"
            await pilot.pause()
            screen.query_one("#next-btn").press()
            await pilot.pause()
            await pilot.pause()
            later = ClipSettingsScreen()
            app.push_screen(later)
            await pilot.pause()
            await pilot.pause()
            seen["broadcaster"] = later.query_one("#broadcaster", Input).value
            seen["clips"] = later.query_one("#clips-per-comp", Input).value

        self._run(steps)
        assert seen["broadcaster"] == "ninja"
        assert seen["clips"] == "7"

    def test_default_leaves_the_base_config_alone(self):
        seen = {}

        async def steps(screen, pilot, app):
            screen.query_one("#next-btn").press()
            await pilot.pause()
            await pilot.pause()
            seen["broadcaster"] = app.config.identity.broadcaster

        self._run(steps)
        assert seen["broadcaster"] == "basechannel"

    def test_an_unknown_profile_does_not_strand_the_wizard(self):
        seen = {}

        async def steps(screen, pilot, app):
            app.apply_profile("no-such-profile")
            await pilot.pause()
            seen["config"] = app.config is not None

        self._run(steps)
        assert seen["config"]
