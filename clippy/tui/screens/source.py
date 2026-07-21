"""Source selection screen — Twitch or Discord."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, RadioButton, RadioSet, Select, Static

from clippy.tui.bbs import BBSScreen


def _profile_names() -> list[str]:
    """Profiles offered in the picker, always including the built-in default."""
    try:
        from clippy.config_loader import list_profiles

        return list_profiles() or ["default"]
    except Exception:
        return ["default"]


def _active_profile() -> str:
    """Whichever profile clippy.yaml currently selects, else the built-in."""
    try:
        import clippy.config as cfg
        from clippy.config_loader import DEFAULT_PROFILE

        name = str(getattr(cfg, "active_profile", "") or "").strip()
        return name if name in _profile_names() else DEFAULT_PROFILE
    except Exception:
        return "default"


class SourceScreen(BBSScreen):
    """Step 1: Choose clip source."""

    STEP = 1
    STEP_TITLE = "Clip Source"
    KEYS = "[UP/DOWN] choose   [ENTER] continue   [Q] quit"

    HINTS = {
        "source-radio": "twitch: top clips by views via Helix / discord: links from a channel",
        "profile-select": "per-streamer defaults and branding; 'default' uses the base config",
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
            yield Static("── PROFILE ──", classes="bbs-section")
            with Horizontal(classes="bbs-row"):
                yield Label("Use profile ")
                yield Select(
                    [(name, name) for name in _profile_names()],
                    value=_active_profile(),
                    id="profile-select",
                    classes="w-med",
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
            # Apply the profile here, on step 1: every later screen prefills
            # from app.config, so switching afterwards would show stale values.
            self.app.apply_profile(str(self.query_one("#profile-select", Select).value))
            self.app.advance_to("credentials")
