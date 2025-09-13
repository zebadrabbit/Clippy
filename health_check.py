"""Environment & dependency sanity check.

Checks:
- ffmpeg and yt-dlp presence and versions (honors local-binary preferences from config)
- NVENC availability (h264_nvenc) for faster GPU encoding (optional)
- Required Python packages (requests, Pillow, yachalk, yt_dlp)
- Directory readiness: cache/, output/, transitions/
- Transitions/static.mp4 presence (warns if missing; runtime can auto-generate)
- Font file presence (Roboto-Medium.ttf)
- Twitch credentials presence in environment (optional)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from config import youtubeDl, ffmpeg, cache, output, fontfile


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
        out = (proc.stdout or b"").decode(errors="ignore") + (proc.stderr or b"").decode(errors="ignore")
        return proc.returncode or 0, out
    except Exception as e:
        return 1, str(e)


# --- Minimal color support (no external deps) ---------------------------------
_CODES = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "gray": "\x1b[90m",
}


def _enable_windows_vt() -> None:
    # Best-effort: enable ANSI sequences in Windows terminals
    try:
        if os.name == "nt":
            import ctypes  # noqa: PLC0415
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:
        pass


def _color_enabled() -> bool:
    if os.getenv("NO_COLOR") is not None:
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def paint(text: str, *styles: str) -> str:
    if not _color_enabled():
        return text
    start = "".join(_CODES.get(s, "") for s in styles if s in _CODES)
    end = _CODES["reset"] if start else ""
    return f"{start}{text}{end}"


def status_tag(kind: str) -> str:
    kinds = {
        "OK": ("OK", "green", "bold"),
        "WARN": ("WARN", "yellow", "bold"),
        "MISSING": ("MISSING", "red", "bold"),
        "INFO": ("INFO", "cyan", "bold"),
    }
    text, *styles = kinds.get(kind, (kind,))
    return paint(f"[{text}]", *styles)


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
        print(f"{status_tag('WARN')} NVENC encoder (h264_nvenc) not found; CPU libx264 will be used if configured")


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


def check_dirs_and_assets(ffmpeg_path: str | None) -> None:
    # cache, output
    for d, label in ((cache, "cache"), (output, "output")):
        if os.path.isdir(d):
            print(f"{status_tag('OK')} {label} dir present: {paint(os.path.abspath(d), 'gray')}")
        else:
            print(f"{status_tag('WARN')} {label} dir missing (will be created on run): {paint(os.path.abspath(d), 'gray')}")
    # transitions folder and static.mp4
    tdir = os.path.abspath(os.path.join(".", "transitions"))
    if os.path.isdir(tdir):
        print(f"{status_tag('OK')} transitions dir present: {paint(tdir, 'gray')}")
    else:
        print(f"{status_tag('WARN')} transitions dir missing (will be created on run): {paint(tdir, 'gray')}")
    static_path = os.path.join(tdir, "static.mp4")
    if os.path.exists(static_path):
        print(f"{status_tag('OK')} transitions/static.mp4 present")
    else:
        if ffmpeg_path:
            print(f"{status_tag('WARN')} transitions/static.mp4 missing; placeholder will be auto-generated on first run")
        else:
            print(f"{status_tag('WARN')} transitions/static.mp4 missing and ffmpeg not found; placeholder cannot be auto-generated")
    # font
    if os.path.exists(fontfile):
        print(f"{status_tag('OK')} font present: {paint(fontfile, 'gray')}")
    else:
        print(f"{status_tag('WARN')} font missing: {paint(fontfile, 'gray')}")


def _parse_env_file(path: str) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
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

    # Look for .env in common locations: CWD and script directory
    candidates = [
        os.path.join(os.getcwd(), ".env"),
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
                print(f"{status_tag('WARN')} .env present but missing: {', '.join(missing)} ({paint(p, 'gray')})")

    if env_ok:
        print(f"{status_tag('OK')} Twitch credentials present in environment")
    elif env_file_ok:
        print(f"{status_tag('INFO')} .env provides credentials; environment variables are optional")
    else:
        if not any_env_found:
            print(f"{status_tag('INFO')} .env not found and environment variables not set.")
        else:
            print(f"{status_tag('INFO')} Twitch credentials not found in environment.")
        print(paint("       Create at https://dev.twitch.tv/console/apps and set TWITCH_CLIENT_ID/SECRET", 'gray'))


def main():
    _enable_windows_vt()
    ok, bin_paths = check_binaries()
    ff = bin_paths.get(ffmpeg)
    if ff:
        check_ffmpeg_features(ff)
    check_python_packages()
    check_dirs_and_assets(ff)
    check_twitch_creds()
    # Exit non-zero only if critical binaries missing
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
