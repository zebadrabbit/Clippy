"""
Global configuration for the clip compilation pipeline.

Notes:
- Secrets (client IDs, secrets) must live in environment variables or `.env`.
- This file now supports a structured YAML config (clippy.yaml) that overrides defaults at import time.
- Variable names and defaults are unchanged to avoid breaking imports; we merge clippy.yaml onto these defaults.
"""

# =============================================================
# Core selection & counts
# =============================================================

# how many clips we should get
amountOfClips: int = 12  # number of clips per compilation

# how many segments
amountOfCompilations: int = 2  # number of compilations to create

# minimum view count
reactionThreshold: int = 1  # minimum views to include a clip

# compilation file naming:  compilation_d_m_yy.mp4
outputFormat: str = 'compilation_'  # base prefix for output naming

# =============================================================
# Assets & overlay
# =============================================================
# font to use for overlay (prefer assets/fonts when present)
fontfile: str = "assets/fonts/Roboto-Medium.ttf"  # font path for overlay drawtext

# file names for transitions, intro, outro
static: str = 'static.mp4'  # required spacer clip used between segments
intro: list[str] = [
	'intro.mp4', 
	'intro_2.mp4'
]
outro: list[str] = [
	'outro.mp4', 
	'outro_2.mp4'
]
transitions: list[str] = [
	'transition_01.mp4', 
	'transition_02.mp4', 
	'transition_03.mp4', 
	'transition_05.mp4', 
	'transition_07.mp4',
	'transition_08.mp4'	
]

# =============================================================
# Transitions & sequencing
# =============================================================
# probability (0.0 - 1.0) to insert a random transition between clips (each gap independent)
transition_probability: float = 0.35  # probability to insert a transition between clips

# Disable random transitions entirely (still uses static.mp4 between clips)
no_random_transitions: bool = False  # disable transitions entirely (still use static)

# Concurrency for clip preparation (downloads/normalization)
max_concurrency: int = 4  # worker threads for download/normalize stage

# Behavior when a clip fails after retries: if True, skip the clip; if False, abort the run
skip_bad_clip: bool = True  # skip failed clips instead of aborting

# Normalize audio on transitions during internal normalization (cache/_trans) using EBU R128 loudnorm
# This helps keep loudness consistent between assets. Can be disabled.
audio_normalize_transitions: bool = True  # apply loudnorm to non-clip assets (intro/static/transition/outro)

# Force re-encode of transitions assets into cache/_trans even if a normalized copy already exists
transitions_rebuild: bool = False  # force rebuild of normalized non-clip assets

# By default, do NOT silence any non-clip assets. All audio is ON unless specified.
silence_nonclip_asset_audio: bool = False  # default: keep audio for non-clip assets unless overridden

# Granular audio silencing controls (applied when silence_nonclip_asset_audio = False)
# Defaults: keep audio for transitions, static, and intro/outro.
silence_transitions: bool = False  # silence audio specifically for transitions when false global
silence_static: bool = False       # silence audio for static spacer when false global
silence_intro_outro: bool = False  # silence audio for intros/outros when false global

# Weighted transition selection and simple cooldown
# - transitions_weights: dict of { filename: weight } where higher weight increases selection likelihood
#   Any missing file uses weight 1.0. Only applies when transitions are enabled by probability.
# - transition_cooldown: number of most recent transition picks to avoid repeating immediately (0 disables)
transitions_weights: dict[str, float] = {}
transition_cooldown: int = 1

# =============================================================
# Encoding: video/audio & quality
# =============================================================
# bitrate target (used as maxrate with NVENC vbr)
bitrate: str = "12M"  # target video bitrate (used as maxrate)

# audio bitrate
audio_bitrate: str = "192k"  # target audio bitrate

# framrate
fps: str = "60"  # output frames per second

# resolution
resolution: str = "1920x1080"  # output resolution

# =============================================================
# Paths: cache/output & preservation
# =============================================================
# cache directory for work we're going to do
cache: str = "./cache"  # working directory for intermediates

# cache subdirectories to preserve on cleanup (relative names)
# Default preserves normalized transitions to avoid costly re-encodes between runs.
cache_preserve_dirs: list[str] = ["_trans"]  # cache subfolders to keep on cleanup

# output the compilation to here
output: str = "./output"  # final outputs directory

# whether to rebuild clips even if outputs already exist
rebuild: bool = False  # force per-clip rebuild even if outputs exist

