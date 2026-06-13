"""Clip settings screen — broadcaster, date range, filters."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static, Switch


def _safe_int(value: str, default: int, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


def _safe_float(value: str, default: float, minimum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and parsed < minimum:
        return minimum
    return parsed


class ClipSettingsScreen(Screen):
    """Step 3: Configure clip selection."""

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        with Vertical(classes="screen-container"):
            yield Static("Step 3 of 6 — Clip Settings", classes="screen-title")

            yield Label("Broadcaster Name")
            yield Input(
                value=cfg.identity.broadcaster,
                placeholder="e.g. somechannel",
                id="broadcaster",
            )
            yield Static(
                "The Twitch channel name to fetch clips from.",
                classes="help-text",
            )

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Start Date (MM/DD/YYYY)")
                    yield Input(placeholder="Leave blank for last 3 days", id="start-date")
                with Vertical(classes="form-group"):
                    yield Label("End Date (MM/DD/YYYY)")
                    yield Input(placeholder="Leave blank for today", id="end-date")
            yield Static(
                "Date range to search for clips. Leave both blank to use the last 3 days.",
                classes="help-text",
            )

            yield Label("Min Views")
            yield Input(value=str(cfg.selection.min_views), id="min-views")
            yield Static(
                "Only include clips with at least this many views. Set to 0 for all clips.",
                classes="help-text",
            )

            # ---- Sizing mode: by clip count or by duration ----
            yield Static("")
            yield Label("Compilation sizing")
            yield RadioSet(
                RadioButton("By clip count", value=True, id="mode-count"),
                RadioButton("By target duration (approx.)", id="mode-duration"),
                id="sizing-mode",
            )
            yield Static(
                "Choose whether to build compilations by a fixed number of clips "
                "or by an approximate target video length.",
                classes="help-text",
            )

            # Count-based fields (shown by default)
            with Vertical(id="count-fields"):
                with Horizontal():
                    with Vertical(classes="form-group"):
                        yield Label("Clips per Compilation")
                        yield Input(
                            value=str(cfg.selection.clips_per_compilation),
                            id="clips-per-comp",
                        )
                        yield Static(
                            "How many clips in each compilation video.",
                            classes="help-text",
                        )
                    with Vertical(classes="form-group"):
                        yield Label("Number of Compilations")
                        yield Input(
                            value=str(cfg.selection.compilations),
                            id="compilations",
                        )
                        yield Static(
                            "How many separate compilation videos to produce.",
                            classes="help-text",
                        )

            # Duration-based fields (hidden by default)
            with Vertical(id="duration-fields", classes="hidden"):
                with Horizontal():
                    with Vertical(classes="form-group"):
                        yield Label("Target length per compilation (minutes)")
                        yield Input(
                            value="10",
                            placeholder="e.g. 10",
                            id="target-duration",
                        )
                        yield Static(
                            "Clips are added until this length is reached. "
                            "Actual duration depends on individual clip lengths.",
                            classes="help-text",
                        )
                    with Vertical(classes="form-group"):
                        yield Label("Number of Compilations")
                        yield Input(
                            value=str(cfg.selection.compilations),
                            id="compilations-dur",
                        )
                        yield Static(
                            "How many separate compilation videos to produce.",
                            classes="help-text",
                        )

            with Horizontal():
                yield Label("Auto-expand to fill quantity")
                yield Switch(value=True, id="auto-expand")
            yield Static(
                "When enabled, fetches clips from outside the date range (newest first) "
                "to fill any shortfall in the requested quantity.",
                classes="help-text",
            )

            with Horizontal():
                yield Label("Nostalgia Mode")
                yield Switch(value=False, id="nostalgia-mode")
            yield Static(
                "Mixes in random older clips (>6 months old) for variety.",
                classes="help-text",
            )

            with Horizontal(classes="button-bar"):
                yield Button("← Back", id="back-btn")
                yield Button("Next →", variant="primary", id="next-btn")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "sizing-mode":
            return
        by_duration = event.pressed.id == "mode-duration"
        self.query_one("#count-fields").set_class(by_duration, "hidden")
        self.query_one("#duration-fields").set_class(not by_duration, "hidden")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "next-btn":
            self._save_and_advance()

    def _save_and_advance(self) -> None:
        radio_set = self.query_one("#sizing-mode", RadioSet)
        by_duration = radio_set.pressed_button.id == "mode-duration"

        settings: dict = {
            "broadcaster": self.query_one("#broadcaster", Input).value.strip(),
            "start": self.query_one("#start-date", Input).value.strip(),
            "end": self.query_one("#end-date", Input).value.strip(),
            "min_views": _safe_int(self.query_one("#min-views", Input).value or "0", 0, 0),
            "auto_expand": self.query_one("#auto-expand", Switch).value,
            "nostalgia_mode": self.query_one("#nostalgia-mode", Switch).value,
            "sizing_mode": "duration" if by_duration else "count",
        }

        if by_duration:
            settings["target_duration_min"] = _safe_float(
                self.query_one("#target-duration", Input).value or "10", 10.0, 0.1
            )
            settings["compilations"] = _safe_int(
                self.query_one("#compilations-dur", Input).value or "2", 2, 1
            )
            # Estimate clips needed so auto-expand has a target
            # Assume ~30s avg clip duration as a rough heuristic
            target_secs = settings["target_duration_min"] * 60
            settings["clips_per_comp"] = max(1, int(target_secs / 30))
        else:
            settings["clips_per_comp"] = _safe_int(
                self.query_one("#clips-per-comp", Input).value or "12", 12, 1
            )
            settings["compilations"] = _safe_int(
                self.query_one("#compilations", Input).value or "2", 2, 1
            )

        self.app.workflow["clip_settings"] = settings
        self.app.advance_to("quality")
