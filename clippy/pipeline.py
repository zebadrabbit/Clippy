"""Video processing pipeline (Discord removed).

Contains generic functions for:
  - Selecting candidate clips from DB (view_count stored in `reactions` column)
  - Downloading clip video via youtube-dl/yt-dlp
  - Avatar/thumbnail handling (avatar may be a Twitch user image or placeholder)
  - Normalizing & overlaying metadata
  - Building ffmpeg concat lists & final compilations
    - Colorizing progress board lines using yachalk

Relies on globals defined in `config.py` and helpers from `utils.py`.
"""

from __future__ import annotations

import json
import logging
import os
import random
import shlex
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from subprocess import Popen
from typing import List, Optional

from yachalk import chalk

try:
    from clippy.theme import THEME, enable_windows_vt  # type: ignore
except ImportError:  # pragma: no cover
    THEME = None  # type: ignore

    def enable_windows_vt():  # type: ignore
        return


import requests
from PIL import Image

from clippy.config import (
    amountOfClips,
    amountOfCompilations,
    aq_strength,
    audio_bitrate,
    bitrate,
    cache,
    cq,
    enable_overlay,
    ffmpeg,
    ffmpegApplyOverlay,
    ffmpegBuildSegments,
    ffmpegCreateThumbnail,
    ffmpegNormalizeVideos,
    ffprobe,
    fps,
    gop,
    nvenc_preset,
    rc_lookahead,
    reactionThreshold,
    rebuild,
    resolution,
    spatial_aq,
    temporal_aq,
    youtubeDl,
    youtubeDlOptions,
)
from clippy.ffmpeg import EncoderParams
from clippy.models import ClipRow
from clippy.utils import (
    find_transition_file,
    log,
    replace_vars,
    resolve_transition_pool,
    resolve_transitions_dir,
)

logger = logging.getLogger(__name__)


def _current_encoder_params() -> EncoderParams:
    """Read the live encoder settings from clippy.config."""
    import clippy.config as _cfg

    return EncoderParams(
        video_codec=str(getattr(_cfg, "video_codec", "h264_nvenc")),
        cq=int(getattr(_cfg, "cq", cq)),
        max_bitrate=str(getattr(_cfg, "bitrate", bitrate)),
        buf_size=str(getattr(_cfg, "bitrate", bitrate)),
        preset=str(getattr(_cfg, "nvenc_preset", nvenc_preset)),
        resolution=str(getattr(_cfg, "resolution", resolution)),
        fps=str(getattr(_cfg, "fps", fps)),
        audio_bitrate=str(getattr(_cfg, "audio_bitrate", audio_bitrate)),
        container_ext=str(getattr(_cfg, "container_ext", "mp4")),
        container_flags=str(getattr(_cfg, "container_flags", "-movflags +faststart")),
        gop=int(getattr(_cfg, "gop", gop)),
        rc_lookahead=int(getattr(_cfg, "rc_lookahead", rc_lookahead)),
        spatial_aq=int(getattr(_cfg, "spatial_aq", spatial_aq)),
        aq_strength=int(getattr(_cfg, "aq_strength", aq_strength)),
        temporal_aq=int(getattr(_cfg, "temporal_aq", temporal_aq)),
    )


def _overlay_filter(author: str, fontfile: str) -> str:
    """Build the drawtext/overlay filter graph for a clip."""
    safe_author = author.replace("'", "\\'")
    safe_font = fontfile.replace("\\", "/")
    return (
        '"[0:v]'
        "drawbox=enable='between(t,3,10)':x=0:y=(ih)-238:h=157:w=1000:color=black@0.7:t=fill,"
        f"drawtext=enable='between(t,3,10)':x=198:y=(h)-190:fontfile='{safe_font}':fontsize=28:fontcolor=white@0.4:text='clip by',"
        f"drawtext=enable='between(t,3,10)':x=198:y=(h)-160:fontfile='{safe_font}':fontsize=48:fontcolor=white@0.9:text='{safe_author}',"
        "overlay=enable='between(t,3,10)':x=50:y=H-223[overlay]\""
    )


SHUTDOWN_EVENT = threading.Event()
_ACTIVE_PROCS: set[Popen] = set()
_PROCS_LOCK = threading.Lock()


def _is_interrupted(err: Optional[bytes | str]) -> bool:
    """Heuristic to determine if a failure was due to user interruption.

    Considers global shutdown flag and common substrings in stderr.
    """
    if SHUTDOWN_EVENT.is_set():
        return True
    try:
        if err is None:
            return False
        s = (
            err.decode("utf-8", errors="ignore")
            if isinstance(err, (bytes, bytearray))
            else str(err)
        )
        s_low = s.lower()
        return (
            ("interrupted" in s_low)
            or ("terminated" in s_low)
            or ("signal" in s_low and "term" in s_low)
        )
    except Exception:  # broad catch: error-detection utility
        return SHUTDOWN_EVENT.is_set()


def _register_proc(p: Popen):
    with _PROCS_LOCK:
        _ACTIVE_PROCS.add(p)


def _unregister_proc(p: Optional[Popen]):
    if p is None:
        return
    with _PROCS_LOCK:
        _ACTIVE_PROCS.discard(p)


def terminate_all_processes(timeout: float = 2.0):
    """Attempt to gracefully terminate any running child processes, then kill."""
    with _PROCS_LOCK:
        procs = list(_ACTIVE_PROCS)
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
        except OSError:
            pass
    # brief wait
    t0 = time.time()
    for p in procs:
        try:
            while p.poll() is None and (time.time() - t0) < timeout:
                time.sleep(0.05)
            if p.poll() is None:
                p.kill()
        except OSError:
            pass
        finally:
            _unregister_proc(p)


