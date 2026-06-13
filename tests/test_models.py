"""Tests for clippy.models — ClippyConfig and ClipRow dataclasses."""

from __future__ import annotations

import pytest

from clippy.config_loader import DEFAULTS
from clippy.models import (
    ClippyConfig,
    EncodingConfig,
)


class TestClipRow:
    def test_field_access(self, sample_clip):
        assert sample_clip.id == "TestClip123"
        assert sample_clip.author == "testuser"
        assert sample_clip.view_count == 42

    def test_positional_index_compat(self, sample_clip):
        """ClipRow[n] should work for backwards compat."""
        assert sample_clip[0] == "TestClip123"
        assert sample_clip[1] == 1700000000.0
        assert sample_clip[2] == "testuser"
        assert sample_clip[3] == "https://example.com/avatar.png"
        assert sample_clip[4] == 42
        assert sample_clip[5] == "https://clips.twitch.tv/TestClip123"

    def test_index_out_of_range(self, sample_clip):
        with pytest.raises(IndexError):
            _ = sample_clip[6]


class TestClippyConfig:
    def test_from_defaults(self, default_config):
        """Config from pure defaults should have expected values."""
        assert default_config.encoding.bitrate == "12M"
        assert default_config.encoding.fps == "60"
        assert default_config.encoding.resolution == "1920x1080"
        assert default_config.encoding.nvenc.cq == "19"
        assert default_config.selection.clips_per_compilation == 12
        assert default_config.selection.compilations == 2
        assert default_config.selection.min_views == 0
        assert default_config.sequencing.transition_mode == "explicit"
        assert default_config.sequencing.transition_exclude == []
        assert default_config.behavior.max_concurrency == 4
        assert default_config.behavior.skip_bad_clip is True

    def test_from_merged_dict_custom_values(self):
        d = dict(DEFAULTS)
        d["bitrate"] = "20M"
        d["amountOfClips"] = 8
        d["reactionThreshold"] = 10
        d["cq"] = "16"
        cfg = ClippyConfig.from_merged_dict(d)
        assert cfg.encoding.bitrate == "20M"
        assert cfg.selection.clips_per_compilation == 8
        assert cfg.selection.min_views == 10
        assert cfg.encoding.nvenc.cq == "16"

    def test_to_flat_dict_roundtrip(self, default_config):
        flat = default_config.to_flat_dict()
        assert flat["bitrate"] == "12M"
        assert flat["amountOfClips"] == 12
        assert flat["reactionThreshold"] == 0
        assert flat["nvenc_preset"] == "slow"
        assert isinstance(flat["intro"], list)
        assert isinstance(flat["transitions"], list)

    def test_replace(self, default_config):
        new_enc = EncodingConfig(bitrate="20M")
        new_cfg = default_config.replace(encoding=new_enc)
        assert new_cfg.encoding.bitrate == "20M"
        # Original unchanged
        assert default_config.encoding.bitrate == "12M"

    def test_discord_channel_id_none(self):
        d = dict(DEFAULTS)
        d["discord_channel_id"] = None
        cfg = ClippyConfig.from_merged_dict(d)
        assert cfg.discord.channel_id is None

    def test_discord_channel_id_set(self):
        d = dict(DEFAULTS)
        d["discord_channel_id"] = 123456789
        cfg = ClippyConfig.from_merged_dict(d)
        assert cfg.discord.channel_id == 123456789

    def test_flat_dict_has_all_expected_keys(self, default_config):
        flat = default_config.to_flat_dict()
        expected_keys = {
            "bitrate",
            "audio_bitrate",
            "fps",
            "resolution",
            "container_ext",
            "container_flags",
            "yt_format",
            "nvenc_preset",
            "cq",
            "gop",
            "rc_lookahead",
            "aq_strength",
            "spatial_aq",
            "temporal_aq",
            "amountOfClips",
            "amountOfCompilations",
            "reactionThreshold",
            "transition_probability",
            "no_random_transitions",
            "transition_mode",
            "transition_exclude",
            "transitions_weights",
            "transition_cooldown",
            "silence_static",
            "audio_normalize_transitions",
            "cache",
            "output",
            "max_concurrency",
            "skip_bad_clip",
            "rebuild",
            "enable_overlay",
            "transitions_rebuild",
            "fontfile",
            "static",
            "intro",
            "outro",
            "transitions",
            "discord_channel_id",
            "discord_message_limit",
            "default_broadcaster",
        }
        assert expected_keys.issubset(flat.keys())
