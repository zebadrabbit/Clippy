"""
Local smoke test for the processing pipeline without Twitch.

What it does:
- Copies transitions/static.mp4 into cache/smoketest/clip.mp4
- Optionally generates a tiny avatar.png for overlay stage
- Runs process_clip (normalize [+ overlay])
- Writes a concat list with the single clip and static
- Runs stage_two to produce a final output file

Usage (PowerShell):
  python .\scripts\smoke_local.py --overlay -y

This exercises Windows path quoting and shell invocation in ffmpeg calls.
"""
from __future__ import annotations

import os
import shutil
import sys
import argparse
from pathlib import Path

# Ensure project root is on sys.path when running from scripts/
_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main():
    ap = argparse.ArgumentParser(description="Local pipeline smoke test (no Twitch)")
    ap.add_argument("--overlay", action="store_true", help="Enable overlay stage (generates avatar.png)")
    ap.add_argument("-y", "--yes", action="store_true", help="Suppress confirmations (unused, kept for consistency)")
    args = ap.parse_args()

    # Prefer debug logging of actual ffmpeg commands
    os.environ["CLIPPY_DEBUG"] = os.environ.get("CLIPPY_DEBUG", "1")

    # Import after env tweaks
    from clippy.config import cache, output
    from clippy import config as _cfg
    from clippy.utils import log, resolve_transitions_dir
    from clippy.pipeline import process_clip, write_concat_file, stage_two

    # Ensure required transitions/static.mp4 exists
    tdir = resolve_transitions_dir()
    static_src = os.path.join(tdir, "static.mp4")
    if not os.path.exists(static_src):
        log("Missing transitions/static.mp4. HealthCheck should ensure this exists.", 5)
        sys.exit(2)

    # Prepare smoketest folder
    clip_id = "smoketest"
    clip_dir = os.path.join(cache, clip_id)
    try:
        shutil.rmtree(clip_dir, ignore_errors=True)
    except Exception:
        pass
    os.makedirs(clip_dir, exist_ok=True)

    # Copy a small sample video as the clip source
    clip_in = os.path.join(clip_dir, "clip.mp4")
    shutil.copy2(static_src, clip_in)

    # Optionally create a simple avatar.png for overlay stage
    if args.overlay:
        try:
            from PIL import Image, ImageDraw
            avatar = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            d = ImageDraw.Draw(avatar)
            d.ellipse((16, 16, 112, 112), fill=(255, 255, 255, 255))
            avatar.save(os.path.join(clip_dir, "avatar.png"), "PNG")
        except Exception:
            # If Pillow is not available in this environment, skip overlay
            args.overlay = False

    # Configure overlay toggle and rebuild behavior
    try:
        _cfg.enable_overlay = bool(args.overlay)
        _cfg.rebuild = True
    except Exception:
        pass

    # Fabricate a ClipRow: (id, created_ts, author, avatar_url, views, url)
    clip = (clip_id, 0.0, "Smoke Test", "", 9999, "")

    log("Running process_clip()", 1)
    rc = process_clip(clip, quiet=False)
    if rc != 0:
        log("process_clip failed", 5)
        sys.exit(3)

    # Write concat for a single-clip compilation (index 0)
    write_concat_file(0, [clip])

    # Perform final concat; provide a deterministic file name via stage_two
    log("Running stage_two()", 1)
    stage_two([[clip]])

    log("Smoke test complete. Check output folder for the final file.", 2)


if __name__ == "__main__":
    main()
