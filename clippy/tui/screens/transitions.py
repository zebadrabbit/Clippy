"""Transitions configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static, Switch


def _resolve_transitions_path() -> str:
    """Return the absolute transitions directory path."""
    try:
        from clippy.utils import resolve_transitions_dir

        return resolve_transitions_dir()
    except Exception:
        import os

        return os.path.abspath("transitions")


class TransitionsScreen(Screen):
    """Step 5: Configure transitions, intro/outro, and audio settings."""

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        with Vertical(classes="screen-container"):
            yield Static("Step 5 of 6 — Transitions", classes="screen-title")

            yield Label("Transitions Directory")
            yield Input(
                value=_resolve_transitions_path(),
                placeholder="Path to transitions directory",
                id="transitions-dir",
            )
            yield Static(
                "Folder containing transition .mp4 clips and the static bumper.",
                classes="help-text",
            )

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Transition Probability (0.0 - 1.0)")
                    yield Input(
                        value=str(cfg.sequencing.transition_probability),
                        id="transition-prob",
                    )
                    yield Static(
                        "Chance of inserting a random transition between each pair of clips. "
                        "0.0 = never, 1.0 = always.",
                        classes="help-text",
                    )
                with Vertical(classes="form-group"):
                    yield Label("Transition Cooldown")
                    yield Input(
                        value=str(cfg.sequencing.transition_cooldown),
                        id="transition-cooldown",
                    )
                    yield Static(
                        "Avoid repeating the same transition within the last N picks. "
                        "Set to 0 to disable.",
                        classes="help-text",
                    )

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Disable random transitions")
                    yield Switch(
                        value=cfg.sequencing.no_random_transitions,
                        id="no-random",
                    )
                    yield Static(
                        "Turns off all random transitions between clips. "
                        "The static bumper is still inserted.",
                        classes="help-text",
                    )
                with Vertical(classes="form-group"):
                    yield Label("Normalize transition audio")
                    yield Switch(
                        value=cfg.audio.audio_normalize_transitions,
                        id="audio-normalize",
                    )
                    yield Static(
                        "Apply EBU R128 loudness normalization to transition clips "
                        "so they match clip audio levels.",
                        classes="help-text",
                    )

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Silence static bumper")
                    yield Switch(
                        value=cfg.audio.silence_static,
                        id="silence-static",
                    )
                    yield Static(
                        "Mute the audio on the static.mp4 bumper clip inserted between clips.",
                        classes="help-text",
                    )
                with Vertical(classes="form-group"):
                    yield Label("Disable clip overlay")
                    yield Switch(value=not cfg.behavior.enable_overlay, id="no-overlay")
                    yield Static(
                        "Skip the 'clip by' text overlay on each clip. "
                        "Useful for a cleaner look.",
                        classes="help-text",
                    )

            with Horizontal(classes="button-bar"):
                yield Button("← Back", id="back-btn")
                yield Button("Next →", variant="primary", id="next-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "next-btn":
            self.app.workflow["transitions"] = {
                "transitions_dir": self.query_one("#transitions-dir", Input).value.strip(),
                "transition_probability": float(
                    self.query_one("#transition-prob", Input).value or "0.35"
                ),
                "transition_cooldown": int(
                    self.query_one("#transition-cooldown", Input).value or "1"
                ),
                "no_random_transitions": self.query_one("#no-random", Switch).value,
                "audio_normalize_transitions": self.query_one("#audio-normalize", Switch).value,
                "silence_static": self.query_one("#silence-static", Switch).value,
                "no_overlay": self.query_one("#no-overlay", Switch).value,
            }
            self.app.advance_to("review")
