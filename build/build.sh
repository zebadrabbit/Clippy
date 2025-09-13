#!/usr/bin/env bash
set -euo pipefail

# Ensure we run from this script's directory
cd -- "$(dirname -- "$0")"

CLEAN=0
if [[ "${1-}" == "--clean" ]]; then
  CLEAN=1
fi

echo '==> Preparing venv and dependencies'
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip

if [[ -f ../requirements.txt ]]; then
  pip install -r ../requirements.txt
else
  echo '(!) requirements.txt not found; installing minimal runtime deps'
  pip install requests pillow yachalk yt_dlp
fi
pip install pyinstaller

# Back-compat: if repo has root-level binaries/fonts, stage them into new layout
mkdir -p ../assets/fonts
mkdir -p ./bin
if [[ -f ../ffmpeg ]]; then
  cp -f ../ffmpeg ./bin/ffmpeg
fi
if [[ -f ../yt-dlp ]]; then
  cp -f ../yt-dlp ./bin/yt-dlp
fi
if [[ -f ../Roboto-Medium.ttf ]]; then
  cp -f ../Roboto-Medium.ttf ../assets/fonts/Roboto-Medium.ttf
fi

if (( CLEAN )); then
  echo '==> Cleaning previous builds'
  rm -rf ./dist ./build ./__pycache__ ./Clippy.spec ./Clippy-portable.zip || true
fi

echo '==> Building portable folder with PyInstaller'
# Determine ffmpeg/yt-dlp binary names for non-Windows
FFMPEG_BIN="../bin/ffmpeg"
YTDLP_BIN="./bin/yt-dlp"

pyinstaller --noconfirm --clean --onedir --name Clippy \
  ../main.py \
  --add-data "../transitions:transitions" \
  --add-data "../assets/fonts:assets/fonts" \
  --add-binary "$FFMPEG_BIN:." \
  --add-binary "$YTDLP_BIN:."

# Build a companion HealthCheck binary
pyinstaller --noconfirm --clean --onefile --name HealthCheck \
  --paths .. \
  --hidden-import config \
  ../scripts/health_check.py
cp -f ./dist/HealthCheck ./dist/Clippy/ || true

# Add helper files
mkdir -p dist/Clippy
if [[ -f ../README.md ]]; then
  cp -f ../README.md dist/Clippy/
else
  cat > dist/Clippy/README.txt << 'EOF'
Clippy Portable
===============

This is a portable build. Place your media assets (already bundled) and run the binary.

Notes:
- Requires network access for downloading clips.
- Ensure ffmpeg and yt-dlp remain alongside the main binary.
- Optionally run HealthCheck to verify environment.
EOF
fi
cat > dist/Clippy/.env.example << 'EOF'
# Twitch credentials (Client Credentials flow)
TWITCH_CLIENT_ID=your_id
TWITCH_CLIENT_SECRET=your_secret
EOF

# Create zip archive
echo '==> Creating zip archive Clippy-portable.zip'
rm -f ./Clippy-portable.zip
( cd dist/Clippy && zip -r -9 ../../Clippy-portable.zip . )

echo '=> Done. Distribute Clippy-portable.zip to end users.'
