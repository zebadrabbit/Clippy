"""Cache policy — TTL and size-budget eviction for per-clip cache directories.

The cache directory structure assumed here:

    cache/
        _trans/         ← shared transition assets, always preserved
        README.md       ← always preserved
        <clip_id>/      ← per-clip processed files (subject to eviction)
        comp0, comp1    ← concat lists, cleaned on each run regardless
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clip_dirs(cache_root: Path) -> list[Path]:
    """Return per-clip subdirectories (skip _trans and any _ prefixed dirs)."""
    try:
        return [p for p in cache_root.iterdir() if p.is_dir() and not p.name.startswith("_")]
    except OSError:
        return []


def _dir_size_mb(path: Path) -> float:
    """Total size of a directory tree in megabytes."""
    try:
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return total / (1024.0 * 1024.0)
    except OSError:
        return 0.0


def _dir_mtime(path: Path) -> float:
    """Most recent file mtime inside the directory (proxy for last-used time)."""
    try:
        mtimes = [f.stat().st_mtime for f in path.rglob("*") if f.is_file()]
        return max(mtimes) if mtimes else path.stat().st_mtime
    except OSError:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0


def _remove_dir(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cache_size_mb(cache_root: str) -> float:
    """Return total size of all per-clip directories in MB (excludes _trans)."""
    root = Path(cache_root)
    return sum(_dir_size_mb(d) for d in _clip_dirs(root))


def apply_cache_policy(
    cache_root: str,
    keep_clips: bool = False,
    ttl_days: int = 0,
    max_size_mb: int = 0,
    purge: bool = False,
) -> None:
    """Apply the configured clip cache retention policy.

    Args:
        cache_root:   Path to the cache directory.
        keep_clips:   When True, retain processed per-clip directories between
                      runs (subject to TTL and size constraint below).
                      When False (default), delete all per-clip dirs at the end
                      of a run — existing behaviour.
        ttl_days:     Maximum age in days for a cached clip directory.
                      0 means unlimited (keep forever).  Only relevant when
                      keep_clips=True.
        max_size_mb:  Maximum total size in MB for all cached clip directories.
                      When exceeded the oldest directories are evicted first.
                      0 means unlimited.  Only relevant when keep_clips=True.
        purge:        When True, delete everything in cache (including _trans).
                      Overrides all other options.

    What is always preserved (unless purge=True):
        - ``_trans/``   — re-encoded transition/intro/outro assets
        - ``README.md`` — informational file written by prep_work()
    """
    root = Path(cache_root)
    if not root.is_dir():
        return

    if purge:
        # Wipe everything, including _trans/
        for entry in root.iterdir():
            if entry.is_dir():
                _remove_dir(entry)
            else:
                _remove_file(entry)
        return

    clip_dirs = _clip_dirs(root)

    if not keep_clips:
        # Default behaviour — delete all per-clip directories
        for d in clip_dirs:
            _remove_dir(d)
        # Also remove non-clip, non-preserved files (comp lists etc.)
        for entry in root.iterdir():
            if entry.is_file() and entry.name.lower() not in {"readme.md"}:
                _remove_file(entry)
        return

    # --- keep_clips=True — apply TTL and/or size budget ---
    now = time.time()

    # Step 1: TTL eviction
    if ttl_days > 0:
        cutoff = now - (ttl_days * 86400.0)
        surviving: list[Path] = []
        for d in clip_dirs:
            if _dir_mtime(d) < cutoff:
                _remove_dir(d)
            else:
                surviving.append(d)
        clip_dirs = surviving

    # Step 2: size-budget eviction (oldest-first)
    if max_size_mb > 0:
        total_mb = sum(_dir_size_mb(d) for d in clip_dirs)
        if total_mb > max_size_mb:
            # Sort ascending by mtime so oldest are evicted first
            by_age = sorted(clip_dirs, key=_dir_mtime)
            for d in by_age:
                if total_mb <= max_size_mb:
                    break
                size = _dir_size_mb(d)
                _remove_dir(d)
                total_mb -= size

    # Step 3: clean up non-clip, non-preserved files (comp lists etc.)
    for entry in root.iterdir():
        if entry.is_file() and entry.name.lower() not in {"readme.md"}:
            _remove_file(entry)
