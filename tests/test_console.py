"""Tests for the `clippy` console entry point dispatch (v2 Track 3)."""

from __future__ import annotations

import pytest

import clippy.run as run


def test_version_subcommand(capsys):
    run.console_main(["version"])
    assert "Clippy" in capsys.readouterr().out


def test_setup_dispatch(monkeypatch):
    called = {}
    monkeypatch.setattr("clippy.wizard.main", lambda *a, **k: called.setdefault("setup", True))
    run.console_main(["setup"])
    assert called.get("setup") is True


def test_tui_dispatch(monkeypatch):
    pytest.importorskip("textual")
    called = {}
    monkeypatch.setattr("clippy.tui.app.run_tui", lambda *a, **k: called.setdefault("tui", True))
    run.console_main(["tui"])
    assert called.get("tui") is True


def test_cli_fallthrough(monkeypatch):
    """Non-subcommand args fall through to the CLI orchestration."""
    called = {}
    monkeypatch.setattr(run, "main", lambda: called.setdefault("main", True))
    run.console_main(["--broadcaster", "somechannel"])
    assert called.get("main") is True


def test_bare_invocation_runs_cli(monkeypatch):
    """`clippy` with no args still runs the CLI (after any first-run hint)."""
    called = {}
    monkeypatch.setattr(run, "main", lambda: called.setdefault("main", True))
    monkeypatch.setattr(run, "_is_first_run", lambda: False)
    run.console_main([])
    assert called.get("main") is True
