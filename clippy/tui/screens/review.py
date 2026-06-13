"""Review screen — summary of all settings before starting."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Static


class ReviewScreen(Screen):
    """Step 6: Review all settings and start processing."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="screen-container"):
            yield Static("Step 6 of 6 — Review & Start", classes="screen-title")
            yield DataTable(id="review-table")
            with Horizontal(classes="button-bar"):
                yield Button("← Back", id="back-btn")
                yield Button("Start Processing", variant="primary", id="start-btn")

    def on_mount(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.add_columns("Setting", "Value")

        wf = self.app.workflow

        # Source
        source = wf.get("source", "twitch")
        table.add_row("Source", source.title())

        # Credentials — show Discord channel if applicable
        creds = wf.get("credentials", {})
        if source == "discord":
            channel_id = creds.get("discord_channel_id", "—")
            table.add_row("Discord Channel ID", channel_id or "—")

        # Clip settings
        cs = wf.get("clip_settings", {})
        table.add_row("Broadcaster", cs.get("broadcaster", "—"))

        start = cs.get("start", "")
        end = cs.get("end", "")
        start_display = start or "last 3 days"
        end_display = end or "today"
        table.add_row("Date Range", f"{start_display} → {end_display}")
        table.add_row("Min Views", str(cs.get("min_views", 0)))

        sizing = cs.get("sizing_mode", "count")
        if sizing == "duration":
            table.add_row("Sizing Mode", "By duration")
            table.add_row(
                "Target Length",
                f"~{cs.get('target_duration_min', 10)} min per compilation",
            )
        else:
            table.add_row("Sizing Mode", "By clip count")
            table.add_row("Clips / Compilation", str(cs.get("clips_per_comp", 12)))

        table.add_row("Compilations", str(cs.get("compilations", 2)))
        table.add_row("Auto-expand", "Yes" if cs.get("auto_expand") else "No")
        table.add_row("Nostalgia Mode", "Yes" if cs.get("nostalgia_mode") else "No")

        # Encoder
        enc = wf.get("encoder_params")
        if enc:
            table.add_row("Codec", enc.video_codec)
            table.add_row("CQ", str(enc.cq))
            table.add_row("Max Bitrate", enc.max_bitrate)
            table.add_row("Resolution", enc.resolution)
            table.add_row("FPS", enc.fps)
            table.add_row("Preset", enc.preset)
            table.add_row("Audio Bitrate", enc.audio_bitrate)
            table.add_row("Container", enc.container_ext)

        # Transitions
        tr = wf.get("transitions", {})
        selected = tr.get("selected_transitions", [])
        excluded = tr.get("transition_exclude", [])
        table.add_row("Transitions Dir", tr.get("transitions_dir", "transitions"))
        table.add_row("Transition Mode", str(tr.get("transition_mode", "explicit")))
        table.add_row(
            "Transitions",
            ", ".join(selected) if selected else "Use configured/discovered pool",
        )
        if excluded:
            table.add_row("Excluded", ", ".join(excluded))
        table.add_row("Transition Prob", str(tr.get("transition_probability", 0.35)))
        table.add_row("Cooldown", str(tr.get("transition_cooldown", 1)))
        table.add_row(
            "Audio Normalize", "Yes" if tr.get("audio_normalize_transitions", True) else "No"
        )
        table.add_row(
            "Clip Audio Normalize", "Yes" if tr.get("audio_normalize_clips", True) else "No"
        )
        table.add_row("Overlay", "No" if tr.get("no_overlay", False) else "Yes")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "start-btn":
            self.app.advance_to("progress")
