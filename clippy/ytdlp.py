"""yt-dlp download configuration and command builder.

Replaces the string-template approach in config.py with a typed dataclass
that produces yt-dlp command lists suitable for subprocess.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class YtDlpConfig:
    """Configuration for yt-dlp downloads."""

    binary: str = "yt-dlp"
    format_spec: str = (
        "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]" "/best[ext=mp4][height<=1080]"
    )
    retries: int = 5
    merge_format: str = "mp4"
    ffmpeg_location: str = "ffmpeg"
    extra_args: List[str] = dataclasses.field(default_factory=list)

    # Metadata
    name: str = ""
    description: str = ""

    def to_command(self, url: str, output_path: str) -> List[str]:
        """Build the complete yt-dlp command as a list of tokens."""
        cmd = [
            self.binary,
            "--no-color",
            "--no-check-certificate",
            "--quiet",
            "--progress",
            "--retries",
            str(self.retries),
            "--ffmpeg-location",
            self.ffmpeg_location,
            "--merge-output-format",
            self.merge_format,
            "--format",
            self.format_spec,
            "-o",
            output_path,
        ]
        cmd.extend(self.extra_args)
        cmd.append(url)
        return cmd

    def to_command_str(self, url: str, output_path: str) -> str:
        """Build the command as a single string (for display / legacy compat)."""
        import shlex

        return " ".join(shlex.quote(t) for t in self.to_command(url, output_path))

    @classmethod
    def from_config(
        cls,
        ytdl_binary: str = "yt-dlp",
        ffmpeg_path: str = "ffmpeg",
        format_spec: Optional[str] = None,
    ) -> "YtDlpConfig":
        """Build from resolved binary paths and optional format override."""
        return cls(
            binary=ytdl_binary,
            ffmpeg_location=ffmpeg_path,
            format_spec=format_spec or cls.format_spec,
        )

    def with_overrides(self, **kwargs: Any) -> "YtDlpConfig":
        """Return a copy with specific fields replaced."""
        return dataclasses.replace(self, **kwargs)


# ---------------------------------------------------------------------------
# Download presets
# ---------------------------------------------------------------------------

YTDLP_PRESETS: Dict[str, YtDlpConfig] = {
    "twitch_1080p": YtDlpConfig(
        format_spec=(
            "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]" "/best[ext=mp4][height<=1080]"
        ),
        name="twitch_1080p",
        description="Twitch clips up to 1080p (default)",
    ),
    "twitch_720p": YtDlpConfig(
        format_spec=(
            "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]" "/best[ext=mp4][height<=720]"
        ),
        name="twitch_720p",
        description="Twitch clips up to 720p — smaller downloads",
    ),
    "twitch_source": YtDlpConfig(
        format_spec="bestvideo+bestaudio/best",
        name="twitch_source",
        description="Twitch clips at source quality — best available",
    ),
}


def ytdlp_from_preset(name: str) -> YtDlpConfig:
    """Return a copy of the named yt-dlp preset."""
    if name not in YTDLP_PRESETS:
        available = ", ".join(sorted(YTDLP_PRESETS.keys()))
        raise KeyError(f"Unknown yt-dlp preset '{name}'. Available: {available}")
    return YTDLP_PRESETS[name].with_overrides()
