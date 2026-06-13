"""Tests for clippy.utils transition discovery and selection."""

from __future__ import annotations

import clippy.config as cfg
from clippy.utils import discover_transition_files, resolve_transition_pool


class TestTransitionResolver:
    def test_discover_transition_files_filters_by_prefix(self, tmp_path, monkeypatch):
        (tmp_path / "transition_01.mp4").write_text("", encoding="utf-8")
        (tmp_path / "transition_bonus.mov").write_text("", encoding="utf-8")
        (tmp_path / "intro.mp4").write_text("", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("", encoding="utf-8")

        monkeypatch.setenv("TRANSITIONS_DIR", str(tmp_path))

        assert discover_transition_files(str(tmp_path)) == [
            "transition_01.mp4",
            "transition_bonus.mov",
        ]

    def test_resolve_transition_pool_hybrid_and_exclude(self, tmp_path, monkeypatch):
        for name in [
            "transition_01.mp4",
            "transition_02.mp4",
            "transition_03.mp4",
            "custom_pick.mp4",
        ]:
            (tmp_path / name).write_text("", encoding="utf-8")

        monkeypatch.setenv("TRANSITIONS_DIR", str(tmp_path))
        monkeypatch.setattr(
            cfg, "transitions", ["custom_pick.mp4", "transition_01.mp4"], raising=False
        )
        monkeypatch.setattr(cfg, "transition_mode", "hybrid", raising=False)
        monkeypatch.setattr(cfg, "transition_exclude", ["transition_02.mp4"], raising=False)

        assert resolve_transition_pool(str(tmp_path)) == [
            "custom_pick.mp4",
            "transition_01.mp4",
            "transition_03.mp4",
        ]
