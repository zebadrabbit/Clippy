"""Tests for named config profiles.

A profile is a partial clippy.yaml merged over the top level, so one install can
carry per-streamer branding (intro/outro) and defaults. Precedence is
base file -> profile -> CLI flags.
"""

from __future__ import annotations

import os

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
        # The built-in "default" leads; the file's own follow in declaration order.
        assert list_profiles() == ["default", "theflood", "ninja"]
        assert list_profiles(include_default=False) == ["theflood", "ninja"]

    def test_only_the_builtin_is_listed_without_a_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert list_profiles() == ["default"]
        assert list_profiles(include_default=False) == []

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

        typed = cfg.reload_with_profile("ninja")
        assert typed.identity.broadcaster == "ninja"
        assert typed.assets.intro == ["ninja_intro.mp4"]
        # The legacy module globals track it too.
        assert cfg.get_config().identity.broadcaster == "ninja"


class TestProfileAssetFolders:
    """Per-streamer branding lives in transitions/<profile>/, shared files stay put."""

    @pytest.fixture
    def assets(self, tmp_path, monkeypatch):
        root = tmp_path / "transitions"
        (root / "theflood").mkdir(parents=True)
        for name in ("static.mp4", "intro.mp4", "transition_01.mp4", "transition_02.mp4"):
            (root / name).write_text("shared", encoding="utf-8")
        for name in ("intro.mp4", "outro.mp4", "transition_01.mp4"):
            (root / "theflood" / name).write_text("profile", encoding="utf-8")
        monkeypatch.setenv("TRANSITIONS_DIR", str(root))
        monkeypatch.chdir(tmp_path)
        return root

    def _with_profile(self, monkeypatch, name):
        import clippy.config as cfg

        monkeypatch.setattr(cfg, "active_profile", name, raising=False)

    def test_profile_asset_wins_over_the_shared_one(self, assets, monkeypatch):
        from clippy.utils import find_transition_file

        self._with_profile(monkeypatch, "theflood")
        found = find_transition_file("intro.mp4")
        assert found is not None
        assert (assets / "theflood" / "intro.mp4").samefile(found)

    def test_shared_asset_is_still_found(self, assets, monkeypatch):
        """static.mp4 is not per-streamer; it must resolve from the root."""
        from clippy.utils import find_transition_file

        self._with_profile(monkeypatch, "theflood")
        found = find_transition_file("static.mp4")
        assert found is not None
        assert (assets / "static.mp4").samefile(found)

    def test_profile_only_asset_resolves(self, assets, monkeypatch):
        from clippy.utils import find_transition_file

        self._with_profile(monkeypatch, "theflood")
        assert find_transition_file("outro.mp4") is not None

    def test_without_a_profile_only_shared_assets_resolve(self, assets, monkeypatch):
        from clippy.utils import find_transition_file

        self._with_profile(monkeypatch, "")
        found = find_transition_file("intro.mp4")
        assert found is not None
        assert (assets / "intro.mp4").samefile(found)

    def test_search_order_is_profile_then_shared(self, assets, monkeypatch):
        from clippy.utils import asset_search_dirs

        self._with_profile(monkeypatch, "theflood")
        dirs = asset_search_dirs()
        assert dirs[0].endswith("theflood")
        assert len(dirs) == 2

    def test_a_missing_profile_folder_is_skipped(self, assets, monkeypatch):
        from clippy.utils import asset_search_dirs

        self._with_profile(monkeypatch, "nobody")
        assert len(asset_search_dirs()) == 1

    def test_discovery_merges_both_folders_profile_first(self, assets, monkeypatch):
        from clippy.utils import discover_transition_files

        self._with_profile(monkeypatch, "theflood")
        found = discover_transition_files()
        # transition_01 exists in both; the profile's copy shadows the shared one.
        assert found == ["transition_01.mp4", "transition_02.mp4"]

    def test_discovery_without_a_profile_sees_only_shared(self, assets, monkeypatch):
        from clippy.utils import discover_transition_files

        self._with_profile(monkeypatch, "")
        assert discover_transition_files() == ["transition_01.mp4", "transition_02.mp4"]


