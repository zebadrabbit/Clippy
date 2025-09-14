# Changelog

All notable changes to this project are documented here. Dates are in YYYY-MM-DD and entries are grouped by date (newest first). This changelog blends commit history with implementation notes from development sessions to provide full context.

## 2025-09-14

- Added — Graceful interruption and shutdown
  - Ctrl-C now cooperatively stops work: signals threads, terminates any running ffmpeg/yt-dlp processes, and performs cleanup.
  - Introduced a cancellable process runner used for long ffmpeg and probe operations.
  - A global shutdown event is checked at safe points within workers and normalization steps.
  - Commit: 3c3257b
- Changed — CLI help organization
  - Grouped `--help` output into logical sections (Required, Window & selection, Output & formatting, Transitions & sequencing, Performance & robustness, Cache management, Encoder tuning, Misc).
  - Widened the help formatter for better alignment and readability.
  - Commit: b6ae13e
- Docs
  - Updated README to document transitions/audio policy, output auto-suffix vs `--overwrite-output`, cache flags, and Ctrl-C behavior.

## 2025-09-13

- CI/Build
  - Auto-fetch `ffmpeg.exe` if missing; ensure `dist/Clippy` exists before copying `HealthCheck.exe`.
  - Commit: 9ffdbd3
- Features — Transitions directory and fail-fast policy
  - Dynamic transitions directory resolution with clear precedence (env, config, bundle, repo, CWD).
  - Enforce presence of `transitions/static.mp4`; fail fast with helpful guidance if missing; add `--transitions-dir` override.
  - Package transitions in portable builds; remove placeholder/copy behavior.
  - Commits: 093e01a, 64e64d1, 3e739f7, b80ee15
- Fixes
  - Correct transition path checks; display final intended filenames during compilation; finalize outputs with proper container extension.
  - Make frozen HealthCheck import config correctly by bundling it and resolving paths; update Windows/Linux builds.
  - Commits: 02f7374, 29d4b8e
- Docs/Tooling
  - Add READMEs for build and scripts; add Linux `build.sh` for portable build.
  - Commits: 578630b
- Repo hygiene
  - Ignore PyInstaller artifacts and zips; untrack build outputs; adjust .gitignore for bin/assets layout.
  - Commits: c8de437, b4c4579, b699658, 65f8b63
- Initial scaffolding
  - Initial project scaffolding and setup.
  - Commit: 5aa350c

### Also delivered across the 2025-09-13 release cycle (implementation notes)

The following changes were implemented and verified during development and reflected in the current codebase. They may span the commits listed above:

- Audio/codec consistency and normalization
  - All segments (clips and non-clip assets) encode with H.264 yuv420p + AAC, enforcing `-ar 48000 -ac 2` for stable concatenation.
  - Transitions/intro/outro/static are normalized into `cache/_trans` on first use; a `_manifest.json` records if audio was kept/silenced and whether loudness normalization applied.
  - Loudness normalization (EBU R128 loudnorm, I=-16, TP=-1.5, LRA=11) is applied to non-clip assets by default; automatic fallback to synthesized clean stereo audio if an asset has no audio or normalization fails.
  - Default policy changed to keep audio ON for transitions/static/intro/outro unless explicitly configured to silence.

- Sequencing and transitions selection
  - Sequencing policy: random(optional intro) → static → clip → static → random_chance(transition → static) … → random(optional outro).
  - Weighted random transition selection with simple cooldown to avoid immediate repeats.

- Output naming and finalization
  - Final names are computed and shown prior to Stage 2; collisions are handled by auto-suffixing `_1`, `_2`, … unless `--overwrite-output` is specified.
  - Finalization uses the correct container extension and moves files from `cache/` to `output/`.

- Cache lifecycle
  - Default cleanup preserves `cache/_trans` to avoid re-encoding non-clip assets; `--keep-cache` retains all, while `--purge-cache` removes everything including preserved folders.

- Tooling and validation scripts
  - `scripts/test_transitions.py` probes/normalizes transitions and runs an audio-only concat check to detect cross-file audio issues.
  - `scripts/health_check.py` validates environment, transitions directory, and required binaries.
  - `scripts/check_sequencing.py` confirms concat sequencing against policy.

- Progress and logging
  - Colorized, readable progress board for Stage 1 with Windows VT enablement; timestamps are timezone-aware (UTC) for consistent logging.

## Notes

- Breaking change: `transitions/static.mp4` is now required. Place your asset in `transitions/` or provide `--transitions-dir`.
- Portable builds package required assets and binaries; see README for details.

