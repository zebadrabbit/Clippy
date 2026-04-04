"""ffmpeg / ffprobe command builder.

Centralizes all ffmpeg command construction that was previously duplicated
across config.py templates (4 copies) and pipeline.py inline f-strings
(5 copies).  The ``EncoderParams`` dataclass holds every encoding knob;
builder functions compose complete commands from it.

This module has NO side effects — it only produces command strings/lists.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, List, Optional

from clippy.models import ClippyConfig

# ---------------------------------------------------------------------------
# Encoder parameters
# ---------------------------------------------------------------------------


@dataclass
class EncoderParams:
    """Complete set of video + audio encoding parameters.

    Designed so that a single instance can produce the flags for *any* ffmpeg
    command in the pipeline (normalize, overlay, concat, transcode).
    """

    # Video codec
    video_codec: str = "h264_nvenc"
    rate_control: str = "vbr"
    cq: int = 19
    max_bitrate: str = "12M"
    buf_size: str = "12M"  # usually same as max_bitrate
    profile: str = "high"
    level: str = "4.2"
    gop: int = 120
    bf: int = 3
    rc_lookahead: int = 20
    spatial_aq: int = 1
    aq_strength: int = 8
    temporal_aq: int = 1
    pixel_format: str = "yuv420p"
    preset: str = "slow"

    # Video sizing
    resolution: str = "1920x1080"
    fps: str = "60"
    scale_flags: str = "lanczos"

    # Audio
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    audio_sample_rate: int = 48000
    audio_channels: int = 2

    # Container
    container_ext: str = "mp4"
    container_flags: str = "-movflags +faststart"

    # yt-dlp
    yt_format: str = (
        "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]" "/best[ext=mp4][height<=1080]"
    )

    # Metadata
    name: str = ""
    description: str = ""

    # -----------------------------------------------------------------------
    # Flag builders
    # -----------------------------------------------------------------------

    def video_flags(self) -> str:
        """Return the video encoding flags as a single string."""
        if self.video_codec == "libx264":
            return (
                f"-c:v libx264 -crf {self.cq} -maxrate {self.max_bitrate} "
                f"-bufsize {self.buf_size} -profile:v {self.profile} "
                f"-preset {self.preset}"
            )
        # NVENC (h264_nvenc)
        return (
            f"-c:v {self.video_codec} -rc {self.rate_control} "
            f"-cq {self.cq} -b:v 0 -maxrate {self.max_bitrate} -bufsize {self.buf_size} "
            f"-profile:v {self.profile} -level {self.level} "
            f"-g {self.gop} -bf {self.bf} "
            f"-rc-lookahead {self.rc_lookahead} "
            f"-spatial_aq {self.spatial_aq} -aq-strength {self.aq_strength} "
            f"-temporal-aq {self.temporal_aq}"
        )

    def audio_flags(self) -> str:
        """Return the audio encoding flags."""
        return (
            f"-c:a {self.audio_codec} -b:a {self.audio_bitrate} "
            f"-ar {self.audio_sample_rate} -ac {self.audio_channels}"
        )

    def sizing_flags(self) -> str:
        """Return resolution / fps / scaler flags."""
        return f"-r {self.fps} -s {self.resolution} -sws_flags {self.scale_flags}"

    def full_encoding_flags(self) -> str:
        """video + pixel_format + audio, for embedding into any command."""
        return f"{self.video_flags()} -pix_fmt {self.pixel_format} " f"{self.audio_flags()}"

    # -----------------------------------------------------------------------
    # Factories
    # -----------------------------------------------------------------------

    @classmethod
    def from_config(cls, cfg: ClippyConfig) -> "EncoderParams":
        """Build from a ClippyConfig, mapping all relevant fields."""
        nv = cfg.encoding.nvenc
        br = cfg.encoding.bitrate
        return cls(
            video_codec="h264_nvenc",
            cq=int(nv.cq),
            max_bitrate=br,
            buf_size=br,
            gop=int(nv.gop),
            rc_lookahead=int(nv.rc_lookahead),
            spatial_aq=int(nv.spatial_aq),
            aq_strength=int(nv.aq_strength),
            temporal_aq=int(nv.temporal_aq),
            preset=nv.preset,
            resolution=cfg.encoding.resolution,
            fps=cfg.encoding.fps,
            audio_bitrate=cfg.encoding.audio_bitrate,
            container_ext=cfg.encoding.container_ext,
            container_flags=cfg.encoding.container_flags,
            yt_format=cfg.encoding.yt_format,
        )

    @classmethod
    def libx264_fallback(cls, cfg: ClippyConfig) -> "EncoderParams":
        """Build a libx264 encoder config (no GPU needed)."""
        params = cls.from_config(cfg)
        return dataclasses.replace(
            params,
            video_codec="libx264",
            preset="medium",
            name="cpu_only",
            description="CPU encoding (libx264) — no GPU required",
        )

    def with_overrides(self, **kwargs: Any) -> "EncoderParams":
        """Return a copy with specific fields replaced."""
        return dataclasses.replace(self, **kwargs)

    # -----------------------------------------------------------------------
    # Preview / validation
    # -----------------------------------------------------------------------

    def to_command_preview(self) -> str:
        """Human-readable preview of the full ffmpeg encoding flags."""
        parts = [
            "ffmpeg -i <input>",
            self.sizing_flags(),
            self.full_encoding_flags(),
            self.container_flags,
            f"-preset {self.preset}",
            "-y <output>",
        ]
        return " \\\n  ".join(parts)

    def validate(self) -> List[str]:
        """Return a list of warnings about potentially problematic settings."""
        warnings: List[str] = []
        if self.cq <= 10:
            warnings.append(f"cq={self.cq} is very low — expect huge file sizes")
        if self.cq >= 35:
            warnings.append(f"cq={self.cq} is very high — expect visible quality loss")
        try:
            br_num = int(self.max_bitrate.rstrip("MmKk"))
            if "M" in self.max_bitrate or "m" in self.max_bitrate:
                if br_num > 30:
                    warnings.append(f"max_bitrate={self.max_bitrate} is very high")
        except (ValueError, AttributeError):
            pass
        return warnings


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------


def build_normalize_cmd(
    clip_id: str,
    encoder: EncoderParams,
    cache_dir: str,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Build the ffmpeg command to normalize a downloaded clip."""
    return (
        f'{ffmpeg_bin} -i "{cache_dir}/{clip_id}/clip.mp4" '
        f"{encoder.sizing_flags()} "
        f"{encoder.full_encoding_flags()} "
        f"-movflags +faststart -preset {encoder.preset} "
        f'-loglevel error -stats -y "{cache_dir}/{clip_id}/normalized.mp4"'
    )