# overlay control
enable_overlay: bool = True  # draw text/avatar overlay on clips

# =============================================================
# Ingest: yt-dlp formats
# =============================================================
# yt-dlp format selection (applied within youtubeDlOptions)
# twitch formats via --list-formats <clip_url> look like:
#    ID           EXT RESOLUTION FPS │ PROTO │ VCODEC  ACODEC
#    ─────────────────────────────────────────────────────────
#    portrait-360 mp4 360p        30 │ https │ unknown unknown
#    portrait-480 mp4 480p        30 │ https │ unknown unknown
#    portrait-607 mp4 607p        60 │ https │ unknown unknown
#    360          mp4 360p        30 │ https │ unknown unknown
#    480          mp4 480p        30 │ https │ unknown unknown
#    720          mp4 720p        60 │ https │ unknown unknown
#    1080         mp4 1080p       60 │ https │ unknown unknown
yt_format: str = "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]"  # yt-dlp format

# =============================================================
# Encoder tuning (NVENC)
# =============================================================
# NVENC encoder tuning (applied in all ffmpeg templates)
# See ffmpeg -h encoder=h264_nvenc for available values
nvenc_preset: str = "slow"  # NVENC preset
cq: str = "19"              # NVENC constant quality value (lower is better)
gop: str = "120"            # keyframe interval
rc_lookahead: str = "20"    # rate-control lookahead frames
aq_strength: str = "8"      # adaptive quantization strength
spatial_aq: str = "1"       # enable spatial AQ (0/1)
temporal_aq: str = "1"      # enable temporal AQ (0/1)


# =============================================================
# DO NOT EDIT BELOW THIS LINE UNLESS YOU KNOW WHAT YOU'RE DOING
# (but feel free to read it)
# =============================================================

# ffmpeg / downloader binaries
import os, sys  # noqa: E401
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
	# When running from source, try to resolve local bin/ executables first
	_ROOT = os.path.dirname(os.path.abspath(__file__))
	_bin_ff = os.path.join(_ROOT, 'bin', 'ffmpeg.exe')
	ffmpeg = _bin_ff if os.path.exists(_bin_ff) else 'ffmpeg'
	_bin_fp = os.path.join(_ROOT, 'bin', 'ffprobe.exe')
	ffprobe = _bin_fp if os.path.exists(_bin_fp) else 'ffprobe'
	# yt-dlp preferred; fall back to youtube-dl if present in bin/
	_bin_ytdlp = os.path.join(_ROOT, 'bin', 'yt-dlp.exe')
	_bin_youtubedl = os.path.join(_ROOT, 'bin', 'youtube-dl.exe')
	if os.path.exists(_bin_ytdlp):
		YTDL_BIN = _bin_ytdlp
	elif os.path.exists(_bin_youtubedl):
		YTDL_BIN = _bin_youtubedl
	else:
		YTDL_BIN = 'yt-dlp'

# Ensure fontfile resolves in both source and frozen modes
try:
	if not os.path.isabs(fontfile):
		# Prefer assets/fonts; fall back to repo root Roboto-Medium.ttf
		_candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), fontfile)
		if not os.path.exists(_candidate):
			_fallback = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Roboto-Medium.ttf')
			if os.path.exists(_fallback):
				fontfile = _fallback
except Exception:
	pass
