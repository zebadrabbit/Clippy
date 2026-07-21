"""Audio and overlay screen — loudness levelling and the creator credit."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Static

from clippy.tui.bbs import BBSScreen


class AudioScreen(BBSScreen):
    """Step 6: Audio levelling and overlay toggles.

    Split out of the transitions screen when that became a full-height picker.
    """

    STEP = 6
    STEP_TITLE = "Audio & Overlay"

    HINTS = {
        "audio-normalize": "EBU R128 loudness match for transition/intro/outro clips",
        "audio-normalize-clips": "EBU R128 loudness match for every Twitch clip",
        "silence-static": "mute the static.mp4 bumper between clips",
        "no-overlay": "skip the 'clip by <creator>' credit drawn on each clip",
        "no-random": "never insert a random transition; the static bumper still goes in",
    }
    DEFAULT_HINT = "Loudness levelling keeps quiet and loud clips from jumping."

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        prev = self.app.workflow.get("transitions", {})

        yield self.title_bar()
        with Vertical(classes="screen-container"):
            yield Static("", classes="bbs-gap")
            yield Static("── AUDIO ──", classes="bbs-section")
            yield Checkbox(
                "Level clip audio",
                value=prev.get("audio_normalize_clips", cfg.audio.audio_normalize_clips),
                id="audio-normalize-clips",
            )
            yield Checkbox(
                "Level transition / intro / outro audio",
                value=prev.get(
                    "audio_normalize_transitions", cfg.audio.audio_normalize_transitions
                ),
                id="audio-normalize",
            )
            yield Checkbox(
                "Mute the static bumper",
                value=prev.get("silence_static", cfg.audio.silence_static),
                id="silence-static",
            )

            yield Static("", classes="bbs-gap")
            yield Static("── OVERLAY & SEQUENCING ──", classes="bbs-section")
            yield Checkbox(
                "Skip the creator credit overlay",
                value=prev.get("no_overlay", not cfg.behavior.enable_overlay),
                id="no-overlay",
            )
            yield Checkbox(
                "No random transitions",
                value=prev.get("no_random_transitions", cfg.sequencing.no_random_transitions),
                id="no-random",
            )

            yield self.progress_bar()
            with Horizontal(classes="button-bar"):
                yield Button("< Back", id="back-btn")
                yield Button("Next >", variant="primary", id="next-btn")

        yield from self.status_bar()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "next-btn":
            # Merge into whatever the transitions picker already recorded.
            settings = dict(self.app.workflow.get("transitions", {}))
            settings.update(
                {
                    "audio_normalize_clips": self.query_one(
                        "#audio-normalize-clips", Checkbox
                    ).value,
                    "audio_normalize_transitions": self.query_one(
                        "#audio-normalize", Checkbox
                    ).value,
                    "silence_static": self.query_one("#silence-static", Checkbox).value,
                    "no_overlay": self.query_one("#no-overlay", Checkbox).value,
                    "no_random_transitions": self.query_one("#no-random", Checkbox).value,
                }
            )
            self.app.workflow["transitions"] = settings
            self.app.advance_to("review")
