from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


DEFAULT_CONFIG_FILE = "clippy.yaml"

# Built-in defaults migrated from previous config.py so users don't have to edit Python files.
# These are used when clippy.yaml is absent or partial.
DEFAULTS: Dict[str, Any] = {
    # Selection & counts
    "amountOfClips": 12,
    "amountOfCompilations": 2,
    "reactionThreshold": 1,

    # Sequencing
    "transition_probability": 0.35,
    "no_random_transitions": False,
    "transitions_weights": {},
    "transition_cooldown": 1,

    # Audio policy for non-clip assets
    "audio_normalize_transitions": True,
    "silence_nonclip_asset_audio": False,
    "silence_static": False,
    "silence_transitions": False,
    "silence_intro_outro": False,

    # Encoding
    "bitrate": "12M",
    "audio_bitrate": "192k",
    "fps": "60",
    "resolution": "1920x1080",
    "nvenc_preset": "slow",
    "cq": "19",
    "gop": "120",
    "rc_lookahead": "20",
    "aq_strength": "8",
    "spatial_aq": "1",
    "temporal_aq": "1",

    # Paths & behavior
    "cache": "./cache",
    "output": "./output",
    "max_concurrency": 4,
    "skip_bad_clip": True,
    "rebuild": False,
    "enable_overlay": True,
    "transitions_rebuild": False,

    # Assets & overlay
    "fontfile": "assets/fonts/Roboto-Medium.ttf",
    "static": "static.mp4",
    "intro": ["intro.mp4", "intro_2.mp4"],
    "outro": ["outro.mp4", "outro_2.mp4"],
    "transitions": [
        "transition_01.mp4",
        "transition_02.mp4",
        "transition_03.mp4",
        "transition_05.mp4",
        "transition_07.mp4",
        "transition_08.mp4",
    ],

    # Container & yt-dlp
    "container_ext": "mp4",
    "container_flags": "-movflags +faststart",
    "yt_format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]",
}


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not yaml:
        return {}
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {}
        return data  # type: ignore
    except Exception:
        return {}


def _coerce_bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "y", "on"): return True
        if s in ("0", "false", "no", "n", "off"): return False
    return default


def _coerce_str(v: Any, default: str) -> str:
    return str(v) if isinstance(v, (str, int, float)) else default


def _coerce_int(v: Any, default: int) -> int:
    try:
        return int(v) if v is not None else default
    except Exception:
        return default


def _coerce_float(v: Any, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _coerce_list_str(v: Any, default: list[str]) -> list[str]:
    if isinstance(v, (list, tuple)):
        out: list[str] = []
        for it in v:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, (int, float)):
                out.append(str(it))
        return out if out else default
    return default


def _coerce_dict_float(v: Any, default: dict[str, float]) -> dict[str, float]:
    if isinstance(v, dict):
        out: dict[str, float] = {}
        for k, val in v.items():
            try:
                out[str(k)] = float(val)
            except Exception:
                pass
        return out if out else default
    return default


