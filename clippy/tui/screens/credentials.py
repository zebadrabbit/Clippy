"""Credentials screen — Twitch / Discord auth."""

from __future__ import annotations

import os
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, Static

from clippy.runtime import save_env
from clippy.tui.bbs import BBSScreen


class CredentialsScreen(BBSScreen):
    """Step 2: Enter credentials."""

    STEP = 2
    STEP_TITLE = "Credentials"
    KEYS = "[TAB] field   [ENTER] continue   [ESC] back   [Q] quit"

    HINTS = {
        "client-id": "client id: from your app at dev.twitch.tv/console/apps",
        "client-secret": "client secret: paired with the client id; never shown again by Twitch",
        "discord-token": "bot token: from the Discord Developer Portal",
        "discord-channel-id": "channel id: right-click the channel > Copy ID (needs Developer Mode)",
        "save-env": "write the credentials to .env so you are not asked again",
    }
    DEFAULT_HINT = "Credentials are read from .env or the environment when present."

    def compose(self) -> ComposeResult:
        source = self.app.workflow.get("source", "twitch")

        yield self.title_bar()
        with Vertical(classes="screen-container"):
            yield Static("", classes="bbs-gap")
            yield Static("── TWITCH ──", classes="bbs-section")

            with Horizontal(classes="bbs-row"):
                yield Label("Client ID    ")
                yield Input(
                    value=os.getenv("TWITCH_CLIENT_ID", ""),
                    placeholder="dev.twitch.tv",
                    password=True,
                    id="client-id",
                    classes="w-wide",
                )
            with Horizontal(classes="bbs-row"):
                yield Label("Client secret")
                yield Input(
                    value=os.getenv("TWITCH_CLIENT_SECRET", ""),
                    placeholder="paired secret",
                    password=True,
                    id="client-secret",
                    classes="w-wide",
                )

            if source == "discord":
                yield Static("", classes="bbs-gap")
                yield Static("── DISCORD ──", classes="bbs-section")
                with Horizontal(classes="bbs-row"):
                    yield Label("Bot token    ")
                    yield Input(
                        value=os.getenv("DISCORD_TOKEN", ""),
                        placeholder="bot token",
                        password=True,
                        id="discord-token",
                        classes="w-wide",
                    )
                with Horizontal(classes="bbs-row"):
                    yield Label("Channel ID   ")
                    yield Input(
                        value=str(self.app.config.discord.channel_id or ""),
                        placeholder="right-click > Copy ID",
                        id="discord-channel-id",
                        classes="w-wide",
                    )

            yield Static("", classes="bbs-gap")
            yield Checkbox(
                "Save credentials to .env",
                value=not Path(".env").is_file(),
                id="save-env",
            )
            yield Static("", id="validation-status")
            yield self.progress_bar()

            with Horizontal(classes="button-bar"):
                yield Button("< Back", id="back-btn")
                yield Button("Validate", id="validate-btn")
                yield Button("Next >", variant="primary", id="next-btn")

        yield from self.status_bar()

    def on_mount(self) -> None:
        """Auto-skip if credentials are already available from env / .env."""
        client_id = os.getenv("TWITCH_CLIENT_ID", "").strip()
        client_secret = os.getenv("TWITCH_CLIENT_SECRET", "").strip()
        source = self.app.workflow.get("source", "twitch")

        if not client_id or not client_secret:
            return

        if source == "discord":
            discord_token = os.getenv("DISCORD_TOKEN", "").strip()
            if not discord_token:
                return

        # All required creds present — save and skip ahead
        self._save_and_advance()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "validate-btn":
            self._validate_credentials()
        elif event.button.id == "next-btn":
            self._save_and_advance()

    def _validate_credentials(self) -> None:
        status = self.query_one("#validation-status", Static)
        client_id = self.query_one("#client-id", Input).value.strip()
        client_secret = self.query_one("#client-secret", Input).value.strip()

        if not client_id or not client_secret:
            status.update("[bold red]Please enter both Client ID and Secret[/]")
            return

        try:
            from clippy.twitch_ingest import get_app_access_token

            token = get_app_access_token(client_id, client_secret)
            if token:
                status.update("[bold green]Credentials valid![/]")
            else:
                status.update("[bold red]Auth failed — check credentials[/]")
        except Exception as e:  # auth can raise requests/runtime/key errors
            status.update(f"[bold red]Error: {e}[/]")

    def _save_and_advance(self) -> None:
        creds = {
            "client_id": self.query_one("#client-id", Input).value.strip(),
            "client_secret": self.query_one("#client-secret", Input).value.strip(),
        }
        try:
            creds["discord_token"] = self.query_one("#discord-token", Input).value.strip()
            creds["discord_channel_id"] = self.query_one("#discord-channel-id", Input).value.strip()
        except Exception:  # discord widgets absent when source is twitch-only
            pass

        # Persist to .env if checkbox is checked
        # Note: discord_channel_id lives in clippy.yaml, not .env
        try:
            if self.query_one("#save-env", Checkbox).value:
                env_vals: dict[str, str] = {
                    "TWITCH_CLIENT_ID": creds["client_id"],
                    "TWITCH_CLIENT_SECRET": creds["client_secret"],
                }
                if creds.get("discord_token"):
                    env_vals["DISCORD_TOKEN"] = creds["discord_token"]
                save_env(env_vals)
        except Exception:
            pass  # don't block the workflow if .env write fails

        self.app.workflow["credentials"] = creds
        self.app.advance_to("clip_settings")
