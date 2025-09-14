"""
Validate that a concat file follows the sequencing:
  [intro?] -> static -> (clip -> static -> [transition? -> static])* -> [outro?]

Usage:
  python scripts/check_sequencing.py --comp d:\\Clippy\\cache\\comp0 --transitions-dir d:\\Clippy\\transitions
"""
from __future__ import annotations
import argparse, os, re, sys

CLIP_RE = re.compile(r"^file\s+(?P<id>[^/\\]+)/(?P=id)\.mp4\s*$")


def parse_lines(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]


def _norm_path(line: str) -> str:
    """Return the path portion after 'file ', normalized to forward slashes."""
    if not line.startswith("file "):
        return ""
    p = line[5:].strip()
    return p.replace("\\", "/")


def is_trans(line: str) -> bool:
    """A transition (including intro/outro/static) is a file under transitions dirs.

    We accept normalized assets located under cache/_trans or raw assets under any
    transitions folder reference.
    """
    p = _norm_path(line)
    if not p:
        return False
    # normalized transitions in cache
    if p.startswith("_trans/"):
        return True
    # raw transitions referenced with an absolute/relative transitions folder
    if "/transitions/" in p:
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comp", required=True)
    ap.add_argument("--static", default="static.mp4")
    ap.add_argument("--transitions-dir")
    args = ap.parse_args()

    lines = parse_lines(args.comp)
    if not lines:
        print("EMPTY concat file")
        sys.exit(1)

    def _is_static(line: str) -> bool:
        p = _norm_path(line)
        return p.endswith("/" + args.static) or p.endswith("\\" + args.static) or p.endswith(args.static)

    def _is_clip(line: str) -> bool:
        """Clips are of form '<id>/<id>.mp4' and not under transitions dirs.

        We match strictly to avoid classifying static or other assets as clips.
        """
        p = _norm_path(line)
        if not p or "/" not in p:
            return False
        if p.startswith("_trans/") or "/transitions/" in p:
            return False
        # exactly one slash and filename endswith .mp4
        if p.count("/") != 1 or not p.endswith(".mp4"):
            return False
        dir_name, file_name = p.split("/", 1)
        if "/" in file_name:
            return False
        stem = file_name[:-4]
        if not dir_name or dir_name.startswith("_"):
            return False
        return dir_name == stem

    # Walk the file and verify pattern roughly
    idx = 0
    n = len(lines)

    # Optional intro (any transition asset that's not static)
    if is_trans(lines[idx]) and not _is_static(lines[idx]):
        idx += 1
        if idx >= n or not _is_static(lines[idx]):
            print("Expected static after intro")
            sys.exit(2)
        idx += 1

    saw_clip = False
    while idx < n:
        # clip
        if idx < n and _is_clip(lines[idx]):
            saw_clip = True
            idx += 1
        else:
            break
        # static
        if idx < n and _is_static(lines[idx]):
            idx += 1
        else:
            print("Expected static after clip")
            sys.exit(3)
        # optional transition + static between clips
        if idx < n and is_trans(lines[idx]) and not _is_static(lines[idx]):
            # If there are no more clips ahead, treat this as an outro handled after the loop
            if not any(_is_clip(ln) for ln in lines[idx + 1:]):
                break
            idx += 1
            if idx >= n or not _is_static(lines[idx]):
                print("Expected static after transition")
                sys.exit(4)
            idx += 1

    # Optional outro at the end
    if idx < n and is_trans(lines[idx]) and not _is_static(lines[idx]):
        idx += 1

    if idx != n:
        print(f"Trailing unexpected lines at {idx}/{n}")
        sys.exit(5)
    if not saw_clip:
        print("No clips found")
        sys.exit(6)

    print("Sequencing OK")


if __name__ == "__main__":
    main()
