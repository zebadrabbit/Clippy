"""
Import and normalize media into the transitions folder using Clipshow settings.

Usage examples (PowerShell):
  python scripts\import_media.py path\to\my_intro.mov --type intro
  python scripts\import_media.py path\to\clip.mp4 --type transition
  python scripts\import_media.py path\to\outro.mp4 --type outro --name outro_custom.mp4
  python scripts\import_media.py path\to\static.webm --type static --overwrite
  python scripts\import_media.py path\to\many\*.mp4 --type transition

Defaults:
- If --type is omitted, type is inferred from the input filename: contains 'intro', 'outro', or 'static'. Else treated as 'transition'.
- If --name is omitted, a smart name is chosen:
  - transition: transition_XX.mp4 with next number (continuing existing set)
  - intro: intro.mp4, intro_2.mp4, intro_3.mp4, ...
  - outro: outro.mp4, outro_2.mp4, outro_3.mp4, ...
  - static: static.mp4 (single required file)

The output video is encoded to match pipeline settings (H.264 NVENC if available, yuv420p, AAC audio, target FPS/res/bitrate),
with -movflags +faststart when supported.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from typing import Optional, Tuple

# Ensure repository root on path for config/utils
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from clippy.config import (
    aq_strength,
    audio_bitrate,
    bitrate,
    cq,
    ffmpeg,
    fps,
    gop,
    nvenc_preset,
    rc_lookahead,
    resolution,
    spatial_aq,
    temporal_aq,
)

# container flags may not be present in older configs
try:
    from clippy.config import container_flags  # type: ignore
except Exception:
    container_flags = "-movflags +faststart"
try:
    from clippy.config import audio_normalize_transitions  # type: ignore
except Exception:
    audio_normalize_transitions = True

from clippy.utils import log, resolve_transitions_dir


def _run(cmd: str) -> Tuple[int, str]:
    try:
        proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = (proc.stdout or b"").decode(errors="ignore") + (proc.stderr or b"").decode(
            errors="ignore"
        )
        return proc.returncode or 0, out
    except Exception as e:
        return 1, str(e)


def _has_nvenc(ff: str) -> bool:
    code, out = _run(f'"{ff}" -hide_banner -encoders')
    return code == 0 and ("h264_nvenc" in out)


def _ext_is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def infer_type_from_name(path: str) -> str:
    name = os.path.basename(path).lower()
    if "static" in name:
        return "static"
    if "intro" in name:
        return "intro"
    if "outro" in name:
        return "outro"
    return "transition"


def ensure_dir(p: str) -> None:
    os.makedirs(p, exist_ok=True)


def next_transition_name(tdir: str) -> str:
    # Find existing transition_XX.mp4 and continue numbering; width dynamically chosen by max existing
    rx = re.compile(r"^transition_(\d+)\.mp4$")
    nums = []
    width = 2
    try:
        for fn in os.listdir(tdir):
            m = rx.match(fn)
            if m:
                n = int(m.group(1))
                nums.append(n)
                width = max(width, len(m.group(1)))
    except FileNotFoundError:
        pass
    nxt = (max(nums) + 1) if nums else 1
    return f"transition_{nxt:0{width}d}.mp4"


essential_names = {
    "intro": ("intro.mp4", "intro_{}.mp4"),
    "outro": ("outro.mp4", "outro_{}.mp4"),
    "static": ("static.mp4", None),
}


def next_named_variant(tdir: str, kind: str) -> str:
    # intro/outro: base then suffix _2, _3, ... if exists; static is fixed
    base, pattern = essential_names[kind]
    target = os.path.join(tdir, base)
    if kind == "static":
        return base
    if not os.path.exists(target):
        return base
    i = 2
    while True:
        name = pattern.format(i)
        if not os.path.exists(os.path.join(tdir, name)):
            return name
        i += 1


def pick_output_name(tdir: str, kind: str, override: Optional[str]) -> str:
    if override:
        return override if override.lower().endswith(".mp4") else (override + ".mp4")
    if kind == "transition":
        return next_transition_name(tdir)
    if kind in ("intro", "outro", "static"):
        return next_named_variant(tdir, kind)
    # default
    return next_transition_name(tdir)


def build_ffmpeg_cmd(src: str, dst: str, use_nvenc: bool, normalize_audio: bool) -> str:
    vcodec = "h264_nvenc" if use_nvenc else "libx264"
    vrc = f"-rc vbr -cq {cq} -b:v 0 -maxrate {bitrate} -bufsize {bitrate}"
    # libx264 doesn't support -rc vbr/-cq; map approximately to CRF
    if not use_nvenc:
        try:
            cq_int = int(str(cq))
        except Exception:
            cq_int = 19
        # Map NVENC cq ~ 19 to libx264 crf ~ 20
        vrc = f"-crf {max(0, min(51, cq_int+1))} -preset slow"
    _af = " -af loudnorm=I=-16:TP=-1.5:LRA=11" if normalize_audio else ""
    cmd = (
        f'"{ffmpeg}" -y -i "{src}" '
        f"-r {fps} -s {resolution} -sws_flags lanczos "
        f"-c:v {vcodec} {vrc} "
        f"-profile:v high -level 4.2 -g {gop} -bf 3 -rc-lookahead {rc_lookahead} "
        f"-spatial_aq {spatial_aq} -aq-strength {aq_strength} -temporal-aq {temporal_aq} "
        f"-pix_fmt yuv420p{_af} -c:a aac -b:a {audio_bitrate} "
        f"{container_flags} -preset {nvenc_preset} "
        f'"{dst}"'
    )
    if not use_nvenc:
        # remove NVENC-only flags when libx264 is used
        cmd = cmd.replace("-rc-lookahead", "#-rc-lookahead")
        cmd = cmd.replace("-spatial_aq", "#-spatial_aq")
        cmd = cmd.replace("-temporal-aq", "#-temporal-aq")
        cmd = cmd.replace("-aq-strength", "#-aq-strength")
        cmd = re.sub(r"\s-rc\s+vbr\s+-cq\s+\S+\s+-b:v 0\s+-maxrate\s+\S+\s+-bufsize\s+\S+", "", cmd)
        cmd = cmd.replace(f"-preset {nvenc_preset}", "-preset slow")
    return cmd


def import_one(
    src: str, tdir: str, kind: str, name: Optional[str], overwrite: bool, normalize_audio: bool
) -> Optional[str]:
    if not os.path.exists(src):
        log("Input not found: " + src, 5)
        return None
    if not _ext_is_video(src):
        log("Skipping non-video: " + src, 1)
        return None
    ensure_dir(tdir)
    out_name = pick_output_name(tdir, kind, name)
    out_path = os.path.join(tdir, out_name)
    if os.path.exists(out_path) and not overwrite:
        log("Exists (use --overwrite): " + out_path, 1)
        return out_path
    # temp path to avoid partial files
    tmp_path = out_path + ".tmp.mp4"
    use_nv = _has_nvenc(ffmpeg)
    cmd = build_ffmpeg_cmd(src, tmp_path, use_nv, normalize_audio)
    log("Encoding: " + cmd, 1)
    code, out = _run(cmd)
    if code != 0:
        # If NVENC failed, retry with libx264 automatically once
        if use_nv:
            log("NVENC failed, retrying with libx264...", 1)
            cmd2 = build_ffmpeg_cmd(src, tmp_path, use_nvenc=False, normalize_audio=normalize_audio)
            code2, out2 = _run(cmd2)
            if code2 != 0:
                log("Encode failed", 5)
                log(out2, 5)
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
                return None
        else:
            log("Encode failed", 5)
            log(out, 5)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            return None
    # move into place
    try:
        if os.path.exists(out_path):
            if overwrite:
                os.remove(out_path)
            else:
                # pick a variant name if overwrite false and exists
                base, ext = os.path.splitext(out_name)
                i = 2
                while True:
                    cand = f"{base}_{i}{ext}"
                    if not os.path.exists(os.path.join(tdir, cand)):
                        out_path = os.path.join(tdir, cand)
                        break
                    i += 1
        shutil.move(tmp_path, out_path)
    except Exception as e:
        log("Failed to finalize file: " + str(e), 5)
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return None
    log("Imported → " + out_path, 1)
    return out_path


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Normalize and import media to transitions directory")
    ap.add_argument("inputs", nargs="+", help="Input video file(s)")
    ap.add_argument(
        "--type",
        dest="kind",
        choices=["intro", "transition", "outro", "static"],
        help="Asset type (default inferred from filename)",
    )
    ap.add_argument("--name", help="Output file name (mp4). If omitted, a smart name is chosen.")
    ap.add_argument("--transitions-dir", dest="tdir", help="Override transitions directory path")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing output if present")
    ap.add_argument(
        "--no-audio-normalize",
        action="store_true",
        help="Disable loudness normalization on import (default enabled)",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if args.tdir:
        os.environ["TRANSITIONS_DIR"] = args.tdir
    tdir = resolve_transitions_dir()
    ensure_dir(tdir)
    results = []
    for raw in args.inputs:
        # Expand simple globs when invoked via shells that don't expand (Windows PowerShell usually expands, but be safe)
        paths = []
        if any(ch in raw for ch in ("*", "?")):
            import glob

            paths = glob.glob(raw)
        else:
            paths = [raw]
        for src in paths:
            kind = args.kind or infer_type_from_name(src)
            # Default behavior follows config.audio_normalize_transitions unless overridden via CLI flag
            normalize_audio = audio_normalize_transitions and (
                not getattr(args, "no_audio_normalize", False)
            )
            out = import_one(src, tdir, kind, args.name, args.overwrite, normalize_audio)
            if out:
                results.append(out)
    if not results:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
