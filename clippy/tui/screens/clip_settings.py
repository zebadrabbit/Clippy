"""Clip settings screen — broadcaster, date range, filters."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static, Switch


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

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Start Date (MM/DD/YYYY)")
                    yield Input(placeholder="Leave blank for last 3 days", id="start-date")
                with Vertical(classes="form-group"):
                    yield Label("End Date (MM/DD/YYYY)")
                    yield Input(placeholder="Leave blank for today", id="end-date")

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Min Views")
                    yield Input(
                        value=str(cfg.selection.min_views),
                        id="min-views",
                    )
                with Vertical(classes="form-group"):
                    yield Label("Max Clips to Fetch")
                    yield Input(value="100", id="max-clips")

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Clips per Compilation")
                    yield Input(
                        value=str(cfg.selection.clips_per_compilation),
                        id="clips-per-comp",
                    )
                with Vertical(classes="form-group"):
                    yield Label("Number of Compilations")
                    yield Input(
                        value=str(cfg.selection.compilations),
                        id="compilations",
                    )

            with Horizontal():
                yield Label("Auto-expand lookback")
                yield Switch(value=False, id="auto-expand")

            with Vertical(classes="button-bar"):
                yield Button("Next →", variant="primary", id="next-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next-btn":
            settings = {
                "broadcaster": self.query_one("#broadcaster", Input).value.strip(),
                "start": self.query_one("#start-date", Input).value.strip(),
                "end": self.query_one("#end-date", Input).value.strip(),
                "min_views": int(self.query_one("#min-views", Input).value or "1"),
                "max_clips": int(self.query_one("#max-clips", Input).value or "100"),
                "clips_per_comp": int(self.query_one("#clips-per-comp", Input).value or "12"),
                "compilations": int(self.query_one("#compilations", Input).value or "2"),
                "auto_expand": self.query_one("#auto-expand", Switch).value,
            }
            self.app.workflow["clip_settings"] = settings
            self.app.advance_to("quality")
