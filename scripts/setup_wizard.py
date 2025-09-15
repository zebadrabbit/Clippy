from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure project root (parent of scripts/) is on sys.path so `clippy` imports work
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Minimal color support via yachalk (fallback to plain)
try:  # pragma: no cover
    from yachalk import chalk  # type: ignore
except Exception:  # pragma: no cover
    class _Plain:
        def __getattr__(self, name):
            return lambda s: s
    chalk = _Plain()  # type: ignore

# --- BBS-style theme (cool cyan/blue/gray) ----------------------------------
class _Theme:
    def __init__(self):
        # Core palette
        self.bar = lambda s: chalk.gray(s)
        self.title = lambda s: chalk.cyan_bright(s)
        self.header = lambda s: chalk.cyan_bright(s)
        self.section = lambda s: chalk.blue(s)
        self.text = lambda s: chalk.gray(s)
        self.path = lambda s: chalk.cyan(s)
        self.success = lambda s: chalk.cyan(s)
        self.warn = lambda s: chalk.magenta(s)
        self.error = lambda s: chalk.magenta(s)
        # Prompt parts
        self.label = lambda s: chalk.cyan(s)
        self.default = lambda s: chalk.blue_bright(s)
        self.sep = lambda s: chalk.gray(s)
        self.choice_default = lambda s: chalk.cyan_bright(s)
        self.choice_other = lambda s: chalk.gray(s)

THEME = _Theme()

# Enable Windows VT so ANSI colors render in default console
def _enable_windows_vt():
    if os.name != 'nt':
        return
    try:  # pragma: no cover
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass

# Try to import project version and defaults
try:
    from clippy import __version__ as CLIPPY_VERSION  # type: ignore
except Exception:
    CLIPPY_VERSION = "unknown"

try:
    # Import defaults for suggestions
    from clippy.config import (
        amountOfClips as DEFAULT_CLIPS,
        amountOfCompilations as DEFAULT_COMPS,
        reactionThreshold as DEFAULT_MIN_VIEWS,
        bitrate as DEFAULT_BITRATE,
        resolution as DEFAULT_RES,
        fps as DEFAULT_FPS,
        audio_bitrate as DEFAULT_AUDIO_BR,
        transition_probability as DEFAULT_TRANS_PROB,
        no_random_transitions as DEFAULT_NO_RANDOM,
        cache as DEFAULT_CACHE,
        output as DEFAULT_OUTPUT,
    max_concurrency as DEFAULT_CONC,
    silence_static as DEFAULT_SILENCE_STATIC,
    )
    try:
        from clippy.config_loader import load_merged_config  # type: ignore
        _existing_cfg = load_merged_config() or {}
        # Prefer flattened key produced by loader; fallback to nested identity if present
        DEFAULT_BROADCASTER = (
            _existing_cfg.get('default_broadcaster') or
            (_existing_cfg.get('identity') or {}).get('broadcaster') or
            None
        )
    except Exception:
        DEFAULT_BROADCASTER = None
except Exception:
    # Fallbacks if config import fails
    DEFAULT_CLIPS = 12
    DEFAULT_COMPS = 2
    DEFAULT_MIN_VIEWS = 1
    DEFAULT_BITRATE = "12M"
    DEFAULT_RES = "1920x1080"
    DEFAULT_FPS = "60"
    DEFAULT_AUDIO_BR = "192k"
    DEFAULT_TRANS_PROB = 0.35
    DEFAULT_NO_RANDOM = False
    DEFAULT_CACHE = "./cache"
    DEFAULT_OUTPUT = "./output"
    DEFAULT_CONC = 4
    DEFAULT_SILENCE_STATIC = False

PS1_HEADER = """"""  # no longer used; keeping symbol to avoid NameError if referenced


def _print_header():
    _enable_windows_vt()
    bar = "=" * 46
    title = THEME.title("Clippy Setup Wizard")
    ver = THEME.text(f"(v{CLIPPY_VERSION})") if CLIPPY_VERSION else ""
    print(THEME.bar(bar))
    print(f"{title}  {ver}")
    print(THEME.text("This will help you get set up with Twitch credentials and sensible defaults."))
    print(THEME.text("You can re-run this anytime; it writes a .env and helper script."))
    print(THEME.bar(bar) + "\n")


