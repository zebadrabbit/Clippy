# Clippy — Twitch Clip Compilation

[![CI](https://github.com/zebadrabbit/Clippy/actions/workflows/ci.yml/badge.svg)](https://github.com/zebadrabbit/Clippy/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/zebadrabbit/Clippy)](https://github.com/zebadrabbit/Clippy/releases/latest)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://github.com/zebadrabbit/Clippy)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Turn your Twitch clips into highlight reels — automatically. Clippy pulls clips, stitches them together with intros, transitions, and outros, and renders a polished compilation ready to upload. Under the hood, every asset gets normalized to a consistent codec (H.264/AAC) so concatenation never breaks mid-render.

## Features

- **Profiles**: one install, any number of channels. Each keeps its own branding —
  intro, outro, transitions — and its own defaults. Switch with a flag, a menu, or a
  dropdown in the TUI
- **Unattended**: `--headless` never prompts and `--json` reports what happened, so a
  scheduled job can build every week without you
- **Two interfaces**: Interactive Textual TUI (`clippy tui`) for beginners, full CLI for power users
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

## Install

Clippy needs **Python 3.10+** and **ffmpeg** (which provides `ffprobe`) on your PATH.

### From a release (quickest)

Grab the wheel from the [latest release](https://github.com/zebadrabbit/Clippy/releases/latest):

```powershell
pip install https://github.com/zebadrabbit/Clippy/releases/latest/download/clippy-0.6.0-py3-none-any.whl
```

Add the TUI with `pip install "clippy[tui] @ <url>"`, or install the extras separately
with `pip install textual`.

### From source

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[tui]"
```

```bash
# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[tui]"
```

This installs Clippy and the `clippy` command (add `,dev` for the test/lint tools:
`pip install -e ".[tui,dev]"`).

Then run the guided setup, which writes `clippy.yaml` and `.env` for you:

```powershell
clippy setup
```

> The examples below use PowerShell, since that is where Clippy gets the most use. Every
> `clippy ...` command is identical on Linux and macOS — only the venv activation and
> path separators differ. The pipeline is exercised on Linux by CI on every push.

## Quick Start

The `clippy` command has three entry points:

```powershell
clippy setup     # guided first-time setup (credentials + defaults)
clippy profile   # per-streamer defaults and branding (short; no credentials)
clippy doctor    # check your setup (ffmpeg, credentials, transitions, ...)
clippy tui       # interactive TUI
clippy           # the CLI (see clippy --help)
```

### TUI (recommended for first-time users)

```powershell
clippy tui
```

The TUI walks you through 7 steps: Source > Credentials > Clip Settings > Quality >
Transitions > Audio & Overlay > Review & Start. It saves credentials to `.env` on
request so subsequent runs auto-fill.

It is styled as a 90s BBS and fits an 80x24 terminal — no maximizing required.
Per-field guidance appears on the status line at the bottom for whichever field
has focus, rather than as paragraphs under every input.

- **Source** also picks the profile for the run, so the steps that follow prefill
  from that streamer's defaults and branding.
- **Clip Settings** picks the date range from presets (Today, This week, Last
  month, Last year, Everything, ...) with a *Custom dates* option for an exact
  window.
- **Transitions** is a two-pane transfer list: AVAILABLE on the left, SELECTED on
  the right. Move clips with the arrow keys or SPACE, `A` for all, `N` for none,
  or the *Add all* / *Clear all* buttons. The right pane is the pool the build
  draws from.
- **Building** shows overall and per-compilation progress, a live ffmpeg activity
  line, and a log that stays readable — progress redraws update in place instead
  of filling the scrollback.

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
clippy --discord --discord-channel-id 123456789012345678 -y
```

What happens: Clippy reads messages from the channel, extracts Twitch clip links, resolves them via Helix, and builds compilations. This lets your Twitch community curate clips collaboratively.

## Profiles — one install, every channel

If you cut compilations for more than one streamer, this is the part that saves you
the most time. A profile bundles a channel with *its own* branding and defaults, so
you stop editing config between runs.

```powershell
clippy profile               # create or edit one — seven fields, no credential prompts
clippy profile use theflood  # make it the default for every run
clippy --list-profiles       # what's defined
```

Then pick one per run, from anywhere:

```powershell
clippy --profile theflood       # CLI
clippy --profile someoneelse    # a different channel, same install
clippy --profile default        # ignore profiles entirely for this run
```

**In the TUI**, it's the first thing you choose. The Source step has a profile
dropdown, and every step after it — channel, clip counts, transitions — prefills from
that streamer's settings. The Review screen shows which profile is about to run.

### Each channel gets its own look

Drop a streamer's artwork in a folder named after their profile. Assets resolve from
there first and fall back to the shared folder, so files everyone uses stay in one
place:

```
transitions/
  static.mp4              # shared by every profile
  transition_01.mp4       # shared
  theflood/
    intro.mp4             # only when the theflood profile is active
    outro.mp4
    transition_01.mp4     # shadows the shared one of the same name
  someoneelse/
    intro.mp4
```

`clippy profile` offers to create the folder for you. **Nothing needs moving to adopt
this** — a flat `transitions/` folder keeps working exactly as before.

### What a profile can override

Anything in `clippy.yaml`. A profile is a partial copy merged over the top, and
whatever it doesn't mention falls back to your shared values:

```yaml
active_profile: theflood
profiles:
  theflood:
    identity:
      broadcaster: theflood
    assets:
      intro: [intro.mp4]
      outro: [outro.mp4]
    selection:
      clips_per_compilation: 20
  someoneelse:
    identity:
      broadcaster: someoneelse
    encoding:
      resolution: 1280x720
```

There's always a built-in `default` profile that applies no overrides at all — the
plain `clippy.yaml` and the transitions root. `clippy profile use default` drops
`active_profile` again.

Precedence is `clippy.yaml` → profile → CLI flags, so `--clips 5` still wins over
whatever the profile says.

## Unattended runs — set it and forget it

Point a scheduler at Clippy and it will keep producing compilations without you.

```bash
clippy --headless --profile theflood --json
```

`--headless` is the one flag that makes a run safe to leave alone: it implies `-y`,
drops colour and the banner so logs stay readable, and **fails instead of waiting**
if anything would have prompted. No half-finished job blocked on a question nobody
is there to answer.

### A weekly build per streamer

Because profiles and headless compose, one scheduled entry per channel is all it
takes:

```bash
# crontab — Monday mornings, one job per streamer
0 6 * * 1  clippy --headless --profile theflood --json >> /var/log/clippy.log 2>&1
0 7 * * 1  clippy --headless --profile someoneelse --json >> /var/log/clippy.log 2>&1
```

```powershell
# Windows Task Scheduler — one weekly task per streamer
schtasks /create /tn "Clippy theflood" /sc weekly /d MON /st 06:00 /tr "clippy --headless --profile theflood --json"
```

### Knowing what happened

`--json` prints one result document, whatever the outcome — success or failure, the
same shape every time:

```json
{
  "status": "ok",
  "exit_code": 0,
  "files": ["theflood_2025-07-01_to_2025-07-07_part1.mp4"],
  "broadcaster": "theflood",
  "compilations": 1,
  "version": "0.6.0"
}
```

And the exit code tells a scheduler how to react without reading a single log line:

| Code | Meaning | What a job should do |
|---|---|---|
| `0` | Built at least one compilation | Nothing — it worked |
| `2` | Bad invocation or configuration | Fix the setup; it won't fix itself |
| `3` | Ran fine, nothing matched | Shrug. A quiet week, or the min-views filter |
| `4` | Credentials missing or rejected | Alert — the token needs attention |
| `5` | ffmpeg or yt-dlp failed | Alert — check the tooling |
| `1` | Unexpected failure | Alert |
| `130` | Interrupted | Someone stopped it |

`3` is deliberately separate from `1`: **a quiet week is not a failure**, and a
nightly job shouldn't page you for one.

## Configuration

- Precedence: CLI flags > Environment (`.env`) > profile > `clippy.yaml` > built-in defaults.
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
clippy --help
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
| `--headless` | Unattended: implies `-y`, no colour, no banner, never prompts |
| `--json` | Print a machine-readable result document |
| `--profile` | Use a named profile from `clippy.yaml` |
| `--list-profiles` | List defined profiles and exit |
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
clippy --broadcaster somechannel --preset youtube_1080p60 --cq 18
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
- **No NVENC?** Nothing to do — Clippy runs a throwaway trial encode at startup and falls back to libx264 (CPU) if it fails. `clippy doctor` warns when it does. Use `--preset cpu_only` to force it.
- **`Cannot load libcuda.so.1`?** Your ffmpeg was built with NVENC but there is no NVIDIA driver — common on packaged Linux ffmpeg and on AMD machines. Clippy detects this and uses libx264; if you see it, you are on a build before v0.6.0.
- **Duplicate log messages in TUI?** Fixed in v0.5.0 — update to latest.

## Health Check

The quickest check is the built-in `clippy doctor`, which verifies ffmpeg, credentials,
the transitions folder, and the overlay font:

```powershell
clippy doctor
```

A deeper environment script is also available:

```powershell
python .\scripts\health_check.py
```

## Docs

- [Contributing](docs/CONTRIBUTING.md)
- [Code of Conduct](docs/CODE_OF_CONDUCT.md)
- [Security Policy](docs/SECURITY.md)
