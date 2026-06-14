# Twitch Clip Compilation

Create highlight compilations directly from Twitch clips. Audio is ON by default for intros, static, transitions, and outros. All non-clip assets are normalized to H.264 (yuv420p) with AAC 48 kHz stereo to keep concatenation stable.

## Features

- **Two interfaces**: Interactive Textual TUI (`--tui`) for beginners, full CLI for power users
- Twitch Helix ingestion with date windows, auto-expand lookback, and nostalgia mode
- Discord channel ingestion (optional): read clip links curated by your community
- Duration-based sizing: request compilations by target length (`--target-duration 20`) instead of clip count
- Auto-expand: fills missing clips from outside the date range (newest to oldest)
- Nostalgia mode: mixes in random older clips (>6 months) for variety
- 5 encoding presets (youtube_1080p60, discord_friendly, archive_hq, quick_preview, cpu_only)
- Min-views filter, weighted selection, and themed colorized logs
- Creator avatar overlay, transitions, and output finalization to `output/`
- yt-dlp downloads with retries; `.env` or env-based credentials
- NVENC-based encoding tuned for fewer artifacts at transitions, with libx264 fallback
- Resilient audio: loudness normalization for assets, synthesize clean stereo audio if missing
- Ctrl-C friendly: cooperative shutdown that stops workers and terminates ffmpeg cleanly
- Save credentials to `.env` from the TUI or CLI (`--save-env`)
- Summary screen with output paths, compilation lengths, and contributor credits

## Setup (first time, PowerShell on Windows)

```powershell
python -m venv .venv
\.\.venv\Scripts\Activate.ps1
pip install -e ".[tui]"
```

This installs Clippy and the `clippy` command (add `,dev` for the test/lint tools:
`pip install -e ".[tui,dev]"`).

Then run the guided setup, which writes `clippy.yaml` and `.env` for you:

```powershell
clippy setup
```

## Quick Start

The `clippy` command has three entry points:

```powershell
clippy setup     # guided first-time setup (credentials + defaults)
clippy doctor    # check your setup (ffmpeg, credentials, transitions, ...)
clippy tui       # interactive TUI
clippy           # the CLI (see clippy --help)
```

### TUI (recommended for first-time users)

```powershell
clippy tui
```

The TUI walks you through 6 steps: Source > Credentials > Clip Settings > Quality > Transitions > Review & Start. It saves credentials to `.env` on request so subsequent runs auto-fill.

### CLI

```powershell
# By clip count
clippy --broadcaster somechannel --clips 12 --compilations 2 --min-views 5

# By target duration (minutes)
clippy --broadcaster somechannel --target-duration 20 --compilations 2

# With auto-expand and nostalgia
clippy --broadcaster somechannel --clips 12 --compilations 2 --auto-expand --nostalgia

# Auto-confirm
clippy --broadcaster somechannel -y
```

> Running from source without installing? Every `clippy ...` command also works as
> `python main.py ...` (e.g. `python main.py --tui`).

### Discord mode

Prerequisites:

- A Discord bot in your server with permission to read the target channel
- The "Message Content Intent" enabled for your bot in the Discord Developer Portal
- Bot token saved to `.env` as `DISCORD_TOKEN`
- Channel ID saved to `.env` as `DISCORD_CHANNEL_ID` (or pass via CLI/TUI)

```powershell
python main.py --discord --discord-channel-id 123456789012345678 -y
```

What happens: Clippy reads messages from the channel, extracts Twitch clip links, resolves them via Helix, and builds compilations. This lets your Twitch community curate clips collaboratively.

## Configuration

- Precedence: CLI flags > Environment (`.env`) > `clippy.yaml` > built-in defaults.
- The TUI and setup wizard create `clippy.yaml` and `.env` for you. A commented example remains in `clippy.yaml.example`.

Key env vars:

| Variable | Description |
|---|---|
| `TWITCH_CLIENT_ID` | Twitch app client ID for Helix API |
| `TWITCH_CLIENT_SECRET` | Twitch app client secret |
| `DISCORD_TOKEN` | Discord bot token (for Discord mode) |
| `DISCORD_CHANNEL_ID` | Discord channel to read clip links from |
| `TRANSITIONS_DIR` | Custom transitions folder path |

