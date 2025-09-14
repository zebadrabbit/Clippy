"""
Package configuration facade.

Loads user settings via config_loader and exposes familiar module-level globals
used throughout the app (ffmpeg templates, binaries, paths, etc.).

This file lives inside the clippy package; path resolution that previously
assumed repo root is adjusted accordingly.
"""

from typing import Any
import os, sys

# Load merged config from YAML/env/defaults
try:
    from .config_loader import load_merged_config  # type: ignore
    _merged: dict[str, Any] = load_merged_config()
except Exception:
    _merged = {
        'yt_format': "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]",
        'bitrate': '12M', 'audio_bitrate': '192k', 'fps': '60', 'resolution': '1920x1080',
        'nvenc_preset': 'slow', 'cq': '19', 'gop': '120', 'rc_lookahead': '20', 'aq_strength': '8', 'spatial_aq': '1', 'temporal_aq': '1',
        'cache': './cache', 'output': './output', 'enable_overlay': True, 'fontfile': 'assets/fonts/Roboto-Medium.ttf',
    }

# Export merged values as module-level globals
globals().update(_merged)

# Ensure essentials exist
yt_format = globals().get('yt_format', "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]")

# Determine repository root (parent of this package directory)
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.abspath(os.path.join(_PKG_DIR, '..'))

# ffmpeg / downloader binaries
if getattr(sys, 'frozen', False):
    # Running from PyInstaller bundle; prefer local binaries next to the exe
    _EXE_DIR = os.path.dirname(sys.executable)
    _FF = os.path.join(_EXE_DIR, 'ffmpeg.exe')
    ffmpeg = _FF if os.path.exists(_FF) else 'ffmpeg'
    _FP = os.path.join(_EXE_DIR, 'ffprobe.exe')
    ffprobe = _FP if os.path.exists(_FP) else 'ffprobe'
    _YTDLP = os.path.join(_EXE_DIR, 'yt-dlp.exe')
    YTDL_BIN = _YTDLP if os.path.exists(_YTDLP) else 'yt-dlp'
else:
    # When running from source, try to resolve repo-level bin/ executables first
    _bin_ff = os.path.join(_REPO_DIR, 'bin', 'ffmpeg.exe')
    ffmpeg = _bin_ff if os.path.exists(_bin_ff) else 'ffmpeg'
    _bin_fp = os.path.join(_REPO_DIR, 'bin', 'ffprobe.exe')
    ffprobe = _bin_fp if os.path.exists(_bin_fp) else 'ffprobe'
    # yt-dlp preferred; fall back to youtube-dl if present in bin/
    _bin_ytdlp = os.path.join(_REPO_DIR, 'bin', 'yt-dlp.exe')
    _bin_youtubedl = os.path.join(_REPO_DIR, 'bin', 'youtube-dl.exe')
    if os.path.exists(_bin_ytdlp):
        YTDL_BIN = _bin_ytdlp
    elif os.path.exists(_bin_youtubedl):
        YTDL_BIN = _bin_youtubedl
    else:
        YTDL_BIN = 'yt-dlp'

# Ensure fontfile resolves in both source and frozen modes
try:
    _ff = globals().get('fontfile', 'assets/fonts/Roboto-Medium.ttf')
    if not isinstance(_ff, str):
        _ff = 'assets/fonts/Roboto-Medium.ttf'
    if not os.path.isabs(_ff):
        # Prefer assets/fonts under repo root; fall back to relative
        _candidate = os.path.join(_REPO_DIR, _ff)
        if os.path.exists(_candidate):
            fontfile = _candidate
        else:
            _fallback = os.path.join(_REPO_DIR, 'assets', 'fonts', 'Roboto-Medium.ttf')
            if os.path.exists(_fallback):
                fontfile = _fallback
            else:
                fontfile = _ff  # keep relative; ffmpeg may still resolve
    else:
        fontfile = _ff
except Exception:
    fontfile = 'assets/fonts/Roboto-Medium.ttf'

