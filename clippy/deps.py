"""Fetch the external tools Clippy needs.

Clippy does not ship ffmpeg or yt-dlp. Common Windows ffmpeg builds are GPL
(they include libx264), and bundling one would push that licence onto this
otherwise-MIT project. Downloading on request keeps the two separate: the user
obtains the tool themselves, from its publisher, and Clippy distributes nothing.

Each download is checked against the checksum the publisher publishes alongside
it, so a truncated or tampered file is rejected rather than half-installed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Iterable, Optional

#: Where the binaries land. config.py already prefers ./bin over PATH.
DEFAULT_DEST = "bin"

_UA = {"User-Agent": "clippy-installer"}

TOOLS: dict[str, dict] = {
    "ffmpeg": {
        "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
        "checksum_url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256",
        "checksum_format": "bare",
        "archive": "zip",
        # ffprobe rides along in the same archive; the pipeline needs both.
        "provides": ("ffmpeg.exe", "ffprobe.exe"),
        "licence": "GPL (gyan.dev essentials build, includes libx264)",
    },
    "yt-dlp": {
        "url": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
        "checksum_url": "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS",
        "checksum_format": "sums",
        "checksum_name": "yt-dlp.exe",
        "archive": None,
        "provides": ("yt-dlp.exe",),
        "licence": "Unlicense",
    },
}


def is_windows() -> bool:
    return os.name == "nt"


def missing_tools(dest: str | os.PathLike = DEFAULT_DEST) -> list[str]:
    """Which tools are neither in *dest* nor on PATH."""
    out = []
    for name, spec in TOOLS.items():
        have = all(
            (Path(dest) / provided).is_file() or shutil.which(Path(provided).stem)
            for provided in spec["provides"]
        )
        if not have:
            out.append(name)
    return out


def _fetch(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=timeout) as r:
        return r.read()


def _expected_checksum(spec: dict) -> Optional[str]:
    """The publisher's own hash for this download, or None if unavailable."""
    try:
        body = _fetch(spec["checksum_url"], timeout=30).decode("utf-8", "replace")
    except Exception:
        return None
    if spec.get("checksum_format") == "sums":
        wanted = spec.get("checksum_name", "")
        for line in body.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].strip() == wanted:
                return parts[0].strip().lower()
        return None
    first = body.split()
    return first[0].strip().lower() if first else None


def _download(url: str, target: Path, on_progress: Optional[Callable[[int, int], None]]) -> str:
    """Stream *url* to *target*, returning its sha256."""
    digest = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=120) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(target, "wb") as fh:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(done, total)
    return digest.hexdigest()


def _extract(archive: Path, provides: Iterable[str], dest: Path) -> list[str]:
    """Pull the wanted executables out of a zip, ignoring its directory layout."""
    wanted = {name.lower() for name in provides}
    written: list[str] = []
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            base = os.path.basename(member).lower()
            if base in wanted:
                with zf.open(member) as src, open(dest / os.path.basename(member), "wb") as out:
                    shutil.copyfileobj(src, out)
                written.append(os.path.basename(member))
    return written


def install(
    names: Optional[Iterable[str]] = None,
    dest: str | os.PathLike = DEFAULT_DEST,
    on_progress: Optional[Callable[[str, int, int], None]] = None,
    log: Callable[[str], None] = print,
) -> list[str]:
    """Download *names* into *dest*. Returns the files written.

    Raises RuntimeError if a download does not match the published checksum.
    """
    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    for name in names or list(TOOLS):
        spec = TOOLS.get(name)
        if spec is None:
            log(f"Unknown tool: {name}")
            continue

        log(f"Downloading {name} — {spec['licence']}")
        expected = _expected_checksum(spec)
        if expected is None:
            log(f"  WARNING: no published checksum for {name}; cannot verify the download")

        with tempfile.TemporaryDirectory() as tmp:
            blob = Path(tmp) / f"{name}.download"
            actual = _download(
                spec["url"],
                blob,
                (lambda d, t, _n=name: on_progress(_n, d, t)) if on_progress else None,
            )
            if expected and actual != expected:
                raise RuntimeError(
                    f"{name}: checksum mismatch — expected {expected}, got {actual}. "
                    "The download was discarded."
                )
            if spec["archive"] == "zip":
                got = _extract(blob, spec["provides"], dest_path)
            else:
                target = dest_path / spec["provides"][0]
                shutil.copyfile(blob, target)
                got = [target.name]

        if not got:
            raise RuntimeError(f"{name}: archive did not contain {', '.join(spec['provides'])}")
        for filename in got:
            path = dest_path / filename
            try:  # no-op on Windows, needed everywhere else
                path.chmod(path.stat().st_mode | 0o111)
            except OSError:
                pass
        written.extend(got)
        log(f"  installed {', '.join(got)} to {dest_path}")

    return written


def advice() -> str:
    """What to tell a non-Windows user, where a package manager is the right answer."""
    if sys.platform == "darwin":
        return "Install them with:  brew install ffmpeg yt-dlp"
    return "Install them with your package manager, e.g.:  sudo apt install ffmpeg yt-dlp"