## CLI Reference

Help is grouped into logical sections:

```powershell
python main.py -h
```

Key flags:

| Flag | Description |
|---|---|
| `--tui` | Launch the interactive TUI |
| `--broadcaster` | Twitch channel name |
| `--clips` | Clips per compilation (default: 12) |
| `--compilations` | Number of compilations (default: 2) |
| `--target-duration` | Target compilation length in minutes (alternative to `--clips`) |
| `--auto-expand` | Fill missing clips from outside date range |
| `--no-auto-expand` | Disable auto-expand |
| `--nostalgia` | Mix in random older clips (>6 months) |
| `--min-views` | Minimum view count filter |
| `--preset` | Encoding preset name (use `--list-presets` to see options) |
| `--nvenc-preset` | NVENC encoder preset (slow, medium, fast, etc.) |
| `--quality` | Quality tier (low, medium, high, max) |
| `--format` | Container format (mp4, mkv) |
| `--save-env` | Save credentials to `.env` for future runs |
| `-y` / `--yes` | Auto-confirm settings |

## Encoding Presets

Use `--list-presets` to see all available presets:

| Preset | Resolution | FPS | Codec | Use Case |
|---|---|---|---|---|
| `youtube_1080p60` | 1920x1080 | 60 | h264_nvenc | YouTube uploads |
| `discord_friendly` | 1280x720 | 30 | h264_nvenc | Discord file size limits |
| `archive_hq` | 1920x1080 | 60 | h264_nvenc | High-quality archive (MKV) |
| `quick_preview` | 1280x720 | 30 | h264_nvenc | Fast preview renders |
| `cpu_only` | 1920x1080 | 60 | libx264 | Systems without NVENC GPU |

Apply a preset and customize:

```powershell
python main.py --broadcaster somechannel --preset youtube_1080p60 --cq 18
```

## Outputs

- Final files are moved to `output/` with names like: `<channel>_<start>_to_<end>_compilation.mp4` (or `.mkv`).
- Work-in-progress artifacts live under `cache/` and are cleaned unless `--keep-cache` is set.
- If a file exists, we auto-suffix with `_1`, `_2`, ... unless `--overwrite-output` is provided.
- The TUI summary screen shows output paths, compilation lengths, and contributor credits.

## Transitions & Sequencing

- `transitions/static.mp4` is required and placed between every segment.
- Sequence: random(optional intro) > static > clip > static > random_chance(transition > static) ... > random(optional outro)
- All non-clip assets are normalized to `cache/_trans` on first use to ensure uniform codecs and audio (48 kHz stereo). You can force a rebuild with `--rebuild-transitions`.

### Intro/Outro configuration

- Where they live: filenames are relative to your transitions folder (default `transitions/`, or whatever you set with `--transitions-dir` or `TRANSITIONS_DIR`).
- Configure via `clippy.yaml` under the `assets` section:

```yaml
assets:
  static: static.mp4
  intro:
    - intro.mp4
  outro:
    - outro.mp4
```

- Override per-run: use `--intro` or `--outro` to force a single file for that run, and `--transition` to force the transition choice when selected.

### Creating and validating transitions

```powershell
# Import an existing clip as a transition
python .\scripts\import_media.py path\to\your\clip.mp4 --type transition

# Generate multiple transitions from a long video
python .\scripts\make_transitions.py -i .\long_source.mp4 -n 8

# Validate transitions
python .\scripts\test_transitions.py --normalize --concat-audio-check
```

## Troubleshooting

- **Seeing only a few clips?** Use `--auto-expand` or `--target-duration` to let Clippy gather more.
- **Pixelation at cuts?** Try `--quality max` or `--bitrate 16M`.
- **Concat AAC errors?** Run `python .\scripts\test_transitions.py --normalize`.
- **No NVENC?** Use `--preset cpu_only` or let Clippy auto-detect with `detect_encoder()`.
- **Duplicate log messages in TUI?** Fixed in v0.5.0 — update to latest.

## Health Check

```powershell
python .\scripts\health_check.py
```

## Docs

- [Contributing](docs/CONTRIBUTING.md)
- [Code of Conduct](docs/CODE_OF_CONDUCT.md)
- [Security Policy](docs/SECURITY.md)
