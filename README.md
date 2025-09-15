# Twitch Clip Compilation

Create highlight compilations directly from Twitch clips. Audio is ON by default for intros, static, transitions, and outros. All non-clip assets are normalized to H.264 (yuv420p) with AAC 48 kHz stereo to keep concatenation stable.

## Features
- Twitch Helix ingestion with simple date window and auto-expand lookback
- Discord channel ingestion (optional): read clip links from a Discord channel using discord.py
- Min-views filter, weighted selection, and themed colorized logs
- Creator avatar overlay, transitions, and output finalization to `output/`
- yt-dlp downloads with retries; `.env` or env-based credentials
- NVENC-based encoding tuned for fewer artifacts at transitions
- Interactive confirmation by default (use `-y` to auto-approve)
- Resilient audio: loudness normalization for assets, synthesize clean stereo audio if missing
- Ctrl-C friendly: cooperative shutdown that stops workers and terminates ffmpeg cleanly

## Setup (first time, PowerShell on Windows)

```powershell
python -m venv .venv
\.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\scripts\setup_wizard.py
```

### What the setup wizard does
- Source selection: choose Twitch or Discord as your clip source
- Guides you through entering your Twitch credentials and saves them to a `.env` file
- Writes a starter `clippy.yaml` with sensible defaults (clips per compilation, min views, quality, fps/resolution)
- Optionally sets a default broadcaster so you can run without specifying `--broadcaster`
- Discord setup (optional): prompts for Discord channel ID and supports masked bot token entry; can perform a quick token login check
- Preserves existing settings on re-run (including Discord config); secrets are masked in prompts
- Checks for ffmpeg/yt-dlp and NVENC availability; suggests fixes if missing
- Helps you select or create a transitions folder (`transitions/`), explains the required `static.mp4`
- Requires `transitions/static.mp4`; you can set a custom directory with `--transitions-dir` or TRANSITIONS_DIR
- You can run with just: `python .\main.py -y` after saving defaults

You can re-run the wizard at any time to adjust settings; it will merge with the existing YAML and leave custom edits intact.

## Configuration

- The wizard creates `clippy.yaml` and `.env` for you. A commented example remains in `clippy.yaml.example`.
- Precedence: CLI flags > Environment (.env) > clippy.yaml > built-in defaults.

Key env vars (advanced):
- `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` – Twitch credentials used by the Helix API
- `TRANSITIONS_DIR` – point to a custom transitions folder (`static.mp4` required)
  

## Usage
Basic:
```powershell
python main.py --broadcaster somechannel --max-clips 80 --clips 12 --compilations 2 --min-views 5
```

Confirm settings (default prompt) or skip with `-y`:
```powershell
python main.py --broadcaster somechannel -y
```
### Discord mode (optional)

Prerequisites:
- A Discord bot in your server with permission to read the target channel
- The “Message Content Intent” enabled for your bot in the Discord Developer Portal
- Bot token saved to `.env` as `DISCORD_TOKEN`

Config:
- Set `discord.channel_id` and optional `discord.message_limit` in `clippy.yaml`
- Or pass `--discord-channel-id` and `--discord-limit` on the CLI

Run:
```powershell
python .\main.py --discord --discord-channel-id 123456789012345678 -y
```

What happens:
- Clippy reads recent messages from the channel, extracts Twitch clip links, resolves them via Helix, and builds compilations
- Logs display the channel name (e.g., “Guild / #clips”), the number of links found, raw clips fetched, clips after min-views, and compilations created
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
- All non-clip assets are normalized to `cache/_trans` on first use to ensure uniform codecs and audio (48 kHz stereo). You can force a rebuild with `--rebuild-transitions`.

### Internal data and ENV

- `static.mp4` is REQUIRED. Place it under `transitions/` or point TRANSITIONS_DIR to a folder that contains it.
- Override transitions location with `TRANSITIONS_DIR` (absolute or relative path).
- Common ENV:
  - `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`: Twitch API credentials
  - TRANSITIONS_DIR: Set a custom transitions directory
  - `TRANSITIONS_DIR=path`: Use a specific transitions folder

### Transitions 101: creating and validating assets

There are two easy ways to prepare transitions:

1) Import existing clips at the correct format

```powershell
# Normalize/convert any video into the transitions folder
python .\scripts\import_media.py path\to\your\clip.mp4 --type transition

# Set a specific output name (e.g., outro_custom.mp4)
python .\scripts\import_media.py path\to\outro.mov --type outro --name outro_custom.mp4

# Replace or create the required static.mp4
python .\scripts\import_media.py path\to\image_or_video.mp4 --type static --overwrite
```

2) Generate multiple transitions from a long video

```powershell
# Slice random 1–3s segments and write transition_XX.mp4 files
python .\scripts\make_transitions.py -i .\long_source.mp4 -n 8
```

Validate and troubleshoot:

```powershell
# Normalize all transitions and run an audio-only concat probe
python .\scripts\test_transitions.py --normalize --concat-audio-check

# Verify a previously generated concat list (e.g., cache\comp0)
python .\scripts\check_sequencing.py --comp .\cache\comp0 --transitions-dir .\transitions
```

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

## Running from source (Python)
This project now runs as a standard Python application. Use the setup steps above to configure your environment, then run commands like:

```powershell
# Health check
python .\scripts\health_check.py

# Build a compilation (skip confirmation with -y)
python .\main.py --broadcaster <name> -y
```

## Manual setup (optional)
If you prefer not to use the wizard, you can create `.env` yourself and edit `clippy.yaml`:

```powershell
"TWITCH_CLIENT_ID=your_id`nTWITCH_CLIENT_SECRET=your_secret" | Out-File -Encoding utf8 .env
```

## Docs
- [Contributing](docs/CONTRIBUTING.md)
- [Code of Conduct](docs/CODE_OF_CONDUCT.md)
- [Security Policy](docs/SECURITY.md)

## Roadmap
- Parallel clip processing
- Optional libx264 encoder flag
- Advanced scoring and auto-keyframe alignment
