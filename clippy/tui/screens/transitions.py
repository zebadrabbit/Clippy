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


def _parse_csv_list(value: str) -> list[str]:
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def _normalize_mode(value: str) -> str:
    mode = (value or "explicit").strip().lower()
    return mode if mode in {"explicit", "discover", "hybrid"} else "explicit"


def _safe_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_float(value: str, default: float, minimum: float, maximum: float) -> float:
    parsed = _safe_float(value, default)
    return max(minimum, min(maximum, parsed))


def _bounded_int(value: str, default: int, minimum: int) -> int:
    parsed = _safe_int(value, default)
    return max(minimum, parsed)


def _available_transitions_text(path: str) -> str:
    try:
        from clippy.utils import discover_transition_files

        names = discover_transition_files(path)
    except Exception:
        names = []
    if not names:
        return "Detected transition clips: none found yet."
    return "Detected transition clips: " + ", ".join(names)


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
            yield Static(
                _available_transitions_text(_resolve_transitions_path()),
                classes="help-text",
                id="available-transitions",
            )

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Transition Selection Mode")
                    yield Input(
                        value=str(getattr(cfg.sequencing, "transition_mode", "explicit")),
                        placeholder="explicit | discover | hybrid",
                        id="transition-mode",
                    )
                    yield Static(
                        "explicit = only listed files, discover = scan for transition_*.mp4, "
                        "hybrid = combine both.",
                        classes="help-text",
                    )
                with Vertical(classes="form-group"):
                    yield Label("Selected transitions (comma-separated)")
                    yield Input(
                        value=", ".join(getattr(cfg.assets, "transitions", [])),
                        placeholder="transition_01.mp4, transition_02.mp4",
                        id="selected-transitions",
                    )
                    yield Static(
                        "Use this allowlist to be selective. In explicit mode, only these files are eligible.",
                        classes="help-text",
                    )

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Excluded transitions (comma-separated)")
                    yield Input(
                        value=", ".join(getattr(cfg.sequencing, "transition_exclude", [])),
                        placeholder="transition_03.mp4",
                        id="transition-exclude",
                    )
                    yield Static(
                        "Optional denylist applied after selection/discovery.",
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
                        "Apply EBU R128 loudness normalization to transition/intro/outro clips "
                        "so they match clip audio levels.",
                        classes="help-text",
                    )

            with Horizontal():
                with Vertical(classes="form-group"):
                    yield Label("Normalize clip audio")
                    yield Switch(
                        value=cfg.audio.audio_normalize_clips,
                        id="audio-normalize-clips",
                    )
                    yield Static(
                        "Apply EBU R128 loudness normalization to every Twitch clip. "
                        "Prevents jarring volume jumps between loud and quiet clips.",
                        classes="help-text",
                    )
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

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "transitions-dir":
            path = event.value.strip() or _resolve_transitions_path()
            self.query_one("#available-transitions", Static).update(
                _available_transitions_text(path)
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "next-btn":
            self.app.workflow["transitions"] = {
                "transitions_dir": self.query_one("#transitions-dir", Input).value.strip(),
                "transition_mode": _normalize_mode(self.query_one("#transition-mode", Input).value),
                "selected_transitions": _parse_csv_list(
                    self.query_one("#selected-transitions", Input).value
                ),
                "transition_exclude": _parse_csv_list(
                    self.query_one("#transition-exclude", Input).value
                ),
                "transition_probability": _bounded_float(
                    self.query_one("#transition-prob", Input).value or "0.35",
                    0.35,
                    0.0,
                    1.0,
                ),
                "transition_cooldown": _bounded_int(
                    self.query_one("#transition-cooldown", Input).value or "1",
                    1,
                    0,
                ),
                "no_random_transitions": self.query_one("#no-random", Switch).value,
                "audio_normalize_clips": self.query_one("#audio-normalize-clips", Switch).value,
                "audio_normalize_transitions": self.query_one("#audio-normalize", Switch).value,
                "silence_static": self.query_one("#silence-static", Switch).value,
                "no_overlay": self.query_one("#no-overlay", Switch).value,
            }
            self.app.advance_to("review")
