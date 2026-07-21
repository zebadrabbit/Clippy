"""Tests for named config profiles.

A profile is a partial clippy.yaml merged over the top level, so one install can
carry per-streamer branding (intro/outro) and defaults. Precedence is
base file -> profile -> CLI flags.
"""

from __future__ import annotations

import pytest
import yaml

from clippy.config_loader import (
    PROFILE_ENV,
    apply_profile,
    list_profiles,
    load_merged_config,
    resolve_profile_name,
)

CONFIG = {
    "identity": {"broadcaster": "basechannel"},
    "selection": {"clips_per_compilation": 12, "compilations": 2, "min_views": 1},
    "assets": {"static": "static.mp4", "intro": ["generic.mp4"]},
    "active_profile": "theflood",
    "profiles": {
        "theflood": {
            "identity": {"broadcaster": "theflood"},
            "assets": {"intro": ["intro_theflood.mp4"], "outro": ["outro_theflood.mp4"]},
            "selection": {"clips_per_compilation": 20},
        },
        "ninja": {
            "identity": {"broadcaster": "ninja"},
            "assets": {"intro": ["ninja_intro.mp4"]},
        },
    },
}


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "clippy.yaml"
    # sort_keys=False so the file preserves declaration order, like the wizard writes it.
    path.write_text(yaml.safe_dump(CONFIG, sort_keys=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    return path


class TestApplyProfile:
    def test_profile_values_win(self):
        merged = apply_profile(CONFIG, "theflood")
        assert merged["identity"]["broadcaster"] == "theflood"
        assert merged["assets"]["intro"] == ["intro_theflood.mp4"]

    def test_unset_keys_survive_the_merge(self):
        """A profile that only sets intro must not wipe the shared static."""
        merged = apply_profile(CONFIG, "ninja")
        assert merged["assets"]["static"] == "static.mp4"
        assert merged["assets"]["intro"] == ["ninja_intro.mp4"]

    def test_sections_the_profile_omits_keep_base_values(self):
        merged = apply_profile(CONFIG, "ninja")
        assert merged["selection"]["clips_per_compilation"] == 12

    def test_unknown_profile_is_ignored(self):
        assert apply_profile(CONFIG, "nope") == CONFIG

    def test_no_profile_is_a_no_op(self):
        assert apply_profile(CONFIG, None) == CONFIG

    def test_the_base_document_is_not_mutated(self):
        apply_profile(CONFIG, "theflood")
        assert CONFIG["identity"]["broadcaster"] == "basechannel"


class TestProfileSelection:
    def test_explicit_name_beats_everything(self):
        env = {PROFILE_ENV: "ninja"}
        assert resolve_profile_name(CONFIG, "theflood", env) == "theflood"

    def test_environment_beats_the_file_default(self):
        assert resolve_profile_name(CONFIG, None, {PROFILE_ENV: "ninja"}) == "ninja"

    def test_file_default_is_the_fallback(self):
        assert resolve_profile_name(CONFIG, None, {}) == "theflood"

    def test_none_when_nothing_is_set(self):
        assert resolve_profile_name({"profiles": {}}, None, {}) is None


class TestLoadMergedConfig:
    def test_active_profile_applies_by_default(self, config_file):
        merged = load_merged_config()
        assert merged["default_broadcaster"] == "theflood"
        assert merged["intro"] == ["intro_theflood.mp4"]
        assert merged["amountOfClips"] == 20

    def test_explicit_profile_overrides_the_active_one(self, config_file):
        merged = load_merged_config(profile="ninja")
        assert merged["default_broadcaster"] == "ninja"
        assert merged["intro"] == ["ninja_intro.mp4"]
        # ninja does not set a clip count, so the base value stands.
        assert merged["amountOfClips"] == 12

    def test_environment_selects_a_profile(self, config_file, monkeypatch):
        monkeypatch.setenv(PROFILE_ENV, "ninja")
        assert load_merged_config()["default_broadcaster"] == "ninja"

    def test_list_profiles_preserves_file_order(self, config_file):
        assert list_profiles() == ["theflood", "ninja"]

    def test_list_profiles_is_empty_without_a_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert list_profiles() == []

    def test_a_config_without_profiles_still_loads(self, tmp_path, monkeypatch):
        path = tmp_path / "clippy.yaml"
        path.write_text(
            yaml.safe_dump({"identity": {"broadcaster": "solo"}}, sort_keys=False), encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        assert load_merged_config()["default_broadcaster"] == "solo"


class TestReloadWithProfile:
    def test_switching_rebuilds_the_typed_config(self, config_file, monkeypatch):
        import clippy.config as cfg

        original = cfg._merged
        try:
            typed = cfg.reload_with_profile("ninja")
            assert typed.identity.broadcaster == "ninja"
            assert typed.assets.intro == ["ninja_intro.mp4"]
            # The legacy module globals track it too.
            assert cfg.get_config().identity.broadcaster == "ninja"
        finally:
            cfg._merged = original
            cfg.refresh_from_globals()
