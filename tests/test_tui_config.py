"""Tests for the TUI -> typed-config sync (v2 Stage 4b).

Skipped when the optional ``textual`` dependency is not installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

import clippy.config as cfg  # noqa: E402
from clippy.ffmpeg import EncoderParams  # noqa: E402
from clippy.models import ClippyConfig  # noqa: E402
from clippy.tui.screens.progress import _sync_encoder_params  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    monkeypatch.setattr(cfg, "_CONFIG", cfg.get_config(), raising=False)
    yield


def test_sync_encoder_params_writes_typed_config(monkeypatch):
    monkeypatch.setattr(cfg, "_CONFIG", ClippyConfig(), raising=False)
    params = EncoderParams(
        video_codec="libx264",
        cq=14,
        max_bitrate="30M",
        buf_size="30M",
        preset="fast",
        resolution="2560x1440",
        fps="30",
        audio_bitrate="256k",
        container_ext="mkv",
        container_flags="",
        gop=99,
        rc_lookahead=8,
        spatial_aq=1,
        aq_strength=5,
        temporal_aq=1,
    )

    _sync_encoder_params(params)

    enc = cfg.get_config().encoding
    assert enc.bitrate == "30M"
    assert enc.resolution == "2560x1440"
    assert enc.container_ext == "mkv"
    assert enc.audio_bitrate == "256k"
    assert enc.nvenc.cq == "14"
    assert enc.nvenc.preset == "fast"
    assert enc.nvenc.gop == "99"
    # video_codec is not modelled on ClippyConfig; kept as a module attribute.
    assert cfg.video_codec == "libx264"
