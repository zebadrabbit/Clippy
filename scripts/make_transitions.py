r"""
Generate random short transition clips from a long-form video using ffmpeg.

Features:
- Picks random start times and durations (default 1-3s) within the source video.
- Normalizes each clip to a target resolution and FPS for safe concatenation.
- Names outputs as transition_##.mp4 into the transitions folder by default.

Examples (PowerShell):
  # 8 clips, random 1-3s, outputs to resolved transitions folder
  python .\scripts\make_transitions.py -i .\long.mp4 -n 8

  # Custom durations and output folder
  python .\scripts\make_transitions.py -i .\long.mp4 -n 12 --min-dur 2 --max-dur 4 --out-dir .\transitions

Requirements:
- ffmpeg and ffprobe available (either in PATH or from config.ffmpeg's directory)
"""

from __future__ import annotations

import argparse
import os
import random
import shlex
import subprocess
import sys
from typing import Optional, Tuple


# Ensure repo root is on sys.path for config/utils imports when run from scripts/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
	sys.path.insert(0, ROOT)


def _try_import_defaults() -> Tuple[int, int, int]:
	"""Try to get default (width, height, fps) from config; else use 1920x1080@60."""
	width, height, fps = 1920, 1080, 60
	try:
		import clippy.config as _cfg  # type: ignore
		# resolution like "1920x1080"
		res = getattr(_cfg, 'resolution', '1920x1080')
		if isinstance(res, str) and 'x' in res:
			w_s, h_s = res.split('x', 1)
			width, height = int(w_s), int(h_s)
		fps_val = getattr(_cfg, 'fps', '60')
		fps = int(str(fps_val))
	except Exception:
		pass
	return width, height, fps


def _resolve_ffmpeg_tools() -> Tuple[str, str]:
	"""Resolve ffmpeg and ffprobe executable paths.

	- Try config.ffmpeg for ffmpeg.
	- Derive ffprobe from the same folder when possible, else use 'ffprobe' from PATH.
	- Fallback to 'ffmpeg'/'ffprobe' names if config is not available.
	"""
	ffmpeg = 'ffmpeg'
	try:
		import clippy.config as _cfg  # type: ignore
		ffmpeg = getattr(_cfg, 'ffmpeg', 'ffmpeg')
	except Exception:
		pass
	# ffprobe usually lives next to ffmpeg when bundled
	ffprobe = 'ffprobe'
	try:
		if ffmpeg and (os.path.sep in ffmpeg or os.path.altsep and os.path.altsep in ffmpeg):
			base = os.path.dirname(os.path.abspath(ffmpeg))
			cand = os.path.join(base, 'ffprobe.exe' if os.name == 'nt' else 'ffprobe')
			if os.path.exists(cand):
				ffprobe = cand
	except Exception:
		pass
	return ffmpeg, ffprobe


def _resolve_out_dir(cli_out: Optional[str]) -> str:
	if cli_out:
		return os.path.abspath(cli_out)
	# Prefer utils.resolve_transitions_dir() if available
	try:
		from clippy.utils import resolve_transitions_dir  # type: ignore
		return os.path.abspath(resolve_transitions_dir())
	except Exception:
		return os.path.abspath(os.path.join(ROOT, 'transitions'))


def _run(cmd: list[str]) -> Tuple[int, str]:
	try:
		proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		out = (proc.stdout or b'').decode(errors='ignore') + (proc.stderr or b'').decode(errors='ignore')
		return int(proc.returncode or 0), out
	except Exception as e:
		return 1, str(e)


def _get_duration(ffprobe: str, input_path: str) -> float:
	"""Return duration in seconds using ffprobe if available; fall back to parsing ffmpeg -i output."""
	# Primary: ffprobe
	cmd = [ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_path]
	code, out = _run(cmd)
	if code == 0 and out.strip():
		try:
			return float(out.strip())
		except Exception:
			pass
	# Fallback: ffmpeg -i (parse "Duration: HH:MM:SS.xx")
	ffmpeg, _ = _resolve_ffmpeg_tools()
	code2, out2 = _run([ffmpeg, '-hide_banner', '-i', input_path])
	text = out2 or ''
	import re
	m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
	if m:
		h, mmin, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
		return h * 3600 + mmin * 60 + s
	raise RuntimeError('Could not read duration from input via ffprobe or ffmpeg')


def _build_vf(width: int, height: int) -> str:
	return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"


def _find_next_start_index(out_dir: str, prefix: str) -> int:
	"""Scan existing files like prefix_##.mp4 and return max(index)+1 (default 1)."""
	try:
		entries = os.listdir(out_dir)
	except Exception:
		return 1
	import re
	rx = re.compile(r'^' + re.escape(prefix) + r'(\d+)\.mp4$', re.IGNORECASE)
	max_n = 0
	for name in entries:
		m = rx.match(name)
		if m:
			try:
				n = int(m.group(1))
				if n > max_n:
					max_n = n
			except Exception:
				pass
	return max_n + 1 if max_n >= 1 else 1


