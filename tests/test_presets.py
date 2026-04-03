"""Tests for clippy.presets — encoding presets."""

from __future__ import annotations

import pytest

from clippy.presets import PRESETS, from_preset, list_presets, preset_names


class TestPresets:
    def test_all_presets_exist(self):
        assert len(PRESETS) >= 5

    def test_preset_names(self):
        names = preset_names()
        assert "youtube_1080p60" in names
        assert "discord_friendly" in names
        assert "archive_hq" in names
        assert "quick_preview" in names
        assert "cpu_only" in names

    def test_list_presets_returns_tuples(self):
        items = list_presets()
        assert all(isinstance(name, str) and isinstance(desc, str) for name, desc in items)
        assert len(items) == len(PRESETS)

    def test_from_preset_valid(self):
        enc = from_preset("youtube_1080p60")
        assert enc.resolution == "1920x1080"
        assert enc.fps == "60"
        assert enc.video_codec == "h264_nvenc"

    def test_from_preset_invalid(self):
        with pytest.raises(KeyError, match="Unknown preset"):
            from_preset("nonexistent_preset")

    def test_from_preset_returns_copy(self):
        """Modifying the returned preset should not affect the original."""
        enc1 = from_preset("discord_friendly")
        enc2 = from_preset("discord_friendly")
        enc1_modified = enc1.with_overrides(cq=30)
        assert enc2.cq != 30  # original unchanged

    def test_cpu_only_uses_libx264(self):
        enc = from_preset("cpu_only")
        assert enc.video_codec == "libx264"

    def test_discord_friendly_720p(self):
        enc = from_preset("discord_friendly")
        assert enc.resolution == "1280x720"
        assert enc.fps == "30"

    def test_archive_hq_mkv(self):
        enc = from_preset("archive_hq")
        assert enc.container_ext == "mkv"

    def test_each_preset_has_name_and_description(self):
        for name, preset in PRESETS.items():
            assert preset.name == name
            assert len(preset.description) > 0
