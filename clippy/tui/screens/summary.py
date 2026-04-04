"""Summary screen — shown after pipeline completes successfully."""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static

from clippy.models import ClipRow


def _fmt_duration(secs: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    s = int(secs)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}h {m:02d}m {s:02d}s"
    return f"{m:d}m {s:02d}s"


class SummaryScreen(Screen):
    """Post-pipeline summary with output paths, stats, and credits."""

    def __init__(
        self,
        output_files: list[str],
        compilations: list[list[ClipRow]],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._output_files = output_files
        self._compilations = compilations

    def compose(self) -> ComposeResult:
        files = self._output_files
        comps = self._compilations

        with VerticalScroll(classes="screen-container"):
            yield Static(
                "[bold green]Pipeline Complete[/]",
                classes="screen-title",
                markup=True,
            )

            # --- Output files ---
            yield Static("[bold]Output Files[/]", classes="section-header", markup=True)
            for i, path in enumerate(files):
                abs_path = os.path.abspath(path)
                _ = os.path.dirname(abs_path)
                yield Static(
                    f"  Compilation {i + 1}: [cyan]{abs_path}[/]",
                    markup=True,
                )
            if files:
                yield Static(
                    f"  Folder: [cyan]{os.path.dirname(os.path.abspath(files[0]))}[/]",
                    markup=True,
                )
            yield Static("")

            # --- Per-compilation stats ---
            yield Static("[bold]Compilation Stats[/]", classes="section-header", markup=True)
            total_clips = 0
            total_duration = 0.0
            for i, comp in enumerate(comps):
                comp_dur = sum(c.duration for c in comp)
                total_clips += len(comp)
                total_duration += comp_dur
                yield Static(
                    f"  Part {i + 1}: {len(comp)} clips, " f"~{_fmt_duration(comp_dur)} estimated",
                    markup=True,
                )
            yield Static(
                f"  [bold]Total: {total_clips} clips, ~{_fmt_duration(total_duration)}[/]",
                markup=True,
            )
            yield Static("")

            # --- Credits (for YouTube description) ---
            yield Static(
                "[bold]Credits (copy for YouTube description)[/]",
                classes="section-header",
                markup=True,
            )
            yield Static("  ─" * 20)

            for i, comp in enumerate(comps):
                if len(comps) > 1:
                    yield Static(f"  [bold]Part {i + 1}[/]", markup=True)
                seen_authors: dict[str, list[str]] = {}
                for clip in comp:
                    title = clip.title or clip.id
                    author = clip.author or "Unknown"
                    seen_authors.setdefault(author, []).append(title)

                for author, titles in seen_authors.items():
                    for title in titles:
                        yield Static(f"    {title} — clipped by {author}")
                yield Static("")

            # Unique contributors list
            all_authors = sorted(
                {c.author for comp in comps for c in comp if c.author},
            )
            if all_authors:
                yield Static(
                    "[bold]Contributors[/]",
                    classes="section-header",
                    markup=True,
                )
                yield Static(f"  {', '.join(all_authors)}")
                yield Static("")

            with Horizontal(classes="button-bar"):
                yield Button("Done — Quit", variant="primary", id="quit-btn")
                yield Button("New Run", id="new-run-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit-btn":
            self.app.exit()
        elif event.button.id == "new-run-btn":
            # Clear workflow and start over
            self.app.workflow = {
                "source": "twitch",
                "credentials": self.app.workflow.get("credentials", {}),
                "clip_settings": {},
                "encoder_params": None,
                "transitions": {},
            }
            # Pop all screens back to default, then push source
            while len(self.app.screen_stack) > 1:
                self.app.pop_screen()
            from clippy.tui.screens.source import SourceScreen

            self.app.push_screen(SourceScreen())