# Higher quality NVENC settings to reduce blockiness at transitions
ffmpegNormalizeVideos = (
    '-i "{cache}/{message_id}/clip.mp4" '
    '-r {fps} -s {resolution} -sws_flags lanczos '
    '-c:v h264_nvenc -rc vbr -cq {cq} -b:v 0 -maxrate {bitrate} -bufsize {bitrate} '
    '-profile:v high -level 4.2 -g {gop} -bf 3 -rc-lookahead {rc_lookahead} -spatial_aq {spatial_aq} -aq-strength {aq_strength} -temporal-aq {temporal_aq} '
    '-pix_fmt yuv420p -c:a aac -b:a {audio_bitrate} -ar 48000 -ac 2 '
    '-movflags +faststart -preset {nvenc_preset} -loglevel error -stats -y "{cache}/{message_id}/normalized.mp4"'
)
ffmpegApplyOverlay = (
    "-i \"{cache}/{message_id}/normalized.mp4\" -i \"{cache}/{message_id}/avatar.png\" "
    "-filter_complex \"[0:v]"
    "drawbox=enable='between(t,3,10)':x=0:y=(ih)-238:h=157:w=1000:color=black@0.7:t=fill,"
    "drawtext=enable='between(t,3,10)':x=198:y=(h)-190:fontfile='{fontfile}':fontsize=28:fontcolor=white@0.4:text='clip by',"
    "drawtext=enable='between(t,3,10)':x=198:y=(h)-160:fontfile='{fontfile}':fontsize=48:fontcolor=white@0.9:text='{author}',"
    "overlay=enable='between(t,3,10)':x=50:y=H-223[overlay]\" "
    "-map \"[overlay]\" -map \"0:a\" "
    "-r {fps} -s {resolution} -sws_flags lanczos "
    "-c:v h264_nvenc -rc vbr -cq {cq} -b:v 0 -maxrate {bitrate} -bufsize {bitrate} "
    "-profile:v high -level 4.2 -g {gop} -bf 3 -rc-lookahead {rc_lookahead} -spatial_aq {spatial_aq} -aq-strength {aq_strength} -temporal-aq {temporal_aq} "
    "-pix_fmt yuv420p -c:a aac -b:a {audio_bitrate} -ar 48000 -ac 2 "
    "-movflags +faststart -preset {nvenc_preset} -loglevel error -stats -y \"{cache}/{message_id}/{message_id}.mp4\""
)
container_ext = globals().get('container_ext', "mp4")
container_flags = globals().get('container_flags', "-movflags +faststart")
ffmpegBuildSegments = (
    '-f concat -safe 0 -i "{cache}/comp{idx}" '
    '-r {fps} -s {resolution} -sws_flags lanczos '
    '-c:v h264_nvenc -rc vbr -cq {cq} -b:v 0 -maxrate {bitrate} -bufsize {bitrate} '
    '-profile:v high -level 4.2 -g {gop} -bf 3 -rc-lookahead {rc_lookahead} -spatial_aq {spatial_aq} -aq-strength {aq_strength} -temporal-aq {temporal_aq} '
    '-pix_fmt yuv420p -c:a aac -b:a {audio_bitrate} -ar 48000 -ac 2 '
    '{container_flags} -preset {nvenc_preset} -loglevel error -stats -y "{cache}/complete_{date}_{idx}.{ext}"'
)
ffmpegCreateThumbnail = '-ss 00:00:05 -i "{cache}/{message_id}/{message_id}.mp4" -vframes 1 -s {resolution} "{cache}/{message_id}/preview.png"'

# youtube-dl stuff (yt-dlp). Legacy variable names retained.
youtubeDl = YTDL_BIN
youtubeDlOptions = ("--no-color --no-check-certificate --quiet --progress --retries 5 "
                    "--ffmpeg-location {ffmpeg_path} "
                    "--merge-output-format mp4 "
                    "--format {yt_format} "
                    "-o {cache}/{message_id}/clip.mp4")

# Alias for clarity (kept for legacy references)
viewThreshold = globals().get('reactionThreshold', 1)
