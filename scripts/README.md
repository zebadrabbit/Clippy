# scripts/

This directory contains utility scripts that support development and distribution.

- `health_check.py`: A standalone preflight that verifies binaries (ffmpeg, yt-dlp), NVENC availability, Python packages, required folders, and `.env` credentials. It provides quick diagnostics before running Clippy or packaging.
 - `test_transitions.py`: Probes each file in `transitions/`, normalizes assets into `cache/_trans` (48 kHz stereo AAC), and can perform an audio-only concat check to detect cross-file issues. Use `--normalize` and `--concat-audio-check`.
 - `check_sequencing.py`: Validates the concat sequence policy (intro? → static → clip → static → chance(transition → static) … → outro?).


## Setup Wizard

- `setup_wizard.py`: An interactive guided setup that helps you:
  - Enter and save your Twitch Client ID/Secret (writes a `.env`)
  - Choose sensible defaults (clips per compilation, number of compilations, min views)
  - Pick quality preset and tune resolution/fps/audio
  - Configure transitions behavior and audio preferences
  - Set cache/output paths and concurrency
  - Prefer bundled transitions via `CLIPPY_USE_INTERNAL=1` or specify a transitions directory
  - Generates a ready-to-run PowerShell helper `run_clippy.ps1`

Usage (PowerShell):

```powershell
python .\scripts\setup_wizard.py
```
Typical usage:

- Run directly from source:
  - `python scripts/health_check.py`
- In the portable build:
  - Use `Start-HealthCheck.bat` (Windows) or run `HealthCheck` (Linux/macOS variant if built).

Notes:
- The checker prefers local `bin/` and `assets/fonts/` paths when running from source, and bundled paths when frozen.
- Coloring is minimal and safe for Windows consoles.