def request_shutdown():
    """Signal threads to stop work and terminate child processes."""
    try:
        SHUTDOWN_EVENT.set()
    except Exception:  # broad catch: shutdown safety
        pass
    try:
        terminate_all_processes()
    except Exception:  # broad catch: shutdown safety
        pass


def run_proc(cmd: str, prefer_shell: bool = False):
    """Run a command and return (returncode, stderr_bytes).

    Windows:
      - If prefer_shell is True (needed for -filter_complex), run with shell=True.
      - Otherwise, split simply on spaces and run without shell.
    POSIX:
      - Split with shlex and run without shell.
    """
    if os.name == "nt":
        if prefer_shell:
            try:
                proc = subprocess.run(
                    cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                return proc.returncode, proc.stderr
            except FileNotFoundError:
                try:
                    log("Executable not found (Windows): " + cmd, 5)
                except Exception:  # broad catch: log safety
                    pass
                raise
        else:
            # Use shlex.split with posix=False to preserve quoted segments on Windows
            tokens = shlex.split(cmd, posix=False)
            try:
                proc = subprocess.run(tokens, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return proc.returncode, proc.stderr
            except FileNotFoundError:
                try:
                    log("Executable not found: " + str(tokens[0]), 5)
                    log(cmd, 5)
                except Exception:  # broad catch: log safety
                    pass
                raise
    else:
        tokens = shlex.split(cmd)
        try:
            proc = subprocess.run(tokens, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return proc.returncode, proc.stderr
        except FileNotFoundError:
            try:
                log("Executable not found: " + str(tokens[0]), 5)
                log(cmd, 5)
            except Exception:  # broad catch: log safety
                pass
            raise


def run_proc_cancellable(
    cmd: str, prefer_shell: bool = False, progress_cb: Optional[callable] = None
) -> tuple[int, bytes | None]:
    """Start a subprocess and allow cooperative shutdown.

    - Registers process handle to a global set so Ctrl-C can terminate them.
    - Periodically checks SHUTDOWN_EVENT; if set, terminates the child.
    Returns (returncode, stderr_bytes_or_None).
    """
    if os.name == "nt":
        # Tokenization similar to run_proc; use shell for complex filters when needed
        if prefer_shell:
            args = cmd
            use_shell = True
        else:
            # Respect quoted paths/args
            args = shlex.split(cmd, posix=False)
            use_shell = False
    else:
        args = shlex.split(cmd)
        use_shell = False
    proc: Optional[Popen] = None
    try:
        proc = subprocess.Popen(
            args,
            shell=use_shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="ignore",
        )
        _register_proc(proc)
    except FileNotFoundError:
        # mirror run_proc error messaging
        try:
            if use_shell:
                log("Executable not found: " + str(cmd), 5)
            else:
                log("Executable not found: " + str(args[0]), 5)
                log((cmd if isinstance(cmd, str) else str(cmd)), 5)
        except Exception:  # broad catch: log safety
            pass
        raise
    # Progress/err reader (reads stderr for -progress pipe:2 lines)
    _err_lines = deque(maxlen=200)
    _reader_stop = threading.Event()

    def _reader():
        try:
            while not _reader_stop.is_set() and proc and proc.poll() is None:
                line = proc.stderr.readline()
                if line == "":
                    # EOF or no data yet; avoid tight loop
                    time.sleep(0.02)
                    continue
                line_str = line.strip()
                if progress_cb and (
                    "out_time=" in line_str
                    or "out_time_ms=" in line_str
                    or line_str.startswith("progress=")
                ):
                    info: dict = {}
                    try:
                        if line_str.startswith("out_time="):
                            # format hh:mm:ss.micro
                            t = line_str.split("=", 1)[1]
                            # parse to seconds
                            hms, _, frac = t.partition(".")
                            h, m, s = hms.split(":")
                            secs = int(h) * 3600 + int(m) * 60 + float(s)
                            if frac:
                                secs += float("0." + "".join(c for c in frac if c.isdigit()))
                            info["out_time"] = float(secs)
                        elif line_str.startswith("out_time_ms="):
                            ms = float(line_str.split("=", 1)[1])
                            info["out_time"] = ms / 1_000_000.0
                        elif line_str.startswith("progress="):
                            info["progress"] = line_str.split("=", 1)[1]
                        if info:
                            progress_cb(info)
                        continue
                    except (ValueError, TypeError):
                        # fall through and buffer
                        pass
                # buffer any non-progress diagnostics
                _err_lines.append(line_str)
        except Exception:  # broad catch: thread reader safety
            pass

    _t = threading.Thread(target=_reader, daemon=True)
    _t.start()

    # Wait loop with cooperative shutdown
    stderr_data: Optional[bytes] = None
    try:
        while True:
            if SHUTDOWN_EVENT.is_set():
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        # give it a moment then force
                        for _ in range(10):
                            if proc.poll() is not None:
                                break
                            time.sleep(0.05)
                        if proc.poll() is None:
                            proc.kill()
                except OSError:
                    pass
                return 1, b"interrupted"
            rc = proc.poll()
            if rc is not None:
                # Completed
                try:
                    # ensure reader stops
                    _reader_stop.set()
                    try:
                        proc.stdout.close()
                    except OSError:
                        pass
                    try:
                        proc.stderr.close()
                    except OSError:
                        pass
                    # capture buffered diagnostics
                    stderr_data = (
                        ("\n".join(list(_err_lines))).encode("utf-8", errors="ignore")
                        if _err_lines
                        else None
                    )
                except Exception:  # broad catch: cleanup encoding
                    stderr_data = None
                return rc, stderr_data
            # still running
            time.sleep(0.05)
    finally:
        _reader_stop.set()
        try:
            _t.join(timeout=0.2)
        except Exception:  # broad catch: thread cleanup
            pass
        _unregister_proc(proc)


def _ffprobe_duration(path: str) -> Optional[float]:
    """Return media duration in seconds using ffprobe, or None on failure."""
    try:
        out = subprocess.check_output(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            universal_newlines=True,
            encoding="utf-8",
            errors="ignore",
        )
        val = out.strip()
        return float(val) if val else None
    except (subprocess.CalledProcessError, FileNotFoundError, OSError, ValueError):
        return None


def _sum_concat_duration(index: int) -> Optional[float]:
    """Sum durations of files referenced by cache/comp{index} for progress percent.

    Returns total seconds or None if the concat file is missing or no inputs found.
    """
    try:
        concat_path = os.path.join(cache, f"comp{index}")
        if not os.path.exists(concat_path):
            return None
        total = 0.0
        with open(concat_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("file "):
                    continue
                rel = line.split(" ", 1)[1].strip().strip("'\"")
                # Paths in concat are relative to cache
                src = os.path.join(cache, rel)
                # Normalize separators
                src = os.path.abspath(src)
                dur = _ffprobe_duration(src)
                if isinstance(dur, (int, float)) and dur > 0:
                    total += float(dur)
        return total if total > 0 else None
    except (OSError, ValueError):
        return None


def ensure_dir(path: str):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def download_avatar(clip: ClipRow, quiet: bool = False) -> int:
    clip_dir = os.path.join(cache, clip.id)
    ensure_dir(clip_dir)
    png_path = os.path.join(clip_dir, "avatar.png")
    webp_path = os.path.join(clip_dir, "avatar.webp")
    if os.path.isfile(png_path):
        return 2
    url = clip.avatar_url or "https://static-cdn.jtvnw.net/jtv_user_pictures/x.png"
    if not quiet:
        log(f"Avatar: {url}", 1)
    resp = requests.get(url)
    if resp.status_code >= 400:
        log("Avatar fetch failed; using placeholder", 2)
        return 1
    with open(webp_path, "wb") as f:
        f.write(resp.content)
    try:
        with Image.open(webp_path) as img:
            img.thumbnail((128, 128))
            img.save(png_path, "PNG")
    finally:
        try:
            os.remove(webp_path)
        except FileNotFoundError:
            pass
    return 0


def download_clip(clip: ClipRow, quiet: bool = False) -> int:
    clip_dir = os.path.join(cache, clip.id)
    ensure_dir(clip_dir)
    final_path = os.path.join(clip_dir, f"{clip.id}.mp4")
    if os.path.isfile(final_path) and not rebuild:
        return 2
    cmd = youtubeDl + " " + replace_vars(youtubeDlOptions, clip) + " " + clip.url
    if SHUTDOWN_EVENT.is_set():
        return 1
    rc, err = run_proc_cancellable(cmd, prefer_shell=False)
    if rc != 0:
        # Decode error for inspection
        err_txt = (
            err.decode("utf-8", errors="ignore")
            if isinstance(err, (bytes, bytearray))
            else str(err)
        )
        if not quiet:
            log("Clip download error", 5)
            log(err_txt, 5)
        return 1
    return 0


def _retry(fn, attempts: int = 3, backoff: float = 1.5):
    last = None
    for i in range(attempts):
        if SHUTDOWN_EVENT.is_set():
            return 1
        rc = fn()
        if rc == 0 or rc == 2:
            return rc
        last = rc
        try:
            time.sleep(backoff * (i + 1))
        except Exception:  # broad catch: sleep may be interrupted
            pass
    return last if last is not None else 1


def create_thumbnail(clip: ClipRow) -> int:
    clip_dir = os.path.join(cache, clip.id)
    preview = os.path.join(clip_dir, "preview.png")
    if os.path.isfile(preview) and not rebuild:
        return 2
    if SHUTDOWN_EVENT.is_set():
        return 1
    rc, err = run_proc_cancellable(
        ffmpeg + " " + replace_vars(ffmpegCreateThumbnail, clip), prefer_shell=False
    )
    if rc != 0:
        log("Thumbnail generation failed", 5)
        log(err, 5)
        return 1
    try:
        with Image.open(preview) as img:
            img.thumbnail((128, 128))
            img.save(preview, "PNG")
    except (OSError, ValueError) as e:
        log(f"Thumbnail resize error: {e}", 5)
        return 1
    return 0


def process_clip(
    clip: ClipRow,
    quiet: bool = False,
    on_norm_progress: Optional[callable] = None,
    on_overlay_progress: Optional[callable] = None,
) -> int:
    import clippy.config as _cfg_mod

    clip_dir = os.path.join(cache, clip.id)
    final_path = os.path.join(clip_dir, f"{clip.id}.mp4")
    if os.path.isfile(final_path) and not rebuild:
        return 2
    if not quiet:
        log("Normalizing", 1)
    if SHUTDOWN_EVENT.is_set():
        return 1
    enc = _current_encoder_params()
    # inject ffmpeg progress flags
    _norm_cmd = (
        f'{ffmpeg} -i "{cache}/{clip.id}/clip.mp4" '
        f"{enc.sizing_flags()} "
        f"{enc.full_encoding_flags()} "
        f"{enc.container_flags} -preset {enc.preset} "
        f'-loglevel error -stats -y "{cache}/{clip.id}/normalized.mp4"'
    )
    # Inject loudnorm for clip audio normalization if enabled
    try:
        from clippy.config import audio_normalize_clips as _audio_norm_clips  # type: ignore
    except ImportError:
        _audio_norm_clips = True
    if _audio_norm_clips and " -movflags " in _norm_cmd:
        _norm_cmd = _norm_cmd.replace(
            " -movflags ", " -af loudnorm=I=-16:TP=-1.5:LRA=11 -movflags "
        )
    # Ensure we suppress ffmpeg periodic stats when using -progress
    if " -stats " in _norm_cmd:
        _norm_cmd = _norm_cmd.replace(" -stats ", " -nostats -progress pipe:2 ")
    else:
        # prefer appending both flags
        if " -progress " not in _norm_cmd:
            _norm_cmd += " -progress pipe:2"
        if " -nostats" not in _norm_cmd:
            _norm_cmd += " -nostats"
    # probe duration for progress percentage
    _in_norm = os.path.join(os.path.join(cache, clip.id), "clip.mp4")
    _dur = _ffprobe_duration(_in_norm)

    def _norm_cb(info: dict):
        if on_norm_progress and "out_time" in info and _dur:
            try:
                on_norm_progress(info["out_time"], _dur)
            except Exception:  # broad catch: callback safety
                pass

    # Debug: show the full command when CLIPPY_DEBUG is set
    try:
        if os.getenv("CLIPPY_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
            log("ffmpeg normalize cmd: " + _norm_cmd, 1)
    except Exception:  # broad catch: debug logging safety
        pass
    rc, err = run_proc_cancellable(
        _norm_cmd, prefer_shell=True, progress_cb=_norm_cb if on_norm_progress else None
    )
    if rc != 0:
        if _is_interrupted(err):
            log("Normalization interrupted by user", 2)
        else:
            log("Normalization failed", 5)
            log(err, 5)
        return 1
    try:
        os.remove(os.path.join(clip_dir, "clip.mp4"))
    except FileNotFoundError:
        pass
    if enable_overlay:
        if not quiet:
            log("Overlay", 1)
        if SHUTDOWN_EVENT.is_set():
            return 1
        _ovl_cmd = (
            f'{ffmpeg} -i "{cache}/{clip.id}/normalized.mp4" '
            f'-i "{cache}/{clip.id}/avatar.png" '
            f'-filter_complex {_overlay_filter(clip.author, _cfg_mod.fontfile)} '
            f'-map "[overlay]" -map "0:a" '
            f"{enc.sizing_flags()} "
            f"{enc.full_encoding_flags()} "
            f"{enc.container_flags} -preset {enc.preset} "
            f'-loglevel error -stats -y "{cache}/{clip.id}/{clip.id}.mp4"'
        )
        if " -stats " in _ovl_cmd:
            _ovl_cmd = _ovl_cmd.replace(" -stats ", " -nostats -progress pipe:2 ")
        else:
            if " -progress " not in _ovl_cmd:
                _ovl_cmd += " -progress pipe:2"
            if " -nostats" not in _ovl_cmd:
                _ovl_cmd += " -nostats"

        def _ovl_cb(info: dict):
            if on_overlay_progress and "out_time" in info and _dur:
                try:
                    on_overlay_progress(info["out_time"], _dur)
                except Exception:  # broad catch: callback safety
                    pass

        try:
            if os.getenv("CLIPPY_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
                log("ffmpeg overlay cmd: " + _ovl_cmd, 1)
        except Exception:  # broad catch: debug logging safety
            pass
        rc, err = run_proc_cancellable(
            _ovl_cmd, prefer_shell=True, progress_cb=_ovl_cb if on_overlay_progress else None
        )
        if rc != 0:
            if _is_interrupted(err):
                log("Overlay interrupted by user", 2)
            else:
                log("Overlay failed", 5)
                log(err, 5)
            return 1
    else:
        # If overlay disabled, use normalized as final
        try:
            os.replace(os.path.join(clip_dir, "normalized.mp4"), final_path)
        except OSError:
            pass
    try:
        os.remove(os.path.join(clip_dir, "normalized.mp4"))
    except FileNotFoundError:
        pass
    return 0


def create_compilations_from(
    clips: List[ClipRow],
    target_duration_secs: float = 0,
) -> List[List[ClipRow]]:
    """Split clips into compilations by count or by target duration.

    When *target_duration_secs* > 0, clips are added to each compilation
    until the cumulative duration reaches the target.  Otherwise the
    legacy count-based logic is used.
    """
    # Read live values from config module (not stale module-level imports)
    import clippy.config as _cfg

    _clips_per = getattr(_cfg, "amountOfClips", amountOfClips)
    _num_comps = getattr(_cfg, "amountOfCompilations", amountOfCompilations)
    _threshold = getattr(_cfg, "reactionThreshold", reactionThreshold)
    # filter by view threshold (reactions reused as views)
    eligible = [c for c in clips if c.view_count >= _threshold]
    random.shuffle(eligible)
    compilations: List[List[ClipRow]] = []

    if target_duration_secs > 0:
        # Duration-based splitting
        while eligible and len(compilations) < _num_comps:
            comp: List[ClipRow] = []
            running = 0.0
            while eligible:
                clip = eligible[0]
                clip_dur = clip.duration if clip.duration > 0 else 30.0  # fallback
                if comp and running + clip_dur > target_duration_secs:
                    break
                comp.append(eligible.pop(0))
                running += clip_dur
            if comp:
                compilations.append(comp)
                log(
                    f"Compilation {len(compilations)}: " f"{len(comp)} clips, ~{running:.0f}s",
                    2,
                )
    else:
        # Count-based splitting.
        # If there aren't enough clips to fully fill every compilation, distribute
        # evenly rather than front-loading comp 1 and leaving comp N short.
        total_needed = _clips_per * _num_comps
        if 0 < len(eligible) < total_needed:
            per = max(1, len(eligible) // _num_comps)
            log(
                f"Only {len(eligible)} clips available for {_num_comps} compilations "
                f"(needed {total_needed}); distributing {per} per compilation",
                2,
            )
        else:
            per = _clips_per
        while eligible and len(compilations) < _num_comps:
            compilations.append(eligible[:per])
            eligible = eligible[per:]

    log(f"Created {len(compilations)} compilations", 2)
    return compilations


def transcode_asset(
    name, transitions_abs, assets_out_dir, rel_assets_dir, asset_manifest, manifest_path
):
    """Transcode a transition/intro/outro asset to a normalized cache copy."""
    if not name:
        return None
    # Resolve asset path across known roots to avoid false missing warnings
    src = find_transition_file(name) or os.path.join(transitions_abs, name)
    if not os.path.exists(src):
        try:
            log("WARN Missing transition file; skipping: " + name, 2)
        except Exception:  # broad catch: log safety
            pass
        return None
    dst = os.path.join(assets_out_dir, name)
    enc = _current_encoder_params()

    # Behavior knobs
    try:
        from clippy.config import transitions_rebuild as _rebuild_trans  # type: ignore
    except ImportError:
        _rebuild_trans = False
    try:
        from clippy.config import audio_normalize_transitions as _aud_norm  # type: ignore
    except ImportError:
        _aud_norm = True
    try:
        from clippy.config import transitions as _cfg_transitions  # type: ignore
    except ImportError:
        _cfg_transitions = []
    try:
        from clippy.config import static as _cfg_static  # type: ignore
    except ImportError:
        _cfg_static = "static.mp4"
    try:
        from clippy.config import intro as _cfg_intro  # type: ignore
    except ImportError:
        _cfg_intro = []
    try:
        from clippy.config import outro as _cfg_outro  # type: ignore
    except ImportError:
        _cfg_outro = []
    try:
        from clippy.config import silence_static as _silence_static  # type: ignore
    except ImportError:
        _silence_static = False

    # Determine whether to force silence via config
    force_silent_audio = bool(name == _cfg_static and _silence_static)

    # Probe for audio stream presence; if no audio and not forcing silence, we'll synthesize clean audio
    has_audio = True
    try:
        probe_cmd = f'{ffprobe} -v error -select_streams a:0 -show_entries stream=codec_type -of csv=p=0 "{src}"'
        rc_probe, _ = run_proc_cancellable(probe_cmd, prefer_shell=True)
        has_audio = rc_probe == 0
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        has_audio = True

    # Determine desired build characteristics for this asset
    desired_silent = bool(force_silent_audio)
    desired_audnorm = (not desired_silent) and bool(_aud_norm)

    # Reuse normalized copy only if manifest matches current desired settings
    if os.path.exists(dst) and not _rebuild_trans:
        try:
            entry = asset_manifest.get(name) if isinstance(asset_manifest, dict) else None
        except (AttributeError, KeyError, TypeError):
            entry = None
        if entry and isinstance(entry, dict):
            if (
                bool(entry.get("silent")) == desired_silent
                and bool(entry.get("aud_norm")) == desired_audnorm
            ):
                return f"{rel_assets_dir}/{name}"
        else:
            # If no manifest entry exists and we now desire silent or audnorm explicitly, force rebuild
            if not desired_silent and not desired_audnorm:
                return f"{rel_assets_dir}/{name}"
            # else fall-through to rebuild

    # Build ffmpeg command
    if force_silent_audio:
        cmd = (
            f'{ffmpeg} -y -i "{src}" -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 '
            f"-map 0:v -map 1:a "
            f"{enc.sizing_flags()} "
            f"{enc.full_encoding_flags()} -shortest "
            f"{enc.container_flags} -preset {enc.preset} -loglevel error -nostats "
            f'"{dst}"'
        )
    else:
        _af = " -af loudnorm=I=-16:TP=-1.5:LRA=11" if _aud_norm else ""
        if has_audio:
            cmd = (
                f'{ffmpeg} -y -i "{src}" '
                f"{enc.sizing_flags()} "
                f"{enc.full_encoding_flags()}{_af} "
                f"{enc.container_flags} -preset {enc.preset} -loglevel error -nostats "
                f'"{dst}"'
            )
        else:
            # Synthesize clean stereo audio if source lacks audio
            cmd = (
                f'{ffmpeg} -y -i "{src}" -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 '
                f"-map 0:v -map 1:a "
                f"{enc.sizing_flags()} "
                f"{enc.full_encoding_flags()} -shortest "
                f"{enc.container_flags} -preset {enc.preset} -loglevel error -nostats "
                f'"{dst}"'
            )

    if SHUTDOWN_EVENT.is_set():
        return None
    rc, err = run_proc_cancellable(cmd, prefer_shell=True)
    if rc != 0:
        # Log stderr for visibility
        try:
            _etxt = (
                err.decode("utf-8", errors="ignore")
                if isinstance(err, (bytes, bytearray))
                else str(err)
            )
            if _is_interrupted(err):
                log("Transition build interrupted by user", 2)
            else:
                log("WARN Failed to normalize transition asset: " + name, 2)
                log(_etxt, 2)
        except Exception:  # broad catch: log safety
            pass
        if SHUTDOWN_EVENT.is_set():
            return None
        # Retry without loudnorm only for intros/outros (non-silent path)
        if (not force_silent_audio) and _aud_norm:
            _af2 = ""
            cmd2 = (
                f'{ffmpeg} -y -i "{src}" '
                f"{enc.sizing_flags()} "
                f"{enc.full_encoding_flags()}{_af2} "
                f"{enc.container_flags} -preset {enc.preset} -loglevel error -nostats "
                f'"{dst}"'
            )
            if SHUTDOWN_EVENT.is_set():
                return None
            rc2, err2 = run_proc_cancellable(cmd2, prefer_shell=True)
            if rc2 != 0:
                # Final fallback: synthesize clean silent audio
                cmd3 = (
                    f'{ffmpeg} -y -i "{src}" -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 '
                    f"-map 0:v -map 1:a "
                    f"{enc.sizing_flags()} "
                    f"{enc.full_encoding_flags()} -shortest "
                    f"{enc.container_flags} -preset {enc.preset} -loglevel error -nostats "
                    f'"{dst}"'
                )
                if SHUTDOWN_EVENT.is_set():
                    return None
                rc3, err3 = run_proc_cancellable(cmd3, prefer_shell=True)
                if rc3 != 0:
                    return None
                else:
                    # Built with silent fallback
                    try:
                        asset_manifest[name] = {"silent": True, "aud_norm": False}
                        with open(manifest_path, "w", encoding="utf-8") as _mf2:
                            json.dump(asset_manifest, _mf2, indent=2)
                    except (OSError, TypeError, ValueError) as e:
                        logger.debug("Failed to write asset manifest: %s", e)
                    return f"{rel_assets_dir}/{name}"
    # Successful build, record in manifest
    try:
        asset_manifest[name] = {"silent": desired_silent, "aud_norm": desired_audnorm}
        with open(manifest_path, "w", encoding="utf-8") as _mf3:
            json.dump(asset_manifest, _mf3, indent=2)
    except (OSError, TypeError, ValueError) as e:
        logger.debug("Failed to write asset manifest: %s", e)
    return f"{rel_assets_dir}/{name}"


def prepare_clips_concurrent(compilation, max_workers):
    """Download, normalize, and overlay clips concurrently with a live progress board."""
    total = len(compilation)
    # Enable VT sequences on Windows for nicer updates
    try:
        if os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    except Exception:  # broad catch: Windows VT mode is optional
        pass

    # Progress board: print N lines and update in-place
    _lock = threading.Lock()

    def _status_text(label: str) -> str:
        low = label.lower()
        try:
            if low.startswith("failed"):
                return THEME.error(label) if THEME else str(chalk.magenta(label))
            if "done" in low:
                return THEME.success(label) if THEME else str(chalk.cyan(label))
            if "download" in low or "avatar" in low:
                return THEME.path(label) if THEME else str(chalk.cyan(label))
            if "normalizing" in low or "overlay" in low or "processing" in low:
                return THEME.section(label) if THEME else str(chalk.blue(label))
            if "queued" in low:
                return THEME.bar(label) if THEME else str(chalk.gray(label))
        except Exception:  # broad catch: theme rendering safety
            pass
        return label

    try:
        enable_windows_vt()
    except Exception:  # broad catch: VT setup is optional
        pass
    hdr = None
    try:
        hdr = (
            THEME.title(f"Preparing {total} clip(s)...")
            if THEME
            else str(chalk.blue_bright(f"Preparing {total} clip(s)..."))
        )
    except Exception:  # broad catch: theme rendering safety
        hdr = str(chalk.blue_bright(f"Preparing {total} clip(s)..."))
    print(hdr)
    for i in range(1, total + 1):
        print(f"Clip {i}: {_status_text('queued')}")

    def _update_line(pos: int, text: str):
        # pos is 1-based index within the board lines
        with _lock:
            # Move cursor up to the target line (header + total lines printed, we are at bottom)
            offset = total - (pos - 1)
            sys.stdout.write(f"\x1b[{offset}A")
            sys.stdout.write("\r\x1b[2K")
            try:
                clip_label = THEME.section("Clip") if THEME else "Clip"
            except Exception:  # broad catch: theme rendering safety
                clip_label = "Clip"
            sys.stdout.write(f"{clip_label} {pos}: {_status_text(text)}\n")
            # Move back down to bottom
            if offset > 1:
                sys.stdout.write(f"\x1b[{offset - 1}B")
            sys.stdout.flush()

    # Prepare all clips concurrently but keep output ordering
    def _prep(clip: ClipRow, pos: int) -> tuple[ClipRow, bool]:
        clip_folder = os.path.join(cache, clip.id)
        ensure_dir(clip_folder)
        _update_line(pos, "Avatar downloading")
        if SHUTDOWN_EVENT.is_set():
            return clip, False
        download_avatar(clip, quiet=True)
        _update_line(pos, "Downloading clip")
        d_rc = _retry(lambda: download_clip(clip, quiet=True))
        if d_rc == 1:
            _update_line(pos, "FAILED (download)")
            return clip, False
        if SHUTDOWN_EVENT.is_set():
            return clip, False

        # Prepare progress updaters
        def _fmt_time(secs: float) -> str:
            try:
                secs_int = int(secs)
                m, s = divmod(secs_int, 60)
                h, m = divmod(m, 60)
                if h > 0:
                    return f"{h:02d}:{m:02d}:{s:02d}"
                return f"{m:02d}:{s:02d}"
            except (ValueError, TypeError):
                return "--:--"

        def _norm_progress(done: float, total: float):
            pct = max(0, min(100, int((done / total) * 100))) if total else 0
            _update_line(pos, f"Normalizing {pct}% ({_fmt_time(done)}/{_fmt_time(total)})")

        def _ovl_progress(done: float, total: float):
            pct = max(0, min(100, int((done / total) * 100))) if total else 0
            _update_line(pos, f"Overlay {pct}% ({_fmt_time(done)}/{_fmt_time(total)})")

        _update_line(pos, "Normalizing")
        p_rc = _retry(
            lambda: process_clip(
                clip,
                quiet=True,
                on_norm_progress=_norm_progress,
                on_overlay_progress=(_ovl_progress if enable_overlay else None),
            )
        )
        if p_rc == 1:
            _update_line(pos, "FAILED (process)")
            return clip, False
        _update_line(pos, "Done")
        return clip, (p_rc != 1)

    results: List[tuple[ClipRow, bool]] = [None] * total  # type: ignore
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_prep, clip, i + 1): i for i, clip in enumerate(compilation)}
        for fut in as_completed(futs):
            idx = futs[fut]
            try:
                results[idx] = fut.result()
            except Exception:  # broad catch: thread worker safety
                results[idx] = (compilation[idx], False)
    return results


def build_concat_list(
    compilation,
    results,
    transitions_abs,
    assets_out_dir,
    rel_assets_dir,
    asset_manifest,
    manifest_path,
):
    """Assemble the ffmpeg concat file lines from processed clips and transition assets."""
    lines = []

    # Pull lists and config values
    try:
        from clippy.config import intro as _intro_list  # type: ignore
    except ImportError:
        _intro_list = []
    try:
        from clippy.config import outro as _outro_list  # type: ignore
    except ImportError:
        _outro_list = []
    _transitions_list = resolve_transition_pool(transitions_dir=transitions_abs)
    try:
        from clippy.config import static as _static_name  # type: ignore
    except ImportError:
        _static_name = "static.mp4"
    try:
        from clippy.config import transition_probability as _trans_prob  # type: ignore
    except ImportError:
        _trans_prob = 0.35
    try:
        from clippy.config import transitions_weights as _trans_weights  # type: ignore
    except ImportError:
        _trans_weights = {}
    try:
        from clippy.config import transition_cooldown as _trans_cooldown  # type: ignore
    except ImportError:
        _trans_cooldown = 0
    try:
        from clippy.config import silence_static as _silence_static  # type: ignore
    except ImportError:
        _silence_static = True
    try:
        from clippy.config import skip_bad_clip as _skip_bad  # type: ignore
    except ImportError:
        _skip_bad = True
    try:
        from clippy.config import no_random_transitions as _no_rand  # type: ignore
    except ImportError:
        _no_rand = False

    def _append_trans_file(name: str) -> bool:
        if not name:
            return False
        # Use normalized copy to ensure decoder compatibility
        rel_norm = transcode_asset(
            name, transitions_abs, assets_out_dir, rel_assets_dir, asset_manifest, manifest_path
        )
        if rel_norm:
            lines.append(f"file {rel_norm}")
            return True
        # If normalization fails or file missing, skip to avoid bad AAC streams
        try:
            log("WARN Skipping transition (normalization failed): " + str(name), 2)
        except Exception:  # broad catch: log safety
            pass
        return False

    # Intro (single random choice, if any), then static
    if isinstance(_intro_list, (list, tuple)) and _intro_list:
        _in_choice = random.choice(list(_intro_list))
        if _append_trans_file(_in_choice):
            _append_trans_file(_static_name)

    # recent transitions for simple cooldown avoidance
    _recent_transitions: list[str] = []

    def _weighted_transition_choice() -> Optional[str]:
        if not (isinstance(_transitions_list, (list, tuple)) and _transitions_list):
            return None
        pool = list(_transitions_list)
        # apply cooldown (avoid last N picks)
        if _trans_cooldown and _recent_transitions:
            pool = [t for t in pool if t not in _recent_transitions[-_trans_cooldown:]] or list(
                _transitions_list
            )
        # build weights
        weights = [float(_trans_weights.get(t, 1.0)) for t in pool]
        try:
            # normalize weights if all non-positive
            if not any(w > 0 for w in weights):
                weights = [1.0] * len(pool)
            # Python's random.choices available from 3.6+
            choice = random.choices(pool, weights=weights, k=1)[0]
            return choice
        except (ValueError, IndexError):
            return random.choice(pool)

    for clip, ok in results:
        if not ok:
            if _skip_bad:
                try:
                    log("WARN Skipping failed clip: " + clip.id, 2)
                except Exception:  # broad catch: log safety
                    pass
                continue
            else:
                try:
                    log("Clip failed and skip disabled; aborting", 5)
                except Exception:  # broad catch: log safety
                    pass
                break
        # successful clip
        lines.append(f"file {clip.id}/{clip.id}.mp4")
        _append_trans_file(_static_name)
        if not _no_rand and isinstance(_transitions_list, (list, tuple)) and _transitions_list:
            try:
                if random.random() < float(_trans_prob):
                    _t_choice = _weighted_transition_choice()
                    if _t_choice and _append_trans_file(_t_choice):
                        _recent_transitions.append(_t_choice)
                        _append_trans_file(_static_name)
            except (ValueError, TypeError) as e:
                logger.debug("Failed to insert random transition: %s", e)
    # Outro (single random choice, if any). The preceding step already placed a static.
    if isinstance(_outro_list, (list, tuple)) and _outro_list:
        _out_choice = random.choice(list(_outro_list))
        _append_trans_file(_out_choice)
    return lines


def write_concat_file(index: int, compilation: List[ClipRow]):
    path = os.path.join(cache, f"comp{index}")
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    # Resolve transitions directory dynamically and reference it relative to cache for ffmpeg concat
    cache_abs = os.path.abspath(cache)
    transitions_abs = os.path.abspath(resolve_transitions_dir())
    enc = _current_encoder_params()
    # Prepare a normalized transitions cache to ensure consistent codecs (avoid AV1 decode issues)
    assets_out_dir = os.path.join(cache_abs, "_trans")
    try:
        os.makedirs(assets_out_dir, exist_ok=True)
    except OSError:
        pass
    rel_assets_dir = os.path.relpath(assets_out_dir, start=cache_abs).replace("\\", "/")
    # Manifest to record how each asset was built (silent vs. normalized) to avoid stale reuse
    manifest_path = os.path.join(assets_out_dir, "_manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as _mf:
            asset_manifest = json.load(_mf) or {}
    except (json.JSONDecodeError, OSError):
        asset_manifest = {}
    # Load max concurrency config
    try:
        from clippy.config import max_concurrency as _max_workers  # type: ignore
    except ImportError:
        _max_workers = 4
    # Process clips concurrently
    results = prepare_clips_concurrent(compilation, _max_workers)
    # Build concat list
    lines = build_concat_list(
        compilation,
        results,
        transitions_abs,
        assets_out_dir,
        rel_assets_dir,
        asset_manifest,
        manifest_path,
    )
    # Write file
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def stage_one(compilations: List[List[ClipRow]]):
    for idx, comp in enumerate(compilations):
        log(f"Concat list {idx}", 1)
        write_concat_file(idx, comp)


def stage_two(compilations: List[List[ClipRow]], final_names: Optional[List[str]] = None):
    for idx, _ in enumerate(compilations):
        # Compute the expected output filename for logging
        date_str = time.strftime("%d_%m_%y")
        out_tmpl = "{cache}/complete_{date}_{idx}.{ext}".replace("{idx}", str(idx)).replace(
            "{date}", date_str
        )
        out_path = replace_vars(out_tmpl, (str(idx), 0, "", "", 0, ""))
        out_name = os.path.basename(out_path)
        if final_names and idx < len(final_names):
            log(f"Compiling {out_name} → {final_names[idx]}", 1)
        else:
            log(f"Compiling {out_name}", 1)
        cmd = (
            f'{ffmpeg} -f concat -safe 0 -i "{cache}/comp{idx}" '
            f"{enc.sizing_flags()} "
            f"{enc.full_encoding_flags()} "
            f"{enc.container_flags} -preset {enc.preset} "
            f'-loglevel error -stats -y "{cache}/complete_{date_str}_{idx}.{enc.container_ext}"'
        )
        # Inject progress reporting
        if " -stats " in cmd:
            cmd = cmd.replace(" -stats ", " -nostats -progress pipe:2 ")
        else:
            cmd += " -progress pipe:2"

        total = _sum_concat_duration(idx)

        def _fmt_time(secs: float) -> str:
            try:
                secs_int = int(secs)
                m, s = divmod(secs_int, 60)
                h, m = divmod(m, 60)
                if h > 0:
                    return f"{h:02d}:{m:02d}:{s:02d}"
                return f"{m:02d}:{s:02d}"
            except (ValueError, TypeError):
                return "--:--"

        # Render a single progress line that updates in-place
        def _concat_progress(info: dict):
            if "out_time" not in info:
                return
            done = float(info["out_time"])
            if total and total > 0:
                pct = max(0, min(100, int((done / total) * 100)))
                try:
                    act = THEME.section("Concatenating") if THEME else chalk.cyan("Concatenating")
                    name = THEME.path(out_name) if THEME else chalk.white(out_name)
                except Exception:  # broad catch: theme rendering safety
                    act = chalk.cyan("Concatenating")
                    name = chalk.white(out_name)
                sys.stdout.write(
                    f"\r{act} {name}: {pct}% ({_fmt_time(done)}/{_fmt_time(total)})   "
                )
            else:
                try:
                    act = THEME.section("Concatenating") if THEME else chalk.cyan("Concatenating")
                    name = THEME.path(out_name) if THEME else chalk.white(out_name)
                except Exception:  # broad catch: theme rendering safety
                    act = chalk.cyan("Concatenating")
                    name = chalk.white(out_name)
                sys.stdout.write(f"\r{act} {name}: {_fmt_time(done)}   ")
            sys.stdout.flush()

        # Use cancellable runner for final concat as well
        try:
            if os.getenv("CLIPPY_DEBUG", "").strip().lower() in ("1", "true", "yes", "on"):
                log("ffmpeg concat cmd: " + cmd, 1)
        except Exception:  # broad catch: debug logging safety
            pass
        rc, err = run_proc_cancellable(cmd, prefer_shell=True, progress_cb=_concat_progress)
        # Ensure we end the progress line cleanly
        try:
            sys.stdout.write("\r\n")
            sys.stdout.flush()
        except OSError:
            pass
        if rc != 0:
            try:
                if _is_interrupted(err):
                    log("Concatenation interrupted by user", 2)
                else:
                    _etxt = (
                        err.decode("utf-8", errors="ignore")
                        if isinstance(err, (bytes, bytearray))
                        else str(err)
                    )
                    log("Concat failed for index " + str(idx), 5)
                    log(_etxt, 5)
            except Exception:  # broad catch: log safety
                pass
