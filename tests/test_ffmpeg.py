"""Tests for clippy.ffmpeg — EncoderParams."""

from __future__ import annotations

import subprocess

import pytest

from clippy.ffmpeg import EncoderParams, detect_encoder


class TestEncoderParams:
    def test_default_nvenc(self):
        enc = EncoderParams()
        flags = enc.video_flags()
        assert "h264_nvenc" in flags
        assert "-cq 19" in flags
        assert "-rc vbr" in flags

    def test_libx264_flags(self):
        enc = EncoderParams(video_codec="libx264")
        flags = enc.video_flags()
        assert "libx264" in flags
        assert "-crf 19" in flags
        # NVENC-specific flags should not appear
        assert "-rc vbr" not in flags
        assert "spatial_aq" not in flags

    def test_amf_flags(self):
        enc = EncoderParams(video_codec="h264_amf")
        flags = enc.video_flags()
        assert "-c:v h264_amf" in flags
        assert "-qp_i 19" in flags
        # NVENC-only flags must not leak into an AMF command — ffmpeg would
        # reject them, which is exactly the bug this branch exists to prevent.
        assert "-rc vbr" not in flags
        assert "-rc-lookahead" not in flags
        assert "spatial_aq" not in flags
        assert "aq-strength" not in flags
        assert "temporal-aq" not in flags

    def test_qsv_flags(self):
        enc = EncoderParams(video_codec="h264_qsv")
        flags = enc.video_flags()
        assert "-c:v h264_qsv" in flags
        assert "-global_quality 19" in flags
        assert "-rc vbr" not in flags
        assert "-rc-lookahead" not in flags
        assert "spatial_aq" not in flags
        assert "aq-strength" not in flags
        assert "temporal-aq" not in flags

    def test_amf_and_qsv_ignore_the_nvenc_tuned_preset(self):
        """preset carries an NVENC-style value (e.g. "slow"/"p4") that AMF/QSV
        don't understand — they use their own hardcoded defaults instead."""
        amf = EncoderParams(video_codec="h264_amf", preset="p4").video_flags()
        qsv = EncoderParams(video_codec="h264_qsv", preset="p4").video_flags()
        assert "p4" not in amf
        assert "p4" not in qsv

    def test_audio_flags(self):
        enc = EncoderParams()
        flags = enc.audio_flags()
        assert "-c:a aac" in flags
        assert "-b:a 192k" in flags
        assert "-ar 48000" in flags
        assert "-ac 2" in flags

    def test_sizing_flags(self):
        enc = EncoderParams(resolution="1280x720", fps="30")
        flags = enc.sizing_flags()
        assert "-r 30" in flags
        assert "-s 1280x720" in flags
        assert "lanczos" in flags

    def test_from_config(self, default_config):
        enc = EncoderParams.from_config(default_config)
        assert enc.video_codec == "h264_nvenc"
        assert enc.resolution == "1920x1080"
        assert enc.fps == "60"

    def test_libx264_fallback(self, default_config):
        enc = EncoderParams.libx264_fallback(default_config)
        assert enc.video_codec == "libx264"
        assert enc.preset == "medium"

    def test_with_overrides(self):
        enc = EncoderParams()
        new = enc.with_overrides(cq=16, max_bitrate="20M")
        assert new.cq == 16
        assert new.max_bitrate == "20M"
        # Original unchanged
        assert enc.cq == 19
        assert enc.max_bitrate == "12M"

    def test_validate_low_cq(self):
        enc = EncoderParams(cq=5)
        warnings = enc.validate()
        assert any("cq=5" in w for w in warnings)

    def test_validate_high_cq(self):
        enc = EncoderParams(cq=40)
        warnings = enc.validate()
        assert any("cq=40" in w for w in warnings)

    def test_validate_normal(self):
        enc = EncoderParams(cq=19)
        assert enc.validate() == []

    def test_command_preview(self):
        enc = EncoderParams()
        preview = enc.to_command_preview()
        assert "ffmpeg" in preview
        assert "<input>" in preview
        assert "<output>" in preview


