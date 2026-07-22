"""Tests for Discord ingestion — the primary source for curated channels.

This path had no coverage at all despite being the one in daily use. The
extractor is pure and tested directly; the fetch path runs against a stand-in
for discord.py so the optional dependency is not needed.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from clippy import exits
from clippy.discord_ingest import (
    _ids_in_message,
    extract_clip_ids_from_text,
    load_discord_token,
)


class TestIngestClipsWithoutDiscordPy:
    """discord.py imports lazily inside fetch_recent_clip_ids (so the URL parser
    works without it installed) — that means a missing install only ever
    surfaces there, not at ``from clippy.discord_ingest import ...``. Regression
    for a crash where that ModuleNotFoundError went uncaught instead of exiting
    cleanly with exits.USAGE.
    """

    def test_a_missing_discord_py_exits_with_the_usage_code(self, monkeypatch):
        import clippy.discord_ingest as discord_ingest
        import clippy.run as run

        async def _boom(*args, **kwargs):
            raise ModuleNotFoundError("No module named 'discord'")

        monkeypatch.setattr(discord_ingest, "fetch_recent_clip_ids", _boom)

        args = types.SimpleNamespace(
            discord=True,
            discord_channel_id=123456789012345678,
            discord_token="faketoken",
            discord_limit=None,
            max_clips=100,
        )
        with pytest.raises(SystemExit) as exc:
            run.ingest_clips(args, cid=None, token=None, window=(None, None))
        assert exc.value.code == exits.USAGE


class TestExtractClipIds:
    """Every URL shape people actually paste into a channel."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("https://clips.twitch.tv/AbcDef", ["AbcDef"]),
            ("http://clips.twitch.tv/AbcDef", ["AbcDef"]),
            ("https://www.twitch.tv/someone/clip/GhiJkl", ["GhiJkl"]),
            ("https://twitch.tv/someone/clip/Mno", ["Mno"]),
            # Phone shares: these were silently dropped.
            ("https://m.twitch.tv/someone/clip/Pqr", ["Pqr"]),
            # Embedded player links; the plain branch used to capture "embed".
            ("https://clips.twitch.tv/embed?clip=Embedded", ["Embedded"]),
        ],
    )
    def test_recognised_forms(self, text, expected):
        assert extract_clip_ids_from_text(text) == expected

    def test_ids_come_back_in_document_order(self):
        """The channel is a curated list; the top of it should win."""
        text = "one https://www.twitch.tv/a/clip/SECOND two https://clips.twitch.tv/FIRST"
        assert extract_clip_ids_from_text(text) == ["SECOND", "FIRST"]

    def test_the_same_clip_in_two_forms_counts_once(self):
        text = "https://clips.twitch.tv/Dup and https://www.twitch.tv/x/clip/Dup"
        assert extract_clip_ids_from_text(text) == ["Dup"]

    def test_query_parameters_are_not_part_of_the_id(self):
        assert extract_clip_ids_from_text("https://clips.twitch.tv/Stu?featured=true") == ["Stu"]

    def test_surrounding_punctuation_is_not_captured(self):
        assert extract_clip_ids_from_text("see <https://clips.twitch.tv/Vwx>!") == ["Vwx"]

    def test_several_clips_in_one_message(self):
        text = "https://clips.twitch.tv/One then https://clips.twitch.tv/Two"
        assert extract_clip_ids_from_text(text) == ["One", "Two"]

    @pytest.mark.parametrize("text", ["", None, "no links here", "https://youtube.com/watch?v=x"])
    def test_nothing_to_find(self, text):
        assert extract_clip_ids_from_text(text) == []

    def test_a_bare_twitch_channel_link_is_not_a_clip(self):
        assert extract_clip_ids_from_text("https://twitch.tv/someone") == []


class _Embed:
    def __init__(self, url=None, title=None, description=None):
        self.url = url
        self.title = title
        self.description = description


class _Attachment:
    def __init__(self, url):
        self.url = url


class _Message:
    def __init__(self, content="", embeds=(), attachments=()):
        self.content = content
        self.embeds = list(embeds)
        self.attachments = list(attachments)


class TestMessageScanning:
    def test_plain_content(self):
        assert _ids_in_message(_Message("https://clips.twitch.tv/A")) == ["A"]

    def test_a_link_only_in_an_embed_is_found(self):
        """A reposting bot often leaves content empty and puts the link in an embed."""
        msg = _Message("", embeds=[_Embed(url="https://clips.twitch.tv/FromEmbed")])
        assert _ids_in_message(msg) == ["FromEmbed"]

    def test_embed_description_is_scanned(self):
        msg = _Message("", embeds=[_Embed(description="watch https://clips.twitch.tv/InDesc")])
        assert _ids_in_message(msg) == ["InDesc"]

    def test_attachment_urls_are_scanned(self):
        msg = _Message("", attachments=[_Attachment("https://clips.twitch.tv/InAttach")])
        assert _ids_in_message(msg) == ["InAttach"]

    def test_a_message_with_nothing_useful(self):
        assert _ids_in_message(_Message("hello")) == []

    def test_missing_attributes_do_not_raise(self):
        assert _ids_in_message(types.SimpleNamespace()) == []


# --- fetch path, against a stand-in for discord.py --------------------------


