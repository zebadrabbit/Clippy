"""Typed data models for Clippy configuration and pipeline data.

Replaces the previous globals().update() + wildcard-import config system
with proper dataclasses that can be validated, passed as arguments, and tested.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Pipeline data models
# ---------------------------------------------------------------------------


@dataclass
class ClipRow:
    """A single clip ready for the processing pipeline.

    Replaces the previous untyped Tuple[str, float, str, str, int, str].
    """

    id: str
    created_ts: float
    author: str
    avatar_url: str
    view_count: int
    url: str
    title: str = ""
    duration: float = 0.0

    # Backwards-compat: allow positional indexing for migration period
    def __getitem__(self, idx: int) -> Any:
        fields = ("id", "created_ts", "author", "avatar_url", "view_count", "url")
        return getattr(self, fields[idx])


# ---------------------------------------------------------------------------
# Configuration sub-models
# ---------------------------------------------------------------------------


@dataclass
class NvencConfig:
    preset: str = "slow"
    cq: str = "19"
    gop: str = "120"
    rc_lookahead: str = "20"
    aq_strength: str = "8"
    spatial_aq: str = "1"
    temporal_aq: str = "1"


@dataclass
class EncodingConfig:
    bitrate: str = "12M"
    audio_bitrate: str = "192k"
    fps: str = "60"
    resolution: str = "1920x1080"
    container_ext: str = "mp4"
    container_flags: str = "-movflags +faststart"
    yt_format: str = (
        "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]" "/best[ext=mp4][height<=1080]"
    )
    nvenc: NvencConfig = field(default_factory=NvencConfig)


@dataclass
class SelectionConfig:
    clips_per_compilation: int = 12
    compilations: int = 2
    min_views: int = 1


@dataclass
class SequencingConfig:
    transition_probability: float = 0.35
    no_random_transitions: bool = False
    transitions_weights: Dict[str, float] = field(default_factory=dict)
    transition_cooldown: int = 1


@dataclass
class AudioConfig:
    silence_static: bool = False
    audio_normalize_transitions: bool = True


@dataclass
class PathsConfig:
    cache: str = "./cache"
    output: str = "./output"


@dataclass
class BehaviorConfig:
    max_concurrency: int = 4
    skip_bad_clip: bool = True
    rebuild: bool = False
    enable_overlay: bool = True
    transitions_rebuild: bool = False


@dataclass
class AssetsConfig:
    fontfile: str = "assets/fonts/Roboto-Medium.ttf"
    static: str = "static.mp4"
    intro: List[str] = field(default_factory=lambda: ["intro.mp4"])
    outro: List[str] = field(default_factory=lambda: ["outro.mp4"])
    transitions: List[str] = field(
        default_factory=lambda: [
            "transition_01.mp4",
            "transition_02.mp4",
            "transition_03.mp4",
            "transition_05.mp4",
            "transition_07.mp4",
            "transition_08.mp4",
        ]
    )


@dataclass
class DiscordConfig:
    channel_id: Optional[int] = None
    message_limit: int = 200


@dataclass
class IdentityConfig:
    broadcaster: str = ""


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


@dataclass
class ClippyConfig:
    """Complete Clippy configuration, built from YAML/env/CLI layers."""

    encoding: EncodingConfig = field(default_factory=EncodingConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    sequencing: SequencingConfig = field(default_factory=SequencingConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    assets: AssetsConfig = field(default_factory=AssetsConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)

    @classmethod
    def from_merged_dict(cls, d: Dict[str, Any]) -> "ClippyConfig":
        """Build a ClippyConfig from the flat dict produced by load_merged_config()."""
        return cls(
            encoding=EncodingConfig(
                bitrate=str(d.get("bitrate", "12M")),
                audio_bitrate=str(d.get("audio_bitrate", "192k")),
                fps=str(d.get("fps", "60")),
                resolution=str(d.get("resolution", "1920x1080")),
                container_ext=str(d.get("container_ext", "mp4")),
                container_flags=str(d.get("container_flags", "-movflags +faststart")),
                yt_format=str(
                    d.get(
                        "yt_format",
                        "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]"
                        "/best[ext=mp4][height<=1080]",
                    )
                ),
                nvenc=NvencConfig(
                    preset=str(d.get("nvenc_preset", "slow")),
                    cq=str(d.get("cq", "19")),
                    gop=str(d.get("gop", "120")),
                    rc_lookahead=str(d.get("rc_lookahead", "20")),
                    aq_strength=str(d.get("aq_strength", "8")),
                    spatial_aq=str(d.get("spatial_aq", "1")),
                    temporal_aq=str(d.get("temporal_aq", "1")),
                ),
            ),
            selection=SelectionConfig(
                clips_per_compilation=int(d.get("amountOfClips", 12)),
                compilations=int(d.get("amountOfCompilations", 2)),
                min_views=int(d.get("reactionThreshold", 1)),
            ),
            sequencing=SequencingConfig(
                transition_probability=float(d.get("transition_probability", 0.35)),
                no_random_transitions=bool(d.get("no_random_transitions", False)),
                transitions_weights=d.get("transitions_weights", {}),
                transition_cooldown=int(d.get("transition_cooldown", 1)),
            ),
            audio=AudioConfig(
                silence_static=bool(d.get("silence_static", False)),
                audio_normalize_transitions=bool(d.get("audio_normalize_transitions", True)),
            ),
            paths=PathsConfig(
                cache=str(d.get("cache", "./cache")),
                output=str(d.get("output", "./output")),
            ),
            behavior=BehaviorConfig(
                max_concurrency=int(d.get("max_concurrency", 4)),
                skip_bad_clip=bool(d.get("skip_bad_clip", True)),
                rebuild=bool(d.get("rebuild", False)),
                enable_overlay=bool(d.get("enable_overlay", True)),
                transitions_rebuild=bool(d.get("transitions_rebuild", False)),
            ),
            assets=AssetsConfig(
                fontfile=str(d.get("fontfile", "assets/fonts/Roboto-Medium.ttf")),
                static=str(d.get("static", "static.mp4")),
                intro=d.get("intro", ["intro.mp4"]),
                outro=d.get("outro", ["outro.mp4"]),
                transitions=d.get(
                    "transitions",
                    [
                        "transition_01.mp4",
                        "transition_02.mp4",
                        "transition_03.mp4",
                        "transition_05.mp4",
                        "transition_07.mp4",
                        "transition_08.mp4",
                    ],
                ),
            ),
            discord=DiscordConfig(
                channel_id=(
                    int(d["discord_channel_id"])
                    if d.get("discord_channel_id") is not None
                    else None
                ),
                message_limit=int(d.get("discord_message_limit", 200)),
            ),
            identity=IdentityConfig(
                broadcaster=str(d.get("default_broadcaster", "")),
            ),
        )

    def to_flat_dict(self) -> Dict[str, Any]:
        """Produce the flat key-value dict matching the legacy config globals.

        This is the bridge that lets existing replace_vars() and template
        code work unchanged during the migration.
        """
        nv = self.encoding.nvenc
        return {
            # Encoding
            "bitrate": self.encoding.bitrate,
            "audio_bitrate": self.encoding.audio_bitrate,
            "fps": self.encoding.fps,
            "resolution": self.encoding.resolution,
            "container_ext": self.encoding.container_ext,
            "container_flags": self.encoding.container_flags,
            "yt_format": self.encoding.yt_format,
            "nvenc_preset": nv.preset,
            "cq": nv.cq,
            "gop": nv.gop,
            "rc_lookahead": nv.rc_lookahead,
            "aq_strength": nv.aq_strength,
            "spatial_aq": nv.spatial_aq,
            "temporal_aq": nv.temporal_aq,
            # Selection (legacy names)
            "amountOfClips": self.selection.clips_per_compilation,
            "amountOfCompilations": self.selection.compilations,
            "reactionThreshold": self.selection.min_views,
            # Sequencing
            "transition_probability": self.sequencing.transition_probability,
            "no_random_transitions": self.sequencing.no_random_transitions,
            "transitions_weights": self.sequencing.transitions_weights,
            "transition_cooldown": self.sequencing.transition_cooldown,
            # Audio
            "silence_static": self.audio.silence_static,
            "audio_normalize_transitions": self.audio.audio_normalize_transitions,
            # Paths
            "cache": self.paths.cache,
            "output": self.paths.output,
            # Behavior
            "max_concurrency": self.behavior.max_concurrency,
            "skip_bad_clip": self.behavior.skip_bad_clip,
            "rebuild": self.behavior.rebuild,
            "enable_overlay": self.behavior.enable_overlay,
            "transitions_rebuild": self.behavior.transitions_rebuild,
            # Assets
            "fontfile": self.assets.fontfile,
            "static": self.assets.static,
            "intro": list(self.assets.intro),
            "outro": list(self.assets.outro),
            "transitions": list(self.assets.transitions),
            # Discord
            "discord_channel_id": self.discord.channel_id,
            "discord_message_limit": self.discord.message_limit,
            # Identity
            "default_broadcaster": self.identity.broadcaster,
        }

    def replace(self, **kwargs: Any) -> "ClippyConfig":
        """Return a shallow copy with top-level fields replaced."""
        return dataclasses.replace(self, **kwargs)