class TestDetectEncoder:
    """NVENC detection must reflect what the machine can *do*, not what ffmpeg lists."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        detect_encoder.cache_clear()
        yield
        detect_encoder.cache_clear()

    def _fake_run(self, monkeypatch, returncode=0, exc=None):
        seen = {}

        def fake(cmd, **kwargs):
            seen["cmd"] = cmd
            if exc is not None:
                raise exc
            return subprocess.CompletedProcess(cmd, returncode, b"", b"")

        monkeypatch.setattr(subprocess, "run", fake)
        return seen

    def _fake_run_per_codec(self, monkeypatch, succeeds: set[str]):
        """A fake where each codec (found via the ``-c:v`` argument) succeeds
        or fails independently, so the probe order can actually be exercised."""
        calls = []

        def fake(cmd, **kwargs):
            codec = cmd[cmd.index("-c:v") + 1]
            calls.append(codec)
            rc = 0 if codec in succeeds else 1
            return subprocess.CompletedProcess(cmd, rc, b"", b"")

        monkeypatch.setattr(subprocess, "run", fake)
        return calls

    def test_successful_trial_encode_selects_nvenc(self, monkeypatch):
        self._fake_run(monkeypatch, returncode=0)
        assert detect_encoder("ffmpeg") == "h264_nvenc"

    def test_failed_trial_encode_falls_back_to_libx264(self, monkeypatch):
        """The CI/distro case: ffmpeg is built with NVENC but there is no driver.

        `ffmpeg -encoders` happily lists h264_nvenc on such a build, so checking
        the listing picked NVENC and every encode then died on libcuda.so.1.
        """
        self._fake_run(monkeypatch, returncode=1)
        assert detect_encoder("ffmpeg") == "libx264"

    def test_missing_ffmpeg_falls_back(self, monkeypatch):
        self._fake_run(monkeypatch, exc=FileNotFoundError())
        assert detect_encoder("nope") == "libx264"

    def test_timeout_falls_back(self, monkeypatch):
        self._fake_run(monkeypatch, exc=subprocess.TimeoutExpired("ffmpeg", 30))
        assert detect_encoder("ffmpeg") == "libx264"

    def test_probe_runs_a_real_encode_not_a_listing(self, monkeypatch):
        seen = self._fake_run(monkeypatch, returncode=0)
        detect_encoder("ffmpeg")
        cmd = seen["cmd"]
        assert "-encoders" not in cmd, "listing an encoder does not prove it works"
        assert "h264_nvenc" in cmd and "-f" in cmd

    def test_result_is_cached_across_calls(self, monkeypatch):
        calls = []

        def fake(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        monkeypatch.setattr(subprocess, "run", fake)
        for _ in range(5):
            detect_encoder("ffmpeg")
        assert len(calls) == 1, "detection is called once per process; it must not re-probe"

    def test_falls_through_to_amf_when_nvenc_fails(self, monkeypatch):
        calls = self._fake_run_per_codec(monkeypatch, succeeds={"h264_amf"})
        assert detect_encoder("ffmpeg") == "h264_amf"
        assert calls == ["h264_nvenc", "h264_amf"]

    def test_falls_through_to_qsv_when_nvenc_and_amf_fail(self, monkeypatch):
        calls = self._fake_run_per_codec(monkeypatch, succeeds={"h264_qsv"})
        assert detect_encoder("ffmpeg") == "h264_qsv"
        assert calls == ["h264_nvenc", "h264_amf", "h264_qsv"]

    def test_falls_back_to_libx264_when_no_hardware_encoder_works(self, monkeypatch):
        calls = self._fake_run_per_codec(monkeypatch, succeeds=set())
        assert detect_encoder("ffmpeg") == "libx264"
        assert calls == ["h264_nvenc", "h264_amf", "h264_qsv"]

    def test_nvenc_is_tried_first_and_short_circuits(self, monkeypatch):
        """A working NVENC must not pay for probing AMF/QSV too."""
        calls = self._fake_run_per_codec(monkeypatch, succeeds={"h264_nvenc", "h264_amf"})
        assert detect_encoder("ffmpeg") == "h264_nvenc"
        assert calls == ["h264_nvenc"]
