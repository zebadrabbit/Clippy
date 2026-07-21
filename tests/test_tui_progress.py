"""Tests for the build screen's log handling.

The log used to fill with near-identical lines during the concat stage: ffmpeg
redraws its progress with a carriage return and no newline, and every redraw was
captured as a new line. With a lot of clips the useful messages scrolled away.

Skipped when the optional ``textual`` dependency is not installed.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from clippy.tui.app import ClippyApp  # noqa: E402
from clippy.tui.screens.progress import _StdoutCapture  # noqa: E402

CR = "\r"
NL = "\n"


class TestStdoutCapture:
    """A carriage return means "redraw this line", not "here is a new line"."""

    def _capture(self):
        lines: list[str] = []
        status: list[str] = []
        return _StdoutCapture(lines.append, status.append), lines, status

    def test_progress_redraws_never_reach_the_log(self):
        cap, lines, status = self._capture()
        for pct in (0, 25, 50, 75, 100):
            cap.write(f"{CR}Concatenating out.mp4: {pct}%   ")
            cap.flush()
        assert lines == [], "in-place progress must not be appended to the log"
        assert status[-1].endswith("100%")

    def test_newline_terminated_output_is_a_log_line(self):
        cap, lines, _ = self._capture()
        cap.write("Compilation 1 complete" + NL)
        assert lines == ["Compilation 1 complete"]

    def test_a_redraw_then_a_newline_logs_the_final_state(self):
        """The last thing drawn before the line ends is what the terminal shows."""
        cap, lines, _ = self._capture()
        cap.write(f"{CR}working 10%")
        cap.write(f"{CR}working 100%{NL}")
        assert lines == ["working 100%"]

    def test_several_lines_in_one_write(self):
        cap, lines, _ = self._capture()
        cap.write(f"one{NL}two{NL}three{NL}")
        assert lines == ["one", "two", "three"]

    def test_ansi_colour_is_stripped(self):
        cap, lines, _ = self._capture()
        cap.write("\x1b[36mcyan text\x1b[39m" + NL)
        assert lines == ["cyan text"]

    def test_blank_output_is_ignored(self):
        cap, lines, status = self._capture()
        cap.write(NL)
        cap.write("   " + NL)
        cap.flush()
        assert lines == [] and status == []

    def test_a_partial_line_stays_out_of_the_log_until_terminated(self):
        cap, lines, status = self._capture()
        cap.write("half a line")
        cap.flush()
        assert lines == []
        assert status == ["half a line"]
        cap.write(NL)
        assert lines == ["half a line"]


def _on_progress_screen(probe):
    """Mount the build screen without letting the pipeline worker run."""
    from clippy.tui.screens.progress import ProgressScreen

    async def run():
        app = ClippyApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            screen = ProgressScreen()
            # The worker needs credentials and a network; this is a log test.
            screen.run_worker = lambda *a, **kw: None
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()
            return await probe(screen, pilot)

    return asyncio.run(run())


class TestRepeatCollapsing:
    def test_identical_lines_collapse_into_a_count(self):
        def written(screen):
            return [str(seg) for seg in screen._log_calls]

        async def probe(screen, pilot):
            screen._log_calls = []
            screen._write = lambda msg: screen._log_calls.append(msg)
            for _ in range(5):
                screen._log("Skipping failed clip")
            screen._log("Something else")
            await pilot.pause()
            return list(screen._log_calls)

        calls = _on_progress_screen(probe)
        assert calls[0] == "Skipping failed clip"
        assert any("repeated 4 more times" in c for c in calls)
        assert calls[-1] == "Something else"

    def test_distinct_lines_are_never_collapsed(self):
        async def probe(screen, pilot):
            screen._log_calls = []
            screen._write = lambda msg: screen._log_calls.append(msg)
            for i in range(3):
                screen._log(f"clip {i}")
            await pilot.pause()
            return list(screen._log_calls)

        assert _on_progress_screen(probe) == ["clip 0", "clip 1", "clip 2"]

    def test_activity_line_is_separate_from_the_log(self):
        async def probe(screen, pilot):
            from textual.widgets import Static

            screen._set_activity("Concatenating out.mp4: 50%")
            await pilot.pause()
            return str(screen.query_one("#activity", Static).content)

        assert "50%" in _on_progress_screen(probe)