def _prompt_str(label: str, default: Optional[str] = None, secret: bool = False) -> str:
    d = f"{default}" if default not in (None, "") else ""
    while True:
        prompt = THEME.label(label)
        if d:
            prompt += THEME.sep(" [") + THEME.default(d) + THEME.sep("]")
        prompt += THEME.sep(": ")
        val = input(prompt).strip()
        if not val and default is not None:
            return str(default)
        if val:
            return val
        print(THEME.error("Please enter a value."))


def _prompt_int(label: str, default: int, min_v: Optional[int] = None, max_v: Optional[int] = None) -> int:
    while True:
        prompt = THEME.label(label) + THEME.sep(" [") + THEME.default(str(default)) + THEME.sep("]: ")
        s = input(prompt).strip()
        if not s:
            return int(default)
        try:
            v = int(s)
            if min_v is not None and v < min_v:
                print(THEME.error(f"Minimum is {min_v}"))
                continue
            if max_v is not None and v > max_v:
                print(THEME.error(f"Maximum is {max_v}"))
                continue
            return v
        except Exception:
            print(THEME.error("Please enter a whole number."))


def _prompt_float(label: str, default: float, min_v: Optional[float] = None, max_v: Optional[float] = None) -> float:
    while True:
        prompt = THEME.label(label) + THEME.sep(" [") + THEME.default(str(default)) + THEME.sep("]: ")
        s = input(prompt).strip()
        if not s:
            return float(default)
        try:
            v = float(s)
            if min_v is not None and v < min_v:
                print(THEME.error(f"Minimum is {min_v}"))
                continue
            if max_v is not None and v > max_v:
                print(THEME.error(f"Maximum is {max_v}"))
                continue
            return v
        except Exception:
            print(THEME.error("Please enter a number."))


def _prompt_yes_no(label: str, default_yes: bool = True) -> bool:
    # Render BBS-style choice with highlighted default
    if default_yes:
        d_colored = THEME.sep("[") + THEME.choice_default("Y") + THEME.sep("/") + THEME.choice_other("n") + THEME.sep("]")
    else:
        d_colored = THEME.sep("[") + THEME.choice_other("y") + THEME.sep("/") + THEME.choice_default("N") + THEME.sep("]")
    while True:
        prompt = THEME.label(label) + THEME.sep(" ") + d_colored + THEME.sep(": ")
        s = input(prompt).strip().lower()
        if not s:
            return default_yes
        if s in ("y", "yes"):
            return True
        if s in ("n", "no"):
            return False
        print(THEME.error("Please answer y or n."))


def _quality_menu() -> tuple[str, str]:
    print("\n" + THEME.section("Quality presets:"))
    print(THEME.text("  1) balanced  (video ~10-12M, good for 1080p60 uploads)"))
    print(THEME.text("  2) high      (video ~12-14M, higher quality, larger files)"))
    print(THEME.text("  3) max       (video ~16M+, best quality, large files)"))
    choice = _prompt_int("Choose quality preset", 1, 1, 3)
    if choice == 1:
        return ("balanced", "10M")
    if choice == 2:
        return ("high", "12M")
    return ("max", "16M")


def _transitions_explain():
    print("\n" + THEME.section("Transitions & sequencing:"))
    print(THEME.text("  - static.mp4 is placed between every segment to provide a clean cut buffer."))
    print(THEME.text("  - You can optionally insert random transitions (video effects) between some clips."))
    print(THEME.text("  - Probability controls how often a transition (beyond static) appears."))
    # Removed silencing transitions/intro/outro; only silence_static is supported


def _find_static_candidates() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "transitions" / "static.mp4",
        root / "_internal" / "transitions" / "static.mp4",
        root / "cache" / "_trans" / "static.mp4",
    ]
    return [p for p in candidates if p.is_file()]


