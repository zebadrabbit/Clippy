# Changelog

All notable changes to this project are documented here. Dates are in YYYY-MM-DD and entries are grouped by date (newest first). This changelog blends commit history with implementation notes from development sessions to provide full context.

## 2025-09-14 — v0.3.2

- UX — Setup wizard default broadcaster visibility
  - Step 2 now always displays the current default broadcaster, showing "(none)" when unset.
  - Prefers the flattened `default_broadcaster` key from the merged config, with a fallback to `identity.broadcaster`.
  - Adds a hint to leave the prompt blank to keep the current value.
  - Files: `scripts/setup_wizard.py`

## 2025-09-14 — v0.3.0

- Cleanup — Remove legacy inline color tags and dead code
  - Deleted unused legacy '{@...}' tag stripping and helper functions; all styling now flows through THEME with heuristics for label/value/path lines.
  - Simplified utils logger and added clearer comments; retained symbol accenting (→, :, *).
  - Fixed an unreachable branch in transition appending and tightened ffprobe usage.
  - Files: `utils.py`, `pipeline.py`, `main.py`

- Fix — Accurate Ctrl-C messaging
  - Gated the "Interrupted by user (Ctrl-C)" line so it only prints when a KeyboardInterrupt actually occurs.
  - Files: `main.py`

- Docs — Minor docstring and README touch-ups (usage reflects current entrypoint)
  - Files: `main.py`, `README.md`


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

- UI — Startup banner and log symbols
  - Added a neon hacker-style ASCII banner at program start (skips when `-h/--help` or non-TTY). Can be disabled with `CLIPPY_NO_BANNER=1`.
  - Switched log prefixes to Markdown-safe symbols to avoid unintended formatting in rich renderers.
  - Files: `clippy/banner.py`, `main.py`, `utils.py`

- Progress — Per-clip ffmpeg progress
  - Parse `-progress` output to display live percentages and ETA-like time for Normalizing/Overlay steps in Stage 1.
  - Added an internal `ffprobe` duration probe helper for accurate progress computation.
  - Files: `pipeline.py`

- Progress — Stage 2 concatenate progress
  - Added a live progress indicator for the final concatenation step using `-progress` `out_time` and total duration from the concat list.
  - Renders a single updating line with percent and time elapsed/total for each compilation.
  - Files: `pipeline.py`

- Fix — Stage 2 compile loop + finalize clarity
  - Ensure the concatenate (Stage 2) runs once per compilation index (bug caused only the last or a single output to be produced).
  - Finalize step now lists exactly which files were moved and warns for any missing compiled indices.
  - Files: `pipeline.py`, `clippy/naming.py`

- Packaging — Internal data and ffprobe
  - New internal data support: `_internal/` folder packaged and discoverable at runtime; resolver honors `CLIPPY_USE_INTERNAL=1` to prefer bundled assets.
  - `transitions/static.mp4` is REQUIRED; build now stages it into `_internal/transitions/static.mp4` (and includes `transitions/` externally) to guarantee availability in portable builds.
  - Bundled `ffprobe` alongside `ffmpeg` and `yt-dlp` in the portable output.
  - Updated PyInstaller spec and build scripts to include `_internal`, fonts, transitions, and `ffprobe`.
  - Files: `build/Clippy.spec`, `build/build.ps1`, `build/build.sh`, `_internal/README.md`, `utils.py`

- Changed — Cleaner Ctrl-C output during ffmpeg runs
  - Paired `-progress` with `-nostats` to suppress noisy frame/fps/bitrate spam on interruption.
  - Failure handling detects user interruption and logs concise messages (e.g., "Normalization interrupted by user") instead of large stderr dumps.
  - Retry loops now stop immediately if a shutdown has been requested; transition asset normalization also uses `-nostats`.
  - Files: `pipeline.py`

- Health check & docs
  - Health check now hints using `CLIPPY_USE_INTERNAL=1` if `transitions/static.mp4` is missing.
  - README: grouped “Internal data and ENV” section covering `CLIPPY_USE_INTERNAL`, `TRANSITIONS_DIR`, and static.mp4 requirement.
  - Files: `scripts/health_check.py`, `README.md`

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
  - Make frozen HealthCheck import clippy.config correctly by bundling it and resolving paths; update Windows/Linux builds.
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

