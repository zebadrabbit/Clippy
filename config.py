"""
	Global configuration for the clip compilation pipeline.

	Secrets (client IDs, secrets) must live in environment variables or `.env`.
"""

# how many clips we should get
amountOfClips = 12

# how many segments
amountOfCompilations = 2

# minimum view count (stored in `reactions` column) to include a clip
reactionThreshold = 1

# compilation file naming:  compilation_d_m_yy.mp4
outputFormat = 'compilation_'

# font to use for overlay (prefer assets/fonts when present)
fontfile = "assets/fonts/Roboto-Medium.ttf"

# transition things - relative to cache
transition = 'static.mp4'
intro = 'intro.mp4'
outro = 'outro.mp4'

# bitrate target (used as maxrate with NVENC vbr)
bitrate = "12M"

# audio bitrate
audio_bitrate = "192k"

# framrate
fps = "60"

# resolution
resolution = "1920x1080"

# cache directory for work we're going to do
cache = "./cache"

# output the compilation to here
output = "./output"

# whether to rebuild clips even if outputs already exist
rebuild = False

# overlay control
enable_overlay = True

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
yt_format = "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]"

# NVENC encoder tuning (applied in all ffmpeg templates)
# See ffmpeg -h encoder=h264_nvenc for available values
nvenc_preset = "slow"
cq = "19"
gop = "120"
rc_lookahead = "20"
aq_strength = "8"
spatial_aq = "1"
temporal_aq = "1"


# #############################################################
# DO NOT EDIT BELOW THIS LINE UNLESS YOU KNOW WHAT YOU'RE DOING

# ffmpeg / downloader binaries
import os, sys  # noqa: E401
if getattr(sys, 'frozen', False):
	# Running from PyInstaller bundle; prefer local binaries next to the exe
	_EXE_DIR = os.path.dirname(sys.executable)
	_FF = os.path.join(_EXE_DIR, 'ffmpeg.exe')
	ffmpeg = _FF if os.path.exists(_FF) else 'ffmpeg'
	_YTDLP = os.path.join(_EXE_DIR, 'yt-dlp.exe')
	YTDL_BIN = _YTDLP if os.path.exists(_YTDLP) else 'yt-dlp'
else:
	# When running from source, try to resolve local bin/ executables first
	_ROOT = os.path.dirname(os.path.abspath(__file__))
	_bin_ff = os.path.join(_ROOT, 'bin', 'ffmpeg.exe')
	ffmpeg = _bin_ff if os.path.exists(_bin_ff) else 'ffmpeg'
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
	'-pix_fmt yuv420p -c:a aac -b:a {audio_bitrate} '
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
	"-pix_fmt yuv420p -c:a aac -b:a {audio_bitrate} "
	"-movflags +faststart -preset {nvenc_preset} -loglevel error -stats -y {cache}/{message_id}/{message_id}.mp4"
)
container_ext = "mp4"
container_flags = "-movflags +faststart"
ffmpegBuildSegments = (
	'-f concat -safe 0 -i {cache}/comp{idx} '
	'-r {fps} -s {resolution} -sws_flags lanczos '
	'-c:v h264_nvenc -rc vbr -cq {cq} -b:v 0 -maxrate {bitrate} -bufsize {bitrate} '
	'-profile:v high -level 4.2 -g {gop} -bf 3 -rc-lookahead {rc_lookahead} -spatial_aq {spatial_aq} -aq-strength {aq_strength} -temporal-aq {temporal_aq} '
	'-pix_fmt yuv420p -c:a aac -b:a {audio_bitrate} '
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
