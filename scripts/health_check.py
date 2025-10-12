"""Environment & dependency sanity check.

Checks:
- ffmpeg and yt-dlp presence and versions (honors local-binary preferences from config)
- NVENC availability (h264_nvenc) for faster GPU encoding (optional)
- Required Python packages (requests, Pillow, yachalk, yt_dlp)
- Directory readiness: cache/, output/, transitions/
- Transitions/static.mp4 presence (REQUIRED)
- Font file presence (Roboto-Medium.ttf)
- Twitch credentials presence in environment (optional)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# Determine repository root (source) and base directory (runtime)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BASE_DIR = ROOT

from clippy.config import cache, ffmpeg, fontfile, output, youtubeDl  # noqa: E402
from clippy.theme import enable_windows_vt, paint, status_tag  # type: ignore  # noqa: E402
from clippy.utils import resolve_transitions_dir  # noqa: E402


def _resolve_exe(name_or_path: str) -> str | None:
    """Return absolute path to executable if found, else None.
    Accepts absolute/relative paths or names to search in PATH.
    """
    # If it's a path and exists, return absolute
    if any(sep in name_or_path for sep in ("/", "\\")) or os.path.isabs(name_or_path):
        p = os.path.abspath(name_or_path)
        return p if os.path.exists(p) else None
    # Else search PATH
    hit = shutil.which(name_or_path)
    return os.path.abspath(hit) if hit else None


def _run(cmd: list[str] | str) -> tuple[int, str]:
    try:
        if isinstance(cmd, str):
            proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = (proc.stdout or b"").decode(errors="ignore") + (proc.stderr or b"").decode(
            errors="ignore"
        )
        return proc.returncode or 0, out
    except Exception as e:
        return 1, str(e)


def _color_enabled() -> bool:
    # Keep for compatibility with paint; theme handles chalk but we still want to avoid styling when redirected
    if os.getenv("NO_COLOR") is not None:
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def check_binaries() -> tuple[bool, dict[str, str | None]]:
    results: dict[str, str | None] = {}
    ok = True
    for tool in (ffmpeg, youtubeDl):
        path = _resolve_exe(tool)
        results[tool] = path
        if not path:
            print(f"{status_tag('MISSING')} {tool} not found")
            ok = False
        else:
            print(f"{status_tag('OK')} {tool} -> {paint(path, 'gray')}")
    return ok, results


def check_ffmpeg_features(ffmpeg_path: str) -> None:
    # Version
    code, out = _run([ffmpeg_path, "-version"])
    if code == 0 and out:
        line1 = out.splitlines()[0] if out.splitlines() else out.strip()
        print(f"{status_tag('OK')} ffmpeg version: {paint(line1, 'gray')}")
    else:
        print(f"{status_tag('WARN')} Could not query ffmpeg version")
    # Encoders
    code, enc = _run([ffmpeg_path, "-hide_banner", "-encoders"])
    if code == 0 and ("h264_nvenc" in enc):
        print(f"{status_tag('OK')} NVENC encoder available: h264_nvenc")
    else:
        print(
            f"{status_tag('WARN')} NVENC encoder (h264_nvenc) not found; CPU libx264 will be used if configured"
        )


def check_python_packages() -> None:
    pkgs = [
        ("requests", "requests"),
        ("Pillow", "PIL"),
        ("yachalk", "yachalk"),
        ("yt_dlp", "yt_dlp"),
    ]
    for display, mod in pkgs:
        try:
            __import__(mod)
            print(f"{status_tag('OK')} Python package: {display}")
        except Exception:
            print(f"{status_tag('MISSING')} Python package: {display}")
    # Optional
    try:
        __import__("discord")
        print(f"{status_tag('OK')} Python package: discord.py (optional)")
    except Exception:
        print(
            f"{status_tag('INFO')} Python package: discord.py not installed (Discord mode optional)"
        )


def check_dirs_and_assets(ffmpeg_path: str | None) -> None:
    # cache, output
    for d, label in ((cache, "cache"), (output, "output")):
        if os.path.isdir(d):
            print(f"{status_tag('OK')} {label} dir present: {paint(os.path.abspath(d), 'gray')}")
        else:
            print(
                f"{status_tag('WARN')} {label} dir missing (will be created on run): {paint(os.path.abspath(d), 'gray')}"
            )
    # transitions folder and static.mp4 (use resolver)
    tdir = os.path.abspath(resolve_transitions_dir())
    if os.path.isdir(tdir):
        print(f"{status_tag('OK')} transitions dir present: {paint(tdir, 'gray')}")
    else:
        print(f"{status_tag('MISSING')} transitions dir missing: {paint(tdir, 'gray')}")
    static_path = os.path.join(tdir, "static.mp4")
    if os.path.exists(static_path):
        print(f"{status_tag('OK')} transitions/static.mp4 present")
    else:
        print(f"{status_tag('MISSING')} transitions/static.mp4 missing (required)")
    # counts for intros/outros/transitions and probability
    try:
        import clippy.config as _cfg

        def _count(names: list[str]) -> int:
            c = 0
            for n in names or []:
                if os.path.exists(os.path.join(tdir, n)):
                    c += 1
            return c

        _intro_cnt = _count(getattr(_cfg, "intro", []))
        _outro_cnt = _count(getattr(_cfg, "outro", []))
        _trans_cnt = _count(getattr(_cfg, "transitions", []))
        _prob = getattr(_cfg, "transition_probability", 0.35)
        _norand = getattr(_cfg, "no_random_transitions", False)
        _weights = getattr(_cfg, "transitions_weights", {})
        _cooldown = getattr(_cfg, "transition_cooldown", 0)
        print(
            f"{status_tag('INFO')} transitions: intro={_intro_cnt}, transitions={_trans_cnt}, outro={_outro_cnt}, prob={_prob}{' (disabled)' if _norand else ''}"
        )
        if _weights:
            print(f"{status_tag('INFO')} transition weights: {paint(str(_weights), 'gray')}")
        if _cooldown:
            print(f"{status_tag('INFO')} transition cooldown: {_cooldown}")
        _sil_st = getattr(_cfg, "silence_static", False)
        _aud_norm = getattr(_cfg, "audio_normalize_transitions", True)
        print(
            f"{status_tag('INFO')} audio: normalize_transitions={_aud_norm}, silence_static={_sil_st}"
        )
    except Exception:
        pass
    # font
    font_abs = (
        os.path.abspath(os.path.join(BASE_DIR, fontfile))
        if not os.path.isabs(fontfile)
        else fontfile
    )
    if os.path.exists(font_abs):
        print(f"{status_tag('OK')} font present: {paint(font_abs, 'gray')}")
    else:
        print(f"{status_tag('WARN')} font missing: {paint(font_abs, 'gray')}")


def _parse_env_file(path: str) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    data[k] = v
    except Exception:
        pass
    return data


def check_twitch_creds() -> None:
    cid_env = os.getenv("TWITCH_CLIENT_ID")
    sec_env = os.getenv("TWITCH_CLIENT_SECRET")
    env_ok = bool(cid_env and sec_env)

    # Look for .env in common locations: CWD, repo root, and script directory
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(BASE_DIR, ".env"),
        os.path.join(ROOT, ".env"),
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".env"),
    ]
    seen = set()
    env_file_ok = False
    any_env_found = False
    for p in candidates:
        if not p or p in seen:
            continue
        seen.add(p)
        if os.path.exists(p):
            any_env_found = True
            data = _parse_env_file(p)
            cid = data.get("TWITCH_CLIENT_ID") or ""
            sec = data.get("TWITCH_CLIENT_SECRET") or ""
            if cid and sec:
                print(f"{status_tag('OK')} Twitch credentials found in .env: {paint(p, 'gray')}")
                env_file_ok = True
            else:
                missing = []
                if not cid:
                    missing.append("TWITCH_CLIENT_ID")
                if not sec:
                    missing.append("TWITCH_CLIENT_SECRET")
                print(
                    f"{status_tag('WARN')} .env present but missing: {', '.join(missing)} ({paint(p, 'gray')})"
                )

    if env_ok:
        print(f"{status_tag('OK')} Twitch credentials present in environment")
    elif env_file_ok:
        print(f"{status_tag('INFO')} .env provides credentials; environment variables are optional")
    else:
        if not any_env_found:
            print(f"{status_tag('INFO')} .env not found and environment variables not set.")
        else:
            print(f"{status_tag('INFO')} Twitch credentials not found in environment.")
        print(
            paint(
                "       Create at https://dev.twitch.tv/console/apps and set TWITCH_CLIENT_ID/SECRET",
                "gray",
            )
        )


def main():
    enable_windows_vt()
    ok, bin_paths = check_binaries()
    ff = bin_paths.get(ffmpeg)
    if ff:
        check_ffmpeg_features(ff)
    check_python_packages()
    check_dirs_and_assets(ff)
    check_twitch_creds()
    # Exit non-zero only if critical binaries missing
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
