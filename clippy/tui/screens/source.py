"""Source selection screen — Twitch or Discord."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, RadioButton, RadioSet, Static

from clippy.tui.bbs import BBSScreen


class SourceScreen(BBSScreen):
    """Step 1: Choose clip source."""

    STEP = 1
    STEP_TITLE = "Clip Source"
    KEYS = "[UP/DOWN] choose   [ENTER] continue   [Q] quit"

    HINTS = {
        "source-radio": "twitch: top clips by views via Helix / discord: links from a channel",
    }
    DEFAULT_HINT = "Choose where Clippy should fetch clips from."

    def compose(self) -> ComposeResult:
        yield self.title_bar()
        with Vertical(classes="screen-container"):
            yield Static("", classes="bbs-gap")
            yield Static("── SOURCE ──", classes="bbs-section")
            yield RadioSet(
                RadioButton("Twitch Helix API", value=True, id="twitch"),
                RadioButton("Discord Channel", id="discord"),
                id="source-radio",
            )
            yield Static("", classes="bbs-gap")
            yield self.progress_bar()
            with Horizontal(classes="button-bar"):
                yield Button("Quit", id="quit-btn")
                yield Button("Next >", variant="primary", id="next-btn")
        yield from self.status_bar()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit-btn":
            self.app.exit()
        elif event.button.id == "next-btn":
            radio_set = self.query_one("#source-radio", RadioSet)
            idx = radio_set.pressed_index
            source = "discord" if idx == 1 else "twitch"
            self.app.workflow["source"] = source
            self.app.advance_to("credentials")
