# build/

Build and packaging scripts for creating a portable distribution of Clippy.

- `build.ps1` (Windows): Creates a self-contained `dist/Clippy` folder with `Clippy.exe`, `HealthCheck.exe`, bundled `ffmpeg.exe`, fonts, and helper BATs, then zips it to `Clippy-portable.zip`.
- `build.sh` (Linux/macOS): Shell equivalent to build a portable folder with `Clippy` and `HealthCheck` binaries using PyInstaller.

## Prerequisites

- Python 3.10+ with `pip`
- `pyinstaller` and runtime deps (`requests`, `Pillow`, `yachalk`, `yt_dlp`)
- On Windows: PowerShell, optional NVENC-capable GPU for hardware encoding
- On Linux/macOS: bash, GNU coreutils, and `zip`

## Outputs

- `build/dist/Clippy/` – portable run folder
- `build/Clippy-portable.zip` – distributable zip (do not commit; ignored by .gitignore)

## Tips

- Run `scripts/health_check.py` first to ensure your environment is healthy.
- ffmpeg.exe and ffprobe.exe are bundled into the portable by default when available at build time (or via the `-FetchFFmpeg` switch).
- Include `_internal/transitions/static.mp4` so new users have a default static clip; they can set `CLIPPY_USE_INTERNAL=1` at runtime to prefer packaged assets.
- Large binaries should not be committed; publish the zip as a release asset or CI artifact.
