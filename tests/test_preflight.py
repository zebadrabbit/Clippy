"""Tests for clippy.preflight — friendly setup checks (v2 Track 2)."""

from __future__ import annotations

import clippy.config as cfg
from clippy import preflight


def _titles(issues):
    return " | ".join(i.title for i in issues)


def test_missing_twitch_credentials(monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)
    monkeypatch.delenv("TWITCH_CLIENT_SECRET", raising=False)
    issues = preflight.run_preflight(require_transitions=False)
    creds = [i for i in issues if "Twitch credentials" in i.title]
    assert creds and creds[0].level == "error"
    assert "clippy setup" in creds[0].fix


def test_present_credentials_pass(monkeypatch):
    monkeypatch.setenv("TWITCH_CLIENT_ID", "abc")
    monkeypatch.setenv("TWITCH_CLIENT_SECRET", "def")
    issues = preflight.run_preflight(require_transitions=False)
    assert not any("Twitch credentials" in i.title for i in issues)


def test_discord_mode_checks_token(monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    issues = preflight.run_preflight(discord_mode=True, require_transitions=False)
    assert any("Discord bot token" in i.title for i in issues)
    # Twitch creds are not required in discord mode
    assert not any("Twitch credentials" in i.title for i in issues)


def test_missing_ffmpeg_is_error(monkeypatch):
    monkeypatch.setattr(cfg, "ffmpeg", "definitely-not-a-real-binary-xyz", raising=False)
    issues = preflight.run_preflight(require_credentials=False, require_transitions=False)
    ff = [i for i in issues if i.title.startswith("ffmpeg not found")]
    assert ff and ff[0].level == "error"


def test_missing_ytdlp_is_error(monkeypatch):
    monkeypatch.setattr(cfg, "youtubeDl", "definitely-not-a-real-binary-xyz", raising=False)
    issues = preflight.run_preflight(require_credentials=False, require_transitions=False)
    yd = [i for i in issues if i.title.startswith("yt-dlp not found")]
    assert yd and yd[0].level == "error"


def test_missing_static_transition(monkeypatch, tmp_path):
    monkeypatch.setattr("clippy.utils.resolve_transitions_dir", lambda: str(tmp_path))
    issues = preflight.run_preflight(require_credentials=False)
    assert any("static.mp4" in i.title for i in issues)


def test_present_static_transition_passes(monkeypatch, tmp_path):
    (tmp_path / "static.mp4").write_bytes(b"")
    monkeypatch.setattr("clippy.utils.resolve_transitions_dir", lambda: str(tmp_path))
    issues = preflight.run_preflight(require_credentials=False)
    assert not any("static.mp4" in i.title for i in issues)
    assert not any("Transitions folder" in i.title for i in issues)


def test_report_returns_true_on_error(monkeypatch):
    logged = []
    issues = [preflight.Issue("error", "boom", "do the thing")]
    assert preflight.report(issues, log=lambda msg, level=0: logged.append(msg)) is True
    assert any("boom" in m for m in logged)


def test_report_returns_false_when_only_warnings():
    issues = [preflight.Issue("warning", "heads up", "optional fix")]
    assert preflight.report(issues, log=lambda msg, level=0: None) is False
