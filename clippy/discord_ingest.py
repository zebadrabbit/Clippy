"""Discord ingest utilities

Reads recent messages from a configured Discord channel and extracts Twitch clip
URLs or IDs. Intended to be used as a source list for Helix lookups.

Requirements:
    - A Discord bot token with read access to the target channel
    - Message Content Intent enabled in the Discord Developer Portal

We use discord.py with a minimal Client and read channel history on_ready.
"""
from __future__ import annotations

import os
import re
import asyncio
from typing import List, Tuple

import discord

_TWITCH_CLIP_RE = re.compile(r"https?://clips\.twitch\.tv/([\w-]+)", re.IGNORECASE)
_TWITCH_URL_ID_RE = re.compile(r"https?://(?:www\.)?twitch\.tv/[^/]+/clip/([\w-]+)", re.IGNORECASE)


def extract_clip_ids_from_text(text: str) -> List[str]:
    ids: List[str] = []
    for m in _TWITCH_CLIP_RE.finditer(text or ""):
        ids.append(m.group(1))
    for m in _TWITCH_URL_ID_RE.finditer(text or ""):
        ids.append(m.group(1))
    # Deduplicate preserving order
    seen = set()
    out: List[str] = []
    for i in ids:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out


async def fetch_recent_clip_ids(token: str, channel_id: int, limit: int = 200) -> Tuple[List[str], str]:
    """Fetch recent messages from a channel and extract Twitch clip IDs.

    Returns a tuple of (ids, channel_display_name) where channel_display_name is
    something like "Guild Name / #general" or just "#general" if no guild.

    - token: Discord bot token
    - channel_id: numeric ID of the channel to read
    - limit: number of messages to scan
    """
    intents = discord.Intents.default()
    intents.message_content = True  # Required to read message content

    class _Collector(discord.Client):
        def __init__(self, *, intents: discord.Intents, channel_id: int, limit: int):
            super().__init__(intents=intents)
            self._channel_id = channel_id
            self._limit = limit
            self.ids: List[str] = []
            self.channel_display: str = f"channel:{channel_id}"

        async def on_ready(self):
            channel = self.get_channel(self._channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(self._channel_id)
                except Exception as e:
                    await self.close()
                    raise RuntimeError(f"Failed to fetch channel: {e}")
            # Build a friendly display name for logs
            try:
                name = getattr(channel, "name", None) or str(self._channel_id)
                guild = getattr(getattr(channel, "guild", None), "name", None)
                if guild:
                    self.channel_display = f"{guild} / #{name}"
                else:
                    self.channel_display = f"#{name}"
            except Exception:
                self.channel_display = f"channel:{self._channel_id}"
            if not hasattr(channel, "history"):
                await self.close()
                raise RuntimeError("Channel does not support history() (must be TextChannel)")
            try:
                async for message in channel.history(limit=self._limit):
                    self.ids.extend(extract_clip_ids_from_text(getattr(message, "content", "") or ""))
                    for att in getattr(message, "attachments", []) or []:
                        if getattr(att, "url", None):
                            self.ids.extend(extract_clip_ids_from_text(att.url))
            finally:
                await self.close()

    client = _Collector(intents=intents, channel_id=channel_id, limit=limit)
    await client.start(token, reconnect=False)
    # Deduplicate preserving order
    seen = set()
    out: List[str] = []
    for i in client.ids:
        if i and i not in seen:
            seen.add(i)
            out.append(i)
    return out, client.channel_display


def load_discord_token(arg_token: str | None = None) -> str:
    """Precedence: CLI arg > DISCORD_TOKEN env > .env file."""
    if arg_token:
        return arg_token
    tok = os.getenv("DISCORD_TOKEN")
    if tok:
        return tok
    # Lightweight .env parsing
    path = ".env"
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == "DISCORD_TOKEN":
                        return v.strip().strip('"').strip("'")
        except Exception:
            pass
    raise SystemExit("Missing Discord token: set DISCORD_TOKEN in env or .env, or provide --discord-token")