def _install_fake_discord(
    monkeypatch,
    *,
    items=None,
    guild_name="Guild",
    channel_name="general",
    channel="build",
    fetch_error=None,
):
    """Register a minimal stand-in for discord.py and return a capture dict.

    ``channel="build"`` makes a text channel carrying *items*; pass an explicit
    object (or None) to model a non-text or unreachable channel.
    """
    captured: dict = {}

    class Intents:
        def __init__(self):
            self.message_content = False

        @staticmethod
        def default():
            return Intents()

    class _History:
        def __init__(self, entries):
            self._entries = list(entries)

        def __aiter__(self):
            async def gen():
                for entry in self._entries:
                    yield entry

            return gen()

    class Channel:
        def __init__(self, name, guild, entries):
            self.name = name
            self.guild = guild
            self._entries = entries

        def history(self, limit=None):
            captured["limit"] = limit
            return _History(self._entries)

    if channel == "build":
        guild = types.SimpleNamespace(name=guild_name) if guild_name else None
        channel = Channel(channel_name, guild, list(items or []))

    class Client:
        def __init__(self, intents=None):
            self.intents = intents

        def get_channel(self, cid):
            return channel

        async def fetch_channel(self, cid):
            if fetch_error:
                raise fetch_error
            return channel

        async def close(self):
            captured["closed"] = True

        async def start(self, token, reconnect=True):
            captured["token"] = token
            captured["reconnect"] = reconnect
            await self.on_ready()

    module = types.ModuleType("discord")
    module.Intents = Intents
    module.Client = Client
    monkeypatch.setitem(sys.modules, "discord", module)
    return captured


def _fetch(limit=50):
    from clippy.discord_ingest import fetch_recent_clip_ids

    return asyncio.run(fetch_recent_clip_ids("token", 123, limit=limit))


class TestFetchRecentClipIds:
    def test_collects_ids_across_messages_in_order(self, monkeypatch):
        _install_fake_discord(
            monkeypatch,
            items=[
                _Message("https://clips.twitch.tv/First"),
                _Message("https://m.twitch.tv/x/clip/Second"),
            ],
        )
        ids, display = _fetch()
        assert ids == ["First", "Second"]
        assert display == "Guild / #general"

    def test_duplicates_across_messages_collapse(self, monkeypatch):
        _install_fake_discord(
            monkeypatch,
            items=[
                _Message("https://clips.twitch.tv/Same"),
                _Message("https://clips.twitch.tv/Same"),
            ],
        )
        assert _fetch()[0] == ["Same"]

    def test_a_link_only_in_an_embed_is_collected(self, monkeypatch):
        _install_fake_discord(
            monkeypatch,
            items=[_Message("", embeds=[_Embed(url="https://clips.twitch.tv/Bot")])],
        )
        assert _fetch()[0] == ["Bot"]

    def test_the_scan_limit_is_passed_through(self, monkeypatch):
        captured = _install_fake_discord(monkeypatch, items=[])
        _fetch(limit=17)
        assert captured["limit"] == 17

    def test_a_channel_without_a_guild_still_gets_a_name(self, monkeypatch):
        _install_fake_discord(monkeypatch, items=[], guild_name=None)
        assert _fetch()[1] == "#general"

    def test_a_failure_to_reach_the_channel_is_raised_not_swallowed(self, monkeypatch):
        """discord.py logs exceptions raised in on_ready and carries on, so this
        used to surface as "no clips found" rather than the real reason."""
        _install_fake_discord(monkeypatch, channel=None, fetch_error=RuntimeError("403 Forbidden"))
        with pytest.raises(RuntimeError, match="Failed to fetch channel"):
            _fetch()

    def test_a_non_text_channel_is_reported(self, monkeypatch):
        _install_fake_discord(monkeypatch, channel=types.SimpleNamespace(name="voice", guild=None))
        with pytest.raises(RuntimeError, match="text channel"):
            _fetch()

    def test_a_history_failure_is_reported(self, monkeypatch):
        """A permissions error or dropped connection mid-scan must not look empty."""

        class Exploding:
            name = "general"
            guild = None

            def history(self, limit=None):
                raise RuntimeError("Missing Access")

        _install_fake_discord(monkeypatch, channel=Exploding())
        with pytest.raises(RuntimeError, match="Failed to read channel history"):
            _fetch()

    def test_the_client_is_always_closed(self, monkeypatch):
        captured = _install_fake_discord(monkeypatch, items=[])
        _fetch()
        assert captured.get("closed") is True

    def test_it_does_not_reconnect(self, monkeypatch):
        """A one-shot scan should not sit in a reconnect loop."""
        captured = _install_fake_discord(monkeypatch, items=[])
        _fetch()
        assert captured["reconnect"] is False


class TestLoadDiscordToken:
    def test_the_argument_wins(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DISCORD_TOKEN", "from-env")
        assert load_discord_token("from-arg") == "from-arg"

    def test_environment_is_next(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DISCORD_TOKEN", "from-env")
        assert load_discord_token(None) == "from-env"

    def test_dotenv_is_the_fallback(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DISCORD_TOKEN", raising=False)
        (tmp_path / ".env").write_text('DISCORD_TOKEN="from-file"\n', encoding="utf-8")
        assert load_discord_token(None) == "from-file"

    def test_a_missing_token_exits_with_the_auth_code(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DISCORD_TOKEN", raising=False)
        with pytest.raises(SystemExit) as exc:
            load_discord_token(None)
        assert exc.value.code == exits.AUTH
