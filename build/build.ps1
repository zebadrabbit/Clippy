Param(
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

# Ensure we run from this script's directory
Set-Location -LiteralPath $PSScriptRoot

Write-Host '==> Preparing venv and dependencies'
if (-not (Test-Path .venv)) {
  python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# Install deps from root requirements.txt if present; else install minimal set
if (Test-Path ..\requirements.txt) {
  pip install -r ..\requirements.txt
} else {
  Write-Host '(!) requirements.txt not found in repo root; installing minimal runtime deps'
  pip install requests pillow yachalk yt_dlp
}
pip install pyinstaller

Write-Host '==> Ensuring yt-dlp.exe is present (used by downloader)'
New-Item -ItemType Directory -Force -Path .\bin | Out-Null
if (-not (Test-Path .\bin\yt-dlp.exe)) {
  $ydl = 'https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe'
  Invoke-WebRequest -Uri $ydl -OutFile .\bin\yt-dlp.exe
}

# Back-compat: if repo has root-level ffmpeg.exe/yt-dlp.exe/Roboto-Medium.ttf, stage them into new layout
if (Test-Path ..\ffmpeg.exe) {
  Copy-Item ..\ffmpeg.exe .\bin\ffmpeg.exe -Force
}
if ((Test-Path ..\yt-dlp.exe) -and -not (Test-Path .\bin\yt-dlp.exe)) {
  Copy-Item ..\yt-dlp.exe .\bin\yt-dlp.exe -Force
}
New-Item -ItemType Directory -Force -Path ..\assets\fonts | Out-Null
if (Test-Path ..\Roboto-Medium.ttf) {
  Copy-Item ..\Roboto-Medium.ttf ..\assets\fonts\Roboto-Medium.ttf -Force
}

if ($Clean) {
  Write-Host '==> Cleaning previous builds'
  Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue
  Remove-Item -Force .\Clippy.spec -ErrorAction SilentlyContinue
  Remove-Item -Force .\Clippy-portable.zip -ErrorAction SilentlyContinue
}

Write-Host '==> Building portable folder with PyInstaller'
pyinstaller --noconfirm --clean --onedir --name Clippy `
  ..\main.py `
  --add-data "..\transitions;transitions" `
  --add-data "..\assets\fonts;assets/fonts" `
  --add-binary "..\bin\ffmpeg.exe;." `
  --add-binary ".\bin\yt-dlp.exe;."

# Build a companion HealthCheck.exe (ensure top-level config is importable)
Write-Host '==> Building HealthCheck utility'
pyinstaller --noconfirm --clean --onefile --name HealthCheck `
  --paths .. `
  --hidden-import config `
  ..\scripts\health_check.py
Copy-Item .\dist\HealthCheck.exe .\dist\Clippy\ -Force

# Ensure a default static.mp4 is bundled if present
if (Test-Path ..\transitions\static.mp4) {
  Write-Host '==> Found transitions/static.mp4, bundling as default stub'
} else {
  Write-Host '==> transitions/static.mp4 not found; runtime will generate a 1s black placeholder'
}

Write-Host '==> Adding helper files to dist'
New-Item -ItemType Directory -Force -Path dist\Clippy | Out-Null
if (Test-Path ..\README.md) {
  Copy-Item ..\README.md dist\Clippy\ -Force
} else {
  @'
Clippy Portable
================

This is a portable build. Place your media assets (already bundled) and run Start-Clippy.bat.

Notes:
- Requires network access for downloading clips.
- Ensure ffmpeg.exe and yt-dlp.exe remain alongside Clippy.exe.
- Optionally run HealthCheck.exe to verify environment.
'@ | Out-File -Encoding utf8 dist\Clippy\README.txt
}
@'
# Twitch credentials (Client Credentials flow)
TWITCH_CLIENT_ID=your_id
TWITCH_CLIENT_SECRET=your_secret
'@ | Out-File -Encoding utf8 dist\Clippy\.env.example
@'
@echo off
REM Launch Clippy
setlocal
"%~dp0Clippy.exe" %*
endlocal
'@ | Out-File -Encoding ascii dist\Clippy\Start-Clippy.bat

@'
@echo off
REM Run environment & dependency health check
setlocal
"%~dp0HealthCheck.exe"
endlocal
'@ | Out-File -Encoding ascii dist\Clippy\Start-HealthCheck.bat
Write-Host '==> Creating zip archive Clippy-portable.zip'
if (Test-Path .\Clippy-portable.zip) { Remove-Item .\Clippy-portable.zip -Force }
Compress-Archive -Path .\dist\Clippy\* -DestinationPath .\Clippy-portable.zip

Write-Host '=> Done. Distribute Clippy-portable.zip to end users.'
