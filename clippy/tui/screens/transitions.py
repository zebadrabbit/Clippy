"""Transitions configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, Static

from clippy.tui.bbs import BBSScreen


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


class TransitionsScreen(BBSScreen):
    """Step 5: Configure transitions, intro/outro, and audio settings."""

    STEP = 5
    STEP_TITLE = "Transitions"

    HINTS = {
        "transitions-dir": "folder holding your transition clips and static.mp4",
        "transition-mode": "explicit = listed only / discover = scan transition_*.mp4 / hybrid = both",
        "selected-transitions": "allowlist; in explicit mode only these files are eligible",
        "transition-exclude": "denylist applied after selection and discovery",
        "transition-prob": "chance of a transition between clips: 0.0 never, 1.0 always",
        "transition-cooldown": "do not repeat a transition within the last N picks (0 = off)",
        "no-random": "turn off random transitions; the static bumper is still inserted",
        "audio-normalize": "EBU R128 loudness match for transition/intro/outro clips",
        "audio-normalize-clips": "EBU R128 loudness match for every Twitch clip",
        "silence-static": "mute the static.mp4 bumper",
        "no-overlay": "skip the 'clip by' credit overlay on each clip",
    }
    DEFAULT_HINT = "Transitions and audio levelling."

    def compose(self) -> ComposeResult:
        cfg = self.app.config

        yield self.title_bar()
        with Vertical(classes="screen-container"):
            with Horizontal(classes="bbs-row"):
                yield Label("Directory ")
                yield Input(
                    value=_resolve_transitions_path(),
                    placeholder="./transitions",
                    id="transitions-dir",
                    classes="w-wide",
                )
            yield Static(
                _available_transitions_text(_resolve_transitions_path()),
                id="available-transitions",
                classes="bbs-dim",
            )

            yield Static("── SELECTION ──", classes="bbs-section")
            with Horizontal(classes="bbs-row"):
                yield Label("Mode  ")
                yield Input(
                    value=str(getattr(cfg.sequencing, "transition_mode", "explicit")),
                    placeholder="explicit|discover|hybrid",
                    id="transition-mode",
                    classes="w-med",
                )
                yield Label("  Prob ")
                yield Input(
                    value=str(cfg.sequencing.transition_probability),
                    id="transition-prob",
                    classes="w-tiny",
                )
                yield Label("  Cooldown ")
                yield Input(
                    value=str(cfg.sequencing.transition_cooldown),
                    id="transition-cooldown",
                    classes="w-tiny",
                )

            with Horizontal(classes="bbs-row"):
                yield Label("Use   ")
                yield Input(
                    value=", ".join(getattr(cfg.assets, "transitions", [])),
                    placeholder="transition_01.mp4, ...",
                    id="selected-transitions",
                    classes="w-wide",
                )
            with Horizontal(classes="bbs-row"):
                yield Label("Skip  ")
                yield Input(
                    value=", ".join(getattr(cfg.sequencing, "transition_exclude", [])),
                    placeholder="transition_03.mp4",
                    id="transition-exclude",
                    classes="w-wide",
                )

            yield Static("── AUDIO & OVERLAY ──", classes="bbs-section")
            with Horizontal(classes="bbs-row"):
                yield Checkbox(
                    "No random", value=cfg.sequencing.no_random_transitions, id="no-random"
                )
                yield Checkbox(
                    "Level assets",
                    value=cfg.audio.audio_normalize_transitions,
                    id="audio-normalize",
                )
            with Horizontal(classes="bbs-row"):
                yield Checkbox(
                    "Level clips", value=cfg.audio.audio_normalize_clips, id="audio-normalize-clips"
                )
                yield Checkbox("Mute static", value=cfg.audio.silence_static, id="silence-static")
            with Horizontal(classes="bbs-row"):
                yield Checkbox("No overlay", value=not cfg.behavior.enable_overlay, id="no-overlay")

            yield self.progress_bar()
            with Horizontal(classes="button-bar"):
                yield Button("< Back", id="back-btn")
                yield Button("Next >", variant="primary", id="next-btn")

        yield from self.status_bar()

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
                "no_random_transitions": self.query_one("#no-random", Checkbox).value,
                "audio_normalize_clips": self.query_one("#audio-normalize-clips", Checkbox).value,
                "audio_normalize_transitions": self.query_one("#audio-normalize", Checkbox).value,
                "silence_static": self.query_one("#silence-static", Checkbox).value,
                "no_overlay": self.query_one("#no-overlay", Checkbox).value,
            }
            self.app.advance_to("review")