# Higher quality NVENC settings to reduce blockiness at transitions
ffmpegNormalizeVideos = (
	'-i {cache}/{message_id}/clip.mp4 '
	'-r {fps} -s {resolution} -sws_flags lanczos '
	'-c:v h264_nvenc -rc vbr -cq {cq} -b:v 0 -maxrate {bitrate} -bufsize {bitrate} '
	'-profile:v high -level 4.2 -g {gop} -bf 3 -rc-lookahead {rc_lookahead} -spatial_aq {spatial_aq} -aq-strength {aq_strength} -temporal-aq {temporal_aq} '
	'-pix_fmt yuv420p -c:a aac -b:a {audio_bitrate} -ar 48000 -ac 2 '
	'-movflags +faststart -preset {nvenc_preset} -loglevel error -stats -y {cache}/{message_id}/normalized.mp4'
)
ffmpegApplyOverlay = (
	"-i {cache}/{message_id}/normalized.mp4 -i {cache}/{message_id}/avatar.png "
	"-filter_complex \"[0:v]"
	"drawbox=enable='between(t,3,10)':x=0:y=(ih)-238:h=157:w=1000:color=black@0.7:t=fill,"
	"drawtext=enable='between(t,3,10)':x=198:y=(h)-190:fontfile={fontfile}:fontsize=28:fontcolor=white@0.4:text='clip by',"
	"drawtext=enable='between(t,3,10)':x=198:y=(h)-160:fontfile={fontfile}:fontsize=48:fontcolor=white@0.9:text='{author}',"
	"overlay=enable='between(t,3,10)':x=50:y=H-223[overlay]\" "
	"-map \"[overlay]\" -map \"0:a\" "
	"-r {fps} -s {resolution} -sws_flags lanczos "
	"-c:v h264_nvenc -rc vbr -cq {cq} -b:v 0 -maxrate {bitrate} -bufsize {bitrate} "
	"-profile:v high -level 4.2 -g {gop} -bf 3 -rc-lookahead {rc_lookahead} -spatial_aq {spatial_aq} -aq-strength {aq_strength} -temporal-aq {temporal_aq} "
	"-pix_fmt yuv420p -c:a aac -b:a {audio_bitrate} -ar 48000 -ac 2 "
	"-movflags +faststart -preset {nvenc_preset} -loglevel error -stats -y {cache}/{message_id}/{message_id}.mp4"
)
container_ext = "mp4"
container_flags = "-movflags +faststart"
ffmpegBuildSegments = (
	'-f concat -safe 0 -i {cache}/comp{idx} '
	'-r {fps} -s {resolution} -sws_flags lanczos '
	'-c:v h264_nvenc -rc vbr -cq {cq} -b:v 0 -maxrate {bitrate} -bufsize {bitrate} '
	'-profile:v high -level 4.2 -g {gop} -bf 3 -rc-lookahead {rc_lookahead} -spatial_aq {spatial_aq} -aq-strength {aq_strength} -temporal-aq {temporal_aq} '
	'-pix_fmt yuv420p -c:a aac -b:a {audio_bitrate} -ar 48000 -ac 2 '
	'{container_flags} -preset {nvenc_preset} -loglevel error -stats -y {cache}/complete_{date}_{idx}.{ext}'
)
ffmpegCreateThumbnail = '-ss 00:00:05 -i {cache}/{message_id}/{message_id}.mp4 -vframes 1 -s {resolution} {cache}/{message_id}/preview.png'

# youtube-dl stuff (yt-dlp). Legacy variable names retained.
youtubeDl = YTDL_BIN
youtubeDlOptions = ("--no-color --no-check-certificate --quiet --progress --retries 5 "
					"--ffmpeg-location {ffmpeg_path} "
					"--merge-output-format mp4 "
					"--format {yt_format} "
					"-o {cache}/{message_id}/clip.mp4")

# Alias for clarity
viewThreshold = reactionThreshold

# =============================================================
# Apply clippy.yaml overrides (if present) after defaults but before templates use values
# =============================================================
try:
	from clippy.config_loader import load_merged_config  # type: ignore
	_defaults = dict(
		amountOfClips=amountOfClips,
		amountOfCompilations=amountOfCompilations,
		reactionThreshold=reactionThreshold,
		transition_probability=transition_probability,
		no_random_transitions=no_random_transitions,
		transitions_weights=transitions_weights,
		transition_cooldown=transition_cooldown,
		silence_nonclip_asset_audio=silence_nonclip_asset_audio,
		silence_static=silence_static,
		audio_normalize_transitions=audio_normalize_transitions,
		bitrate=bitrate,
		audio_bitrate=audio_bitrate,
		fps=fps,
		resolution=resolution,
		nvenc_preset=nvenc_preset,
		cq=cq,
		gop=gop,
		rc_lookahead=rc_lookahead,
		aq_strength=aq_strength,
		spatial_aq=spatial_aq,
		temporal_aq=temporal_aq,
		cache=cache,
		output=output,
		max_concurrency=max_concurrency,
		skip_bad_clip=skip_bad_clip,
		rebuild=rebuild,
		enable_overlay=enable_overlay,
		static=static,
		intro=intro,
		outro=outro,
		transitions=transitions,
	)
	_merged = load_merged_config(_defaults)
	# Assign back to module globals
	for _k, _v in _merged.items():
		try:
			globals()[_k] = _v
		except Exception:
			pass
except Exception:
	pass
