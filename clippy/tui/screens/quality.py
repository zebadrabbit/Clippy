"""Quality preset + builder screen with live ffmpeg command preview."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from clippy.ffmpeg import EncoderParams
from clippy.presets import PRESETS, list_presets


def _clamp_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


class QualityScreen(Screen):
    """Step 4: Choose encoding preset and customize parameters."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="screen-container"):
            yield Static("Step 4 of 6 — Quality & Encoding", classes="screen-title")

            with Horizontal():
                # Left panel: preset selector
                with Vertical(id="preset-panel"):
                    yield Label("Encoding Preset")
                    yield OptionList(
                        *[Option(f"{name} — {desc}", id=name) for name, desc in list_presets()],
                        id="preset-list",
                    )
                    yield Static(
                        "Pick a preset to auto-fill the parameters, then tweak as needed.",
                        classes="help-text",
                    )

                # Right panel: parameter builder
                with Vertical(id="builder-panel"):
                    yield Label("Parameters (editable)")

                    with Horizontal():
                        with Vertical(classes="form-group"):
                            yield Label("Codec")
                            yield Select(
                                [("h264_nvenc (GPU)", "h264_nvenc"), ("libx264 (CPU)", "libx264")],
                                value="h264_nvenc",
                                id="codec-select",
                            )
                            yield Static(
                                "NVENC uses your GPU for fast encoding. "
                                "libx264 is a CPU fallback.",
                                classes="help-text",
                            )
                        with Vertical(classes="form-group"):
                            yield Label("CQ (quality)")
                            yield Input(value="19", id="cq-input")
                            yield Static(
                                "Constant quality level. Lower = better quality, larger files. "
                                "Typical range: 16-28.",
                                classes="help-text",
                            )

                    with Horizontal():
                        with Vertical(classes="form-group"):
                            yield Label("Max Bitrate")
                            yield Input(value="12M", id="bitrate-input")
                            yield Static(
                                "Peak bitrate cap (e.g. 12M, 8M). "
                                "Prevents spikes in complex scenes.",
                                classes="help-text",
                            )
                        with Vertical(classes="form-group"):
                            yield Label("Preset")
                            yield Select(
                                [
                                    ("slow", "slow"),
                                    ("medium", "medium"),
                                    ("fast", "fast"),
                                ],
                                value="slow",
                                id="preset-select",
                            )
                            yield Static(
                                "Encoder speed/quality trade-off. "
                                "Slow = best quality, Fast = quicker encode.",
                                classes="help-text",
                            )

                    with Horizontal():
                        with Vertical(classes="form-group"):
                            yield Label("Resolution")
                            yield Select(
                                [
                                    ("1920x1080", "1920x1080"),
                                    ("2560x1440", "2560x1440"),
                                    ("1280x720", "1280x720"),
                                ],
                                value="1920x1080",
                                id="resolution-select",
                            )
                            yield Static(
                                "Output video resolution. Clips are scaled to fit.",
                                classes="help-text",
                            )
                        with Vertical(classes="form-group"):
                            yield Label("FPS")
                            yield Select(
                                [("60", "60"), ("30", "30")],
                                value="60",
                                id="fps-select",
                            )
                            yield Static(
                                "Frames per second. 60 for smooth gameplay, 30 for smaller files.",
                                classes="help-text",
                            )

                    with Horizontal():
                        with Vertical(classes="form-group"):
                            yield Label("Audio Bitrate")
                            yield Input(value="192k", id="audio-bitrate-input")
                            yield Static(
                                "AAC audio bitrate (e.g. 192k, 128k). "
                                "Higher = better audio quality.",
                                classes="help-text",
                            )
                        with Vertical(classes="form-group"):
                            yield Label("Container")
                            yield Select(
                                [("mp4", "mp4"), ("mkv", "mkv")],
                                value="mp4",
                                id="container-select",
                            )
                            yield Static(
                                "MP4 for broad compatibility, MKV for lossless container features.",
                                classes="help-text",
                            )

            # Bottom: command preview
            yield Label("ffmpeg Command Preview")
            yield Static("", id="command-preview", classes="command-preview")

            # Warnings
            yield Static("", id="warnings")

            with Horizontal(classes="button-bar"):
                yield Button("← Back", id="back-btn")
                yield Button("Next →", variant="primary", id="next-btn")

    def on_mount(self) -> None:
        self._update_preview()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """When a preset is selected, populate the builder fields."""
        preset_name = event.option.id
        if preset_name and preset_name in PRESETS:
            enc = PRESETS[preset_name]
            self._populate_from_params(enc)
            self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._update_preview()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._update_preview()

    def _populate_from_params(self, enc: EncoderParams) -> None:
        """Fill builder fields from an EncoderParams instance."""
        try:
            self.query_one("#codec-select", Select).value = enc.video_codec
            self.query_one("#cq-input", Input).value = str(enc.cq)
            self.query_one("#bitrate-input", Input).value = enc.max_bitrate
            self.query_one("#preset-select", Select).value = enc.preset
            self.query_one("#resolution-select", Select).value = enc.resolution
            self.query_one("#fps-select", Select).value = enc.fps
            self.query_one("#audio-bitrate-input", Input).value = enc.audio_bitrate
            self.query_one("#container-select", Select).value = enc.container_ext
        except Exception:  # Textual widget query; UI may not be fully composed
            pass

    def _build_params(self) -> EncoderParams:
        """Build EncoderParams from current form values."""
        codec = self.query_one("#codec-select", Select).value
        return EncoderParams(
            video_codec=str(codec) if codec != Select.BLANK else "h264_nvenc",
            cq=_clamp_int(self.query_one("#cq-input", Input).value or "19", 19, 0, 51),
            max_bitrate=self.query_one("#bitrate-input", Input).value or "12M",
            buf_size=self.query_one("#bitrate-input", Input).value or "12M",
            preset=str(self.query_one("#preset-select", Select).value or "slow"),
            resolution=str(self.query_one("#resolution-select", Select).value or "1920x1080"),
            fps=str(self.query_one("#fps-select", Select).value or "60"),
            audio_bitrate=self.query_one("#audio-bitrate-input", Input).value or "192k",
            container_ext=str(self.query_one("#container-select", Select).value or "mp4"),
        )

    def _update_preview(self) -> None:
        """Update the command preview and warnings."""
        try:
            params = self._build_params()
            preview = self.query_one("#command-preview", Static)
            preview.update(params.to_command_preview())

            warnings_widget = self.query_one("#warnings", Static)
            warnings = params.validate()
            if warnings:
                warnings_widget.update("[bold yellow]" + "\n".join(warnings) + "[/]")
            else:
                warnings_widget.update("")
        except Exception:  # preview is best-effort; don't block the UI
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "next-btn":
            self.app.workflow["encoder_params"] = self._build_params()
            self.app.advance_to("transitions")
