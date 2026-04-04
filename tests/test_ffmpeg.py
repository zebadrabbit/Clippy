"""Tests for clippy.ffmpeg — EncoderParams and command builders."""

from __future__ import annotations

from clippy.ffmpeg import (
    EncoderParams,
    build_concat_cmd,
    build_ffprobe_audio_check_cmd,
    build_ffprobe_duration_cmd,
    build_normalize_cmd,
    build_overlay_cmd,
    build_thumbnail_cmd,
    build_transcode_cmd,
)


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


class TestBuildCommands:
    def test_normalize_cmd(self):
        enc = EncoderParams(resolution="1920x1080", fps="60")
        cmd = build_normalize_cmd("clip123", enc, "./cache")
        assert "clip123/clip.mp4" in cmd
        assert "clip123/normalized.mp4" in cmd
        assert "h264_nvenc" in cmd

    def test_overlay_cmd(self):
        enc = EncoderParams()
        cmd = build_overlay_cmd("clip123", "testuser", enc, "./cache", "fonts/Roboto.ttf")
        assert "clip123/normalized.mp4" in cmd
        assert "clip123/avatar.png" in cmd
        assert "testuser" in cmd
        assert "filter_complex" in cmd

    def test_overlay_cmd_escapes_quotes(self):
        enc = EncoderParams()
        cmd = build_overlay_cmd("clip123", "user's name", enc, "./cache", "fonts/Roboto.ttf")
        assert "user\\'s name" in cmd

    def test_concat_cmd(self):
        enc = EncoderParams(container_ext="mp4")
        cmd = build_concat_cmd(0, "2025-09-14", enc, "./cache")
        assert "concat" in cmd
        assert "comp0" in cmd
        assert "complete_2025-09-14_0.mp4" in cmd

    def test_thumbnail_cmd(self):
        cmd = build_thumbnail_cmd("clip123", "1920x1080", "./cache")
        assert "clip123" in cmd
        assert "preview.png" in cmd
        assert "-vframes 1" in cmd

    def test_transcode_cmd_normal(self):
        enc = EncoderParams()
        cmd = build_transcode_cmd("in.mp4", "out.mp4", enc)
        assert '"in.mp4"' in cmd
        assert '"out.mp4"' in cmd
        assert "h264_nvenc" in cmd

    def test_transcode_cmd_force_silent(self):
        enc = EncoderParams()
        cmd = build_transcode_cmd("in.mp4", "out.mp4", enc, force_silent=True)
        assert "anullsrc" in cmd
        assert "-shortest" in cmd

    def test_transcode_cmd_audio_filter(self):
        enc = EncoderParams()
        cmd = build_transcode_cmd("in.mp4", "out.mp4", enc, audio_filter="loudnorm=I=-16")
        assert "loudnorm" in cmd

    def test_ffprobe_duration_cmd(self):
        cmd = build_ffprobe_duration_cmd("test.mp4")
        assert cmd[0] == "ffprobe"
        assert "format=duration" in cmd

    def test_ffprobe_audio_check_cmd(self):
        cmd = build_ffprobe_audio_check_cmd("test.mp4")
        assert "a:0" in cmd
        assert "codec_type" in " ".join(cmd)
