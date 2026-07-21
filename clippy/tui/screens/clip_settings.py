"""Clip settings screen — broadcaster, date range, filters."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, RadioButton, RadioSet, Select, Static

from clippy.tui.bbs import BBSScreen
from clippy.window import RANGE_CHOICES, window_from_preset


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


class ClipSettingsScreen(BBSScreen):
    """Step 3: Configure clip selection."""

    STEP = 3
    STEP_TITLE = "Clip Settings"

    HINTS = {
        "broadcaster": "broadcaster: the Twitch channel to pull clips from",
        "date-range": "how far back to search; the clip count trims it down anyway",
        "start-date": "from: MM/DD/YY, MM/DD/YYYY, YYYY-MM-DD or RFC3339",
        "end-date": "to: blank = now",
        "min-views": "min views: only clips with at least this many views (0 = all)",
        "clips-per-comp": "clips per compilation",
        "compilations": "how many compilation videos to produce",
        "target-duration": "target minutes per compilation; clips are added until reached",
        "compilations-dur": "how many compilation videos to produce",
        "sizing-mode": "size compilations by a clip count or by an approximate length",
        "auto-expand": "auto-expand: reach outside the date range to fill a shortfall",
        "nostalgia-mode": "nostalgia: mix in random clips older than 6 months",
    }

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        yield self.title_bar()
        with Vertical(classes="screen-container"):
            yield Static("", classes="bbs-gap")

            with Horizontal(classes="bbs-row"):
                yield Label("Broadcaster  ")
                yield Input(
                    value=cfg.identity.broadcaster,
                    placeholder="somechannel",
                    id="broadcaster",
                    classes="w-wide",
                )

            with Horizontal(classes="bbs-row"):
                yield Label("Date range   ")
                yield Select(
                    [(label, key) for key, label in RANGE_CHOICES] + [("Custom dates", "custom")],
                    value="week",
                    id="date-range",
                    classes="w-med",
                )

            # Only shown for "Custom dates"; presets cover the common cases.
            with Horizontal(id="custom-dates", classes="bbs-row hidden"):
                yield Label("From ")
                yield Input(placeholder="MM/DD/YY", id="start-date", classes="w-med")
                yield Label("  To ")
                yield Input(placeholder="blank=now", id="end-date", classes="w-med")

            with Horizontal(classes="bbs-row"):
                yield Label("Min views    ")
                yield Input(value=str(cfg.selection.min_views), id="min-views", classes="w-sm")

            yield Static("", classes="bbs-gap")
            yield Static("── SIZING ──", classes="bbs-section")
            yield RadioSet(
                RadioButton("By clip count", value=True, id="mode-count"),
                RadioButton("By target duration", id="mode-duration"),
                id="sizing-mode",
            )

            with Vertical(id="count-fields"):
                with Horizontal(classes="bbs-row"):
                    yield Label("Clips/comp   ")
                    yield Input(
                        value=str(cfg.selection.clips_per_compilation),
                        id="clips-per-comp",
                        classes="w-sm",
                    )
                    yield Label("  Comps    ")
                    yield Input(
                        value=str(cfg.selection.compilations),
                        id="compilations",
                        classes="w-sm",
                    )

            with Vertical(id="duration-fields", classes="hidden"):
                with Horizontal(classes="bbs-row"):
                    yield Label("Minutes/comp ")
                    yield Input(value="10", id="target-duration", classes="w-sm")
                    yield Label("  Comps    ")
                    yield Input(
                        value=str(cfg.selection.compilations),
                        id="compilations-dur",
                        classes="w-sm",
                    )

            yield Static("", classes="bbs-gap")
            with Horizontal(classes="bbs-row"):
                yield Checkbox("Auto-expand", value=True, id="auto-expand")
                yield Checkbox("Nostalgia", value=False, id="nostalgia-mode")

            yield self.progress_bar()

            with Horizontal(classes="button-bar"):
                yield Button("< Back", id="back-btn")
                yield Button("Next >", variant="primary", id="next-btn")

        yield from self.status_bar()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "date-range":
            self.query_one("#custom-dates").set_class(event.value != "custom", "hidden")

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

        date_range = self.query_one("#date-range", Select).value
        if date_range == "custom":
            start = self.query_one("#start-date", Input).value.strip()
            end = self.query_one("#end-date", Input).value.strip()
        else:
            # Resolve to RFC3339 now, so the pipeline never has to parse a
            # human-entered date and cannot fail on one mid-run.
            start, end = window_from_preset(str(date_range))
            start, end = start or "", end or ""

        settings: dict = {
            "broadcaster": self.query_one("#broadcaster", Input).value.strip(),
            "start": start,
            "end": end,
            "min_views": _safe_int(self.query_one("#min-views", Input).value or "0", 0, 0),
            "auto_expand": self.query_one("#auto-expand", Checkbox).value,
            "nostalgia_mode": self.query_one("#nostalgia-mode", Checkbox).value,
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
