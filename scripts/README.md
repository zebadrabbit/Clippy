# scripts/

This directory contains utility scripts that support development and distribution.

- `health_check.py`: A standalone preflight that verifies binaries (ffmpeg, yt-dlp), NVENC availability, Python packages, required folders, and `.env` credentials. It provides quick diagnostics before running Clippy or packaging.
 - `test_transitions.py`: Probes each file in `transitions/`, normalizes assets into `cache/_trans` (48 kHz stereo AAC), and can perform an audio-only concat check to detect cross-file issues. Use `--normalize` and `--concat-audio-check`.
 - `check_sequencing.py`: Validates the concat sequence policy (intro? → static → clip → static → chance(transition → static) … → outro?).

Typical usage:

- Run directly from source:
  - `python scripts/health_check.py`
- In the portable build:
  - Use `Start-HealthCheck.bat` (Windows) or run `HealthCheck` (Linux/macOS variant if built).

Notes:
- The checker prefers local `bin/` and `assets/fonts/` paths when running from source, and bundled paths when frozen.
- Coloring is minimal and safe for Windows consoles.
