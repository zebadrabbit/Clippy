"""Tests for clippy.config_loader — YAML loading and merging."""

from __future__ import annotations

import os
import tempfile

import pytest

from clippy.config_loader import (
    DEFAULTS,
    _coerce_bool,
    _coerce_float,
    _coerce_int,
    _coerce_list_str,
    _coerce_str,
    load_merged_config,
)


class TestCoercion:
    def test_coerce_bool_true_values(self):
        for v in [True, "1", "true", "yes", "y", "on", "True", "YES"]:
            assert _coerce_bool(v, False) is True

    def test_coerce_bool_false_values(self):
        for v in [False, "0", "false", "no", "n", "off", "False", "NO"]:
            assert _coerce_bool(v, True) is False

    def test_coerce_bool_default(self):
        assert _coerce_bool("invalid", True) is True
        assert _coerce_bool(None, False) is False

    def test_coerce_str(self):
        assert _coerce_str("hello", "default") == "hello"
        assert _coerce_str(42, "default") == "42"
        assert _coerce_str(3.14, "default") == "3.14"
        assert _coerce_str(None, "default") == "default"
        assert _coerce_str([], "default") == "default"

    def test_coerce_int(self):
        assert _coerce_int(42, 0) == 42
        assert _coerce_int("42", 0) == 42
        assert _coerce_int(None, 99) == 99
        assert _coerce_int("invalid", 99) == 99

    def test_coerce_float(self):
        assert _coerce_float(3.14, 0.0) == 3.14
        assert _coerce_float("0.35", 0.0) == 0.35
        assert _coerce_float(None, 1.0) == 1.0
        assert _coerce_float("invalid", 1.0) == 1.0

    def test_coerce_list_str(self):
        assert _coerce_list_str(["a", "b"], []) == ["a", "b"]
        assert _coerce_list_str([1, 2], []) == ["1", "2"]
        assert _coerce_list_str("not a list", ["default"]) == ["default"]
        assert _coerce_list_str(None, ["default"]) == ["default"]


class TestLoadMergedConfig:
    def test_defaults_only(self):
        merged = load_merged_config(defaults=DEFAULTS, env={}, file_path="/nonexistent.yaml")
        assert merged["bitrate"] == "12M"
        assert merged["amountOfClips"] == 12
        assert merged["reactionThreshold"] == 1

    def test_yaml_override(self, tmp_path):
        yaml_content = """
encoding:
  bitrate: "20M"
  fps: "30"
selection:
  clips_per_compilation: 8
"""
        yaml_file = tmp_path / "clippy.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")
        merged = load_merged_config(
            defaults=DEFAULTS, env={}, file_path=str(yaml_file)
        )
        assert merged["bitrate"] == "20M"
        assert merged["fps"] == "30"
        assert merged["amountOfClips"] == 8

    def test_env_transitions_dir(self):
        merged = load_merged_config(
            defaults=DEFAULTS,
            env={"TRANSITIONS_DIR": "/custom/transitions"},
            file_path="/nonexistent.yaml",
        )
        assert merged.get("transitions_dir") == "/custom/transitions"

    def test_missing_yaml_uses_defaults(self):
        merged = load_merged_config(
            defaults=DEFAULTS, env={}, file_path="/definitely/nonexistent.yaml"
        )
        assert merged["bitrate"] == DEFAULTS["bitrate"]

    def test_malformed_yaml_uses_defaults(self, tmp_path):
        yaml_file = tmp_path / "clippy.yaml"
        yaml_file.write_text("not: [valid: yaml: content", encoding="utf-8")
        # Should not raise, should fall back to defaults
        merged = load_merged_config(
            defaults=DEFAULTS, env={}, file_path=str(yaml_file)
        )
        assert merged["bitrate"] == DEFAULTS["bitrate"]
