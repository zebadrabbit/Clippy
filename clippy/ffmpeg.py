"""Encoding parameters and encoder detection.

``EncoderParams`` holds every encoding knob and renders the flag groups that
``pipeline.py`` composes its ffmpeg commands from.  ``detect_encoder`` probes
ffmpeg for NVENC support.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, List

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
        """Return the video encoding flags as a single string.

        NVENC's flags (-rc, -cq, -rc-lookahead, -spatial_aq, ...) are specific
        to that encoder and would be rejected by ffmpeg if sent to AMF or QSV,
        so each hardware encoder gets its own branch rather than sharing one
        "everything that isn't libx264" fallback. AMF/QSV intentionally ignore
        ``self.preset`` (an NVENC-tuned value like "slow"/"p4") in favor of
        their own hardcoded good-enough defaults below, rather than adding a
        second preset-name validator alongside x264's.
        """
        if self.video_codec == "libx264":
            # No -preset here: every caller appends it after these flags, and
            # emitting it twice put a duplicate in every libx264 command.
            return (
                f"-c:v libx264 -crf {self.cq} -maxrate {self.max_bitrate} "
                f"-bufsize {self.buf_size} -profile:v {self.profile}"
            )
        if self.video_codec == "h264_amf":
            return (
                f"-c:v h264_amf -quality balanced -rc cqp "
                f"-qp_i {self.cq} -qp_p {self.cq} -maxrate {self.max_bitrate} "
                f"-bufsize {self.buf_size} -profile:v {self.profile}"
            )
        if self.video_codec == "h264_qsv":
            return (
                f"-c:v h264_qsv -preset medium -global_quality {self.cq} "
                f"-maxrate {self.max_bitrate} -bufsize {self.buf_size} -profile:v {self.profile}"
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
# NVENC detection
# ---------------------------------------------------------------------------


#: Hardware encoders to probe, in priority order, before falling back to the
#: CPU. NVENC first (the only one with tuned flags today), then AMD AMF, then
#: Intel QSV.
_HW_ENCODER_PROBE_ORDER = ("h264_nvenc", "h264_amf", "h264_qsv")


def _trial_encode_succeeds(ffmpeg_bin: str, codec: str) -> bool:
    """Run a throwaway encode with *codec*, rather than reading ``ffmpeg -encoders``.

    Distro/vendor ffmpeg builds are routinely compiled with hardware encoder
    support listed even with no matching GPU or driver installed, so the
    listing says nothing about whether encoding will actually work -- it
    fails later (e.g. "Cannot load libcuda.so.1") once every clip has already
    been downloaded.
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=256x256:d=0.1",
                "-c:v",
                codec,
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@lru_cache(maxsize=None)
def detect_encoder(ffmpeg_bin: str = "ffmpeg") -> str:
    """Probe which hardware encoder this machine can actually use, if any.

    Tries NVENC, then AMD AMF, then Intel QSV (``_HW_ENCODER_PROBE_ORDER``),
    each via a real trial encode; the first that succeeds wins. Falls back to
    ``"libx264"`` (CPU) if none do. Cached: the answer cannot change within a
    run, and this is called once per process (not per clip — the result is
    cached across every call).
    """
    for codec in _HW_ENCODER_PROBE_ORDER:
        if _trial_encode_succeeds(ffmpeg_bin, codec):
            return codec
    return "libx264"
