"""Credentials screen — Twitch / Discord auth."""

from __future__ import annotations

import os
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, Label, Static

from clippy.runtime import save_env


class CredentialsScreen(Screen):
    """Step 2: Enter credentials."""

    def compose(self) -> ComposeResult:
        source = self.app.workflow.get("source", "twitch")

        with Vertical(classes="screen-container"):
            yield Static("Step 2 of 6 — Credentials", classes="screen-title")

            yield Label("Twitch Client ID")
            yield Input(
                value=os.getenv("TWITCH_CLIENT_ID", ""),
                placeholder="Enter Twitch Client ID",
                password=True,
                id="client-id",
            )
            yield Static(
                "Your Twitch application's Client ID from dev.twitch.tv.",
                classes="help-text",
            )

            yield Label("Twitch Client Secret")
            yield Input(
                value=os.getenv("TWITCH_CLIENT_SECRET", ""),
                placeholder="Enter Twitch Client Secret",
                password=True,
                id="client-secret",
            )
            yield Static(
                "The secret key paired with your Client ID. "
                "Pre-filled from .env or environment variables if available.",
                classes="help-text",
            )

            if source == "discord":
                yield Label("Discord Bot Token")
                yield Input(
                    value=os.getenv("DISCORD_TOKEN", ""),
                    placeholder="Enter Discord bot token",
                    password=True,
                    id="discord-token",
                )
                yield Static(
                    "Bot token from the Discord Developer Portal.",
                    classes="help-text",
                )
                yield Label("Discord Channel ID")
                yield Input(
                    value=str(self.app.config.discord.channel_id or ""),
                    placeholder="Enter Discord channel ID",
                    id="discord-channel-id",
                )
                yield Static(
                    "Right-click the channel in Discord and Copy ID (Developer Mode must be on). "
                    "Pre-filled from clippy.yaml if available.",
                    classes="help-text",
                )

            yield Static("")
            yield Checkbox(
                "Save credentials to .env for next time",
                value=not Path(".env").is_file(),
                id="save-env",
            )
            yield Static(
                "Writes API credentials (Client ID, Secret, Discord token) to .env. "
                "Channel ID and other settings are saved in clippy.yaml.",
                classes="help-text",
            )

            yield Static("", id="validation-status")

            with Horizontal(classes="button-bar"):
                yield Button("← Back", id="back-btn")
                yield Button("Validate", id="validate-btn")
                yield Button("Next →", variant="primary", id="next-btn")

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
