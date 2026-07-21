"""Tests for clippy.pipeline.build_concat_list — the compilation sequencing policy.

The policy this pins is the one scripts/check_sequencing.py validates by hand
against a real build:

    [intro static] (clip static [transition static])* [outro]

A static separator follows every clip and every transition, so the concat
demuxer never butts two dissimilar streams together.
"""

from __future__ import annotations

import dataclasses

import pytest

import clippy.config as cfg
import clippy.pipeline as pipeline
from clippy.models import ClipRow


def _clip(i: int) -> ClipRow:
    return ClipRow(id=f"c{i}", created_ts=0.0, author="a", avatar_url="", view_count=1, url="")


@pytest.fixture
def sequencing(monkeypatch):
    """Neutralise ffmpeg work and give the policy a known asset pool.

    ``transcode_asset`` normally re-encodes an asset and returns its cached path;
    here it just echoes the name, so the assertions read as the sequence itself.
    """
    monkeypatch.setattr(
        pipeline,
        "transcode_asset",
        lambda name, *a, **kw: (f"_trans/{name}" if name else ""),
    )
    monkeypatch.setattr(pipeline, "resolve_transition_pool", lambda **kw: ["t1.mp4", "t2.mp4"])

    def configure(**over):
        c = cfg.get_config()
        assets = dataclasses.replace(
            c.assets,
            intro=over.pop("intro", []),
            outro=over.pop("outro", []),
            static=over.pop("static", "static.mp4"),
        )
        sequencing = dataclasses.replace(
            c.sequencing,
            transition_probability=over.pop("transition_probability", 0.0),
            no_random_transitions=over.pop("no_random_transitions", False),
            transition_cooldown=over.pop("transition_cooldown", 0),
            transitions_weights=over.pop("transitions_weights", {}),
        )
        behavior = dataclasses.replace(c.behavior, skip_bad_clip=over.pop("skip_bad_clip", True))
        monkeypatch.setattr(
            cfg,
            "_CONFIG",
            dataclasses.replace(c, assets=assets, sequencing=sequencing, behavior=behavior),
        )

    return configure


def _build(results):
    return pipeline.build_concat_list(
        [c for c, _ in results], results, "/transitions", "/out", "_trans", {}, "/manifest.json"
    )


class TestCoreSequence:
    def test_every_clip_is_followed_by_a_static(self, sequencing):
        sequencing()
        lines = _build([(_clip(1), True), (_clip(2), True)])
        assert lines == [
            "file c1/c1.mp4",
            "file _trans/static.mp4",
            "file c2/c2.mp4",
            "file _trans/static.mp4",
        ]

    def test_intro_is_followed_by_a_static(self, sequencing):
        sequencing(intro=["intro.mp4"])
        lines = _build([(_clip(1), True)])
        assert lines[:2] == ["file _trans/intro.mp4", "file _trans/static.mp4"]

    def test_outro_goes_last_with_no_trailing_static(self, sequencing):
        """The static after the final clip already separates it from the outro."""
        sequencing(outro=["outro.mp4"])
        lines = _build([(_clip(1), True)])
        assert lines[-1] == "file _trans/outro.mp4"
        assert lines[-2] == "file _trans/static.mp4"

    def test_full_shape_intro_clips_outro(self, sequencing):
        sequencing(intro=["intro.mp4"], outro=["outro.mp4"])
        lines = _build([(_clip(1), True), (_clip(2), True)])
        assert lines == [
            "file _trans/intro.mp4",
            "file _trans/static.mp4",
            "file c1/c1.mp4",
            "file _trans/static.mp4",
            "file c2/c2.mp4",
            "file _trans/static.mp4",
            "file _trans/outro.mp4",
        ]

    def test_no_intro_or_outro_configured(self, sequencing):
        sequencing()
        lines = _build([(_clip(1), True)])
        assert lines == ["file c1/c1.mp4", "file _trans/static.mp4"]


