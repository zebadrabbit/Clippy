"""Clippy TUI — main application shell.

Launch via ``python main.py --tui`` or ``python -m clippy.tui.app``.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from clippy.config import get_config
from clippy.models import ClippyConfig


class ClippyApp(App):
    """Guided workflow TUI for building Twitch clip compilations."""

    TITLE = "Clippy"
    SUB_TITLE = "Twitch Clip Compiler"
    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("escape", "back", "Back", show=True),
    ]

    def __init__(self, config: ClippyConfig | None = None, **kwargs):
        super().__init__(**kwargs)
        self.config = config or get_config()
        # Accumulate user choices across screens
        self.workflow: dict = {
            "source": "twitch",
            "credentials": {},
            "clip_settings": {},
            "encoder_params": None,
            "transitions": {},
        }

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        from clippy.tui.screens.source import SourceScreen

        self.push_screen(SourceScreen())

    def action_back(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()

    def advance_to(self, screen_name: str, **kwargs) -> None:
        """Navigate to the next screen in the workflow."""
        from clippy.tui.screens.clip_settings import ClipSettingsScreen
        from clippy.tui.screens.credentials import CredentialsScreen
        from clippy.tui.screens.progress import ProgressScreen
        from clippy.tui.screens.quality import QualityScreen
        from clippy.tui.screens.review import ReviewScreen
        from clippy.tui.screens.source import SourceScreen
        from clippy.tui.screens.summary import SummaryScreen
        from clippy.tui.screens.transitions import TransitionsScreen

        if screen_name == "summary":
            self.push_screen(SummaryScreen(**kwargs))
            return

        screens = {
            "source": SourceScreen,
            "credentials": CredentialsScreen,
            "clip_settings": ClipSettingsScreen,
            "quality": QualityScreen,
            "transitions": TransitionsScreen,
            "review": ReviewScreen,
            "progress": ProgressScreen,
        }
        screen_cls = screens.get(screen_name)
        if screen_cls:
            self.push_screen(screen_cls())


def run_tui(config: ClippyConfig | None = None) -> None:
    """Entry point for the TUI."""
    from clippy.runtime import _load_env_if_present

    _load_env_if_present()
    app = ClippyApp(config=config)
    app.run()


if __name__ == "__main__":
    run_tui()
