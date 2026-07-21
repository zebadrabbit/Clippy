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
from typing import Iterable, List, Optional, Tuple

# discord is imported lazily inside fetch_recent_clip_ids: extracting clip IDs
# from text has no business requiring the library, and keeping it out of module
# scope means the parser can be used (and tested) without the optional extra.

#: One pattern, scanned in document order, covering the forms people actually
#: paste into a channel:
#:   https://clips.twitch.tv/SomeClip
#:   https://clips.twitch.tv/embed?clip=SomeClip
#:   https://www.twitch.tv/someone/clip/SomeClip
#:   https://m.twitch.tv/someone/clip/SomeClip      <- phone shares
#: The embed branch comes first, or the plain branch would capture "embed" as
#: the clip ID.
_CLIP_RE = re.compile(
    r"https?://clips\.twitch\.tv/embed\?clip=(?P<embed>[\w-]+)"
    r"|https?://clips\.twitch\.tv/(?P<direct>[\w-]+)"
    r"|https?://(?:[\w-]+\.)?twitch\.tv/[^/\s]+/clip/(?P<channel>[\w-]+)",
    re.IGNORECASE,
)


def _dedupe(ids: Iterable[str]) -> List[str]:
    """Unique IDs, first occurrence wins."""
    seen: set[str] = set()
    out: List[str] = []
    for value in ids:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def extract_clip_ids_from_text(text: str) -> List[str]:
    """Clip IDs found in *text*, in the order they appear.

    Document order matters: the channel is a curated list, and when it holds
    more clips than a compilation needs, the ones nearest the top win.
    """
    found = (
        match.group("embed") or match.group("direct") or match.group("channel")
        for match in _CLIP_RE.finditer(text or "")
    )
    return _dedupe(found)


def _ids_in_message(message) -> List[str]:
    """Every clip ID a single message contributes.

    Covers the message text, any attachment URLs, and embeds -- a bot that
    reposts clips often puts the link only in an embed, leaving ``content``
    empty, so scanning text alone would silently miss those.
    """
    found: List[str] = []
    found.extend(extract_clip_ids_from_text(getattr(message, "content", "") or ""))

    for attachment in getattr(message, "attachments", None) or []:
        url = getattr(attachment, "url", None)
        if url:
            found.extend(extract_clip_ids_from_text(url))

    for embed in getattr(message, "embeds", None) or []:
        for part in ("url", "title", "description"):
            value = getattr(embed, part, None)
            if isinstance(value, str):
                found.extend(extract_clip_ids_from_text(value))

    return found


async def fetch_recent_clip_ids(
    token: str, channel_id: int, limit: int = 200
) -> Tuple[List[str], str]:
    """Fetch recent messages from a channel and extract Twitch clip IDs.

    Returns a tuple of (ids, channel_display_name) where channel_display_name is
    something like "Guild Name / #general" or just "#general" if no guild.

    - token: Discord bot token
    - channel_id: numeric ID of the channel to read
    - limit: number of messages to scan
    """
    import discord

    intents = discord.Intents.default()
    intents.message_content = True  # Required to read message content

    class _Collector(discord.Client):
        def __init__(self, *, intents: discord.Intents, channel_id: int, limit: int):
            super().__init__(intents=intents)
            self._channel_id = channel_id
            self._limit = limit
            self.ids: List[str] = []
            self.channel_display: str = f"channel:{channel_id}"
            # discord.py routes exceptions raised in an event handler to
            # on_error, which logs and carries on -- so a failure in on_ready
            # would otherwise surface as "no clips found" rather than the real
            # reason. Stash it and re-raise once start() returns.
            self.failure: Optional[BaseException] = None

        async def on_ready(self):
            channel = self.get_channel(self._channel_id)
            if channel is None:
                try:
                    channel = await self.fetch_channel(self._channel_id)
                except Exception as e:  # wrap any discord/network error
                    self.failure = RuntimeError(f"Failed to fetch channel: {e}")
                    await self.close()
                    return
            # Build a friendly display name for logs
            try:
                name = getattr(channel, "name", None) or str(self._channel_id)
                guild = getattr(getattr(channel, "guild", None), "name", None)
                if guild:
                    self.channel_display = f"{guild} / #{name}"
                else:
                    self.channel_display = f"#{name}"
            except AttributeError:
                self.channel_display = f"channel:{self._channel_id}"
            if not hasattr(channel, "history"):
                self.failure = RuntimeError(
                    "Channel does not support history() (must be a text channel)"
                )
                await self.close()
                return
            try:
                async for message in channel.history(limit=self._limit):
                    self.ids.extend(_ids_in_message(message))
            except Exception as e:  # network drop mid-scan, permissions, ...
                self.failure = RuntimeError(f"Failed to read channel history: {e}")
            finally:
                await self.close()

    client = _Collector(intents=intents, channel_id=channel_id, limit=limit)
    await client.start(token, reconnect=False)
    if client.failure is not None:
        raise client.failure
    return _dedupe(client.ids), client.channel_display


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
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == "DISCORD_TOKEN":
                        return v.strip().strip('"').strip("'")
        except OSError:
            pass
    from clippy import exits
    from clippy.utils import log

    log("Missing Discord token: set DISCORD_TOKEN in env or .env, or provide --discord-token", 5)
    raise SystemExit(exits.AUTH)
