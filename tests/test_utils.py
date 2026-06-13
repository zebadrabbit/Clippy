"""Tests for clippy.utils transition discovery and selection."""

from __future__ import annotations

import dataclasses

import clippy.config as cfg
from clippy.models import ClippyConfig
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
        # Drive the resolver through the typed config (the single source of truth).
        base = ClippyConfig()
        custom = base.replace(
            assets=dataclasses.replace(
                base.assets, transitions=["custom_pick.mp4", "transition_01.mp4"]
            ),
            sequencing=dataclasses.replace(
                base.sequencing,
                transition_mode="hybrid",
                transition_exclude=["transition_02.mp4"],
            ),
        )
        monkeypatch.setattr(cfg, "_CONFIG", custom, raising=False)

        assert resolve_transition_pool(str(tmp_path)) == [
            "custom_pick.mp4",
            "transition_01.mp4",
            "transition_03.mp4",
        ]