def main():
    _print_header()

    # Step 0: Choose source of clips
    print(THEME.header("Step 0: Choose your clip source"))
    print(THEME.text("  You can fetch clips directly from Twitch (by broadcaster)"))
    print(THEME.text("  or read links from a specific Discord channel."))
    print(THEME.text("  Note: Even in Discord mode, Twitch API credentials are required to resolve clip details."))
    print("")
    print(THEME.section("Sources:"))
    print(THEME.text("  1) Twitch (Helix) — fetch recent clips for a broadcaster"))
    print(THEME.text("  2) Discord channel — users paste clip links; we'll read and resolve them"))
    def _prompt_source() -> str:
        while True:
            s = input(THEME.label("Select source") + THEME.sep(" [") + THEME.choice_default("1") + THEME.sep("/2]: ")).strip()
            if not s:
                return "twitch"
            if s in ("1", "t", "T", "twitch"):
                return "twitch"
            if s in ("2", "d", "D", "discord"):
                return "discord"
            print(THEME.error("Please enter 1 or 2."))
    source_choice = _prompt_source()

    # Step 1: Twitch credentials (required for either source)
    print(THEME.header("Step 1: Twitch Client ID & Secret"))
    print(THEME.text("  Get credentials: https://dev.twitch.tv/console/apps (create an application)"))
    print(THEME.text("  Client Credentials flow is used; redirect URL is not required for clip fetching."))
    env_path = Path(".env")
    existing = {}
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
        except Exception:
            pass
    cid_default = existing.get("TWITCH_CLIENT_ID") or os.getenv("TWITCH_CLIENT_ID", "")
    sec_default = existing.get("TWITCH_CLIENT_SECRET") or os.getenv("TWITCH_CLIENT_SECRET", "")
    client_id = _prompt_str("Twitch Client ID", cid_default or None)
    client_secret = _prompt_str("Twitch Client Secret", sec_default or None)

    # Step 2: Defaults for selection and identity (broadcaster prompt only for Twitch source)
    print("\n" + THEME.header("Step 2: Clip selection & identity"))
    if source_choice == "twitch":
        _shown = str(DEFAULT_BROADCASTER) if (DEFAULT_BROADCASTER not in (None, "")) else "(none)"
        print(THEME.text("  Current default broadcaster:") + " " + THEME.path(_shown))
        print(THEME.text("  Set a default to skip typing --broadcaster each run (leave blank to keep)."))
    min_views = _prompt_int("Minimum views to include a clip", DEFAULT_MIN_VIEWS, 0)
    clips_per_comp = _prompt_int("Clips per compilation", DEFAULT_CLIPS, 1)
    num_compilations = _prompt_int("Number of compilations per run", DEFAULT_COMPS, 1)
    default_broadcaster = ""
    if source_choice == "twitch":
        default_broadcaster = _prompt_str("Default broadcaster", DEFAULT_BROADCASTER or "")

    # Step 3: Quality and format
    print("\n" + THEME.header("Step 3: Output quality & format"))
    preset_name, bitrate = _quality_menu()
    resolution = _prompt_str("Resolution (e.g., 1920x1080)", DEFAULT_RES)
    fps = _prompt_str("Framerate (e.g., 60)", DEFAULT_FPS)
    audio_br = _prompt_str("Audio bitrate (e.g., 192k)", DEFAULT_AUDIO_BR)

    # Step 4: Transitions
    _transitions_explain()
    use_random = not _prompt_yes_no("Disable random transitions?", default_yes=DEFAULT_NO_RANDOM)
    trans_prob = DEFAULT_TRANS_PROB
    if use_random:
        trans_prob = _prompt_float("Probability to insert a transition (0.0 - 1.0)", DEFAULT_TRANS_PROB, 0.0, 1.0)
    silence_static = _prompt_yes_no("Silence static.mp4 audio?", default_yes=DEFAULT_SILENCE_STATIC)

    # Step 5: Paths & concurrency
    print("\n" + THEME.header("Step 5: Paths & concurrency"))
    cache_dir = _prompt_str("Cache directory", DEFAULT_CACHE)
    output_dir = _prompt_str("Output directory", DEFAULT_OUTPUT)
    conc = _prompt_int("Max concurrent workers (downloads/normalize)", DEFAULT_CONC, 1)

    # Step 6: Transitions location
    print("\n" + THEME.header("Step 6: Transitions directory"))
    print(THEME.text("  The tool requires transitions/static.mp4. You can set a custom directory or use the bundled internal data."))
    use_internal = _prompt_yes_no("Prefer bundled internal transitions when available?", default_yes=True)
    trans_dir = _prompt_str("Custom transitions directory (blank to skip)", "")

    # Step 7 (Discord only): Discord configuration
    discord_section = None
    discord_token = ""
    if source_choice == "discord":
        print("\n" + THEME.header("Step 7: Discord setup"))
        print(THEME.text("  1) Enable Developer Mode in Discord: User Settings -> Advanced -> Developer Mode"))
        print(THEME.text("  2) Right-click the target channel -> Copy Channel ID"))
        print(THEME.text("  3) Create a bot at https://discord.com/developers/applications and copy the Bot Token"))
        print(THEME.text("  4) Ensure the 'Message Content Intent' is enabled for your bot"))
        print(THEME.text("  5) Invite the bot to your server with permissions to read the channel"))
        ch = _prompt_str("Discord channel ID (numeric)")
        lim = _prompt_int("Discord message scan limit", 200, 1)
        discord_token = _prompt_str("Discord bot token (stored in .env)")
        try:
            discord_section = {"channel_id": int(ch), "message_limit": int(lim)}
        except Exception:
            discord_section = {"channel_id": ch, "message_limit": int(lim)}

    # Write .env
    lines = [
        f"TWITCH_CLIENT_ID={client_id}",
        f"TWITCH_CLIENT_SECRET={client_secret}",
    ]
    if use_internal:
        lines.append("CLIPPY_USE_INTERNAL=1")
    if trans_dir:
        lines.append(f"TRANSITIONS_DIR={trans_dir}")
    if discord_token:
        lines.append(f"DISCORD_TOKEN={discord_token}")
    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n" + THEME.success(f"Wrote {env_path.resolve()}"))
    except Exception as e:
        print("\n" + THEME.warn(f"WARN: Failed to write .env: {e}"))

    # Write YAML config (clippy.yaml)
    cfg = {
        "selection": {
            "min_views": min_views,
            "clips_per_compilation": clips_per_comp,
            "compilations": num_compilations,
        },
        "identity": {
            "broadcaster": default_broadcaster or None,
        },
        "sequencing": {
            "transition_probability": trans_prob,
            "no_random_transitions": (not use_random),
            "transitions_weights": {},
            "transition_cooldown": 1,
        },
        "audio": {
            "silence_static": silence_static,
            "audio_normalize_transitions": True,
        },
        "encoding": {
            "bitrate": bitrate,
            "audio_bitrate": audio_br,
            "fps": fps,
            "resolution": resolution,
            "nvenc": {"preset": "slow", "cq": "19", "gop": "120", "rc_lookahead": "20", "aq_strength": "8", "spatial_aq": "1", "temporal_aq": "1"},
        },
        "paths": {"cache": cache_dir, "output": output_dir},
        "behavior": {"max_concurrency": conc, "skip_bad_clip": True, "rebuild": False, "enable_overlay": True},
        "assets": {
            "static": "static.mp4",
            # leave lists to file defaults; user can edit later if desired
        },
        "_meta": {"generated_by": f"setup_wizard v{CLIPPY_VERSION}"},
    }
    if discord_section:
        cfg["discord"] = discord_section
    try:
        import yaml  # type: ignore
        yaml_text = yaml.safe_dump(cfg, sort_keys=False)
        yaml_path = Path("clippy.yaml")
        yaml_path.write_text(yaml_text, encoding="utf-8")
        print(THEME.success(f"Wrote {yaml_path.resolve()}"))
    except Exception as e:
        # Fallback to JSON if PyYAML missing
        try:
            json_path = Path("clippy.yaml.json")
            json_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            print(THEME.warn(f"PyYAML not available; wrote JSON fallback: {json_path.resolve()}"))
        except Exception as e2:
            print(THEME.warn(f"WARN: Failed to write config file: {e} / {e2}"))

    # No longer generating run_clippy.ps1; rely on clippy.yaml defaults and CLI overrides

    # Final checks & suggestions
    print("\n" + THEME.section("Final checks:"))
    statics = _find_static_candidates()
    if statics:
        print(THEME.text("  Found static.mp4 here: ") + THEME.path(f"{statics[0]}"))
    else:
        print(THEME.warn("  static.mp4 not found in transitions/. If you don't have one, set CLIPPY_USE_INTERNAL=1 or set --transitions-dir."))
    print("\n" + THEME.header("All set! Next steps:"))
    if source_choice == "discord":
        print(THEME.text("  1) Run a compile using Discord as the source:"))
        print(THEME.path("     python .\\main.py --discord -y"))
        print(THEME.text("     (Override channel via --discord-channel-id if not set in clippy.yaml)"))
    else:
        if default_broadcaster:
            print(THEME.text("  1) Run a compile using your saved defaults:"))
            print(THEME.path("     python .\\main.py -y"))
        else:
            print(THEME.text("  1) Run a compile by providing a broadcaster:"))
            print(THEME.path("     python .\\main.py --broadcaster <name> -y"))
    print(THEME.text("  2) Check output/ for your compiled videos and manifest.json"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSetup cancelled by user.")