def build_overlay_cmd(
    clip_id: str,
    author: str,
    encoder: EncoderParams,
    cache_dir: str,
    fontfile: str,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Build the ffmpeg command to apply the author/avatar overlay."""
    # Escape single quotes for drawtext
    safe_author = author.replace("'", "\\'")
    # Normalize font path for ffmpeg on Windows
    safe_font = fontfile.replace("\\", "/")

    filter_complex = (
        '"[0:v]'
        f"drawbox=enable='between(t,3,10)':x=0:y=(ih)-238:h=157:w=1000:color=black@0.7:t=fill,"
        f"drawtext=enable='between(t,3,10)':x=198:y=(h)-190:fontfile='{safe_font}':fontsize=28:fontcolor=white@0.4:text='clip by',"
        f"drawtext=enable='between(t,3,10)':x=198:y=(h)-160:fontfile='{safe_font}':fontsize=48:fontcolor=white@0.9:text='{safe_author}',"
        f"overlay=enable='between(t,3,10)':x=50:y=H-223[overlay]\""
    )

    return (
        f'{ffmpeg_bin} -i "{cache_dir}/{clip_id}/normalized.mp4" '
        f'-i "{cache_dir}/{clip_id}/avatar.png" '
        f"-filter_complex {filter_complex} "
        f'-map "[overlay]" -map "0:a" '
        f"{encoder.sizing_flags()} "
        f"{encoder.full_encoding_flags()} "
        f"-movflags +faststart -preset {encoder.preset} "
        f'-loglevel error -stats -y "{cache_dir}/{clip_id}/{clip_id}.mp4"'
    )


def build_concat_cmd(
    index: int,
    date_str: str,
    encoder: EncoderParams,
    cache_dir: str,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Build the ffmpeg concat-demuxer command for final compilation."""
    ext = encoder.container_ext
    return (
        f'{ffmpeg_bin} -f concat -safe 0 -i "{cache_dir}/comp{index}" '
        f"{encoder.sizing_flags()} "
        f"{encoder.full_encoding_flags()} "
        f"{encoder.container_flags} -preset {encoder.preset} "
        f'-loglevel error -stats -y "{cache_dir}/complete_{date_str}_{index}.{ext}"'
    )


def build_thumbnail_cmd(
    clip_id: str,
    resolution: str,
    cache_dir: str,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Build the ffmpeg command to extract a single-frame thumbnail."""
    return (
        f"{ffmpeg_bin} -ss 00:00:05 "
        f'-i "{cache_dir}/{clip_id}/{clip_id}.mp4" '
        f"-vframes 1 -s {resolution} "
        f'"{cache_dir}/{clip_id}/preview.png"'
    )


def build_transcode_cmd(
    src: str,
    dst: str,
    encoder: EncoderParams,
    ffmpeg_bin: str = "ffmpeg",
    audio_filter: Optional[str] = None,
    force_silent: bool = False,
) -> str:
    """Build the ffmpeg command to transcode a transition asset.

    Args:
        src: input file path
        dst: output file path
        encoder: encoding parameters
        audio_filter: optional audio filter (e.g. "loudnorm=I=-16:TP=-1.5:LRA=11")
        force_silent: synthesize silent audio via anullsrc
    """
    if force_silent:
        return (
            f'{ffmpeg_bin} -i "{src}" '
            f"-f lavfi -i anullsrc=channel_layout=stereo:sample_rate={encoder.audio_sample_rate} "
            f"-map 0:v -map 1:a "
            f"{encoder.sizing_flags()} "
            f"{encoder.video_flags()} -pix_fmt {encoder.pixel_format} "
            f"-c:a {encoder.audio_codec} -b:a {encoder.audio_bitrate} "
            f"-ar {encoder.audio_sample_rate} -ac {encoder.audio_channels} "
            f"-shortest -movflags +faststart -preset {encoder.preset} "
            f'-loglevel error -stats -y "{dst}"'
        )

    af_part = f'-af "{audio_filter}" ' if audio_filter else ""
    return (
        f'{ffmpeg_bin} -i "{src}" '
        f"{encoder.sizing_flags()} "
        f"{encoder.full_encoding_flags()} "
        f"{af_part}"
        f"-movflags +faststart -preset {encoder.preset} "
        f'-loglevel error -stats -y "{dst}"'
    )


def build_ffprobe_duration_cmd(
    path: str,
    ffprobe_bin: str = "ffprobe",
) -> List[str]:
    """Build ffprobe command to get file duration (returns list for subprocess)."""
    return [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]


def build_ffprobe_audio_check_cmd(
    path: str,
    ffprobe_bin: str = "ffprobe",
) -> List[str]:
    """Build ffprobe command to check if a file has an audio stream."""
    return [
        ffprobe_bin,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        path,
    ]


# ---------------------------------------------------------------------------
# NVENC detection
# ---------------------------------------------------------------------------


def detect_encoder(ffmpeg_bin: str = "ffmpeg") -> str:
    """Probe ffmpeg for h264_nvenc support.

    Returns ``"h264_nvenc"`` if NVENC is available, else ``"libx264"``.
    """
    import subprocess

    try:
        result = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "h264_nvenc" in result.stdout:
            return "h264_nvenc"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return "libx264"
