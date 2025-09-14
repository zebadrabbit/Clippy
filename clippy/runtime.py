from __future__ import annotations

import os
import sys
from typing import Optional


def _load_env_if_present():
    """Tiny .env loader: sets env vars from a local .env if they aren't set."""
    try:
        env_path = os.path.join(os.getcwd(), ".env")
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        # best-effort; ignore parse errors
        pass


def ensure_twitch_credentials_if_needed():
    """If run in Twitch mode (e.g., --broadcaster), ensure creds are present.
    Shows a helpful message and exits if missing.
    """
    # Detect Twitch mode by common flags; keeps this check non-invasive.
    args = sys.argv[1:]
    broadcaster_requested = ("--broadcaster" in args) or ("-b" in args)
    if not broadcaster_requested:
        return

    # Populate env from .env if present
    _load_env_if_present()

    try:
        from utils import log  # type: ignore
    except Exception:
        def log(msg, level=0):
            print(msg)

    cid = os.getenv("TWITCH_CLIENT_ID") or ""
    secret = os.getenv("TWITCH_CLIENT_SECRET") or ""

    if not cid or not secret:
        log("Twitch credentials missing", 5)
        log("ID and Secret needed: https://dev.twitch.tv/console/apps", 1)
        log("Provide credentials via one of:", 1)
        log("  - .env file: TWITCH_CLIENT_ID=<id>, TWITCH_CLIENT_SECRET=<secret>", 1)
        log("  - PowerShell env vars: $env:TWITCH_CLIENT_ID='...'; $env:TWITCH_CLIENT_SECRET='...'", 1)
        log("  - CLI flags (if supported): --client-id <id> --client-secret <secret>", 1)
        raise SystemExit(2)


def ensure_transitions_static_present(transitions_dir: Optional[str] = None):
    """Resolve transitions directory and require static.mp4 to exist; exit with a helpful error if missing."""
    try:
        from utils import resolve_transitions_dir  # type: ignore
    except Exception:
        def resolve_transitions_dir():
            import os as _os
            return _os.path.abspath(_os.path.join(_os.getcwd(), 'transitions'))
    # Allow override via CLI-provided transitions_dir
    if transitions_dir:
        os.environ['TRANSITIONS_DIR'] = transitions_dir
    tdir = resolve_transitions_dir()
    static_path = os.path.join(tdir, 'static.mp4')
    try:
        from utils import log as _log  # type: ignore
    except Exception:
        def _log(msg, level=0):
            print(msg)
    if not os.path.isdir(tdir):
        _log("Transitions directory missing: " + tdir, 5)
        _log("Place your clips (intro.mp4, static.mp4, outro.mp4) in this folder or provide --transitions-dir.", 1)
        raise SystemExit(2)
    if not os.path.exists(static_path):
        _log("Missing required file: static.mp4 in " + tdir, 5)
        _log("This project requires transitions/static.mp4. Set TRANSITIONS_DIR, use --transitions-dir, or place the file.", 1)
        raise SystemExit(2)
