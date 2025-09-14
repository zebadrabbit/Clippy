# _internal

Packaged, read-only data used by the portable build.

Contents (recommended):
- transitions/static.mp4 (REQUIRED): default static bumper used between clips
- assets/fonts/*: fonts used by overlays
- Optional: other default media or licenses

Runtime selection:
- Set `CLIPPY_USE_INTERNAL=1` to prefer bundled data first (falls back to external transitions if missing)
- `TRANSITIONS_DIR` can still override to a custom folder and takes precedence when set

Build packaging notes:
- Windows portable zips include `ffmpeg.exe`, `ffprobe.exe`, and `yt-dlp.exe` when available.
