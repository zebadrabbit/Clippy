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


def _eval_ffmpeg_expr(expr: str, t: float) -> float:
    """Evaluate the subset of ffmpeg expression syntax used by the credit motion.

    ``if`` is a Python keyword and cannot be called, so it is renamed before
    evaluation. Both branches are evaluated eagerly, which is harmless for these
    expressions.
    """
    import math

    env = {
        "t": t,
        "if_": lambda cond, a, b: a if cond else b,
        "lt": lambda a, b: a < b,
        "pow": math.pow,
        "min": min,
        "max": max,
    }
    return float(eval(expr.replace("if(", "if_("), {"__builtins__": {}}, env))  # noqa: S307


class TestCreditAnimation:
    """The credit slides in from the left, holds, then slides back out.

    Timing comes from OVERLAY_IN / OVERLAY_OUT / OVERLAY_SLIDE, so the maths is
    checked here and the rendering was verified against real ffmpeg frames.
    """

    DIST = 1000

    def _motion(self):
        return pipeline._overlay_motion(self.DIST)

    def test_starts_fully_off_screen(self):
        offset, _ = self._motion()
        assert _eval_ffmpeg_expr(offset, pipeline.OVERLAY_IN) == pytest.approx(-self.DIST)

    def test_reaches_its_resting_place(self):
        offset, _ = self._motion()
        settled = pipeline.OVERLAY_IN + pipeline.OVERLAY_SLIDE
        assert _eval_ffmpeg_expr(offset, settled) == pytest.approx(0, abs=1e-9)

    def test_holds_still_in_the_middle(self):
        offset, _ = self._motion()
        midpoint = (pipeline.OVERLAY_IN + pipeline.OVERLAY_OUT) / 2
        assert _eval_ffmpeg_expr(offset, midpoint) == 0

    def test_leaves_by_the_way_it_came(self):
        offset, _ = self._motion()
        assert _eval_ffmpeg_expr(offset, pipeline.OVERLAY_OUT) == pytest.approx(-self.DIST)

    def test_motion_is_monotonic_on_the_way_in(self):
        """Easing may decelerate, but it must never travel backwards."""
        offset, _ = self._motion()
        steps = [
            _eval_ffmpeg_expr(offset, pipeline.OVERLAY_IN + i * pipeline.OVERLAY_SLIDE / 10)
            for i in range(11)
        ]
        assert steps == sorted(steps)

    def test_fade_runs_from_zero_to_one_and_back(self):
        _, fade = self._motion()
        assert _eval_ffmpeg_expr(fade, pipeline.OVERLAY_IN) == pytest.approx(0)
        assert _eval_ffmpeg_expr(fade, (pipeline.OVERLAY_IN + pipeline.OVERLAY_OUT) / 2) == 1
        assert _eval_ffmpeg_expr(fade, pipeline.OVERLAY_OUT) == pytest.approx(0)

    def test_fade_never_leaves_zero_to_one(self):
        _, fade = self._motion()
        for i in range(0, 140):
            value = _eval_ffmpeg_expr(fade, i / 10)
            assert 0.0 <= value <= 1.0

    def test_panel_is_overlaid_not_drawbox(self):
        """drawbox in ffmpeg 4.4 ignores `t`, so a drawbox panel cannot move."""
        f = pipeline._overlay_filter("Bob", "/f.ttf", "1920x1080")
        assert "drawbox" not in f
        assert "color=c=black@0.7" in f
        # Defined once and consumed once: a dangling label is an invalid graph.
        assert f.count("[panel]") == 2

    def test_shortest_is_only_on_the_panel_overlay(self):
        """On the avatar overlay it would truncate the clip to one frame."""
        f = pipeline._overlay_filter("Bob", "/f.ttf", "1920x1080")
        assert f.count("shortest=1") == 1
        assert "shortest=1[bg]" in f

    def test_every_element_shares_one_offset(self):
        """Panel, both text lines and the avatar must move as a single object."""
        import re

        f = pipeline._overlay_filter("Bob", "/f.ttf", "1920x1080")
        # The slide distance is the panel width, which now follows the name.
        width = int(re.search(r"s=(\d+)x", f).group(1))
        offset, _ = pipeline._overlay_motion(width)
        assert f.count(offset) == 4


