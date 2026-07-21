"""Tests for unattended operation: exit codes, --headless and --json.

A scheduled run has no one to read the log, so the outcome has to be legible
from the exit code and, optionally, a JSON document. The distinction that
matters most is "ran fine, nothing to build" versus a real failure.
"""

from __future__ import annotations

import json

import pytest

from clippy import exits
from clippy import run as run_mod


class TestExitCodes:
    def test_every_code_has_a_name(self):
        for code in (
            exits.OK,
            exits.ERROR,
            exits.USAGE,
            exits.NO_CLIPS,
            exits.AUTH,
            exits.TOOL,
            exits.INTERRUPTED,
        ):
            assert exits.name(code)

    def test_codes_are_distinct(self):
        codes = [exits.OK, exits.ERROR, exits.USAGE, exits.NO_CLIPS, exits.AUTH, exits.TOOL]
        assert len(set(codes)) == len(codes)

    def test_success_is_zero_and_the_rest_are_not(self):
        assert exits.OK == 0
        for code in (exits.ERROR, exits.USAGE, exits.NO_CLIPS, exits.AUTH, exits.TOOL):
            assert code != 0

    def test_nothing_to_build_is_not_a_generic_error(self):
        """The whole point: a nightly job can ignore 3 and alert on the rest."""
        assert exits.NO_CLIPS not in (exits.OK, exits.ERROR)

    def test_unknown_code_falls_back_to_error(self):
        assert exits.name(99) == "error"


class TestFail:
    def test_it_exits_with_the_given_code(self):
        with pytest.raises(SystemExit) as exc:
            run_mod._fail("nothing matched", exits.NO_CLIPS)
        assert exc.value.code == exits.NO_CLIPS

    def test_the_message_is_reported(self, monkeypatch):
        seen = []
        monkeypatch.setattr(run_mod, "log", lambda msg, level=0: seen.append(str(msg)))
        with pytest.raises(SystemExit):
            run_mod._fail("nothing matched", exits.NO_CLIPS)
        assert any("nothing matched" in m for m in seen)


def _console(monkeypatch, argv, outcome):
    """Run console_main with main() replaced by *outcome*, returning (code, stdout)."""
    import io
    import sys

    monkeypatch.setattr(run_mod, "main", outcome)
    monkeypatch.setattr(run_mod, "_is_first_run", lambda: False)
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    code = 0
    try:
        run_mod.console_main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    return code, buf.getvalue()


class TestJsonOutput:
    MANIFEST = {
        "broadcaster": "somechannel",
        "window": {"start": "2025-07-01T00:00:00Z", "end": "2025-07-07T00:00:00Z"},
        "files": ["somechannel_part1.mp4", "somechannel_part2.mp4"],
        "version": "0.6.0",
    }

    def test_success_reports_the_files(self, monkeypatch):
        code, out = _console(monkeypatch, ["--json"], lambda: self.MANIFEST)
        doc = json.loads(out)
        assert code == exits.OK
        assert doc["status"] == "ok"
        assert doc["files"] == self.MANIFEST["files"]
        assert doc["compilations"] == 2

    def test_a_failure_still_produces_a_document(self, monkeypatch):
        """One shape to parse, whatever happened."""

        def boom():
            raise SystemExit(exits.TOOL)

        code, out = _console(monkeypatch, ["--json"], boom)
        doc = json.loads(out)
        assert code == exits.TOOL
        assert doc["status"] == "tool"
        assert doc["files"] == []

    def test_nothing_to_build_is_reported_as_such(self, monkeypatch):
        def empty():
            raise SystemExit(exits.NO_CLIPS)

        code, out = _console(monkeypatch, ["--json"], empty)
        doc = json.loads(out)
        assert code == exits.NO_CLIPS
        assert doc["status"] == "no-clips"

    def test_the_document_is_valid_json_and_nothing_else(self, monkeypatch):
        _, out = _console(monkeypatch, ["--json"], lambda: self.MANIFEST)
        json.loads(out)  # raises if the banner or a log line leaked in

    def test_no_json_without_the_flag(self, monkeypatch):
        _, out = _console(monkeypatch, [], lambda: self.MANIFEST)
        assert out.strip() == ""


class TestHeadless:
    def test_it_implies_yes(self):
        import sys

        argv = ["clippy", "--headless", "--broadcaster", "x"]
        old = sys.argv
        try:
            sys.argv = argv
            from clippy.cli import parse_args

            args = parse_args()
        finally:
            sys.argv = old
        assert args.yes is True, "a headless run must not wait at the confirmation prompt"

    def test_it_disables_colour(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        _console(monkeypatch, ["--headless"], lambda: None)
        import os

        assert os.environ.get("NO_COLOR") == "1"

    def test_an_interrupt_is_distinguishable(self, monkeypatch):
        def interrupted():
            raise KeyboardInterrupt

        code, _ = _console(monkeypatch, ["--json"], interrupted)
        assert code == exits.INTERRUPTED

    def test_a_message_only_exit_still_yields_a_code(self, monkeypatch):
        """Any site not yet converted must not report success."""

        def legacy():
            raise SystemExit("something went wrong")

        code, _ = _console(monkeypatch, [], legacy)
        assert code == exits.ERROR
