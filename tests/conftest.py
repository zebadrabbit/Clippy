"""Shared test fixtures for Clippy tests."""

from __future__ import annotations

import pytest

from clippy.models import ClippyConfig, ClipRow


@pytest.fixture
def default_config() -> ClippyConfig:
    """A ClippyConfig built from pure defaults (no YAML, no env)."""
    from clippy.config_loader import DEFAULTS, load_merged_config

    merged = load_merged_config(defaults=DEFAULTS, env={}, file_path="/nonexistent.yaml")
    return ClippyConfig.from_merged_dict(merged)


@pytest.fixture
def sample_clip() -> ClipRow:
    """A sample ClipRow for testing."""
    return ClipRow(
        id="TestClip123",
        created_ts=1700000000.0,
        author="testuser",
        avatar_url="https://example.com/avatar.png",
        view_count=42,
        url="https://clips.twitch.tv/TestClip123",
    )


@pytest.fixture(autouse=True)
def _isolate_config_module():
    """Undo any config mutation a test performs.

    ``clippy.config`` is a module-level singleton: the typed config, the merged
    dict and a set of legacy globals, all rewritten in place by set_config() and
    reload_with_profile(). Without this, a test that switches profile leaks that
    profile into every test that runs after it -- across files, in whatever order
    pytest happens to pick.
    """
    import clippy.config as cfg

    saved_config = cfg.get_config()
    saved_merged = dict(cfg._merged)
    saved_globals = {
        name: getattr(cfg, name, None)
        for name in ("active_profile", "video_codec", "fontfile", "transitions_dir")
    }
    try:
        yield
    finally:
        cfg._merged = saved_merged
        cfg.set_config(saved_config)
        for name, value in saved_globals.items():
            if value is None:
                if hasattr(cfg, name):
                    delattr(cfg, name)
            else:
                setattr(cfg, name, value)