class TestPanelWidth:
    """The panel used to be a fixed 1000px slab whatever the name was."""

    def _width(self, author: str, resolution: str = "1920x1080") -> int:
        import re

        f = pipeline._overlay_filter(author, "/f.ttf", resolution)
        return int(re.search(r"s=(\d+)x", f).group(1))

    def test_a_short_name_gets_a_short_panel(self):
        assert self._width("Bo") < 600

    def test_a_longer_name_gets_a_wider_panel(self):
        assert self._width("AVeryLongStreamerName") > self._width("Bo")

    def test_width_is_clamped_at_both_ends(self):
        assert self._width("") >= 400
        assert self._width("x" * 200) <= 1000

    def test_width_scales_with_resolution(self):
        assert self._width("SomeStreamer", "1280x720") < self._width("SomeStreamer", "1920x1080")

    def test_the_slide_covers_the_whole_panel(self):
        """Otherwise a sliver of the panel stays parked on screen."""
        import re

        f = pipeline._overlay_filter("SomeStreamer", "/f.ttf", "1920x1080")
        width = int(re.search(r"s=(\d+)x", f).group(1))
        offset, _ = pipeline._overlay_motion(width)
        assert _eval_ffmpeg_expr(offset, pipeline.OVERLAY_IN) == pytest.approx(-width)


class TestMotionFeel:
    """Regressions in how the entrance reads, not just whether it happens."""

    def test_the_slide_is_brisk(self):
        assert pipeline.OVERLAY_SLIDE <= 0.35, "a long slide reads as sluggish"

    def test_easing_is_not_so_steep_it_crawls(self):
        """A cubic spends half the slide covering the last eighth of the way."""
        offset, _ = pipeline._overlay_motion(1000)
        halfway = pipeline.OVERLAY_IN + pipeline.OVERLAY_SLIDE / 2
        remaining = abs(_eval_ffmpeg_expr(offset, halfway))
        assert remaining >= 150, "at the halfway point it should still have visible travel left"

    def test_fade_completes_with_the_slide_not_before(self):
        """The complaint: the text was fully lit long before the panel landed."""
        offset, fade = pipeline._overlay_motion(1000)
        three_quarters = pipeline.OVERLAY_IN + pipeline.OVERLAY_SLIDE * 0.75
        assert _eval_ffmpeg_expr(fade, three_quarters) < 1.0
        assert _eval_ffmpeg_expr(offset, three_quarters) != 0


class TestFadeIsVisible:
    """The fade has to happen where it can be seen.

    Sharing the slide's window looked like no fade at all: the text enters from
    off-screen, so it was already at ~50% alpha by the time it crossed the left
    edge, and the rest completed while it was still moving.
    """

    DIST = 572  # a representative panel width
    TEXT_X = 198  # where the author line sits inside the panel

    def _at(self, expr, t):
        return _eval_ffmpeg_expr(expr, t)

    def test_text_is_invisible_until_it_is_on_screen(self):
        offset, fade = pipeline._overlay_motion(self.DIST)
        # Walk the entry; alpha must stay at 0 while the text is off the left edge.
        for i in range(40):
            t = pipeline.OVERLAY_IN + i * pipeline.OVERLAY_SLIDE / 40
            if self.TEXT_X + self._at(offset, t) < 0:
                assert self._at(fade, t) == 0, f"fading at t={t} while still off-screen"

    def test_most_of_the_fade_happens_after_the_panel_lands(self):
        _, fade = pipeline._overlay_motion(self.DIST)
        landed = pipeline.OVERLAY_IN + pipeline.OVERLAY_SLIDE
        assert self._at(fade, landed) < 0.75, "the fade is mostly over before you can see it"

    def test_fade_finishes_after_the_slide(self):
        _, fade = pipeline._overlay_motion(self.DIST)
        landed = pipeline.OVERLAY_IN + pipeline.OVERLAY_SLIDE
        assert self._at(fade, landed + pipeline.OVERLAY_FADE) == pytest.approx(1)

    def test_text_is_gone_before_the_panel_leaves(self):
        offset, fade = pipeline._overlay_motion(self.DIST)
        leaves = pipeline.OVERLAY_OUT - pipeline.OVERLAY_SLIDE
        assert self._at(fade, leaves) == pytest.approx(0, abs=1e-9)
        assert self._at(offset, leaves) == 0, "the panel should not have moved yet"

    def test_the_fade_is_long_enough_to_perceive(self):
        assert pipeline.OVERLAY_FADE >= 0.15, "a shorter fade reads as a pop"
