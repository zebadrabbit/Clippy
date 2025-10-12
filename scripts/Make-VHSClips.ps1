param(
  [Parameter(Mandatory=$true)][string]$InputPath,
  [int]$Count = 8,
  [string]$OutDir = ".\vhs_clips",
  [switch]$VerboseFilters,
  [switch]$UseNvenc,
  [double]$MinSeconds = 3.0,
  [double]$MaxSeconds = 5.0,
  [string]$Fps = '30000/1001',
  [int]$Seed,
  [switch]$NoAudioFx
)

function Resolve-Binary([string]$preferredPath, [string]$fallbackName) {
  if ($preferredPath -and (Test-Path $preferredPath)) { return (Resolve-Path $preferredPath).Path }
  $cmd = Get-Command $fallbackName -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

# --- sanity ---
if (!(Test-Path $InputPath)) { throw "Input not found: $InputPath" }
if (!(Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }

# Prefer repo-bundled ffmpeg/ffprobe if present
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptRoot '..')
$ffmpeg = Resolve-Binary (Join-Path $repoRoot 'bin/ffmpeg.exe') 'ffmpeg'
$ffprobe = Resolve-Binary (Join-Path $repoRoot 'bin/ffprobe.exe') 'ffprobe'
if (-not $ffprobe) { throw "ffprobe not found (looked in repo bin/ and PATH)." }
if (-not $ffmpeg)  { throw "ffmpeg not found (looked in repo bin/ and PATH)." }

# Optional deterministic randomness
if ($PSBoundParameters.ContainsKey('Seed')) { Get-Random -SetSeed $Seed | Out-Null }

if ($MinSeconds -le 0 -or $MaxSeconds -le 0 -or $MaxSeconds -le $MinSeconds) {
  throw "Invalid duration bounds. Ensure MinSeconds > 0, MaxSeconds > 0, and MaxSeconds > MinSeconds."
}

# --- get duration ---
$duration = [double](& $ffprobe -v error -show_entries format=duration `
  -of default=noprint_wrappers=1:nokey=1 -- $InputPath)
if ($duration -le ($MinSeconds + 1.0)) { throw "Video too short for random $($MinSeconds)-$($MaxSeconds) s clips." }

# --- VHS VIDEO PRESETS ---
# Notes:
# - We downscale/upscale for softness, add chroma bleed, noise, ghosting, mild wobble, etc.
# - All end with format=yuv420p to keep players happy.
$videoPresets = @(
  # A) Soft blur + chroma bleed + noise (classic tape softness)
  "fps=30000/1001,scale=360:-2,scale=1920:1080:flags=neighbor,chromashift=cbh=2:crh=-2:cbv=1,boxblur=2:1,noise=alls=20:allf=t+u,eq=contrast=0.9:saturation=1.2:gamma=1.02,format=yuv420p",

  # B) Ghosting (frame blending) + light noise
  "fps=30000/1001,tmix=frames=3:weights='1 0.7 0.3',scale=1920:1080,noise=alls=12:allf=t+u,format=yuv420p",

  # C) Mild “handheld wobble” + occasional tracking bar
  "fps=30000/1001,scale=1920:1080,rotate=0.008*sin(2*PI*t):ow='rotw(iw)':oh='roth(ih)':fillcolor=black,drawbox=x=0:y=ih-12:w=iw:h=12:color=white@0.06:t=fill:enable='gt(mod(t,3),2.6)',noise=alls=10:allf=t+u,format=yuv420p",

  # D) Down-up res + slight unsharp (edge mush + tiny crisp) + vintage curve
  "fps=30000/1001,scale=640:-2,scale=1920:1080:flags=bilinear,unsharp=lx=5:ly=5:la=-1.0:cx=5:cy=5:ca=1.0,curves=preset=medium_contrast,format=yuv420p",

  # E) Color drift via hue wobble + noise (time-varying hue shift)
  "fps=30000/1001,scale=1920:1080,hue=h='15*sin(2*PI*t*0.8)':s=1,noise=alls=8:allf=t+u,format=yuv420p"
)

# Add two more variants with subtle line bleed and scanlines
$videoPresets += @(
  # F) Horizontal line bleed + gentle noise
  "fps=30000/1001,scale=960:-2,scale=1920:1080:flags=bilinear,hqdn3d=2.5:2.5:6:6,lagfun=decay=0.92,noise=alls=10:allf=t+u,format=yuv420p",
  # G) Fake scanlines overlay using drawbox repeats
  "fps=30000/1001,scale=1920:1080,format=yuv420p,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)',drawbox=x=0:y=0:w=iw:h=1:color=black@0.08:t=fill:enable='lt(mod(n,2),1)'"
)

# --- AUDIO PRESETS (tape-ish) ---
$audioPresets = @(
  # 1) Telephone-ish band limit + gentle comp
  "lowpass=f=3600,highpass=f=60,acompressor=threshold=-18dB:ratio=3,volume=0.95",
  # 2) Mild bit crush + band limit
  "acrusher=bits=12:mix=0.2,highpass=f=80,lowpass=f=3400,volume=0.95",
  # 3) Tiny slapback echo + lowpass
  "aecho=0.6:0.6:20:0.2,lowpass=f=3200,volume=0.95",
  # 4) Subtle wow/flutter (vibrato) + lowpass
  "vibrato=f=4.5:d=0.006,lowpass=f=3500,volume=0.95"
)

# --- helper: pick random float in [min,max) ---
function Get-RandFloat([double]$min, [double]$max) {
  $r = Get-Random -Minimum 0.0 -Maximum 1.0
  return ($min + ($max - $min) * $r)
}

# --- main loop ---
for ($i=1; $i -le $Count; $i++) {
  $len = [Math]::Round((Get-RandFloat $MinSeconds $MaxSeconds),2)
  $maxStart = [Math]::Max(0.0, $duration - ($len + 0.25))
  $start = [Math]::Round((Get-RandFloat 0.0 $maxStart),2)

  $vf = $videoPresets | Get-Random
  $af = if ($NoAudioFx) { $null } else { $audioPresets | Get-Random }

  $baseName = [System.IO.Path]::GetFileNameWithoutExtension($InputPath)
  $out = Join-Path $OutDir ("{0}_vhs_{1:00}.mp4" -f $baseName,$i)

  if ($VerboseFilters) {
    Write-Host "`nClip $i  start=$start  len=$len"
    Write-Host "VF: $vf"
    Write-Host "AF: $af"
  }

  # -ss before -i for fast seek; we also set -t for duration
  # choose encoder args
  $vArgs = @()
  if ($UseNvenc) {
    # Try to detect NVENC availability; if missing, fall back to libx264
    $encList = (& $ffmpeg -hide_banner -encoders 2>$null) | Select-String -SimpleMatch 'h264_nvenc'
    if (-not $encList) {
      Write-Warning "h264_nvenc not available in this ffmpeg build. Falling back to libx264."
      $UseNvenc = $false
    }
  }
  if ($UseNvenc) {
    $vArgs = @('-c:v','h264_nvenc','-rc','vbr','-cq','21','-b:v','0','-preset','p5')
  } else {
    $vArgs = @('-c:v','libx264','-crf','18','-preset','veryfast','-tune','film')
  }

  $common = @('-y','-ss', $start, '-t', $len, '-i', $InputPath, '-vf', $vf, '-s','1920x1080','-r', $Fps) + $vArgs + @('-c:a','aac','-b:a','128k','-movflags','+faststart','--', $out)

  if ($af) {
    $common = @('-y','-ss', $start, '-t', $len, '-i', $InputPath, '-vf', $vf, '-af', $af, '-s','1920x1080','-r', $Fps) + $vArgs + @('-c:a','aac','-b:a','128k','-movflags','+faststart','--', $out)
  }

  & $ffmpeg @common | Out-Null
}

Write-Host "`nDone. Clips in: $OutDir"
