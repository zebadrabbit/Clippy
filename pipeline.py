"""Video processing pipeline (Discord removed).

Contains generic functions for:
  - Selecting candidate clips from DB (view_count stored in `reactions` column)
  - Downloading clip video via youtube-dl/yt-dlp
  - Avatar/thumbnail handling (avatar may be a Twitch user image or placeholder)
  - Normalizing & overlaying metadata
  - Building ffmpeg concat lists & final compilations

Relies on globals defined in `config.py` and helpers from `utils.py`.
"""

from __future__ import annotations

import os
import json
import random
import re
import shlex
import subprocess
import time
from subprocess import Popen
from typing import List, Tuple, Optional

import requests
from PIL import Image

from config import *  # noqa: F401,F403
from utils import log, replace_vars

ClipRow = Tuple[str, float, str, str, int, str]  # (id, created_ts, author, avatar_url, views, url)


def run_proc(cmd: str, prefer_shell: bool = False):
    """Run a command and return (returncode, stderr_bytes).

    Windows:
      - If prefer_shell is True (needed for -filter_complex), run with shell=True.
      - Otherwise, split simply on spaces and run without shell.
    POSIX:
      - Split with shlex and run without shell.
    """
    if os.name == 'nt':
        if prefer_shell:
            try:
                proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return proc.returncode, proc.stderr
            except FileNotFoundError:
                try:
                    log("{@redbright}{@bold}Executable not found (Windows):{@reset} {@white}" + cmd, 5)
                except Exception:
                    pass
                raise
        else:
            tokens = cmd.split()
            try:
                proc = subprocess.run(tokens, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                return proc.returncode, proc.stderr
            except FileNotFoundError:
                try:
                    log("{@redbright}{@bold}Executable not found:{@reset} {@white}" + str(tokens[0]), 5)
                    log("{@gray}" + cmd, 5)
                except Exception:
                    pass
                raise
    else:
        tokens = shlex.split(cmd)
        try:
            proc = subprocess.run(tokens, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return proc.returncode, proc.stderr
        except FileNotFoundError:
            try:
                log("{@redbright}{@bold}Executable not found:{@reset} {@white}" + str(tokens[0]), 5)
                log("{@gray}" + cmd, 5)
            except Exception:
                pass
            raise


def ensure_dir(path: str):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def download_avatar(clip: ClipRow) -> int:
    clip_dir = os.path.join(cache, str(clip[0]))
    ensure_dir(clip_dir)
    png_path = os.path.join(clip_dir, 'avatar.png')
    webp_path = os.path.join(clip_dir, 'avatar.webp')
    if os.path.isfile(png_path):
        return 2
    url = clip[3] or 'https://static-cdn.jtvnw.net/jtv_user_pictures/x.png'
    log(f"{{@green}}Avatar:{{@reset}} {{@cyan}}{url}", 1)
    resp = requests.get(url)
    if resp.status_code >= 400:
        log('Avatar fetch failed; using placeholder', 2)
        return 1
    with open(webp_path, 'wb') as f:
        f.write(resp.content)
    try:
        with Image.open(webp_path) as img:
            img.thumbnail((128, 128))
            img.save(png_path, 'PNG')
    finally:
        try:
            os.remove(webp_path)
        except FileNotFoundError:
            pass
    return 0


def download_clip(clip: ClipRow) -> int:
    clip_dir = os.path.join(cache, str(clip[0]))
    ensure_dir(clip_dir)
    final_path = os.path.join(clip_dir, f'{clip[0]}.mp4')
    if os.path.isfile(final_path) and not rebuild:
        return 2
    cmd = youtubeDl + ' ' + replace_vars(youtubeDlOptions, clip) + ' ' + clip[5]
    rc, err = run_proc(cmd, prefer_shell=False)
    if rc != 0:
        # Decode error for inspection
        err_txt = err.decode('utf-8', errors='ignore') if isinstance(err, (bytes, bytearray)) else str(err)
        log('{@redbright}{@bold}Clip download error', 5)
        log(err_txt, 5)
        return 1
    return 0


def create_thumbnail(clip: ClipRow) -> int:
    clip_dir = os.path.join(cache, str(clip[0]))
    preview = os.path.join(clip_dir, 'preview.png')
    if os.path.isfile(preview) and not rebuild:
        return 2
    rc, err = run_proc(ffmpeg + ' ' + replace_vars(ffmpegCreateThumbnail, clip), prefer_shell=False)
    if rc != 0:
        log('{@redbright}{@bold}Thumbnail generation failed', 5)
        log(err, 5)
        return 1
    try:
        with Image.open(preview) as img:
            img.thumbnail((128, 128))
            img.save(preview, 'PNG')
    except Exception as e:
        log(f"{{@redbright}}{{@bold}}Thumbnail resize error:{{@reset}} {{@white}}{e}", 5)
        return 1
    return 0


def process_clip(clip: ClipRow) -> int:
    clip_dir = os.path.join(cache, str(clip[0]))
    final_path = os.path.join(clip_dir, f'{clip[0]}.mp4')
    if os.path.isfile(final_path) and not rebuild:
        return 2
    log('{@green}Normalizing', 1)
    rc, err = run_proc(ffmpeg + ' ' + replace_vars(ffmpegNormalizeVideos, clip), prefer_shell=False)
    if rc != 0:
        log('{@redbright}{@bold}Normalization failed', 5)
        log(err, 5)
        return 1
    try:
        os.remove(os.path.join(clip_dir, 'clip.mp4'))
    except FileNotFoundError:
        pass
    if enable_overlay:
        log('{@green}Overlay', 1)
        rc, err = run_proc(ffmpeg + ' ' + replace_vars(ffmpegApplyOverlay, clip), prefer_shell=True)
        if rc != 0:
            log('{@redbright}{@bold}Overlay failed', 5)
            log(err, 5)
            return 1
    else:
        # If overlay disabled, use normalized as final
        try:
            os.replace(os.path.join(clip_dir, 'normalized.mp4'), final_path)
        except Exception:
            pass
    try:
        os.remove(os.path.join(clip_dir, 'normalized.mp4'))
    except FileNotFoundError:
        pass
    return 0


def create_compilations_from(clips: List[ClipRow]) -> List[List[ClipRow]]:
    # filter by view threshold (reactions reused as views)
    eligible = [c for c in clips if c[4] >= reactionThreshold]
    random.shuffle(eligible)
    compilations: List[List[ClipRow]] = []
    while eligible and len(compilations) < amountOfCompilations:
        compilations.append(eligible[:amountOfClips])
        eligible = eligible[amountOfClips:]
    log(f"{{@blue}}Created {{@white}}{len(compilations)}{{@blue}} compilations", 2)
    return compilations


def write_concat_file(index: int, compilation: List[ClipRow]):
    path = os.path.join(cache, f'comp{index}')
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    lines = []
    # Resolve transitions directory relative to the cache directory so checks are accurate
    cache_abs = os.path.abspath(cache)
    transitions_abs = os.path.abspath(os.path.join(cache_abs, '..', 'transitions'))
    # Compute the relative path from concat file location (cache) to transitions for ffmpeg concat entries
    rel_trans_dir = os.path.relpath(transitions_abs, start=cache_abs).replace('\\', '/')
    # Guard intro/transition/outro against missing files so ffmpeg concat doesn't fail
    if intro:
        _intro_path = os.path.join(transitions_abs, intro)
        if os.path.exists(_intro_path):
            lines.append(f'file {rel_trans_dir}/{intro}')
        else:
            try:
                log("{@yellow}{@bold}WARN{@reset} Missing intro clip; skipping", 2)
            except Exception:
                pass
    _trans_path = os.path.join(transitions_abs, transition)
    if os.path.exists(_trans_path):
        lines.append(f'file {rel_trans_dir}/{transition}')
    else:
        try:
            log("{@yellow}{@bold}WARN{@reset} Missing transition clip; proceeding without separators", 2)
        except Exception:
            pass
    total = len(compilation)
    for pos, clip in enumerate(compilation, start=1):
        clip_folder = os.path.join(cache, str(clip[0]))
        ensure_dir(clip_folder)
        download_avatar(clip)
        # Informative download progress
        log(f"{{@green}}Downloading clip {{@white}}({pos}{{@reset}}/{{@white}}{total}{{@reset}}){{@reset}} {{@cyan}}{clip[5]}", 1)
        if download_clip(clip) != 1 and process_clip(clip) != 1:
            lines.append(f'file {clip[0]}/{clip[0]}.mp4')
            if os.path.exists(_trans_path):
                lines.append(f'file ../transitions/{transition}')
    if outro:
        _outro_path = os.path.join(transitions_abs, outro)
        if os.path.exists(_outro_path):
            lines.append(f'file {rel_trans_dir}/{outro}')
        else:
            try:
                log("{@yellow}{@bold}WARN{@reset} Missing outro clip; skipping", 2)
            except Exception:
                pass
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def stage_one(compilations: List[List[ClipRow]]):
    for idx, comp in enumerate(compilations):
        log(f"{{@green}}Concat list{{@reset}} {{@white}}{idx}", 1)
        write_concat_file(idx, comp)


def stage_two(compilations: List[List[ClipRow]], final_names: Optional[List[str]] = None):
    for idx, _ in enumerate(compilations):
        # Compute the expected output filename for logging
        date_str = time.strftime('%d_%m_%y')
        out_tmpl = '{cache}/complete_{date}_{idx}.{ext}'.replace('{idx}', str(idx)).replace('{date}', date_str)
        out_path = replace_vars(out_tmpl, (str(idx), 0, '', '', 0, ''))
        out_name = os.path.basename(out_path)
        if final_names and idx < len(final_names):
            log(f"{{@green}}Compiling{{@reset}} {{@white}}{out_name}{{@reset}} -> {{@white}}{final_names[idx]}", 1)
        else:
            log(f"{{@green}}Compiling{{@reset}} {{@white}}{out_name}", 1)
        # Prepare template with index/date and run through replace_vars to fill all tokens
        tmpl = (ffmpegBuildSegments
            .replace('{idx}', str(idx))
            .replace('{date}', date_str))
        cmd = ffmpeg + ' ' + replace_vars(tmpl, (str(idx), 0, '', '', 0, ''))
        subprocess.call(cmd, shell=True, stdout=subprocess.PIPE)


# Backwards compatible aliases
createCompilations = create_compilations_from  # pragma: no cover
downloadAvatar = download_avatar  # pragma: no cover
downloadClip = download_clip  # pragma: no cover
createThumbnail = create_thumbnail  # pragma: no cover
processClip = process_clip  # pragma: no cover