def load_merged_config(defaults: dict[str, Any] | None = None, env: dict[str, str] | None = None, file_path: str | None = None) -> dict[str, Any]:
    """Merge config from YAML (if exists) and environment onto defaults.

    - defaults: dict of baseline values (from config.py constants)
    - env: environment vars (os.environ if None)
    - file_path: explicit clippy.yaml path (else search in CWD)
    """
    env = env or os.environ
    cfg_path = Path(file_path or DEFAULT_CONFIG_FILE)
    data = _load_yaml(cfg_path)

    # Decompose structured sections to flat keys matching existing config module globals
    base = defaults if defaults is not None else DEFAULTS
    merged = dict(base)

    sel = data.get("selection", {}) if isinstance(data, dict) else {}
    seq = data.get("sequencing", {}) if isinstance(data, dict) else {}
    aud = data.get("audio", {}) if isinstance(data, dict) else {}
    enc = data.get("encoding", {}) if isinstance(data, dict) else {}
    nv  = enc.get("nvenc", {}) if isinstance(enc, dict) else {}
    paths = data.get("paths", {}) if isinstance(data, dict) else {}
    beh = data.get("behavior", {}) if isinstance(data, dict) else {}
    assets = data.get("assets", {}) if isinstance(data, dict) else {}
    identity = data.get("identity", {}) if isinstance(data, dict) else {}

    # Map fields to existing names
    merged["amountOfClips"] = _coerce_int(sel.get("clips_per_compilation"), merged.get("amountOfClips"))
    merged["amountOfCompilations"] = _coerce_int(sel.get("compilations"), merged.get("amountOfCompilations"))
    merged["reactionThreshold"] = _coerce_int(sel.get("min_views"), merged.get("reactionThreshold"))

    merged["transition_probability"] = float(_coerce_float(seq.get("transition_probability"), merged.get("transition_probability", 0.35)))
    merged["no_random_transitions"] = _coerce_bool(seq.get("no_random_transitions"), merged.get("no_random_transitions", False))
    merged["transitions_weights"] = _coerce_dict_float(seq.get("transitions_weights"), merged.get("transitions_weights", {}))
    merged["transition_cooldown"] = _coerce_int(seq.get("transition_cooldown"), merged.get("transition_cooldown", 0))

    merged["silence_nonclip_asset_audio"] = _coerce_bool(aud.get("silence_nonclip_asset_audio"), merged.get("silence_nonclip_asset_audio", False))
    merged["silence_static"] = _coerce_bool(aud.get("silence_static"), merged.get("silence_static", False))
    merged["silence_transitions"] = _coerce_bool(aud.get("silence_transitions"), merged.get("silence_transitions", False))
    merged["silence_intro_outro"] = _coerce_bool(aud.get("silence_intro_outro"), merged.get("silence_intro_outro", False))
    merged["audio_normalize_transitions"] = _coerce_bool(aud.get("audio_normalize_transitions"), merged.get("audio_normalize_transitions", True))

    merged["bitrate"] = _coerce_str(enc.get("bitrate"), merged.get("bitrate"))
    merged["audio_bitrate"] = _coerce_str(enc.get("audio_bitrate"), merged.get("audio_bitrate"))
    merged["fps"] = _coerce_str(enc.get("fps"), merged.get("fps"))
    merged["resolution"] = _coerce_str(enc.get("resolution"), merged.get("resolution"))
    merged["yt_format"] = _coerce_str(enc.get("yt_format"), merged.get("yt_format"))
    merged["container_ext"] = _coerce_str(enc.get("container_ext"), merged.get("container_ext", "mp4"))
    merged["container_flags"] = _coerce_str(enc.get("container_flags"), merged.get("container_flags", "-movflags +faststart"))

    merged["nvenc_preset"] = _coerce_str(nv.get("preset"), merged.get("nvenc_preset"))
    merged["cq"] = _coerce_str(nv.get("cq"), merged.get("cq"))
    merged["gop"] = _coerce_str(nv.get("gop"), merged.get("gop"))
    merged["rc_lookahead"] = _coerce_str(nv.get("rc_lookahead"), merged.get("rc_lookahead"))
    merged["aq_strength"] = _coerce_str(nv.get("aq_strength"), merged.get("aq_strength"))
    merged["spatial_aq"] = _coerce_str(nv.get("spatial_aq"), merged.get("spatial_aq"))
    merged["temporal_aq"] = _coerce_str(nv.get("temporal_aq"), merged.get("temporal_aq"))

    merged["cache"] = _coerce_str(paths.get("cache"), merged.get("cache"))
    merged["output"] = _coerce_str(paths.get("output"), merged.get("output"))

    merged["max_concurrency"] = _coerce_int(beh.get("max_concurrency"), merged.get("max_concurrency", 4))
    merged["skip_bad_clip"] = _coerce_bool(beh.get("skip_bad_clip"), merged.get("skip_bad_clip", True))
    merged["rebuild"] = _coerce_bool(beh.get("rebuild"), merged.get("rebuild", False))
    merged["enable_overlay"] = _coerce_bool(beh.get("enable_overlay"), merged.get("enable_overlay", True))
    merged["transitions_rebuild"] = _coerce_bool(beh.get("transitions_rebuild"), merged.get("transitions_rebuild", False))

    merged["static"] = _coerce_str(assets.get("static"), merged.get("static"))
    merged["intro"] = _coerce_list_str(assets.get("intro"), merged.get("intro", []))
    merged["outro"] = _coerce_list_str(assets.get("outro"), merged.get("outro", []))
    merged["transitions"] = _coerce_list_str(assets.get("transitions"), merged.get("transitions", []))

    # Identity
    merged["default_broadcaster"] = _coerce_str(identity.get("broadcaster"), merged.get("default_broadcaster", ""))

    # Environment overrides (non-secret convenience)
    if env.get("TRANSITIONS_DIR"):
        merged["TRANSITIONS_DIR"] = env.get("TRANSITIONS_DIR")
        # also expose as config.transitions_dir for compatibility with utils
        merged["transitions_dir"] = env.get("TRANSITIONS_DIR")
    if env.get("CLIPPY_USE_INTERNAL"):
        merged["CLIPPY_USE_INTERNAL"] = env.get("CLIPPY_USE_INTERNAL")

    return merged
