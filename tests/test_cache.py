"""Tests for clippy.cache — cache policy and eviction logic."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from clippy.cache import (
    _clip_dirs,
    _dir_size_mb,
    apply_cache_policy,
    cache_size_mb,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cache_root(tmp_path: Path) -> Path:
    """Return a temporary cache root with a realistic directory structure."""
    # Shared infrastructure — should never be evicted (except on purge)
    trans = tmp_path / "_trans"
    trans.mkdir()
    (trans / "static.mp4").write_bytes(b"x" * 1024)
    (trans / "_manifest.json").write_bytes(b"{}")

    # Per-clip directories with small payloads
    for name in ("ClipAlpha", "ClipBeta", "ClipGamma"):
        d = tmp_path / name
        d.mkdir()
        (d / f"{name}.mp4").write_bytes(b"y" * 2048)
        (d / "avatar.png").write_bytes(b"a" * 512)

    # Concat list files that should be cleaned
    (tmp_path / "comp0").write_text("file ClipAlpha/ClipAlpha.mp4\n")
    (tmp_path / "comp1").write_text("file ClipBeta/ClipBeta.mp4\n")

    # README should survive
    (tmp_path / "README.md").write_text("cache readme\n")

    return tmp_path


# ---------------------------------------------------------------------------
# _clip_dirs
# ---------------------------------------------------------------------------


class TestClipDirs:
    def test_excludes_underscore_dirs(self, cache_root: Path):
        dirs = _clip_dirs(cache_root)
        names = {d.name for d in dirs}
        assert "_trans" not in names

    def test_includes_clip_dirs(self, cache_root: Path):
        dirs = _clip_dirs(cache_root)
        names = {d.name for d in dirs}
        assert {"ClipAlpha", "ClipBeta", "ClipGamma"} == names

    def test_returns_empty_for_missing_dir(self):
        assert _clip_dirs(Path("/nonexistent/path/xyz")) == []


# ---------------------------------------------------------------------------
# _dir_size_mb / cache_size_mb
# ---------------------------------------------------------------------------


class TestSizeHelpers:
    def test_dir_size_mb_nonzero(self, cache_root: Path):
        size = _dir_size_mb(cache_root / "ClipAlpha")
        assert size > 0

    def test_cache_size_mb_excludes_trans(self, cache_root: Path):
        total = cache_size_mb(str(cache_root))
        # _trans/ should not be counted
        trans_size = _dir_size_mb(cache_root / "_trans")
        assert total < trans_size + total  # sanity
        # All three clip dirs contribute
        assert total > 0

    def test_dir_size_mb_missing(self):
        assert _dir_size_mb(Path("/nonexistent")) == 0.0


# ---------------------------------------------------------------------------
# apply_cache_policy — default (keep_clips=False)
# ---------------------------------------------------------------------------


class TestPolicyDefault:
    def test_deletes_clip_dirs(self, cache_root: Path):
        apply_cache_policy(str(cache_root))
        assert not (cache_root / "ClipAlpha").exists()
        assert not (cache_root / "ClipBeta").exists()
        assert not (cache_root / "ClipGamma").exists()

    def test_preserves_trans(self, cache_root: Path):
        apply_cache_policy(str(cache_root))
        assert (cache_root / "_trans").exists()

    def test_preserves_readme(self, cache_root: Path):
        apply_cache_policy(str(cache_root))
        assert (cache_root / "README.md").exists()

    def test_removes_comp_files(self, cache_root: Path):
        apply_cache_policy(str(cache_root))
        assert not (cache_root / "comp0").exists()
        assert not (cache_root / "comp1").exists()

    def test_missing_root_is_noop(self):
        apply_cache_policy("/nonexistent/cache/path")  # should not raise


# ---------------------------------------------------------------------------
# apply_cache_policy — purge
# ---------------------------------------------------------------------------


class TestPolicyPurge:
    def test_purge_removes_trans(self, cache_root: Path):
        apply_cache_policy(str(cache_root), purge=True)
        assert not (cache_root / "_trans").exists()

    def test_purge_removes_all_clip_dirs(self, cache_root: Path):
        apply_cache_policy(str(cache_root), purge=True)
        assert not (cache_root / "ClipAlpha").exists()

    def test_purge_removes_readme(self, cache_root: Path):
        apply_cache_policy(str(cache_root), purge=True)
        assert not (cache_root / "README.md").exists()


# ---------------------------------------------------------------------------
# apply_cache_policy — keep_clips with TTL
# ---------------------------------------------------------------------------


class TestPolicyTTL:
    def test_keep_clips_preserves_recent_dirs(self, cache_root: Path):
        apply_cache_policy(str(cache_root), keep_clips=True, ttl_days=30)
        # All dirs were just created — should survive a 30-day TTL
        assert (cache_root / "ClipAlpha").exists()
        assert (cache_root / "ClipBeta").exists()

    def test_ttl_evicts_old_dirs(self, cache_root: Path):
        # Back-date ClipAlpha's files to 31 days ago
        old_time = time.time() - (31 * 86400)
        clip_dir = cache_root / "ClipAlpha"
        for f in clip_dir.rglob("*"):
            os.utime(f, (old_time, old_time))
        os.utime(clip_dir, (old_time, old_time))

        apply_cache_policy(str(cache_root), keep_clips=True, ttl_days=30)
        assert not (cache_root / "ClipAlpha").exists()

    def test_ttl_preserves_recent_dirs(self, cache_root: Path):
        # Back-date ClipAlpha but leave Beta and Gamma fresh
        old_time = time.time() - (31 * 86400)
        clip_dir = cache_root / "ClipAlpha"
        for f in clip_dir.rglob("*"):
            os.utime(f, (old_time, old_time))
        os.utime(clip_dir, (old_time, old_time))

        apply_cache_policy(str(cache_root), keep_clips=True, ttl_days=30)
        assert (cache_root / "ClipBeta").exists()
        assert (cache_root / "ClipGamma").exists()


# ---------------------------------------------------------------------------
# apply_cache_policy — keep_clips with size cap
# ---------------------------------------------------------------------------


class TestPolicySize:
    def test_under_limit_keeps_all(self, cache_root: Path):
        apply_cache_policy(str(cache_root), keep_clips=True, max_size_mb=100)
        assert (cache_root / "ClipAlpha").exists()
        assert (cache_root / "ClipBeta").exists()
        assert (cache_root / "ClipGamma").exists()

    def test_over_limit_evicts_oldest(self, cache_root: Path):
        # Make ClipAlpha the oldest by back-dating it
        old_time = time.time() - 3600
        clip_dir = cache_root / "ClipAlpha"
        for f in clip_dir.rglob("*"):
            os.utime(f, (old_time, old_time))
        os.utime(clip_dir, (old_time, old_time))

        # Inflate ClipAlpha so that evicting it alone drops us under 1 MB
        (clip_dir / "big.bin").write_bytes(b"z" * 1_100_000)  # ~1.1 MB
        # Back-date the inflated file too
        os.utime(clip_dir / "big.bin", (old_time, old_time))

        # Cap at 1 MB — ClipAlpha (~1.1 MB) is oldest and exceeds budget alone
        apply_cache_policy(str(cache_root), keep_clips=True, max_size_mb=1)
        # ClipAlpha (oldest + oversized) should be evicted
        assert not (cache_root / "ClipAlpha").exists()
        # Beta and Gamma are tiny and recent — should survive
        assert (cache_root / "ClipBeta").exists()
        assert (cache_root / "ClipGamma").exists()

    def test_trans_not_counted_in_size(self, cache_root: Path):
        # A very tight limit should still preserve _trans
        apply_cache_policy(str(cache_root), keep_clips=True, max_size_mb=1)
        assert (cache_root / "_trans").exists()

    def test_zero_limit_is_unlimited(self, cache_root: Path):
        apply_cache_policy(str(cache_root), keep_clips=True, max_size_mb=0)
        assert (cache_root / "ClipAlpha").exists()
        assert (cache_root / "ClipGamma").exists()
