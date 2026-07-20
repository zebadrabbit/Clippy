"""Tests for clippy.naming — output file naming and the cache -> output move.

This is the code that touches the user's finished videos, so the cases that
matter are the ones where a name already exists on disk.
"""

from __future__ import annotations

import dataclasses
import time

import pytest

import clippy.config as cfg
from clippy.naming import ensure_unique_names, finalize_outputs, sanitize_filename


class TestSanitizeFilename:
    def test_replaces_path_and_shell_hostile_characters(self):
        assert sanitize_filename("a/b\\c:d*e?f") == "a_b_c_d_e_f"

    def test_keeps_safe_characters(self):
        assert sanitize_filename("cool.stream-name_1") == "cool.stream-name_1"

    def test_truncates_to_80_chars(self):
        assert len(sanitize_filename("x" * 200)) == 80


class TestEnsureUniqueNames:
    def test_untouched_when_nothing_collides(self, tmp_path):
        names = ["a.mp4", "b.mp4"]
        assert ensure_unique_names(names, str(tmp_path), overwrite=False) == names

    def test_suffixes_around_an_existing_file(self, tmp_path):
        (tmp_path / "a.mp4").write_text("existing")
        assert ensure_unique_names(["a.mp4"], str(tmp_path), overwrite=False) == ["a_1.mp4"]

    def test_suffix_counts_up_past_several_existing_files(self, tmp_path):
        for n in ("a.mp4", "a_1.mp4", "a_2.mp4"):
            (tmp_path / n).write_text("existing")
        assert ensure_unique_names(["a.mp4"], str(tmp_path), overwrite=False) == ["a_3.mp4"]

    def test_dedupes_within_a_single_batch(self, tmp_path):
        got = ensure_unique_names(["a.mp4", "a.mp4", "a.mp4"], str(tmp_path), overwrite=False)
        assert got == ["a.mp4", "a_1.mp4", "a_2.mp4"]

    def test_collision_check_is_case_insensitive(self, tmp_path):
        """Windows and macOS would otherwise silently overwrite the earlier file."""
        (tmp_path / "A.MP4").write_text("existing")
        assert ensure_unique_names(["a.mp4"], str(tmp_path), overwrite=False) == ["a_1.mp4"]

    def test_overwrite_returns_names_verbatim(self, tmp_path):
        (tmp_path / "a.mp4").write_text("existing")
        assert ensure_unique_names(["a.mp4"], str(tmp_path), overwrite=True) == ["a.mp4"]

    def test_extension_is_preserved(self, tmp_path):
        (tmp_path / "a.mkv").write_text("existing")
        assert ensure_unique_names(["a.mkv"], str(tmp_path), overwrite=False) == ["a_1.mkv"]


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Point the config at throwaway cache/output dirs and hand them back."""
    cache = tmp_path / "cache"
    output = tmp_path / "output"
    cache.mkdir()
    output.mkdir()
    c = cfg.get_config()
    monkeypatch.setattr(
        cfg,
        "_CONFIG",
        dataclasses.replace(
            c, paths=dataclasses.replace(c.paths, cache=str(cache), output=str(output))
        ),
    )
    return cache, output


def _compiled(cache, index: int, ext: str = "mp4") -> None:
    """Drop a file matching what the pipeline leaves in the cache."""
    (cache / f"complete_01_01_25_{index}.{ext}").write_text(f"video {index}")


class TestFinalizeOutputs:
    def test_moves_and_names_a_single_compilation(self, workspace):
        cache, output = workspace
        _compiled(cache, 0)
        names = finalize_outputs(
            "SomeChannel", ("2025-07-01T00:00:00Z", "2025-07-07T23:59:59Z"), 1, keep_cache=True
        )
        assert names == ["somechannel_2025-07-01_to_2025-07-07_compilation.mp4"]
        assert (output / names[0]).read_text() == "video 0"
        assert not list(cache.glob("complete_*"))

    def test_multiple_compilations_are_numbered(self, workspace):
        cache, output = workspace
        _compiled(cache, 0)
        _compiled(cache, 1)
        names = finalize_outputs("chan", ("2025-07-01T00:00:00Z", None), 2, keep_cache=True)
        assert [n.split("_")[-1] for n in names] == ["part1.mp4", "part2.mp4"]
        assert all((output / n).exists() for n in names)

    def test_existing_output_is_not_clobbered(self, workspace):
        """Default behaviour must never destroy a previous render."""
        cache, output = workspace
        _compiled(cache, 0)
        target = output / "chan_2025-07-01_to_2025-07-01_compilation.mp4"
        target.write_text("precious")

        names = finalize_outputs("chan", ("2025-07-01T00:00:00Z", None), 1, keep_cache=True)

        assert target.read_text() == "precious"
        assert names[0].endswith("_1.mp4"), "returned name must be the file actually written"
        assert (output / names[0]).read_text() == "video 0"

    def test_overwrite_output_replaces_it(self, workspace):
        cache, output = workspace
        _compiled(cache, 0)
        target = output / "chan_2025-07-01_to_2025-07-01_compilation.mp4"
        target.write_text("stale")

        names = finalize_outputs(
            "chan", ("2025-07-01T00:00:00Z", None), 1, keep_cache=True, overwrite_output=True
        )

        assert names == [target.name]
        assert target.read_text() == "video 0"

    def test_explicit_final_names_are_used(self, workspace):
        cache, output = workspace
        _compiled(cache, 0)
        names = finalize_outputs(
            "chan", (None, None), 1, keep_cache=True, final_names=["my_video.mp4"]
        )
        assert names == ["my_video.mp4"]
        assert (output / "my_video.mp4").exists()

    def test_cache_file_built_today_is_found_directly(self, workspace):
        """The primary path: the cache name embeds today's date."""
        cache, output = workspace
        (cache / f"complete_{time.strftime('%d_%m_%y')}_0.mp4").write_text("video 0")
        names = finalize_outputs("chan", (None, None), 1, keep_cache=True)
        assert (output / names[0]).read_text() == "video 0"

    def test_cache_file_from_another_day_is_still_found(self, workspace):
        """The fallback: the build ran yesterday, or finalize crossed midnight."""
        cache, output = workspace
        (cache / "complete_31_12_24_0.mp4").write_text("video 0")
        names = finalize_outputs("chan", (None, None), 1, keep_cache=True)
        assert (output / names[0]).read_text() == "video 0"

    def test_missing_compilation_is_reported_not_fatal(self, workspace):
        cache, output = workspace
        _compiled(cache, 0)  # index 1 never rendered
        names = finalize_outputs("chan", (None, None), 2, keep_cache=True)
        assert (output / names[0]).exists()
        assert not (output / names[1]).exists()

    def test_container_extension_follows_config(self, workspace, monkeypatch):
        cache, output = workspace
        c = cfg.get_config()
        monkeypatch.setattr(
            cfg,
            "_CONFIG",
            dataclasses.replace(c, encoding=dataclasses.replace(c.encoding, container_ext="mkv")),
        )
        _compiled(cache, 0, ext="mkv")
        names = finalize_outputs("chan", (None, None), 1, keep_cache=True)
        assert names[0].endswith(".mkv")
        assert (output / names[0]).exists()
