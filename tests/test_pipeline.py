"""Tests for clippy.pipeline command assembly.

Regression coverage for stage_two, which referenced an undefined ``enc`` name
(a NameError that crashed the final concat on every run) until the v2 config
refinement defined the encoder params locally.
"""

from __future__ import annotations

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
