"""Tests for clippy.ffmpeg — EncoderParams."""

from __future__ import annotations

from clippy.ffmpeg import EncoderParams


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
