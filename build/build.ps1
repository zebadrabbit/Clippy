Param(
  [switch]$Clean,
  [switch]$FetchFFmpeg
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

# Fetch ffmpeg.exe for bundling (used by runtime and placeholder generation)
function Get-PortableFFmpeg {
  param([string]$OutPath)
  $url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
  $tmp = Join-Path $env:TEMP ("ffmpeg_dl_" + (Get-Random))
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  Write-Host "==> Downloading ffmpeg from $url"
  $zip = Join-Path $tmp 'ffmpeg.zip'
  Invoke-WebRequest -Uri $url -OutFile $zip
  Expand-Archive -LiteralPath $zip -DestinationPath (Join-Path $tmp 'unz') -Force
  $ff = Get-ChildItem -Recurse -Filter ffmpeg.exe -Path (Join-Path $tmp 'unz') | Select-Object -First 1
  $fp = Get-ChildItem -Recurse -Filter ffprobe.exe -Path (Join-Path $tmp 'unz') | Select-Object -First 1
  if (-not $ff) { throw 'Could not locate ffmpeg.exe in archive.' }
  if (-not $fp) { Write-Warning 'Could not locate ffprobe.exe in archive.' }
  Copy-Item $ff.FullName $OutPath -Force
  if ($fp) {
    $probeOut = Join-Path (Split-Path -Parent $OutPath) 'ffprobe.exe'
    Copy-Item $fp.FullName $probeOut -Force
  }
  # Try to capture a license text file alongside
  $lic = Get-ChildItem -Recurse -Path (Join-Path $tmp 'unz') -Include 'LICENSE*.txt','COPYING*.txt' | Select-Object -First 1
  if ($lic) { Copy-Item $lic.FullName (Join-Path (Split-Path -Parent $OutPath) 'ffmpeg-LICENSE.txt') -Force }
  Write-Host "==> ffmpeg.exe fetched to $OutPath"
}

# Always ensure ffmpeg.exe is present; download if missing
if (-not (Test-Path .\bin\ffmpeg.exe)) {
  try {
    $out = Join-Path (Resolve-Path .\bin).Path 'ffmpeg.exe'
    Get-PortableFFmpeg -OutPath $out
  } catch {
    Write-Warning "ffmpeg.exe missing and could not be downloaded: $_"
  }
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

Write-Host '==> Preparing assets (transitions/static.mp4)'
# Ensure transitions/static.mp4 exists before bundling; also stage a copy under _internal/transitions
New-Item -ItemType Directory -Force -Path ..\transitions | Out-Null
New-Item -ItemType Directory -Force -Path ..\_internal\transitions | Out-Null
$tDir = (Resolve-Path ..\transitions).Path
$iDir = (Resolve-Path ..\_internal\transitions).Path
$staticPath = Join-Path $tDir 'static.mp4'
$internalStatic = Join-Path $iDir 'static.mp4'
if (-not (Test-Path $staticPath)) {
  # Try to find ffmpeg for placeholder generation
  $ff = $null
  if (Test-Path ..\bin\ffmpeg.exe) { $ff = (Resolve-Path ..\bin\ffmpeg.exe).Path }
  elseif (Test-Path .\bin\ffmpeg.exe) { $ff = (Resolve-Path .\bin\ffmpeg.exe).Path }
  else {
    try { $ffCmd = Get-Command ffmpeg -ErrorAction Stop; $ff = $ffCmd.Source } catch { $ff = $null }
  }
  if ($ff) {
    Write-Host '==> Creating default transitions/static.mp4 placeholder (1s 1080p black)'
    & "$ff" -y -f lavfi -i color=black:s=1920x1080:d=1 -c:v libx264 -pix_fmt yuv420p "$staticPath" | Out-Null
  } else {
    Write-Warning 'ffmpeg not available during build; static.mp4 will be generated at runtime if possible.'
  }
}
if (-not (Test-Path $internalStatic) -and (Test-Path $staticPath)) {
  Copy-Item $staticPath $internalStatic -Force
}

Write-Host '==> Building portable folder with PyInstaller'
# Select ffmpeg/yt-dlp binary paths to bundle (support repo bin/ and build/bin/)
$ffmpegRepo = Join-Path .. 'bin/ffmpeg.exe'
$ffmpegBuild = '.\\bin\\ffmpeg.exe'
$ffprobeRepo = Join-Path .. 'bin/ffprobe.exe'
$ffprobeBuild = '.\\bin\\ffprobe.exe'
$ytDlpRepo = Join-Path .. 'bin/yt-dlp.exe'
$ytDlpBuild = '.\\bin\\yt-dlp.exe'

$pyArgs = @(
  '--noconfirm','--clean','--onedir','--name','Clippy',
  '..\\main.py',
  '--add-data','..\\transitions;transitions',
  '--add-data','..\\assets\\fonts;assets/fonts',
  '--add-data','..\\_internal;_internal'
)
if (Test-Path $ffmpegBuild) { $pyArgs += @('--add-binary', "${ffmpegBuild};.") }
elseif (Test-Path $ffmpegRepo) { $pyArgs += @('--add-binary', "${ffmpegRepo};.") }
else { Write-Host '(!) ffmpeg.exe not found in ..\bin or .\bin; runtime will try PATH' -ForegroundColor Yellow }

if (Test-Path $ytDlpBuild) { $pyArgs += @('--add-binary', "${ytDlpBuild};.") }
elseif (Test-Path $ytDlpRepo) { $pyArgs += @('--add-binary', "${ytDlpRepo};.") }
else { Write-Host '(!) yt-dlp.exe not found in .\bin or ..\bin; runtime will try PATH' -ForegroundColor Yellow }

# Also add ffprobe.exe if present
if (Test-Path $ffprobeBuild) { $pyArgs += @('--add-binary', "${ffprobeBuild};.") }
elseif (Test-Path $ffprobeRepo) { $pyArgs += @('--add-binary', "${ffprobeRepo};.") }
else { Write-Host '(!) ffprobe.exe not found in ..\bin or .\bin; runtime will try PATH' -ForegroundColor Yellow }

& pyinstaller @pyArgs

# Build a companion HealthCheck.exe (ensure top-level config is importable)
Write-Host '==> Building HealthCheck utility'
$hcArgs = @(
  '--noconfirm','--clean','--onefile','--name','HealthCheck',
  '--paths','..',
  '--hidden-import','clippy.config',
  '..\\scripts\\health_check.py'
)
& pyinstaller @hcArgs

# Ensure destination exists before copying HealthCheck
if (-not (Test-Path .\dist\Clippy)) {
  New-Item -ItemType Directory -Force -Path .\dist\Clippy | Out-Null
}
Copy-Item .\dist\HealthCheck.exe .\dist\Clippy\ -Force

# Ensure a default static.mp4 is bundled if present
if (Test-Path ..\transitions\static.mp4) {
  Write-Host '==> Found transitions/static.mp4, bundling as default stub'
} else {
  Write-Host '==> transitions/static.mp4 not found; runtime will generate a 1s black placeholder'
}

Write-Host '==> Adding helper files to dist'
New-Item -ItemType Directory -Force -Path dist\Clippy | Out-Null
# If we fetched/copied a license text for ffmpeg, surface it in dist
if (Test-Path .\bin\ffmpeg-LICENSE.txt) {
  Copy-Item .\bin\ffmpeg-LICENSE.txt dist\Clippy\ -Force
}
# Ensure assets/fonts exists in portable and copy bundled font if present
New-Item -ItemType Directory -Force -Path dist\Clippy\assets\fonts | Out-Null
# Try common internal data locations for the font
if (Test-Path .\dist\Clippy\_internal\Roboto-Medium.ttf) {
  Copy-Item .\dist\Clippy\_internal\Roboto-Medium.ttf dist\Clippy\assets\fonts\Roboto-Medium.ttf -Force
} elseif (Test-Path .\dist\Clippy\_internal\assets\fonts\Roboto-Medium.ttf) {
  Copy-Item .\dist\Clippy\_internal\assets\fonts\Roboto-Medium.ttf dist\Clippy\assets\fonts\Roboto-Medium.ttf -Force
}

# Ensure ffmpeg.exe and yt-dlp.exe are at app root; some PyInstaller versions place them under _internal
if ((-not (Test-Path .\dist\Clippy\ffmpeg.exe)) -and (Test-Path .\dist\Clippy\_internal\ffmpeg.exe)) {
  Copy-Item .\dist\Clippy\_internal\ffmpeg.exe .\dist\Clippy\ffmpeg.exe -Force
}
if ((-not (Test-Path .\dist\Clippy\yt-dlp.exe)) -and (Test-Path .\dist\Clippy\_internal\yt-dlp.exe)) {
  Copy-Item .\dist\Clippy\_internal\yt-dlp.exe .\dist\Clippy\yt-dlp.exe -Force
}
if ((-not (Test-Path .\dist\Clippy\ffprobe.exe)) -and (Test-Path .\dist\Clippy\_internal\ffprobe.exe)) {
  Copy-Item .\dist\Clippy\_internal\ffprobe.exe .\dist\Clippy\ffprobe.exe -Force
}
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