class TestTransitions:
    def test_transition_is_wrapped_in_statics(self, sequencing, monkeypatch):
        """Always-on probability: clip, static, transition, static."""
        sequencing(transition_probability=1.0)
        monkeypatch.setattr(pipeline.random, "random", lambda: 0.0)
        monkeypatch.setattr(pipeline.random, "choices", lambda pool, weights, k: ["t1.mp4"])
        lines = _build([(_clip(1), True)])
        assert lines == [
            "file c1/c1.mp4",
            "file _trans/static.mp4",
            "file _trans/t1.mp4",
            "file _trans/static.mp4",
        ]

    def test_probability_zero_inserts_none(self, sequencing, monkeypatch):
        sequencing(transition_probability=0.0)
        monkeypatch.setattr(pipeline.random, "random", lambda: 0.999)
        lines = _build([(_clip(1), True)])
        assert not any("t1" in ln or "t2" in ln for ln in lines)

    def test_no_random_transitions_overrides_probability(self, sequencing, monkeypatch):
        sequencing(transition_probability=1.0, no_random_transitions=True)
        monkeypatch.setattr(pipeline.random, "random", lambda: 0.0)
        lines = _build([(_clip(1), True)])
        assert not any("t1" in ln or "t2" in ln for ln in lines)

    def test_cooldown_excludes_recent_picks(self, sequencing, monkeypatch):
        """With a cooldown of 1, the previous transition must not be offered again."""
        sequencing(transition_probability=1.0, transition_cooldown=1)
        monkeypatch.setattr(pipeline.random, "random", lambda: 0.0)
        offered: list[list[str]] = []

        def fake_choices(pool, weights, k):
            offered.append(list(pool))
            return [pool[0]]

        monkeypatch.setattr(pipeline.random, "choices", fake_choices)
        _build([(_clip(1), True), (_clip(2), True)])

        assert offered[0] == ["t1.mp4", "t2.mp4"]
        assert offered[1] == ["t2.mp4"], "the just-used transition is on cooldown"

    def test_weights_are_passed_through(self, sequencing, monkeypatch):
        sequencing(transition_probability=1.0, transitions_weights={"t1.mp4": 5.0})
        monkeypatch.setattr(pipeline.random, "random", lambda: 0.0)
        seen = {}

        def fake_choices(pool, weights, k):
            seen["weights"] = dict(zip(pool, weights))
            return [pool[0]]

        monkeypatch.setattr(pipeline.random, "choices", fake_choices)
        _build([(_clip(1), True)])
        assert seen["weights"] == {"t1.mp4": 5.0, "t2.mp4": 1.0}

    def test_all_zero_weights_fall_back_to_uniform(self, sequencing, monkeypatch):
        """Otherwise random.choices raises on a zero total and drops the transition."""
        sequencing(transition_probability=1.0, transitions_weights={"t1.mp4": 0.0, "t2.mp4": 0.0})
        monkeypatch.setattr(pipeline.random, "random", lambda: 0.0)
        seen = {}

        def fake_choices(pool, weights, k):
            seen["weights"] = list(weights)
            return [pool[0]]

        monkeypatch.setattr(pipeline.random, "choices", fake_choices)
        _build([(_clip(1), True)])
        assert seen["weights"] == [1.0, 1.0]


class TestFailedClips:
    def test_failed_clip_is_skipped_by_default(self, sequencing):
        sequencing(skip_bad_clip=True)
        lines = _build([(_clip(1), True), (_clip(2), False), (_clip(3), True)])
        assert [ln for ln in lines if "/c" in ln] == ["file c1/c1.mp4", "file c3/c3.mp4"]

    def test_a_skipped_clip_leaves_no_orphan_static(self, sequencing):
        sequencing(skip_bad_clip=True)
        lines = _build([(_clip(1), False)])
        assert lines == [], "a failed-only compilation must not emit a lone separator"

    def test_skip_disabled_stops_at_the_failure(self, sequencing):
        sequencing(skip_bad_clip=False)
        lines = _build([(_clip(1), True), (_clip(2), False), (_clip(3), True)])
        assert [ln for ln in lines if "/c" in ln] == ["file c1/c1.mp4"]


class TestAssetFailures:
    def test_an_unusable_intro_suppresses_its_static(self, sequencing, monkeypatch):
        """If the intro cannot be normalized, it must not leave a leading static.

        Only the intro fails here; static still normalizes fine, so a stray
        leading separator would be visible.
        """
        monkeypatch.setattr(
            pipeline,
            "transcode_asset",
            lambda name, *a, **kw: ("" if name == "broken.mp4" else f"_trans/{name}"),
        )
        sequencing(intro=["broken.mp4"])
        lines = _build([(_clip(1), True)])
        assert lines == ["file c1/c1.mp4", "file _trans/static.mp4"]
        assert lines[0] != "file _trans/static.mp4", "no separator before the first clip"

    def test_every_asset_failing_yields_clips_only(self, sequencing, monkeypatch):
        monkeypatch.setattr(pipeline, "transcode_asset", lambda name, *a, **kw: "")
        sequencing(intro=["intro.mp4"], outro=["outro.mp4"])
        assert _build([(_clip(1), True)]) == ["file c1/c1.mp4"]

    def test_missing_transition_pool_is_not_fatal(self, sequencing, monkeypatch):
        monkeypatch.setattr(pipeline, "resolve_transition_pool", lambda **kw: [])
        sequencing(transition_probability=1.0)
        monkeypatch.setattr(pipeline.random, "random", lambda: 0.0)
        lines = _build([(_clip(1), True)])
        assert lines == ["file c1/c1.mp4", "file _trans/static.mp4"]


class TestPolicyInvariant:
    def test_output_satisfies_the_check_sequencing_grammar(self, sequencing, monkeypatch):
        """Cross-check against the shape scripts/check_sequencing.py enforces."""
        sequencing(intro=["intro.mp4"], outro=["outro.mp4"], transition_probability=1.0)
        monkeypatch.setattr(pipeline.random, "random", lambda: 0.0)
        monkeypatch.setattr(pipeline.random, "choices", lambda pool, weights, k: [pool[0]])
        lines = _build([(_clip(i), True) for i in range(1, 4)])

        def is_static(ln):
            return ln.endswith("static.mp4")

        def is_clip(ln):
            p = ln[len("file ") :]
            return "/" in p and not p.startswith("_trans/")

        # Every clip is immediately followed by a static separator.
        for i, ln in enumerate(lines):
            if is_clip(ln):
                assert is_static(lines[i + 1]), f"clip at {i} is not followed by a static"
        # No two statics ever sit next to each other.
        for a, b in zip(lines, lines[1:]):
            assert not (is_static(a) and is_static(b)), "duplicate separator"
        assert lines[0] == "file _trans/intro.mp4"
        assert lines[-1] == "file _trans/outro.mp4"
