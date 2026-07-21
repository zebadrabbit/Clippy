"""Tests for clippy.run.filter_and_expand — min-views filtering, auto-expand, nostalgia.

This is the clip-selection core: it decides which clips end up in a compilation
and how far back Clippy reaches to find them.
"""

from __future__ import annotations

import argparse
import dataclasses

import pytest

import clippy.config as cfg
import clippy.run as run_mod


def _clip(clip_id: str, views: int = 100) -> dict:
    return {"id": clip_id, "view_count": views}


def _args(**overrides):
    base = dict(
        amountOfClips=4,
        amountOfCompilations=1,
        max_clips=100,
        target_duration=0,
        auto_expand=False,
        no_auto_expand=False,
        expand_step_days=7,
        max_lookback_days=90,
        nostalgia=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


WINDOW = ("2025-07-01T00:00:00Z", "2025-07-08T00:00:00Z")


@pytest.fixture(autouse=True)
def _min_views(monkeypatch):
    """Default to no view floor; individual tests raise it."""

    def _set(n: int) -> None:
        c = cfg.get_config()
        monkeypatch.setattr(
            cfg,
            "_CONFIG",
            dataclasses.replace(c, selection=dataclasses.replace(c.selection, min_views=n)),
        )

    _set(0)
    return _set


def _call(clips, args):
    return run_mod.filter_and_expand(clips, args, "cid", "token", "bid", WINDOW)


class TestMinViews:
    def test_filters_below_threshold(self, _min_views):
        _min_views(50)
        filtered, _ = _call([_clip("a", 100), _clip("b", 10), _clip("c", 50)], _args())
        assert [c["id"] for c in filtered] == ["a", "c"]  # boundary is inclusive

    def test_no_survivors_without_auto_expand_exits(self, _min_views):
        _min_views(1000)
        with pytest.raises(SystemExit):
            _call([_clip("a", 10)], _args())


class TestAutoExpand:
    def test_reaches_back_until_target_is_met(self, monkeypatch):
        """Two clips in window, target of 4 -> keep fetching earlier segments."""
        segments = [[_clip("old1")], [_clip("old2")], [_clip("old3")]]
        calls: list[tuple[str, str]] = []

        def fake_fetch(*, started_at, ended_at, **_kw):
            calls.append((started_at, ended_at))
            return segments.pop(0) if segments else []

        monkeypatch.setattr(run_mod, "fetch_clips", fake_fetch)
        filtered, window = _call(
            [_clip("new1"), _clip("new2")], _args(auto_expand=True, amountOfClips=4)
        )

        assert [c["id"] for c in filtered] == ["new1", "new2", "old1", "old2"]
        assert len(calls) == 2, "should stop as soon as the target is reached"
        # Each segment walks strictly backwards from the previous start.
        assert calls[0][1] == WINDOW[0]
        assert calls[1][1] == calls[0][0]
        # The reported window start moves back to match what was actually searched.
        assert window[0] < WINDOW[0]
        assert window[1] == WINDOW[1]

    def test_dedupes_clips_already_held(self, monkeypatch):
        monkeypatch.setattr(run_mod, "fetch_clips", lambda **_kw: [_clip("dup"), _clip("fresh")])
        filtered, _ = _call([_clip("dup")], _args(auto_expand=True, amountOfClips=3))
        assert [c["id"] for c in filtered].count("dup") == 1
        assert "fresh" in [c["id"] for c in filtered]

    def test_stops_at_max_lookback(self, monkeypatch):
        """An unreachable target must not loop forever."""
        calls = []

        def fake_fetch(**_kw):
            calls.append(1)
            return []

        monkeypatch.setattr(run_mod, "fetch_clips", fake_fetch)
        filtered, _ = _call(
            [_clip("only")],
            _args(auto_expand=True, amountOfClips=99, expand_step_days=7, max_lookback_days=28),
        )
        assert [c["id"] for c in filtered] == ["only"]
        # The lower bound matters: filter_and_expand swallows exceptions, so a
        # zero-call run would otherwise pass this test without expanding at all.
        assert 1 <= len(calls) <= 5, "28 days of lookback in 7-day steps"

    def test_no_auto_expand_flag_wins(self, monkeypatch):
        monkeypatch.setattr(run_mod, "fetch_clips", lambda **_kw: pytest.fail("should not expand"))
        filtered, window = _call(
            [_clip("a")], _args(auto_expand=True, no_auto_expand=True, amountOfClips=10)
        )
        assert [c["id"] for c in filtered] == ["a"]
        assert window == WINDOW

    def test_target_duration_drives_the_target(self, monkeypatch):
        """10 minutes at ~30s per clip = 20 clips, not amountOfClips."""
        fetched = []

        def fake_fetch(**_kw):
            fetched.append(1)
            return [_clip(f"x{len(fetched)}")]

        monkeypatch.setattr(run_mod, "fetch_clips", fake_fetch)
        filtered, _ = _call(
            [_clip("a")],
            _args(auto_expand=True, amountOfClips=2, target_duration=10, max_lookback_days=365),
        )
        assert len(filtered) == 20


class TestNostalgia:
    def test_mixes_in_older_clips_without_growing_the_set(self, monkeypatch):
        monkeypatch.setattr(
            run_mod, "fetch_clips", lambda **_kw: [_clip("old1"), _clip("old2"), _clip("old3")]
        )
        current = [_clip(f"n{i}") for i in range(4)]
        filtered, _ = _call(current, _args(nostalgia=True, amountOfClips=4))

        ids = [c["id"] for c in filtered]
        assert len(ids) == 4, "nostalgia replaces clips, it does not extend the set"
        assert any(i.startswith("old") for i in ids)

    def test_skips_when_older_clips_are_all_duplicates(self, monkeypatch):
        monkeypatch.setattr(run_mod, "fetch_clips", lambda **_kw: [_clip("n0")])
        filtered, _ = _call([_clip("n0")], _args(nostalgia=True, amountOfClips=4))
        assert [c["id"] for c in filtered] == ["n0"]

    def test_fetch_failure_is_not_fatal(self, monkeypatch):
        """A Helix outage must not lose the clips we already have."""
        import requests

        def boom(**_kw):
            raise requests.RequestException("helix is down")

        monkeypatch.setattr(run_mod, "fetch_clips", boom)
        filtered, _ = _call([_clip("a")], _args(nostalgia=True))
        assert [c["id"] for c in filtered] == ["a"]


class TestErrorsAreNotSwallowed:
    """Recoverable conditions are logged; bugs must surface.

    filter_and_expand used to catch bare Exception, so an AttributeError from a
    refactor looked identical to "the window held no clips" -- the same failure
    mode that let the broken smoke test pass for months.
    """

    def test_network_failure_is_recoverable(self, monkeypatch):
        import requests

        def flaky(**_kw):
            raise requests.RequestException("helix timeout")

        monkeypatch.setattr(run_mod, "fetch_clips", flaky)
        filtered, _ = _call([_clip("a")], _args(auto_expand=True, amountOfClips=10))
        assert [c["id"] for c in filtered] == ["a"], "keeps what it already had"

    def test_malformed_clip_data_is_recoverable(self, monkeypatch):
        monkeypatch.setattr(run_mod, "fetch_clips", lambda **_kw: [{"id": "x", "view_count": "??"}])
        filtered, _ = _call([_clip("a")], _args(auto_expand=True, amountOfClips=10))
        assert [c["id"] for c in filtered] == ["a"]

    def test_a_programming_error_propagates(self, monkeypatch):
        def buggy(**_kw):
            raise AttributeError("'tuple' object has no attribute 'id'")

        monkeypatch.setattr(run_mod, "fetch_clips", buggy)
        with pytest.raises(AttributeError):
            _call([_clip("a")], _args(auto_expand=True, amountOfClips=10))

    def test_a_programming_error_in_nostalgia_propagates(self, monkeypatch):
        def buggy(**_kw):
            raise AttributeError("boom")

        monkeypatch.setattr(run_mod, "fetch_clips", buggy)
        with pytest.raises(AttributeError):
            _call([_clip("a")], _args(nostalgia=True))
