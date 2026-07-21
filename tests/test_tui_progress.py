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
    """A repeat must cost zero extra rows -- that was the whole complaint."""

    def _logged(self, probe):
        async def run(screen, pilot):
            screen._written = []
            screen._write = screen._written.append
            await probe(screen, pilot)
            screen._flush_repeats()
            return list(screen._written)

        return _on_progress_screen(run)

    def test_a_long_run_costs_one_line_plus_a_tally(self):
        async def probe(screen, pilot):
            for _ in range(20):
                screen._log("Skipping failed clip")

        written = self._logged(probe)
        assert written == ["Skipping failed clip", "[dim]   x20[/]"]

    def test_a_lone_duplicate_costs_nothing(self):
        """This was the complaint: "repeated 1 times" took the row it saved."""

        async def probe(screen, pilot):
            screen._log("same")
            screen._log("same")

        assert self._logged(probe) == ["same"]

    def test_distinct_lines_are_never_collapsed(self):
        async def probe(screen, pilot):
            for i in range(3):
                screen._log(f"clip {i}")

        assert self._logged(probe) == ["clip 0", "clip 1", "clip 2"]

    def test_the_counter_resets_after_a_different_line(self):
        async def probe(screen, pilot):
            for _ in range(3):
                screen._log("a")
            screen._log("b")
            screen._log("a")

        assert self._logged(probe) == ["a", "[dim]   x3[/]", "b", "a"]

    def test_alternating_pairs_do_not_double_the_output(self):
        """A,A,B,B,... is the pattern that produced a wall of tally lines."""

        async def probe(screen, pilot):
            for _ in range(5):
                screen._log("A")
                screen._log("A")
                screen._log("B")
                screen._log("B")

        written = self._logged(probe)
        assert written == ["A", "B"] * 5
        assert not any("x" in w for w in written), "no tally lines for lone duplicates"

    def test_activity_line_is_separate_from_the_log(self):
        async def probe(screen, pilot):
            from textual.widgets import Static

            screen._set_activity("Concatenating out.mp4: 50%")
            await pilot.pause()
            return str(screen.query_one("#activity", Static).content)

        assert "50%" in _on_progress_screen(probe)


class TestNoDoubleEmission:
    """Every message must reach the log exactly once.

    The clippy logger builds its handlers lazily on the first log() call. If
    that happened inside the capture block, the new StreamHandler bound to the
    already-replaced stdout and each message arrived twice -- which is what
    produced a "repeated" tally under every single line.
    """

    def test_a_logged_message_appears_once(self):
        async def probe(screen, pilot):
            import logging

            written = []
            screen._write = written.append
            # Handlers do not exist yet, exactly as on a fresh run.
            logging.getLogger("clippy").handlers.clear()
            with screen._capture_output():
                from clippy.utils import log as clippy_log

                clippy_log("a distinctive message")
            screen._flush_repeats()
            return [w for w in written if "distinctive" in w]

        assert len(_on_progress_screen(probe)) == 1
