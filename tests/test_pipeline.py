"""Tests for clippy.pipeline command assembly.

Regression coverage for stage_two, which referenced an undefined ``enc`` name
(a NameError that crashed the final concat on every run) until the v2 config
refinement defined the encoder params locally.
"""

from __future__ import annotations

import pytest

import clippy.pipeline as pipeline


def test_stage_two_builds_concat_command(monkeypatch, sample_clip):
    """stage_two should assemble an ffmpeg concat command without NameError."""
    captured: dict = {}

    def fake_run(cmd, prefer_shell=False, progress_cb=None):
        captured["cmd"] = cmd
        return 0, None

    monkeypatch.setattr(pipeline, "run_proc_cancellable", fake_run)
    monkeypatch.setattr(pipeline, "_sum_concat_duration", lambda idx: None)

    pipeline.stage_two([[sample_clip]])

    cmd = captured["cmd"]
    assert "-f concat" in cmd
    # Encoder params resolved from the typed config (regression: enc was undefined).
    assert "-preset " in cmd
    assert "complete_" in cmd


def test_stage_two_honors_typed_config_resolution(monkeypatch, sample_clip):
    """The concat command reflects the live typed-config encoder settings."""
    import dataclasses

    import clippy.config as cfg
    from clippy.models import ClippyConfig

    base = ClippyConfig()
    custom = base.replace(encoding=dataclasses.replace(base.encoding, resolution="1280x720"))
    monkeypatch.setattr(cfg, "_CONFIG", custom, raising=False)

    captured: dict = {}

    def fake_run(cmd, prefer_shell=False, progress_cb=None):
        captured["cmd"] = cmd
        return 0, None

    monkeypatch.setattr(pipeline, "run_proc_cancellable", fake_run)
    monkeypatch.setattr(pipeline, "_sum_concat_duration", lambda idx: None)

    pipeline.stage_two([[sample_clip]])

    assert "1280x720" in captured["cmd"]


def test_overlay_filter_scales_with_resolution():
    f1080 = pipeline._overlay_filter("Bob", "/f.ttf", "1920x1080")
    f720 = pipeline._overlay_filter("Bob", "/f.ttf", "1280x720")
    # Author text: 48px at 1080p -> 32px at 720p (48 * 720/1080).
    assert "fontsize=48" in f1080
    assert "fontsize=32" in f720
    # Avatar scaled: 128px at 1080p -> 85px at 720p.
    assert "scale=-2:128" in f1080
    assert "scale=-2:85" in f720
    # Content preserved.
    assert "text='Bob'" in f1080
    assert "clip by" in f1080


def test_overlay_filter_bad_resolution_defaults_to_1080():
    f = pipeline._overlay_filter("X", "/f.ttf", "not-a-resolution")
    assert "fontsize=48" in f  # falls back to 1080p scaling
    assert "scale=-2:128" in f


def test_encoder_falls_back_to_libx264_without_nvenc(monkeypatch):
    """No NVENC and no explicit codec choice -> CPU encoding, with a valid x264 preset."""
    import clippy.config as cfg

    monkeypatch.setattr(cfg, "video_codec", "", raising=False)
    monkeypatch.setattr(pipeline, "detect_encoder", lambda _bin: "libx264")
    monkeypatch.setattr(cfg.get_config().encoding.nvenc, "preset", "p4")

    enc = pipeline._current_encoder_params()
    assert enc.video_codec == "libx264"
    assert enc.preset == "medium"  # "p4" is NVENC-only
    assert "-c:v libx264" in enc.video_flags()


def test_explicit_codec_choice_skips_detection(monkeypatch):
    """A --preset or TUI choice wins over probing."""
    import clippy.config as cfg

    monkeypatch.setattr(cfg, "video_codec", "h264_nvenc", raising=False)
    monkeypatch.setattr(
        pipeline, "detect_encoder", lambda _bin: pytest.fail("should not probe ffmpeg")
    )
    assert pipeline._current_encoder_params().video_codec == "h264_nvenc"
