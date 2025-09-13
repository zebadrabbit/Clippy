# scripts/

This directory contains utility scripts that support development and distribution.

- `health_check.py`: A standalone preflight that verifies binaries (ffmpeg, yt-dlp), NVENC availability, Python packages, required folders, and `.env` credentials. It provides quick diagnostics before running Clippy or packaging.

Typical usage:

- Run directly from source:
  - `python scripts/health_check.py`
- In the portable build:
  - Use `Start-HealthCheck.bat` (Windows) or run `HealthCheck` (Linux/macOS variant if built).

Notes:
- The checker prefers local `bin/` and `assets/fonts/` paths when running from source, and bundled paths when frozen.
- Coloring is minimal and safe for Windows consoles.
