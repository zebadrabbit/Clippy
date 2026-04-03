"""Credentials screen — Twitch / Discord auth."""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static


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

            yield Label("Twitch Client Secret")
            yield Input(
                value=os.getenv("TWITCH_CLIENT_SECRET", ""),
                placeholder="Enter Twitch Client Secret",
                password=True,
                id="client-secret",
            )

            if source == "discord":
                yield Label("Discord Bot Token")
                yield Input(
                    value=os.getenv("DISCORD_TOKEN", ""),
                    placeholder="Enter Discord bot token",
                    password=True,
                    id="discord-token",
                )
                yield Label("Discord Channel ID")
                yield Input(
                    placeholder="Enter Discord channel ID",
                    id="discord-channel-id",
                )

            yield Static("", id="validation-status")

            with Vertical(classes="button-bar"):
                yield Button("Validate", id="validate-btn")
                yield Button("Next →", variant="primary", id="next-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "validate-btn":
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
        except Exception as e:
            status.update(f"[bold red]Error: {e}[/]")

    def _save_and_advance(self) -> None:
        creds = {
            "client_id": self.query_one("#client-id", Input).value.strip(),
            "client_secret": self.query_one("#client-secret", Input).value.strip(),
        }
        try:
            creds["discord_token"] = self.query_one("#discord-token", Input).value.strip()
            creds["discord_channel_id"] = self.query_one("#discord-channel-id", Input).value.strip()
        except Exception:
            pass
        self.app.workflow["credentials"] = creds
        self.app.advance_to("clip_settings")
