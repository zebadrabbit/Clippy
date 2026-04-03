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