class TestFontSurvivesReload:
    """Re-merging the config must not un-resolve the overlay font.

    reload_with_profile() re-reads clippy.yaml, which puts the raw relative
    "assets/fonts/Roboto-Medium.ttf" back into the globals. The resolution to an
    absolute path only ran at import, so preflight then reported the overlay font
    as missing on any run that switched profile.
    """

    def test_font_stays_resolved_across_a_reload(self, config_file):
        import clippy.config as cfg

        before = cfg.fontfile
        assert os.path.isabs(before) and os.path.exists(before)
        cfg.reload_with_profile("ninja")
        assert cfg.fontfile == before
        assert cfg.get_config().assets.fontfile == before

    def test_preflight_is_clean_after_a_reload(self, config_file):
        import clippy.config as cfg
        from clippy.preflight import _check_overlay_font

        cfg.reload_with_profile("ninja")
        assert _check_overlay_font() == []

    def test_an_existing_absolute_font_is_left_alone(self, tmp_path):
        import clippy.config as cfg

        custom = tmp_path / "Custom.ttf"
        custom.write_bytes(b"font")
        assert cfg.resolve_fontfile(str(custom)) == str(custom)

    def test_an_unknown_font_is_returned_unchanged(self):
        """So preflight can still report it rather than silently substituting."""
        import clippy.config as cfg

        assert cfg.resolve_fontfile("nope/missing.ttf") == "nope/missing.ttf"

    def test_the_packaged_font_is_the_fallback(self):
        import clippy.config as cfg

        resolved = cfg.resolve_fontfile("assets/fonts/Roboto-Medium.ttf")
        assert os.path.exists(resolved)


class TestBuiltInDefaultProfile:
    """ "default" always exists and means "no overrides"."""

    def test_it_is_listed_even_with_no_profiles_section(self, tmp_path, monkeypatch):
        path = tmp_path / "clippy.yaml"
        path.write_text(yaml.safe_dump({"identity": {"broadcaster": "solo"}}), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert list_profiles() == ["default"]

    def test_it_is_listed_first(self, config_file):
        assert list_profiles()[0] == "default"

    def test_it_can_be_excluded(self, config_file):
        assert "default" not in list_profiles(include_default=False)

    def test_applying_it_changes_nothing(self):
        assert apply_profile(CONFIG, "default") == CONFIG

    def test_it_yields_the_base_config(self, config_file):
        merged = load_merged_config(profile="default")
        assert merged["default_broadcaster"] == "basechannel"
        assert merged["intro"] == ["generic.mp4"]
        assert merged["amountOfClips"] == 12

    def test_it_overrides_an_active_profile(self, config_file):
        """active_profile is theflood; --profile default must still give the base."""
        assert load_merged_config()["default_broadcaster"] == "theflood"
        assert load_merged_config(profile="default")["default_broadcaster"] == "basechannel"

    def test_a_user_defined_default_wins(self, tmp_path, monkeypatch):
        """Someone who writes their own 'default' profile gets theirs, not the built-in."""
        data = dict(CONFIG)
        data["profiles"] = dict(CONFIG["profiles"])
        data["profiles"]["default"] = {"identity": {"broadcaster": "mine"}}
        path = tmp_path / "clippy.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(PROFILE_ENV, raising=False)
        assert load_merged_config(profile="default")["default_broadcaster"] == "mine"
        # and it is not duplicated in the listing
        assert list_profiles().count("default") == 1

    def test_default_uses_the_transitions_root(self, tmp_path, monkeypatch):
        """No profile folder lookup when the built-in default is active."""
        from clippy.utils import asset_search_dirs

        root = tmp_path / "transitions"
        (root / "theflood").mkdir(parents=True)
        monkeypatch.setenv("TRANSITIONS_DIR", str(root))
        import clippy.config as cfg

        monkeypatch.setattr(cfg, "active_profile", "default", raising=False)
        dirs = asset_search_dirs()
        assert len(dirs) == 1 and dirs[0].endswith("transitions")
