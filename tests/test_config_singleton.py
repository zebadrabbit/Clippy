"""Tests for the single-source-of-truth config contract.

Stage 1 of the v2 config refinement: the typed ``ClippyConfig`` singleton is the
authoritative store. Reads go through it, and legacy-global overrides (applied by
the CLI path) are folded back into it via ``refresh_from_globals()``.
"""

from __future__ import annotations

import dataclasses

import clippy.config as cfg
from clippy.models import ClippyConfig
from clippy.utils import _cfg_get


def test_cfg_get_reads_from_typed_config(monkeypatch):
    """_cfg_get should prefer the typed config over stale module globals."""
    base = ClippyConfig()
    custom = base.replace(encoding=dataclasses.replace(base.encoding, bitrate="99M"))
    monkeypatch.setattr(cfg, "_CONFIG", custom, raising=False)

    assert _cfg_get("bitrate") == "99M"


def test_cfg_get_falls_back_to_globals_for_unmodelled_keys(monkeypatch):
    """Values not modelled on ClippyConfig (e.g. binaries) come from the module."""
    monkeypatch.setattr(cfg, "ffmpeg", "/custom/ffmpeg", raising=False)
    assert _cfg_get("ffmpeg") == "/custom/ffmpeg"


def test_refresh_from_globals_folds_cli_override(monkeypatch):
    """A CLI-style global mutation is reconciled into the typed config."""
    # Snapshot the current singleton so monkeypatch restores it after the test.
    monkeypatch.setattr(cfg, "_CONFIG", cfg.get_config(), raising=False)
    monkeypatch.setattr(cfg, "bitrate", "77M", raising=False)
    monkeypatch.setattr(cfg, "cq", "12", raising=False)

    cfg.refresh_from_globals()

    active = cfg.get_config()
    assert active.encoding.bitrate == "77M"
    assert active.encoding.nvenc.cq == "12"
    # And the read seam now reflects it too.
    assert _cfg_get("bitrate") == "77M"
