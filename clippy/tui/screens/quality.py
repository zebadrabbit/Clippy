"""Quality preset + builder screen with live ffmpeg command preview."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from clippy.ffmpeg import EncoderParams
from clippy.presets import PRESETS, list_presets
from clippy.tui.bbs import BBSScreen


def _clamp_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


class QualityScreen(BBSScreen):
    """Step 4: Choose encoding preset and customize parameters."""

    STEP = 4
    STEP_TITLE = "Quality & Encoding"

    HINTS = {
        "preset-list": "pick a preset to fill every parameter below, then tweak",
        "codec-select": "nvenc encodes on the GPU; libx264 is the CPU fallback",
        "cq-input": "constant quality: lower = better and larger. typical 16-28",
        "bitrate-input": "peak bitrate cap, e.g. 12M. limits spikes in busy scenes",
        "preset-select": "encoder speed/quality trade-off",
        "resolution-select": "output resolution; clips are scaled to fit",
        "fps-select": "60 for gameplay, 30 for smaller files",
        "audio-bitrate-input": "AAC audio bitrate, e.g. 192k",
        "container-select": "mp4 for compatibility, mkv for lossless container features",
    }
    DEFAULT_HINT = "Choose a preset, or set the encoder parameters by hand."

    def compose(self) -> ComposeResult:
        yield self.title_bar()
        with Vertical(classes="screen-container"):
            yield Static("── PRESET ──", classes="bbs-section")
            yield OptionList(
                *[Option(f"{name} — {desc}", id=name) for name, desc in list_presets()],
                id="preset-list",
                classes="preset-list",
            )

            yield Static("── PARAMETERS ──", classes="bbs-section")
            with Horizontal(classes="bbs-row"):
                yield Label("Codec ")
                yield Select(
                    [("nvenc (GPU)", "h264_nvenc"), ("libx264 (CPU)", "libx264")],
                    value="h264_nvenc",
                    id="codec-select",
                    classes="w-med",
                )
                yield Label("  CQ ")
                yield Input(value="19", id="cq-input", classes="w-tiny")
                yield Label("  Rate ")
                yield Input(value="12M", id="bitrate-input", classes="w-sm")

            with Horizontal(classes="bbs-row"):
                yield Label("Speed ")
                yield Select(
                    [("slow", "slow"), ("medium", "medium"), ("fast", "fast")],
                    value="slow",
                    id="preset-select",
                    classes="w-med",
                )
                yield Label("  Res ")
                yield Select(
                    [
                        ("1920x1080", "1920x1080"),
                        ("2560x1440", "2560x1440"),
                        ("1280x720", "1280x720"),
                    ],
                    value="1920x1080",
                    id="resolution-select",
                    classes="w-med",
                )

            with Horizontal(classes="bbs-row"):
                yield Label("FPS   ")
                yield Select(
                    [("60", "60"), ("30", "30")], value="60", id="fps-select", classes="w-tiny"
                )
                yield Label("  Audio ")
                yield Input(value="192k", id="audio-bitrate-input", classes="w-sm")
                yield Label("  Fmt ")
                yield Select(
                    [("mp4", "mp4"), ("mkv", "mkv")],
                    value="mp4",
                    id="container-select",
                    classes="w-sm",
                )

            yield Static("", id="command-preview", classes="command-preview")
            yield Static("", id="warnings")
            yield self.progress_bar()

            with Horizontal(classes="button-bar"):
                yield Button("< Back", id="back-btn")
                yield Button("Next >", variant="primary", id="next-btn")

        yield from self.status_bar()

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
