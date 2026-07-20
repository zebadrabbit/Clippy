"""Tests for main.apply_cli_overrides — the single CLI->typed-config writer (v2 Stage 3)."""

from __future__ import annotations

import argparse

import pytest

import clippy.config as cfg
import clippy.run as main_mod


def _args(**overrides):
    """Build an argparse.Namespace with the attributes apply_cli_overrides reads."""
    base = dict(
        amountOfClips=12,
        amountOfCompilations=2,
        reactionThreshold=0,
        bitrate=None,
        quality=None,
        format=None,
        cq=None,
        nvenc_preset=None,
        gop=None,
        rc_lookahead=None,
        spatial_aq=None,
        temporal_aq=None,
        aq_strength=None,
        resolution=None,
        fps=None,
        audio_bitrate=None,
        yt_format=None,
        cache_dir=None,
        output_dir=None,
        intro=None,
        outro=None,
        transition=None,
        transition_prob=None,
        no_random_transitions=False,
        no_overlay=False,
        rebuild=False,
        skip_bad_clip=False,
        max_concurrency=None,
        transitions_dir=None,
        discord=False,
        broadcaster="somechannel",
    )
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    """Snapshot/restore the config singleton (and the codec global) between tests."""
    monkeypatch.setattr(cfg, "_CONFIG", cfg.get_config(), raising=False)
    monkeypatch.setattr(
        cfg, "video_codec", getattr(cfg, "video_codec", "h264_nvenc"), raising=False
    )
    yield


def test_overrides_flow_into_typed_config():
    main_mod.apply_cli_overrides(
        _args(
            amountOfClips=5,
            amountOfCompilations=3,
            reactionThreshold=10,
            bitrate="20M",
            format="mkv",
            cq="16",
            nvenc_preset="fast",
            resolution="1280x720",
            fps="30",
            no_overlay=True,
            rebuild=True,
            max_concurrency=8,
            transition_prob=0.9,
        )
    )

    c = cfg.get_config()
    assert c.selection.clips_per_compilation == 5
    assert c.selection.compilations == 3
    assert c.selection.min_views == 10
    assert c.encoding.bitrate == "20M"
    assert c.encoding.resolution == "1280x720"
    assert c.encoding.fps == "30"
    assert c.encoding.container_ext == "mkv"
    assert c.encoding.container_flags == ""
    # Previously dead in the CLI path (only set main's globals) — now live.
    assert c.encoding.nvenc.cq == "16"
    assert c.encoding.nvenc.preset == "fast"
    assert c.behavior.enable_overlay is False
    assert c.behavior.rebuild is True
    assert c.behavior.max_concurrency == 8
    assert c.sequencing.transition_probability == 0.9


def test_quality_maps_to_bitrate_when_not_explicit():
    main_mod.apply_cli_overrides(_args(quality="max"))
    assert cfg.get_config().encoding.bitrate == "16M"


def test_explicit_bitrate_beats_quality():
    main_mod.apply_cli_overrides(_args(quality="max", bitrate="25M"))
    assert cfg.get_config().encoding.bitrate == "25M"


def test_transition_single_override_sets_pool():
    main_mod.apply_cli_overrides(_args(transition="my_transition.mp4"))
    assert cfg.get_config().assets.transitions == ["my_transition.mp4"]


def test_preset_sets_encoding_baseline():
    main_mod.apply_cli_overrides(_args(encoding_preset="discord_friendly"))
    c = cfg.get_config()
    assert c.encoding.resolution == "1280x720"
    assert c.encoding.fps == "30"
    assert c.encoding.bitrate == "8M"
    assert c.encoding.audio_bitrate == "128k"
    assert c.encoding.nvenc.cq == "23"


def test_explicit_flags_beat_preset():
    main_mod.apply_cli_overrides(
        _args(encoding_preset="discord_friendly", resolution="1920x1080", bitrate="20M", cq="18")
    )
    c = cfg.get_config()
    assert c.encoding.resolution == "1920x1080"
    assert c.encoding.bitrate == "20M"
    assert c.encoding.nvenc.cq == "18"
    # Untouched preset values still apply.
    assert c.encoding.fps == "30"


def test_cpu_only_preset_switches_codec():
    main_mod.apply_cli_overrides(_args(encoding_preset="cpu_only"))
    assert cfg.video_codec == "libx264"


def test_unknown_preset_exits():
    with pytest.raises(SystemExit):
        main_mod.apply_cli_overrides(_args(encoding_preset="does_not_exist"))
