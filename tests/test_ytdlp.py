"""Tests for clippy.ytdlp — yt-dlp configuration and command builder."""

from __future__ import annotations

import pytest

from clippy.ytdlp import YTDLP_PRESETS, YtDlpConfig, ytdlp_from_preset


class TestYtDlpConfig:
    def test_to_command_basic(self):
        cfg = YtDlpConfig()
        cmd = cfg.to_command("https://example.com/clip", "./cache/clip.mp4")
        assert cmd[0] == "yt-dlp"
        assert "https://example.com/clip" in cmd
        assert "./cache/clip.mp4" in cmd
        assert "--retries" in cmd

    def test_to_command_custom_binary(self):
        cfg = YtDlpConfig(binary="/usr/local/bin/yt-dlp")
        cmd = cfg.to_command("https://example.com", "out.mp4")
        assert cmd[0] == "/usr/local/bin/yt-dlp"

    def test_from_config(self):
        cfg = YtDlpConfig.from_config(
            ytdl_binary="/custom/yt-dlp",
            ffmpeg_path="/custom/ffmpeg",
        )
        assert cfg.binary == "/custom/yt-dlp"
        assert cfg.ffmpeg_location == "/custom/ffmpeg"

    def test_with_overrides(self):
        cfg = YtDlpConfig()
        new = cfg.with_overrides(retries=10, merge_format="mkv")
        assert new.retries == 10
        assert new.merge_format == "mkv"
        assert cfg.retries == 5  # original unchanged

    def test_extra_args(self):
        cfg = YtDlpConfig(extra_args=["--cookies", "cookies.txt"])
        cmd = cfg.to_command("https://example.com", "out.mp4")
        assert "--cookies" in cmd
        assert "cookies.txt" in cmd


class TestYtDlpPresets:
    def test_presets_exist(self):
        assert "twitch_1080p" in YTDLP_PRESETS
        assert "twitch_720p" in YTDLP_PRESETS
        assert "twitch_source" in YTDLP_PRESETS

    def test_from_preset_valid(self):
        cfg = ytdlp_from_preset("twitch_1080p")
        assert "1080" in cfg.format_spec

    def test_from_preset_invalid(self):
        with pytest.raises(KeyError, match="Unknown yt-dlp preset"):
            ytdlp_from_preset("nonexistent")

    def test_720p_format(self):
        cfg = ytdlp_from_preset("twitch_720p")
        assert "720" in cfg.format_spec

    def test_source_format(self):
        cfg = ytdlp_from_preset("twitch_source")
        assert "bestvideo+bestaudio" in cfg.format_spec
