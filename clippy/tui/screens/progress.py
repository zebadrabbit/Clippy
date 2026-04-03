"""Progress dashboard — live view of pipeline execution."""

from __future__ import annotations

import logging
from typing import Protocol

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Label, ProgressBar, RichLog, Static


# ---------------------------------------------------------------------------
# Pipeline callback protocol (consumed by both TUI and CLI)
# ---------------------------------------------------------------------------


class PipelineCallbacks(Protocol):
    """Interface for pipeline progress reporting."""

    def on_clip_status(self, clip_id: str, status: str, progress: float | None = None) -> None:
        ...

    def on_stage_change(self, stage: str) -> None:
        ...

    def on_concat_progress(self, index: int, progress: float) -> None:
        ...

    def on_log(self, message: str, level: int = 0) -> None:
        ...


# ---------------------------------------------------------------------------
# Progress Screen
# ---------------------------------------------------------------------------


class ProgressScreen(Screen):
    """Live progress dashboard during pipeline execution."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="screen-container"):
            yield Static("Processing", classes="screen-title")

            with Vertical(classes="progress-section"):
                yield Label("Overall Progress")
                yield ProgressBar(total=100, id="overall-progress")

            yield Label("Stage: Initializing...", id="stage-label")

            yield Label("Clip Status")
            yield DataTable(id="clip-table")

            with Vertical(classes="progress-section"):
                yield Label("Compilation Progress")
                yield ProgressBar(total=100, id="concat-progress")

            yield Label("Log")
            yield RichLog(id="log-panel", classes="log-panel", markup=True)

            with Vertical(classes="button-bar"):
                yield Button("Cancel", variant="error", id="cancel-btn")

    def on_mount(self) -> None:
        table = self.query_one("#clip-table", DataTable)
        table.add_columns("Clip ID", "Status", "Progress")

        log_widget = self.query_one("#log-panel", RichLog)
        log_widget.write("[bold cyan]Pipeline starting...[/]")

        # Start the pipeline in a worker thread
        self.run_worker(self._run_pipeline, thread=True)

    async def _run_pipeline(self) -> None:
        """Execute the pipeline in a background thread."""
        log_widget = self.query_one("#log-panel", RichLog)

        try:
            log_widget.write("Building configuration from workflow settings...")
            wf = self.app.workflow
            cs = wf.get("clip_settings", {})
            broadcaster = cs.get("broadcaster", "")

            if not broadcaster:
                log_widget.write("[bold red]Error: No broadcaster specified[/]")
                return

            log_widget.write(f"Broadcaster: {broadcaster}")
            log_widget.write(f"Source: {wf.get('source', 'twitch')}")

            enc = wf.get("encoder_params")
            if enc:
                log_widget.write(f"Codec: {enc.video_codec}, CQ: {enc.cq}, {enc.resolution}@{enc.fps}fps")

            log_widget.write("")
            log_widget.write("[bold yellow]Pipeline execution is not yet wired to the TUI.[/]")
            log_widget.write("The full pipeline integration will connect in a future update.")
            log_widget.write("")
            log_widget.write("For now, use the CLI to run the pipeline:")
            log_widget.write(f"  python main.py --broadcaster {broadcaster} -y")
            if enc:
                log_widget.write(f"  --preset {enc.name}" if enc.name else "")

        except Exception as e:  # surface any pipeline error in the UI
            log_widget.write(f"[bold red]Error: {e}[/]")

    # Callback methods (for future pipeline integration)

    def update_clip_status(self, clip_id: str, status: str, progress: float | None = None) -> None:
        """Update a clip's status in the table."""
        table = self.query_one("#clip-table", DataTable)
        prog_str = f"{progress:.0f}%" if progress is not None else ""
        # Try to update existing row, else add new
        try:
            for row_key in table.rows:
                row = table.get_row(row_key)
                if row[0] == clip_id:
                    table.update_cell(row_key, "Status", status)
                    table.update_cell(row_key, "Progress", prog_str)
                    return
        except Exception:  # Textual table API; row may not exist yet
            pass
        table.add_row(clip_id[:20], status, prog_str)

    def update_stage(self, stage: str) -> None:
        """Update the stage label."""
        label = self.query_one("#stage-label", Label)
        label.update(f"Stage: {stage}")

    def update_overall_progress(self, pct: float) -> None:
        """Update the overall progress bar."""
        self.query_one("#overall-progress", ProgressBar).update(progress=pct)

    def update_concat_progress(self, pct: float) -> None:
        """Update the compilation progress bar."""
        self.query_one("#concat-progress", ProgressBar).update(progress=pct)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            log_widget = self.query_one("#log-panel", RichLog)
            log_widget.write("[bold red]Cancelling...[/]")
            self.app.pop_screen()
