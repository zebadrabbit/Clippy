"""Tests for clippy.window.resolve_date_window — the Helix query window."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clippy.window import resolve_date_window


class TestDateFormats:
    @pytest.mark.parametrize(
        "given",
        ["07/01/2025", "07-01-2025", "2025-07-01"],
    )
    def test_bare_dates_start_at_midnight(self, given):
        start, _ = resolve_date_window(given, None)
        assert start == "2025-07-01T00:00:00Z"

    def test_bare_end_date_covers_the_whole_day(self):
        _, end = resolve_date_window(None, "2025-07-07")
        assert end == "2025-07-07T23:59:59Z"

    def test_rfc3339_input_is_accepted(self):
        """The quick-start example in run.py's docstring used to raise ValueError."""
        start, end = resolve_date_window("2025-07-01T00:00:00Z", "2025-07-07T12:30:00Z")
        assert start == "2025-07-01T00:00:00Z"
        # An explicit time is honoured rather than pushed to end-of-day.
        assert end == "2025-07-07T12:30:00Z"

    def test_offset_is_converted_to_utc(self):
        start, _ = resolve_date_window("2025-07-01T00:00:00-04:00", None)
        assert start == "2025-07-01T04:00:00Z"

    def test_garbage_is_rejected_with_a_useful_message(self):
        with pytest.raises(ValueError, match="RFC3339"):
            resolve_date_window("last tuesday", None)


class TestDefaults:
    def test_no_input_is_the_last_three_days(self):
        start, end = resolve_date_window(None, None)
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        assert (e.date() - s.date()).days == 3
        assert s.hour == s.minute == s.second == 0
        assert e <= datetime.now(timezone.utc)

    def test_start_only_ends_now(self):
        _, end = resolve_date_window("2025-07-01", None)
        assert datetime.fromisoformat(end.replace("Z", "+00:00")) <= datetime.now(timezone.utc)

    def test_end_only_leaves_start_open(self):
        start, end = resolve_date_window(None, "2025-07-07")
        assert start is None
        assert end == "2025-07-07T23:59:59Z"
