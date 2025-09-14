from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from utils import log


def _parse_simple_date(s: str) -> datetime:
    """Parse simple date strings in a few common formats.

    Accepted: MM/DD/YYYY, MM-DD-YYYY, YYYY-MM-DD
    Returns naive datetime (date) which will be assigned UTC.
    """
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid date format: {s}. Use MM/DD/YYYY.")


def resolve_date_window(start_str: Optional[str], end_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Convert simple date inputs to RFC3339 (ISO8601) strings for Helix.

    Start becomes 00:00:00Z; end becomes 23:59:59Z of that date.
    If only start provided, end is current UTC time.
    Default when both missing: last 3 days up to now.
    """
    if not start_str and not end_str:
        # default window: last 3 days up to now (inclusive)
        now = datetime.now(timezone.utc).date()
        start_date = now - timedelta(days=3)
        start_iso = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        end_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return start_iso, end_iso
    start_iso = end_iso = None
    if start_str:
        d = _parse_simple_date(start_str)
        start_iso = d.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    if end_str:
        d2 = _parse_simple_date(end_str)
        # End of day 23:59:59
        d2 = d2 + timedelta(hours=23, minutes=59, seconds=59)
        end_iso = d2.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    elif start_iso:
        # If only start provided, use now as end
        end_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return start_iso, end_iso


def summarize(cfg, resolved_window: Tuple[Optional[str], Optional[str]], resolution: Optional[str], container_ext: str, bitrate: Optional[str]):
    start_iso, end_iso = resolved_window
    log("{@green}Broadcaster:{@reset} {@cyan}" + str(cfg.broadcaster), 1)
    if start_iso or end_iso:
        log("{@green}Time Window:{@reset} {@yellow}" + (start_iso or 'ANY') + "{@reset} {@white}->{@reset} {@yellow}" + (end_iso or 'NOW'), 1)
    else:
        log("{@green}Time Window:{@reset} {@yellow}ANY", 1)
    log("{@green}Max Clips Fetch:{@reset} {@white}" + str(cfg.max_clips), 1)
    try:
        _tot = int(getattr(cfg, "amountOfCompilations")) * int(getattr(cfg, "amountOfClips"))
    except Exception:
        _tot = None
    msg = "{@green}Compilations:{@reset} {@white}" + str(cfg.amountOfCompilations) + "{@reset} {@green}| Clips each:{@reset} {@white}" + str(cfg.amountOfClips)
    if _tot is not None:
        msg += " {@green}({@white}" + str(_tot) + "{@green} total)"
    log(msg, 1)
    log("{@green}Min Views:{@reset} {@yellow}" + str(cfg.reactionThreshold), 1)
    # Show selected resolution/format/bitrate
    try:
        log("{@green}Resolution:{@reset} {@white}" + str(resolution or ""), 1)
        log("{@green}Format:{@reset} {@white}" + str(container_ext or "mp4"), 1)
        log("{@green}Bitrate:{@reset} {@white}" + str(bitrate or ""), 1)
    except Exception:
        pass
    try:
        if getattr(cfg, "auto_expand", False):
            log("{@green}Auto-expand:{@reset} {@cyan}enabled", 1)
            log("{@green}Expand step:{@reset} {@white}" + str(getattr(cfg, "expand_step_days", 7)) + "{@reset} {@green}days", 1)
            log("{@green}Max lookback:{@reset} {@white}" + str(getattr(cfg, "max_lookback_days", 90)) + "{@reset} {@green}days", 1)
    except Exception:
        pass
