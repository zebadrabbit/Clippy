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
    if os.name != "nt":
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
    )
    from clippy.config import (
        amountOfCompilations as DEFAULT_COMPS,
    )
    from clippy.config import (
        audio_bitrate as DEFAULT_AUDIO_BR,
    )
    from clippy.config import (
        bitrate as DEFAULT_BITRATE,
    )
    from clippy.config import (
        cache as DEFAULT_CACHE,
    )
    from clippy.config import (
        fps as DEFAULT_FPS,
    )
    from clippy.config import (
        max_concurrency as DEFAULT_CONC,
    )
    from clippy.config import (
        no_random_transitions as DEFAULT_NO_RANDOM,
    )
    from clippy.config import (
        output as DEFAULT_OUTPUT,
    )
    from clippy.config import (
        reactionThreshold as DEFAULT_MIN_VIEWS,
    )
    from clippy.config import (
        resolution as DEFAULT_RES,
    )
    from clippy.config import (
        silence_static as DEFAULT_SILENCE_STATIC,
    )
    from clippy.config import (
        transition_probability as DEFAULT_TRANS_PROB,
    )

    try:
        from clippy.config_loader import load_merged_config  # type: ignore

        _existing_cfg = load_merged_config() or {}
        # Prefer flattened key produced by loader; fallback to nested identity if present
        DEFAULT_BROADCASTER = (
            _existing_cfg.get("default_broadcaster")
            or (_existing_cfg.get("identity") or {}).get("broadcaster")
            or None
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
    print(
        THEME.text("This will help you get set up with Twitch credentials and sensible defaults.")
    )
    print(THEME.text("You can re-run this anytime; it writes a .env and helper script."))
    print(THEME.bar(bar) + "\n")


def _mask_default(s: str, left: int = 6, right: int = 2) -> str:
    try:
        if not s:
            return s
        if len(s) <= left + right + 3:
            # For very short strings, show first half and last char
            cut = max(1, len(s) // 2)
            return f"{s[:cut]}…{s[-1:]}"
        return f"{s[:left]}…{s[-right:]}"
    except Exception:
        return s


def _prompt_str(label: str, default: Optional[str] = None, secret: bool = False) -> str:
    d = f"{default}" if default not in (None, "") else ""
    while True:
        prompt = THEME.label(label)
        if d:
            disp = _mask_default(d) if secret else d
            prompt += THEME.sep(" [") + THEME.default(disp) + THEME.sep("]")
        prompt += THEME.sep(": ")
        val = input(prompt).strip()
        if not val and default is not None:
            return str(default)
        if val:
            return val
        print(THEME.error("Please enter a value."))


def _prompt_int(
    label: str, default: int, min_v: Optional[int] = None, max_v: Optional[int] = None
) -> int:
    while True:
        prompt = (
            THEME.label(label) + THEME.sep(" [") + THEME.default(str(default)) + THEME.sep("]: ")
        )
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


def _prompt_float(
    label: str, default: float, min_v: Optional[float] = None, max_v: Optional[float] = None
) -> float:
    while True:
        prompt = (
            THEME.label(label) + THEME.sep(" [") + THEME.default(str(default)) + THEME.sep("]: ")
        )
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
        d_colored = (
            THEME.sep("[")
            + THEME.choice_default("Y")
            + THEME.sep("/")
            + THEME.choice_other("n")
            + THEME.sep("]")
        )
    else:
        d_colored = (
            THEME.sep("[")
            + THEME.choice_other("y")
            + THEME.sep("/")
            + THEME.choice_default("N")
            + THEME.sep("]")
        )
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


def _prompt_list_csv(label: str, default: Optional[list[str]] = None) -> tuple[bool, list[str]]:
    """Prompt for a comma/semicolon-separated list of filenames.

    Returns (changed, value). If the user presses Enter, returns (False, default or []).
    To explicitly clear the list, enter '-' or 'none'.
    """
    default_list = list(default or [])
    shown = ", ".join(default_list) if default_list else "(none)"
    while True:
        prompt = THEME.label(label) + THEME.sep(" [") + THEME.default(shown) + THEME.sep("]: ")
        s = input(prompt).strip()
        if not s:
            return False, default_list
        low = s.strip().lower()
        if low in ("-", "none", "[]"):
            return True, []
        # split by comma or semicolon
        parts = [p.strip() for p in s.replace(";", ",").split(",")]
        items = [p for p in parts if p]
        if items:
            return True, items
        print(THEME.error("Please enter one or more names separated by commas, or '-' to clear."))


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
    print(
        THEME.text("  - static.mp4 is placed between every segment to provide a clean cut buffer.")
    )
    print(
        THEME.text(
            "  - You can optionally insert random transitions (video effects) between some clips."
        )
    )
    print(THEME.text("  - Probability controls how often a transition (beyond static) appears."))
    # Removed silencing transitions/intro/outro; only silence_static is supported


def _find_static_candidates() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / "transitions" / "static.mp4",
        root / "cache" / "_trans" / "static.mp4",
    ]
    return [p for p in candidates if p.is_file()]


def main():
    _print_header()

    # Step 0: Choose source of clips
    print(THEME.header("Step 0: Choose your clip source"))
    print(THEME.text("  You can fetch clips directly from Twitch (by broadcaster)"))
    print(THEME.text("  or read links from a specific Discord channel."))
    print(
        THEME.text(
            "  Note: Even in Discord mode, Twitch API credentials are required to resolve clip details."
        )
    )
    print("")
    print(THEME.section("Sources:"))
    print(THEME.text("  1) Twitch (Helix) — fetch recent clips for a broadcaster"))
    print(THEME.text("  2) Discord channel — users paste clip links; we'll read and resolve them"))

    def _prompt_source() -> str:
        while True:
            s = input(
                THEME.label("Select source")
                + THEME.sep(" [")
                + THEME.choice_default("1")
                + THEME.sep("/2]: ")
            ).strip()
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
    print(
        THEME.text("  Get credentials: https://dev.twitch.tv/console/apps (create an application)")
    )
    print(
        THEME.text(
            "  Client Credentials flow is used; redirect URL is not required for clip fetching."
        )
    )
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
    client_id = _prompt_str("Twitch Client ID", cid_default or None, secret=True)
    client_secret = _prompt_str("Twitch Client Secret", sec_default or None, secret=True)

    # Step 2 (Discord only): Discord configuration (moved near top)
    discord_section = None
    discord_token = ""
    if source_choice == "discord":
        print("\n" + THEME.header("Step 2: Discord setup"))
        print(
            THEME.text(
                "  1) Enable Developer Mode in Discord: User Settings -> Advanced -> Developer Mode"
            )
        )
        print(THEME.text("  2) Right-click the target channel -> Copy Channel ID"))
        print(
            THEME.text(
                "  3) Create a bot at https://discord.com/developers/applications and copy the Bot Token (Bot tab)"
            )
        )
        print(THEME.text("  4) Ensure the 'Message Content Intent' is enabled for your bot"))
        print(THEME.text("  5) Invite the bot to your server with permissions to read the channel"))
        # Defaults: from clippy.yaml (via load_merged_config) and .env
        try:
            ch_def = (
                _existing_cfg.get("discord_channel_id") if isinstance(_existing_cfg, dict) else None
            )
            lim_def = (
                int(_existing_cfg.get("discord_message_limit", 200))
                if isinstance(_existing_cfg, dict)
                else 200
            )
        except Exception:
            ch_def = None
            lim_def = 200
        tok_def = existing.get("DISCORD_TOKEN") or os.getenv("DISCORD_TOKEN", "")
        ch = _prompt_str("Discord channel ID (numeric)", str(ch_def) if ch_def else None)
        lim = _prompt_int("Discord message scan limit", lim_def, 1)
        discord_token = _prompt_str(
            "Discord bot token (stored in .env)", tok_def or None, secret=True
        )
        try:
            discord_section = {"channel_id": int(ch), "message_limit": int(lim)}
        except Exception:
            discord_section = {"channel_id": ch, "message_limit": int(lim)}

        # Optional: quick token validation (no-op login)
        def _mask(s: str) -> str:
            try:
                return _mask_default(s)
            except Exception:
                return s

        try:
            # Only attempt if a token string is present
            if discord_token:
                try:
                    import asyncio  # type: ignore

                    import discord  # type: ignore
                except Exception:
                    print(THEME.warn("  Skipping token validation: discord.py not installed"))
                else:

                    async def _login_once(tok: str) -> tuple[bool, str]:
                        try:
                            intents = discord.Intents.none()
                            client = discord.Client(intents=intents)
                            try:
                                await client.login(tok)
                            except discord.LoginFailure:
                                return False, "Invalid Discord token (login failed)"
                            except Exception as e:
                                return False, f"Login error: {e}"
                            finally:
                                try:
                                    await client.close()
                                except Exception:
                                    pass
                            return True, "Discord token login OK"
                        except Exception as e:
                            return False, f"Validation error: {e}"

                    try:
                        ok, msg = asyncio.run(
                            asyncio.wait_for(_login_once(discord_token), timeout=6.0)
                        )
                        if ok:
                            print(THEME.success("  ✔ Discord token validated (login OK)"))
                            print(
                                THEME.text(
                                    "    Ensure 'Message Content Intent' is enabled for your bot in the Developer Portal."
                                )
                            )
                        else:
                            print(THEME.warn("  ⚠ Discord token check: " + msg))
                            print(
                                THEME.text(
                                    "    Tip: Copy the token from the Bot tab (not Application ID/Public Key)."
                                )
                            )
                    except Exception as e:
                        print(THEME.warn(f"  ⚠ Token validation skipped (timeout or error): {e}"))
            else:
                print(
                    THEME.warn(
                        "  No Discord token provided; you'll need DISCORD_TOKEN in .env for --discord mode."
                    )
                )
        except Exception:
            # Non-fatal; continue wizard
            pass

    # Step 3: Defaults for selection and identity (always capture a broadcaster name)
    print("\n" + THEME.header("Step 3: Clip selection & identity"))
    _shown = str(DEFAULT_BROADCASTER) if (DEFAULT_BROADCASTER not in (None, "")) else "(none)"
    print(THEME.text("  Current default broadcaster:") + " " + THEME.path(_shown))
    print(THEME.text("  Even in Discord mode, we use a broadcaster name for naming and defaults."))
    print(
        THEME.text("  Set a default to skip typing --broadcaster each run (leave blank to keep).")
    )
    min_views = _prompt_int("Minimum views to include a clip", DEFAULT_MIN_VIEWS, 0)
    clips_per_comp = _prompt_int("Clips per compilation", DEFAULT_CLIPS, 1)
    num_compilations = _prompt_int("Number of compilations per run", DEFAULT_COMPS, 1)
    default_broadcaster = _prompt_str(
        "Default broadcaster (Twitch username)", DEFAULT_BROADCASTER or ""
    )

    # Step 4: Quality and format
    print("\n" + THEME.header("Step 4: Output quality & format"))
    preset_name, bitrate = _quality_menu()
    resolution = _prompt_str("Resolution (e.g., 1920x1080)", DEFAULT_RES)
    fps = _prompt_str("Framerate (e.g., 60)", DEFAULT_FPS)
    audio_br = _prompt_str("Audio bitrate (e.g., 192k)", DEFAULT_AUDIO_BR)

    # Step 5: Transitions & intros/outros
    _transitions_explain()
    use_random = not _prompt_yes_no("Disable random transitions?", default_yes=DEFAULT_NO_RANDOM)
    trans_prob = DEFAULT_TRANS_PROB
    if use_random:
        trans_prob = _prompt_float(
            "Probability to insert a transition (0.0 - 1.0)", DEFAULT_TRANS_PROB, 0.0, 1.0
        )
    silence_static = _prompt_yes_no("Silence static.mp4 audio?", default_yes=DEFAULT_SILENCE_STATIC)

    # Intro/Outro configuration
    try:
        _existing_intro = (
            _existing_cfg.get("intro") if isinstance(_existing_cfg, dict) else None
        ) or []
    except Exception:
        _existing_intro = []
    try:
        _existing_outro = (
            _existing_cfg.get("outro") if isinstance(_existing_cfg, dict) else None
        ) or []
    except Exception:
        _existing_outro = []
    print("")
    print(THEME.section("Intro/Outro assets (in transitions/)"))
    print(
        THEME.text(
            "  Enter filenames relative to your transitions folder. Press Enter to keep current values."
        )
    )
    print(THEME.text("  Enter '-' or 'none' to clear the list."))
    intro_changed, intro_list = _prompt_list_csv("Intro file(s)", _existing_intro)
    outro_changed, outro_list = _prompt_list_csv("Outro file(s)", _existing_outro)

    # Step 6: Paths & concurrency
    print("\n" + THEME.header("Step 6: Paths & concurrency"))
    cache_dir = _prompt_str("Cache directory", DEFAULT_CACHE)
    output_dir = _prompt_str("Output directory", DEFAULT_OUTPUT)
    conc = _prompt_int("Max concurrent workers (downloads/normalize)", DEFAULT_CONC, 1)

    # Step 7: Transitions location
    print("\n" + THEME.header("Step 7: Transitions directory"))
    print(
        THEME.text(
            "  The tool requires transitions/static.mp4. Place one in transitions/ or set a custom directory."
        )
    )
    trans_dir = _prompt_str("Custom transitions directory (blank to skip)", "")

    # Write .env (merge with existing to avoid dropping values like DISCORD_TOKEN)
    env_out = dict(existing)
    env_out["TWITCH_CLIENT_ID"] = client_id
    env_out["TWITCH_CLIENT_SECRET"] = client_secret
    if trans_dir:
        env_out["TRANSITIONS_DIR"] = trans_dir
    # Preserve TRANSITIONS_DIR if user left blank
    # Update DISCORD_TOKEN only if provided this run (e.g., in Discord mode); otherwise preserve existing
    if discord_token:
        env_out["DISCORD_TOKEN"] = discord_token
    # Emit in a stable order (Twitch first), then others
    ordered_keys = ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "TRANSITIONS_DIR", "DISCORD_TOKEN"]
    other_items = [(k, v) for k, v in env_out.items() if k not in ordered_keys]
    lines = []
    for k in ordered_keys:
        if k in env_out and env_out[k] not in (None, ""):
            lines.append(f"{k}={env_out[k]}")
    for k, v in other_items:
        if v not in (None, ""):
            lines.append(f"{k}={v}")
    try:
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n" + THEME.success(f"Wrote {env_path.resolve()}"))
    except Exception as e:
        print("\n" + THEME.warn(f"WARN: Failed to write .env: {e}"))

    # Write YAML config (clippy.yaml) — preserve existing discord section if not updated this run
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
            "nvenc": {
                "preset": "slow",
                "cq": "19",
                "gop": "120",
                "rc_lookahead": "20",
                "aq_strength": "8",
                "spatial_aq": "1",
                "temporal_aq": "1",
            },
        },
        "paths": {"cache": cache_dir, "output": output_dir},
        "behavior": {
            "max_concurrency": conc,
            "skip_bad_clip": True,
            "rebuild": False,
            "enable_overlay": True,
        },
        "assets": {
            "static": "static.mp4",
        },
        "_meta": {"generated_by": f"setup_wizard v{CLIPPY_VERSION}"},
    }
    # Load existing YAML (if any) to preserve discord block when not provided this run
    existing_yaml = {}
    try:
        import yaml  # type: ignore

        yaml_path = Path("clippy.yaml")
        if yaml_path.is_file():
            existing_yaml = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if not isinstance(existing_yaml, dict):
                existing_yaml = {}
    except Exception:
        existing_yaml = {}
    if discord_section:
        cfg["discord"] = discord_section
    else:
        # Keep prior discord settings if present in file
        try:
            if isinstance(existing_yaml, dict) and existing_yaml.get("discord"):
                cfg["discord"] = existing_yaml.get("discord")
        except Exception:
            pass
    # Merge/preserve assets.intro/outro
    try:
        prior_assets = existing_yaml.get("assets") if isinstance(existing_yaml, dict) else {}
    except Exception:
        prior_assets = {}
    # Apply intro/outro based on user choice; else preserve prior if present
    if intro_changed:
        cfg["assets"]["intro"] = intro_list
    elif isinstance(prior_assets, dict) and prior_assets.get("intro") is not None:
        cfg["assets"]["intro"] = prior_assets.get("intro")
    if outro_changed:
        cfg["assets"]["outro"] = outro_list
    elif isinstance(prior_assets, dict) and prior_assets.get("outro") is not None:
        cfg["assets"]["outro"] = prior_assets.get("outro")
    try:
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
        print(
            THEME.warn(
                "  static.mp4 not found in transitions/. Place one there or set --transitions-dir to a folder that contains it."
            )
        )
    print("\n" + THEME.header("All set! Next steps:"))
    if source_choice == "discord":
        print(THEME.text("  1) Run a compile using Discord as the source:"))
        print(THEME.path("     python .\\main.py --discord -y"))
        print(
            THEME.text("     (Override channel via --discord-channel-id if not set in clippy.yaml)")
        )
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
