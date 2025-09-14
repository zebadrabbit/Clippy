from __future__ import annotations

import argparse
import os
import subprocess
from typing import List, Tuple

import sys
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from config import ffmpeg, ffprobe, cache, fps, resolution, bitrate, audio_bitrate, cq, gop, rc_lookahead, spatial_aq, temporal_aq, aq_strength, nvenc_preset
from utils import log, resolve_transitions_dir


def run(cmd: List[str]) -> Tuple[int, bytes, bytes]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        log("Executable not found: " + str(e), 5)
        return 127, b"", str(e).encode()


def probe_has_audio(path: str) -> bool:
    rc, _out, _err = run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", path])
    return rc == 0 and (_out.strip() != b"")


def decode_check(path: str) -> Tuple[bool, str]:
    rc, _out, _err = run([ffmpeg, "-v", "error", "-xerror", "-i", path, "-f", "null", "-"])
    ok = (rc == 0)
    return ok, _err.decode("utf-8", errors="ignore")


def ensure_dir(p: str):
    if not os.path.isdir(p):
        os.makedirs(p, exist_ok=True)


def normalize_asset(src: str, dst: str, loudnorm: bool = True):
    af = ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"] if loudnorm else []
    if probe_has_audio(src):
        cmd = [
            ffmpeg, "-y", "-i", src,
            "-r", str(fps), "-s", str(resolution), "-sws_flags", "lanczos",
            "-c:v", "h264_nvenc", "-rc", "vbr", "-cq", str(cq), "-b:v", "0", "-maxrate", str(bitrate), "-bufsize", str(bitrate),
            "-profile:v", "high", "-level", "4.2", "-g", str(gop), "-bf", "3", "-rc-lookahead", str(rc_lookahead),
            "-spatial_aq", str(spatial_aq), "-aq-strength", str(aq_strength), "-temporal-aq", str(temporal_aq),
            "-pix_fmt", "yuv420p", *af, "-c:a", "aac", "-b:a", str(audio_bitrate), "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-preset", str(nvenc_preset), "-loglevel", "error", "-stats", dst,
        ]
    else:
        # synthesize clean stereo audio when missing
        cmd = [
            ffmpeg, "-y", "-i", src, "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-map", "0:v", "-map", "1:a",
            "-r", str(fps), "-s", str(resolution), "-sws_flags", "lanczos",
            "-c:v", "h264_nvenc", "-rc", "vbr", "-cq", str(cq), "-b:v", "0", "-maxrate", str(bitrate), "-bufsize", str(bitrate),
            "-profile:v", "high", "-level", "4.2", "-g", str(gop), "-bf", "3", "-rc-lookahead", str(rc_lookahead),
            "-spatial_aq", str(spatial_aq), "-aq-strength", str(aq_strength), "-temporal-aq", str(temporal_aq),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", str(audio_bitrate), "-ar", "48000", "-ac", "2", "-shortest",
            "-movflags", "+faststart", "-preset", str(nvenc_preset), "-loglevel", "error", "-stats", dst,
        ]
    rc, _out, _err = run(cmd)
    return rc == 0, _err.decode("utf-8", errors="ignore")


def build_concat_and_check(norm_dir: str, names: List[str]) -> Tuple[bool, str]:
    """Create a concat list that walks through normalized names with statics between where available; audio-only decode check."""
    concat_path = os.path.join(cache, "trans_test_concat")
    static_name = "static.mp4"
    lines: List[str] = []
    def _add(n: str):
        lines.append(f"file _trans/{n}")
    # simple ordering: intros -> static -> others -> static -> outros
    intros = [n for n in names if n.lower().startswith("intro")]
    outros = [n for n in names if n.lower().startswith("outro")]
    static_present = static_name in set(names)
    others = [n for n in names if n not in intros + outros]
    for n in intros:
        _add(n)
        if static_present:
            _add(static_name)
    for n in others:
        _add(n)
        if static_present:
            _add(static_name)
    for n in outros:
        _add(n)
    with open(concat_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    rc, _out, _err = run([ffmpeg, "-v", "error", "-f", "concat", "-safe", "0", "-i", concat_path, "-map", "0:a", "-f", "null", "-"])
    ok = (rc == 0 and _err.decode("utf-8", errors="ignore").strip() == "")
    return ok, _err.decode("utf-8", errors="ignore")


def main():
    ap = argparse.ArgumentParser(description="Probe/validate all transition files")
    ap.add_argument("--normalize", action="store_true", help="Create normalized copies in cache/_trans")
    ap.add_argument("--rebuild", action="store_true", help="Force re-normalize even if outputs exist")
    ap.add_argument("--no-audnorm", action="store_true", help="Disable loudness normalization when normalizing")
    ap.add_argument("--concat-audio-check", action="store_true", help="Build a concat list and run audio-only decode check across all normalized assets")
    args = ap.parse_args()

    tdir = resolve_transitions_dir()
    log("Transitions dir: " + tdir, 1)
    files = [f for f in os.listdir(tdir) if f.lower().endswith(".mp4")]
    files.sort()
    if not files:
        log("No .mp4 files found in transitions directory", 1)
        return 0

    ok_count = 0
    fail_count = 0
    for name in files:
        p = os.path.join(tdir, name)
        has_aud = probe_has_audio(p)
        ok, err = decode_check(p)
        status = "OK" if ok else "FAILED"
        aud = "audio" if has_aud else "no-audio"
        if ok:
            ok_count += 1
            log(f"Probe {name} → {status} ({aud})", 2)
        else:
            fail_count += 1
            log(f"Probe {name} → {status}", 2)
            if err:
                log(err, 5)

    # Normalization pass
    norm_dir = os.path.join(os.path.abspath(cache), "_trans")
    ensure_dir(norm_dir)
    normalized_ok: List[str] = []
    if args.normalize or args.concat_audio_check:
        for name in files:
            src = os.path.join(tdir, name)
            dst = os.path.join(norm_dir, name)
            if (not args.rebuild) and os.path.exists(dst):
                normalized_ok.append(name)
                log("Normalized exists: " + name, 1)
                continue
            ok, err = normalize_asset(src, dst, loudnorm=(not args.no_audnorm))
            if ok:
                normalized_ok.append(name)
                log("Normalized: " + name, 1)
            else:
                log("WARN Failed to normalize: " + name, 2)
                if err:
                    log(err, 5)

    # Concat audio-only decode check over normalized assets
    if args.concat_audio_check and normalized_ok:
        ok, err = build_concat_and_check(norm_dir, normalized_ok)
        if ok:
            log("Concat audio-only check passed", 1)
        else:
            log("Concat audio-only check found errors", 2)
            if err:
                log(err, 5)

    log(f"Summary: ok={ok_count}, failed={fail_count}, files={len(files)}", 2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
