from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from clippy.utils import log


def _parse_date_input(s: str) -> Tuple[datetime, bool]:
    """Parse a date, or a full RFC3339 timestamp as Helix itself returns.

    Accepted: MM/DD/YYYY, MM-DD-YYYY, YYYY-MM-DD, and ISO8601/RFC3339
    (``2025-07-01T00:00:00Z``).

    Returns ``(utc_datetime, has_time)``. ``has_time`` is True when the caller
    supplied a time of day, so the day-boundary defaults are left alone.
    """
    s = s.strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(
                f"Invalid date format: {s}. Use MM/DD/YYYY, YYYY-MM-DD, "
                "or an RFC3339 timestamp like 2025-07-01T00:00:00Z."
            ) from None
    # Naive input is read as UTC; an explicit offset is converted to UTC.
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt, ("T" in s or " " in s)


def _iso_z(dt: datetime) -> str:
    """Render a UTC datetime the way Helix expects it."""
    return dt.isoformat().replace("+00:00", "Z")


def resolve_date_window(
    start_str: Optional[str], end_str: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Convert simple date inputs to RFC3339 (ISO8601) strings for Helix.

    Start becomes 00:00:00Z; end becomes 23:59:59Z of that date.
    If only start provided, end is current UTC time.
    Default when both missing: last 3 days up to now.
    """
    if not start_str and not end_str:
        # default window: last 3 days up to now (inclusive)
        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(days=3)).date()
        start_iso = _iso_z(
            datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        )
        return start_iso, _iso_z(now)
    start_iso = end_iso = None
    if start_str:
        d, _ = _parse_date_input(start_str)
        start_iso = _iso_z(d)
    if end_str:
        d2, has_time = _parse_date_input(end_str)
        if not has_time:
            # A bare date means "through the end of that day".
            d2 += timedelta(hours=23, minutes=59, seconds=59)
        end_iso = _iso_z(d2)
    elif start_iso:
        # If only start provided, use now as end
        end_iso = _iso_z(datetime.now(timezone.utc))
    return start_iso, end_iso


def summarize(
    cfg,
    resolved_window: Tuple[Optional[str], Optional[str]],
    resolution: Optional[str],
    container_ext: str,
    bitrate: Optional[str],
):
    start_iso, end_iso = resolved_window
    log("Broadcaster: " + str(cfg.broadcaster), 1)
    if start_iso or end_iso:
        log("Time Window: " + (start_iso or "ANY") + " -> " + (end_iso or "NOW"), 1)
    else:
        log("Time Window: ANY", 1)
    log("Max Clips Fetch: " + str(cfg.max_clips), 1)
    try:
        _tot = int(getattr(cfg, "amountOfCompilations")) * int(getattr(cfg, "amountOfClips"))
    except (ValueError, TypeError, AttributeError):
        _tot = None
    msg = (
        "Compilations: "
        + str(cfg.amountOfCompilations)
        + " | Clips each: "
        + str(cfg.amountOfClips)
    )
    if _tot is not None:
        msg += " (" + str(_tot) + " total)"
    log(msg, 1)
    log("Min Views: " + str(cfg.reactionThreshold), 1)
    # Show selected resolution/format/bitrate
    try:
        log("Resolution: " + str(resolution or ""), 1)
        log("Format: " + str(container_ext or "mp4"), 1)
        log("Bitrate: " + str(bitrate or ""), 1)
    except Exception:  # log formatting is best-effort
        pass
    try:
        if getattr(cfg, "auto_expand", False):
            log("Auto-expand: enabled", 1)
            log("Expand step: " + str(getattr(cfg, "expand_step_days", 7)) + " days", 1)
            log("Max lookback: " + str(getattr(cfg, "max_lookback_days", 90)) + " days", 1)
    except AttributeError:
        pass
