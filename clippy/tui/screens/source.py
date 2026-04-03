"""Source selection screen — Twitch or Discord."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Label, RadioButton, RadioSet, Static


class SourceScreen(Screen):
    """Step 1: Choose clip source."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="screen-container"):
            yield Static("Step 1 of 6 — Clip Source", classes="screen-title")
            yield Label("Where should Clippy fetch clips from?")
            yield RadioSet(
                RadioButton("Twitch Helix API", value=True, id="twitch"),
                RadioButton("Discord Channel", id="discord"),
                id="source-radio",
            )
            with Vertical(classes="button-bar"):
                yield Button("Next →", variant="primary", id="next-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "next-btn":
            radio_set = self.query_one("#source-radio", RadioSet)
            idx = radio_set.pressed_index
            source = "discord" if idx == 1 else "twitch"
            self.app.workflow["source"] = source
            self.app.advance_to("credentials")