def generate_clips(input_path: str, out_dir: str, count: int, min_dur: int, max_dur: int, width: int, height: int, fps: int, prefix: str, overwrite: bool, seed: Optional[int], start_index: Optional[int] = None) -> None:
	if not os.path.isfile(input_path):
		raise FileNotFoundError(f"Input not found: {input_path}")
	if count <= 0:
		raise ValueError('Count must be > 0')
	if min_dur < 1 or max_dur < min_dur:
		raise ValueError('Invalid duration range')
	os.makedirs(out_dir, exist_ok=True)

	ffmpeg, ffprobe = _resolve_ffmpeg_tools()
	dur = _get_duration(ffprobe, input_path)
	if dur <= min_dur:
		raise ValueError('Input is too short for the requested durations')

	rng = random.Random(seed)
	vf = _build_vf(width, height)

	# Determine starting index: continue numbering after existing files unless explicitly overwriting
	idx = int(start_index) if start_index is not None else _find_next_start_index(out_dir, prefix)
	if idx > 1:
		print(f"Starting at index {idx} (continuing after existing files)")

	made = []
	for j in range(count):
		i = idx + j
		seg_dur = rng.randint(min_dur, max_dur)
		max_start = max(0.0, dur - seg_dur - 0.25)
		if max_start <= 0:
			raise ValueError('Input is too short for segment selection')
		start = rng.uniform(0.0, max_start)
		start = round(start, 3)  # milliseconds precision

		out_name = f"{prefix}{i:02d}.mp4"
		out_path = os.path.join(out_dir, out_name)
		if os.path.exists(out_path) and not overwrite:
			# If collision, bump index to next available and recompute
			i = _find_next_start_index(out_dir, prefix)
			out_name = f"{prefix}{i:02d}.mp4"
			out_path = os.path.join(out_dir, out_name)

		print(f"- clip {i}/{count}: start={start}s dur={seg_dur}s -> {out_name}")
		cmd = [
			ffmpeg, '-y',
			'-ss', str(start), '-i', input_path, '-t', str(seg_dur),
			'-vf', vf, '-r', str(fps),
			'-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
			'-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2',
			'-movflags', '+faststart',
			out_path,
		]
		code, out = _run(cmd)
		if code != 0:
			raise RuntimeError(f"ffmpeg failed for {out_name}:\n{out}")
		made.append(out_path)

	print(f"Done. Created {len(made)} file(s) in: {out_dir}")


def parse_args(argv: Optional[list[str]] = None):
	W, H, FPS = _try_import_defaults()
	p = argparse.ArgumentParser(description='Generate random transition clips from a long video')
	p.add_argument('-i', '--input', required=True, help='Input long-form video file')
	p.add_argument('-n', '--count', type=int, default=6, help='Number of clips to produce')
	p.add_argument('--min-dur', type=int, default=1, help='Minimum duration (seconds)')
	p.add_argument('--max-dur', type=int, default=3, help='Maximum duration (seconds)')
	p.add_argument('--out-dir', help='Output directory (default: transitions folder)')
	p.add_argument('--width', type=int, default=W, help='Output width (default from config or 1920)')
	p.add_argument('--height', type=int, default=H, help='Output height (default from config or 1080)')
	p.add_argument('--fps', type=int, default=FPS, help='Output framerate (default from config or 60)')
	p.add_argument('--prefix', default='transition_', help='Output filename prefix (default transition_)')
	p.add_argument('--seed', type=int, help='Random seed for reproducible selection')
	p.add_argument('--start-index', type=int, help='Manual starting index instead of auto-continue')
	p.add_argument('--overwrite', action='store_true', help='Overwrite existing files if present')
	return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
	args = parse_args(argv)
	try:
		out_dir = _resolve_out_dir(args.out_dir)
		generate_clips(
			input_path=os.path.abspath(args.input),
			out_dir=out_dir,
			count=int(args.count),
			min_dur=int(args.min_dur),
			max_dur=int(args.max_dur),
			width=int(args.width),
			height=int(args.height),
			fps=int(args.fps),
			prefix=str(args.prefix),
			overwrite=bool(args.overwrite),
			seed=args.seed,
			start_index=args.start_index,
		)
		return 0
	except KeyboardInterrupt:
		print('Aborted')
		return 130
	except Exception as e:
		print('ERROR: ' + str(e))
		return 1


if __name__ == '__main__':
	raise SystemExit(main())

