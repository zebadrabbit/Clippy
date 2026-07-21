"""Tests for clippy.window.resolve_date_window — the Helix query window."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from clippy.window import RANGE_CHOICES, resolve_date_window, window_from_preset


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


class TestTwoDigitYears:
    """07/01/26 crashed a TUI run with "Invalid date format"."""

    @pytest.mark.parametrize(
        "given,expected",
        [
            ("07/01/26", "2026-07-01T00:00:00Z"),
            ("07-01-26", "2026-07-01T00:00:00Z"),
            ("7/1/2026", "2026-07-01T00:00:00Z"),
            ("2026/07/01", "2026-07-01T00:00:00Z"),
        ],
    )
    def test_accepted_short_forms(self, given, expected):
        assert resolve_date_window(given, None)[0] == expected

    def test_two_digit_year_uses_the_c_convention(self):
        """00-68 land in the 2000s, 69-99 in the 1900s."""
        assert resolve_date_window("01/01/68", None)[0].startswith("2068")
        assert resolve_date_window("01/01/69", None)[0].startswith("1969")


class TestRangePresets:
    def test_every_choice_resolves(self):
        for key, _label in RANGE_CHOICES:
            start, end = window_from_preset(key)
            assert end, f"{key} produced no end"
            if key != "everything":
                assert start < end, f"{key} start is not before end"

    def test_everything_has_no_lower_bound(self):
        start, end = window_from_preset("everything")
        assert start is None
        assert end

    def test_today_starts_at_midnight(self):
        now = datetime(2026, 7, 21, 13, 45, tzinfo=timezone.utc)
        start, end = window_from_preset("today", now=now)
        assert start == "2026-07-21T00:00:00Z"
        assert end == "2026-07-21T13:45:00Z"

    @pytest.mark.parametrize(
        "name,days", [("week", 7), ("two_weeks", 14), ("month", 30), ("year", 365)]
    )
    def test_lookback_length(self, name, days):
        now = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
        start, _ = window_from_preset(name, now=now)
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
        assert (now - parsed).days == days

    def test_unknown_name_falls_back_instead_of_raising(self):
        """This feeds a picker; a bad value must not be able to kill a run."""
        start, end = window_from_preset("nonsense")
        assert start and end

    def test_presets_round_trip_through_the_resolver(self):
        """What the picker stores must be re-parseable by the pipeline."""
        for key, _label in RANGE_CHOICES:
            start, end = window_from_preset(key)
            resolved = resolve_date_window(start or None, end)
            assert resolved[1]

    def test_timestamps_have_no_microseconds(self):
        for key, _label in RANGE_CHOICES:
            for value in window_from_preset(key):
                if value:
                    assert "." not in value, f"{key} leaked microseconds: {value}"
