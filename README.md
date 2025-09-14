# Twitch Clip Compilation

Create highlight compilations directly from Twitch clips. Audio is ON by default for intros, static, transitions, and outros. All non-clip assets are normalized to H.264 (yuv420p) with AAC 48 kHz stereo to keep concatenation stable.

## Features
- Twitch Helix ingestion with simple date window and auto-expand lookback
- Min-views filter, weighted selection, and themed colorized logs
- Creator avatar overlay, transitions, and output finalization to `output/`
- yt-dlp downloads with retries; `.env` or env-based credentials
- NVENC-based encoding tuned for fewer artifacts at transitions
- Interactive confirmation by default (use `-y` to auto-approve)
- Resilient audio: loudness normalization for assets, synthesize clean stereo audio if missing
- Ctrl-C friendly: cooperative shutdown that stops workers and terminates ffmpeg cleanly

## Setup (PowerShell on Windows)
```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
"TWITCH_CLIENT_ID=your_id`nTWITCH_CLIENT_SECRET=your_secret" | Out-File -Encoding utf8 .env
```

## Usage
Basic:
```powershell
python main.py --broadcaster somechannel --max-clips 80 --clips 12 --compilations 2 --min-views 5
```

Confirm settings (default prompt) or skip with `-y`:
```powershell
python main_twitch.py --broadcaster somechannel -y
```

Auto-expand lookback to gather more clips:
```powershell
python main.py --broadcaster somechannel --auto-expand --expand-step-days 14 --max-lookback-days 180
```

Quality, resolution, and container:
```powershell
# Preset quality (sets bitrate unless --bitrate provided)
python main.py --broadcaster somechannel --quality high

# Explicit bitrate and resolution
python main.py --broadcaster somechannel --bitrate 16M --resolution 1920x1080

# Container format (mp4 with faststart, or mkv)
python main.py --broadcaster somechannel --format mkv
```

Help is now grouped into logical sections:

```powershell
python main.py -h
```
Sections include: Required, Window & selection, Output & formatting, Transitions & sequencing, Performance & robustness, Cache management, Encoder (NVENC) tuning, Misc.

## Outputs
- Final files are moved to `output/` with names like: `<channel>_<start>_to_<end>_compilation.mp4` (or `.mkv`).
- Work-in-progress artifacts live under `cache/` and are cleaned unless `--keep-cache` is set.
- If a file exists, we auto-suffix with `_1`, `_2`, ... unless `--overwrite-output` is provided.

## Transitions & sequencing
- `transitions/static.mp4` is required and placed between every segment.
- Sequence: random(optional intro) → static → clip → static → random_chance(transition → static) … → random(optional outro)
- All non-clip assets are normalized to cache/_trans on first use to ensure uniform codecs and audio (48 kHz stereo). You can force a rebuild with `--rebuild-transitions`.

### Internal data and ENV

- `static.mp4` is REQUIRED. If you ship a portable build, include it under `transitions/` (runtime) and/ or `_internal/transitions/static.mp4` (packaged). At runtime, set `CLIPPY_USE_INTERNAL=1` to prefer packaged assets.
- Override transitions location with `TRANSITIONS_DIR` (absolute or relative path).
- Common ENV:
	- `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`: Twitch API credentials
	- `CLIPPY_USE_INTERNAL=1`: Prefer `_internal` packaged data
	- `TRANSITIONS_DIR=path`: Use a specific transitions folder

## Notes
- Min views equals `--min-views` (maps to `reactionThreshold`).
- NVENC settings aim to reduce blockiness: VBR HQ + CQ, B-frames, lookahead, AQ, lanczos scaling.
- If your GPU lacks NVENC, we can switch to libx264 on request.
- Ctrl-C: The app will stop workers and terminate any ongoing ffmpeg/yt-dlp processes, then perform normal cleanup.

## Health Check
```powershell
python .\scripts\health_check.py
```

## Troubleshooting
- Seeing only a few clips? Use `--auto-expand` or expand the date window. The app logs effective Helix parameters.
- Pixelation at cuts? Try `--quality max` or `--bitrate 16M`.
- Concat AAC errors? Ensure your transitions are normalized by running `python .\scripts\test_transitions.py --normalize`.

## Distribute as a portable app (Windows)
For non-technical users, build a zip they can unzip and run without installing Python:

1) Build (developer machine):
```powershell
# from repo root
powershell -ExecutionPolicy Bypass -File .\build\build.ps1 -Clean
```

This creates `Clippy-portable.zip` with:
- Clippy.exe (bundled Python)
- ffmpeg.exe, yt-dlp.exe
- transitions/, Roboto-Medium.ttf, README.md
- Start-Clippy.bat and .env.example
 - HealthCheck.exe

2) End-user steps:
- Unzip `Clippy-portable.zip`
- Open `.env.example`, set TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET, save as `.env`
- Double-click `Start-Clippy.bat` or run `Clippy.exe --broadcaster <name> -y`

Optional: Create a shortcut to `Start-Clippy.bat` with your preferred default flags.

## Docs
- [Contributing](docs/CONTRIBUTING.md)
- [Code of Conduct](docs/CODE_OF_CONDUCT.md)
- [Security Policy](docs/SECURITY.md)

## Roadmap
- Parallel clip processing
- Optional libx264 encoder flag
- Advanced scoring and auto-keyframe alignment
