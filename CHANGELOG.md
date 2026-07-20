# Changelog

## 2026-07-20 — Unreleased (cleanup + hardening)

- Fix — `--preset` and `--list-presets` now do something
  - Both flags were declared and documented (with worked examples in the README) but
    nothing read them: `--preset` was silently ignored and `--list-presets` built a
    compilation instead of listing. A preset now replaces the encoding baseline, with
    individual flags still winning on top, so `--preset discord_friendly --bitrate 20M`
    keeps the preset's 720p/30 and takes your bitrate.

- Fix — Automatic libx264 fallback when NVENC is missing
  - `h264_nvenc` was hardcoded as the default codec, so a machine without an NVIDIA GPU
    failed every encode. `detect_encoder()` had existed since the ffmpeg module landed
    but was never called, while the README claimed auto-detection was already happening.
    Clippy now probes ffmpeg when no codec was chosen explicitly, and `clippy doctor`
    warns when it falls back. NVENC preset names (`p1`-`p7`) are normalized for x264.

- Fix — `--start` / `--end` accept RFC3339 timestamps
  - `clippy --start 2025-07-01T00:00:00Z`, the example in the tool's own quick-start,
    died with "Invalid date format". The rejected format is the one Helix uses. Bare
    dates behave exactly as before; an explicit time of day is now honoured.

- Fix — The end-to-end smoke test runs again
  - `scripts/smoke_local.py` had been broken since the ClipRow migration and, once
    fixed, was compiling the transition assets *without* the clip. Both bugs are fixed
    and CI now runs the real ffmpeg pipeline on every push, on a runner with no NVENC,
    asserting the processed clip is actually in the compilation.

- Housekeeping
  - Removed ~500 lines of dead code: a stale parallel set of ffmpeg command builders
    (still on pre-resolution-aware 1080p geometry), four unused ffmpeg templates in
    `config.py`, `pipeline.run_proc`, `create_thumbnail`, two superseded `runtime`
    helpers, the whole `clippy/ytdlp.py` module, and a duplicated copy of the font.
  - Tests for the previously uncovered core: the Helix window resolver, clip selection
    with auto-expand and nostalgia, and output naming. Each verified by mutation.
  - CI lint steps could never have passed — `ruff` and `black` were not in the `dev`
    extra. The `build-portable` workflow referenced a `build/` directory that has never
    existed in this repo; replaced with a release workflow that builds and attaches a
    wheel and sdist on a `v*` tag.
  - Packaging metadata (readme, URLs, classifiers, keywords) filled in, and the version
    is single-sourced from `clippy.__version__`.

## 2026-06-13 — Unreleased (v2 refinement)

- Packaging — Bundle assets so an installed `clippy` works outside the repo
  - The overlay font (`Roboto-Medium.ttf`) and the TUI stylesheet (`app.tcss`) now ship
    as package data; `config.py` resolves the font from the installed package location
    (falling back to the repo for source checkouts). Verified the built wheel contains
    `clippy/assets/fonts/Roboto-Medium.ttf` and `clippy/tui/app.tcss`.
  - Transitions remain user-supplied (preflight guides you to add `static.mp4`).

- Feature — `clippy doctor`
  - Runs the preflight checks on demand and reports your setup status, so you can
    diagnose problems without starting a full run. Exits non-zero if anything is wrong.

- Fix — Resolution-aware creator overlay (Track 2)
  - The credit banner, "clip by" / author text, and avatar were hand-tuned with 1080p
    pixel coordinates, so they were mis-placed/oversized at other resolutions (e.g. the
    720p `discord_friendly` preset). All coordinates, font sizes, and the avatar now
    scale by `height / 1080`. Validated against ffmpeg at 720p and 1080p.
  - Tests: add overlay-scaling cases to `tests/test_pipeline.py`.

- Feature — Friendly preflight checks (Track 2)
  - New `clippy/preflight.py` collects common setup problems and reports them all at
    once in plain English with a concrete fix for each, instead of failing on the first
    or surfacing a traceback mid-run: missing ffmpeg/ffprobe, missing Twitch creds (or
    Discord token in Discord mode), missing transitions folder / `static.mp4`, missing
    overlay font (warning), and an unwritable output folder.
  - Wired into both the CLI (`clippy`, before auth) and the TUI (before the pipeline).
    Replaces the piecemeal `ensure_twitch_credentials_if_needed` /
    `ensure_transitions_static_present` first-failure checks in the run path.
  - Tests: add `tests/test_preflight.py`.

- Feature — `clippy` console command + packaged entry point
  - `pip install -e .` now provides a `clippy` command with three entry points:
    `clippy setup` (guided first-run wizard), `clippy tui` (interactive TUI), and
    `clippy [options]` (the CLI). A first-run hint suggests `clippy setup` when no
    `clippy.yaml` exists and the terminal is interactive.
  - The orchestration moved from root `main.py` into the package as `clippy/run.py`
    (so it ships in the installed package); `main.py` is now a thin shim, so
    `python main.py ...` keeps working unchanged.
  - The setup wizard moved into the package as `clippy/wizard.py`
    (`scripts/setup_wizard.py` is a shim). Added `[build-system]`, `[project.scripts]`,
    and explicit `[tool.setuptools] packages` to pyproject.
  - Tests: add `tests/test_console.py` (subcommand dispatch). README/CONTRIBUTING
    updated to the `clippy` workflow. 101 passing.

- Tooling — Reliable lint/format gate + CI
  - Replaced the hanging pre-commit setup with a native git hook (`.githooks/pre-commit`)
    that runs black then ruff on staged Python files using the project's own tools — no
    framework/env-build step to stall on. Enable with `git config core.hooksPath .githooks`
    or `scripts/install-hooks.{sh,ps1}`. (The `pre-commit` framework's `run` step stalled
    during store init on Windows, leaving commits hung with a stale index.lock.)
  - `.pre-commit-config.yaml` switched to local/system hooks for anyone who still uses the
    framework.
  - Added `.github/workflows/ci.yml`: ruff + black --check + pytest on Python 3.10/3.11/3.12
    for pushes and PRs. This is the gate that would have caught this session's bugs/lint debris.

- Refactor — Config single source of truth (Stage 4b: TUI writer)
  - The TUI progress screen now builds a `ClippyConfig` and calls `set_config()`
    (like the CLI) instead of poking module globals and folding them back via
    `refresh_from_globals()`. Both entry paths now write the typed config the same way.
  - `_sync_encoder_params` and the transition/audio/selection settings sync are
    expressed as `dataclasses.replace` updates; the unused `clippy.pipeline` alias and
    the dead `getattr(_cfg_mod, "cache", ...)` read were removed.
  - Tests: add `tests/test_tui_config.py` (skipped without `textual`). 96 passing.

- Refactor — Config single source of truth (Stage 4a: remaining readers)
  - Migrated the remaining function-local `from clippy.config import X` reads to
    `get_config()` in `pipeline.py` (audio-normalize flags, transition assets/weights/
    cooldown/probability, intro/outro/static, skip-bad-clip, max-concurrency, fontfile),
    `naming.py` (cache/output/container_ext), `cli.py` (selection defaults), and
    `utils.py` (yt-dlp format). Only genuinely unmodelled values (binary paths,
    `video_codec`, `transitions_dir`) still read module attributes.

- Fix — Default broadcaster from `clippy.yaml` (`identity.broadcaster`) never worked:
  `main()` read `globals().get("default_broadcaster")` from its own module, where the
  name never existed, so it was always empty. Now reads `get_config().identity.broadcaster`.
- Fix — Several CLI encoder flags (`--cq`, `--gop`, `--nvenc-preset`, `--rc-lookahead`,
  `--spatial-aq`, `--temporal-aq`, `--aq-strength`) were effectively no-ops: they only
  set `main`'s module globals, which the config reconciliation never read. They now
  flow into the typed config and reach the encoder.
- Refactor — Config single source of truth (Stage 3: `apply_cli_overrides` is the single writer)
  - `apply_cli_overrides` now builds a `ClippyConfig` from defaults + CLI args and calls
    `set_config()` once, instead of hand-poking module globals on `main`, `clippy.config`,
    `clippy.pipeline`, and `clippy.utils`. All four-way global juggling is gone.
  - `main`'s readers (`display_confirmation`, `filter_and_expand`, `run_pipeline`, the
    startup summary) read from `get_config()` instead of module globals.
  - Removed all now-dead module-level config imports and module aliases from `main.py`.
  - Tests: add `tests/test_main_overrides.py` (CLI→typed-config mapping); whole repo now
    passes `ruff` (95 passing).
- Fix — `stage_two` crashed on every run with `NameError: enc` when building the
  final concat command; the encoder params are now resolved locally. (Surfaced
  because the pre-commit lint hooks were not running.)
- Refactor — Config single source of truth (Stage 2: pipeline reads)
  - `pipeline.py` no longer relies on stale import-time global bindings: `rebuild`,
    `enable_overlay`, the selection counts, and `_current_encoder_params` now read
    from the typed `ClippyConfig`. This closes a latent TUI bug where disabling the
    overlay (or other settings) silently had no effect.
  - The TUI's `_run_pipeline` now calls `config.refresh_from_globals()` after writing
    its selections, so the typed config (the source of truth after Stage 1) reflects
    them — without this, Stage 1 would have read TUI encoder choices stale.
  - Removed dead imports (`ffmpegApplyOverlay`, `ffmpegBuildSegments`,
    `ffmpegNormalizeVideos`) that the inline command builders had superseded.
  - Tests: add `tests/test_pipeline.py` covering stage_two command assembly (91 passing).
- Refactor — Config single source of truth (Stage 1)
  - The typed `ClippyConfig` singleton is now authoritative. `utils._cfg_get` (and
    therefore the ffmpeg templating hot path) reads from the typed config, falling
    back to module globals only for values it does not model (binary paths, etc.).
  - New `config.refresh_from_globals()` folds the legacy-global overrides applied by
    the CLI (`apply_cli_overrides`) back into the typed config, so CLI and TUI paths
    can no longer diverge.
  - The singleton is initialised from the fully-resolved globals at import (e.g.
    absolute fontfile path), so `get_config()` is correct from the first read.
  - Tests: add `tests/test_config_singleton.py`; update transition-pool test to drive
    through the typed config (89 passing).

## 2026-05-30 — Unreleased

- Fix — TUI encoder settings now reach the pipeline
  - Quality screen selections are synced into the live config before processing starts.
  - Clip normalization, overlay processing, transition transcoding, and concat output now use the selected codec and encode settings.

- Fix — Workflow inputs are clamped at entry
  - Clip counts and compilation counts are forced to positive values.
  - CQ is clamped to the valid 0-51 range.
  - Transition probability is clamped to 0.0-1.0 and cooldown to 0 or higher.

- UX — Review screen now shows both audio-normalization toggles.

## 2026-04-03 — v0.5.0

TUI enhancements, duration-based compilations, nostalgia mode, and UX polish.

- Feature — Duration-based compilations
  - New `--target-duration` CLI flag: specify target compilation length in minutes instead of clip count.
  - TUI clip settings screen offers "By count" vs "By duration" sizing mode.
  - `ClipRow` now captures `title` and `duration` from Helix for accurate duration math.
  - `create_compilations_from()` supports `target_duration_secs` parameter.

- Feature — Nostalgia mode
  - `--nostalgia` CLI flag mixes in random older clips (>6 months) for variety.
  - Replaces ~20% of clips with nostalgia picks inserted at random positions.

- Feature — Auto-expand improvements
  - Auto-expand now defaults on in TUI; fills clips from outside date range (newest to oldest).
  - `--no-auto-expand` flag to explicitly disable.
  - Blank date ranges display as "All time" instead of empty arrow.

- Feature — Save credentials to `.env`
  - TUI credentials screen has "Save to .env" button.
  - CLI `--save-env` flag writes/updates `.env` with Twitch/Discord credentials.
  - Pre-fills credentials from existing `.env` on next launch.

- Feature — Summary screen
  - New post-pipeline summary with copyable output file paths.
  - Shows compilation lengths, clip counts, and contributor credits (for YouTube descriptions).

- Feature — Transition file picker (TUI)
  - Transitions screen shows absolute directory path and scan button.
  - Configurable probability, cooldown, audio normalization, and overlay toggle.
  - All options have descriptive help text.

- UX — TUI polish
  - All screens now have a Back button for navigation.
  - All form fields have muted help text explaining their purpose.
  - Discord channel ID pre-fills from `.env`.
  - Fixed `--preset` / `--nvenc-preset` CLI conflict (renamed NVENC preset flag).
  - Fixed duplicate log messages in TUI progress screen.
  - Fixed docstring escape sequence warning (`\m` → raw string).

- CLI — New flags
  - `--tui`: launch the interactive TUI.
  - `--target-duration`: compilation length in minutes.
  - `--nostalgia`: enable nostalgia mode.
  - `--no-auto-expand`: disable auto-expand.
  - `--save-env`: save credentials to `.env`.
  - `--nvenc-preset`: renamed from `--preset` to avoid conflict with encoding presets.

- Docs — README rewrite
  - Reorganized around TUI-first workflow with CLI reference table.
  - Added encoding presets table, duration-based examples, Discord setup section.
  - Removed outdated setup wizard references; streamlined troubleshooting.

## 2026-04-02 — v0.4.0

Major architecture overhaul: robustness, Textual TUI, and ffmpeg preset system.

- Architecture — Typed config dataclasses (`clippy/models.py`)
  - Replaced 40+ mutable module-level globals with `ClippyConfig` and nested typed dataclasses.
  - `ClipRow` is now a dataclass with named fields; backwards-compatible `__getitem__` for migration.
  - `get_config()` / `set_config()` singleton with `to_flat_dict()` bridge for legacy `replace_vars()`.

- Architecture — Stdlib logging (`clippy/log.py`)
  - Replaced custom 80-line `utils.log()` with Python `logging` module.
  - `ClippyFormatter` preserves BBS-style theme coloring with Unicode symbols.
  - Forces UTF-8 stdout on Windows to prevent cp1252 encoding errors.

- Architecture — ffmpeg command builder (`clippy/ffmpeg.py`)
  - `EncoderParams` dataclass eliminates 9 duplicate NVENC encoding strings.
  - Structured flag builders: `video_flags()`, `audio_flags()`, `sizing_flags()`.
  - Command builders for all pipeline operations: normalize, overlay, concat, transcode, thumbnail.
  - `detect_encoder()` auto-probes for NVENC and falls back to libx264.

- Architecture — Removed wildcard imports
  - Replaced `from clippy.config import *` with explicit imports in main.py, pipeline.py, utils.py.
  - Migrated all `clip[N]` positional access to named `clip.id`, `clip.author`, etc.

- Architecture — Monolith breakup
  - `main()` (628 lines) split into 5 functions: `apply_cli_overrides()`, `display_confirmation()`, `ingest_clips()`, `filter_and_expand()`, `run_pipeline()`.
  - `write_concat_file()` (460 lines) split into 3 functions: `transcode_asset()`, `prepare_clips_concurrent()`, `build_concat_list()`.

- Robustness — Error handling (~190 locations)
  - Narrowed ~80 blanket `except Exception` to specific types (ImportError, OSError, ValueError, etc.).
  - Added `logger.debug()` to ~40 silent swallows for visibility.
  - Kept ~70 as broad catches with inline comments explaining why.

- Feature — Encoding presets (`clippy/presets.py`)
  - 5 named presets: youtube_1080p60, discord_friendly, archive_hq, quick_preview, cpu_only.
  - `--preset` CLI flag and `--list-presets` for discovery.
  - `EncoderParams.with_overrides()` for customization, `validate()` for warnings.

- Feature — yt-dlp abstraction (`clippy/ytdlp.py`)
  - `YtDlpConfig` dataclass with `to_command()` builder and 3 presets.

- Feature — Textual TUI (`clippy/tui/`)
  - 6-step guided workflow: Source > Credentials > Clip Settings > Quality > Transitions > Review.
  - Live ffmpeg command preview in the Quality screen with preset selector and parameter builder.
  - Progress dashboard with per-clip status, overall progress bar, and log panel.
  - BBS-inspired dark theme stylesheet.

- Testing — pytest infrastructure
  - 63 tests across 6 test modules covering models, config loader, ffmpeg builder, presets, yt-dlp.
  - pytest configured via pyproject.toml with coverage support.

- Cleanup
  - Removed camelCase aliases from pipeline.py.
  - Fixed `datetime.utcnow()` deprecations (use `datetime.now(timezone.utc)`).
  - Updated pyproject.toml: Python >=3.10, optional deps for discord/tui/dev.
  - Version bumped to 0.4.0.

## 2025-10-12 — v0.3.6

- Wizard — Configure intros/outros

  - The setup wizard now prompts for `assets.intro` and `assets.outro` filenames (relative to your transitions directory).
  - Press Enter to keep existing values; enter `-` or `none` to clear the list. Values are merged into `clippy.yaml`.
  - Files: `scripts/setup_wizard.py`, `clippy/config_loader.py` (already supports `assets.intro/outro`).

- Docs — README updates

  - Document how to configure intros/outros via the wizard, YAML, and per-run CLI overrides.
  - Clarify transitions folder usage and overrides.
  - Files: `README.md`.

- Tooling — Pre-commit baseline green
  - Black + Ruff hooks added and passing; minor lint fixes (unused/ambiguous vars) in `main.py` and `clippy/pipeline.py`.
  - Files: `.pre-commit-config.yaml`, `pyproject.toml`, `main.py`, `clippy/pipeline.py`.

All notable changes to this project are documented here. Dates are in YYYY-MM-DD and entries are grouped by date (newest first).

## 2025-09-14 — v0.3.5

- Feature — Discord mode UX and summaries

  - Show friendly Discord channel name (e.g., "Guild / #clips") when ingesting.
  - Log a concise summary for Discord runs: links found, raw clips fetched, filtered count, and compilations created.
  - Remove duplicate "Created N compilations" log (now logged once from the pipeline).
  - Normalize manifest path display to forward slashes on Windows.
  - Files: `clippy/discord_ingest.py`, `main.py`.

- Wizard — Safer prompts and preservation

  - Source selection includes Discord; prompts mask secrets and can validate the bot token with a quick login.
  - Re-running the wizard preserves existing Discord settings unless explicitly changed.
  - Files: `scripts/setup_wizard.py`.

- Docs — Update READMEs and examples
  - Document Discord mode setup and usage, wizard flow, and transitions directory precedence.
  - Ensure references to internal assets fallback are removed; clarify `TRANSITIONS_DIR` usage and `static.mp4` requirement.
  - Files: `README.md`, `scripts/README.md`, `transitions/README.md`, `clippy.yaml.example`.

All notable changes to this project are documented here. Dates are in YYYY-MM-DD and entries are grouped by date (newest first). This changelog blends commit history with implementation notes from development sessions to provide full context.

## 2025-09-14 — v0.3.4

- Repo hygiene — Remove portable CI and clean ignores
  - Deleted `.github/workflows/build-portable.yml` (portable build disabled while we iterate Python-only).
  - Cleaned `.gitignore` to drop PyInstaller/portable build remnants. If packaging returns, we’ll reintroduce targeted ignore rules.
  - No functional changes to the app; health check and smoke/sequencing remain green.

## 2025-09-14 — v0.3.3

- Breaking/Docs — Removed portable build system; Python-only
  - Deleted portable build scripts and artifacts; documentation updated to reflect running from source only.
  - Removed `_internal` sample asset fallback and CLIPPY_USE_INTERNAL; use TRANSITIONS_DIR instead.
  - Files: removed `build/` folder, updated `README.md`, `scripts/README.md`, `_internal/README.md`.

## 2025-09-14 — v0.3.2

- UX — Setup wizard default broadcaster visibility
  - Step 2 now always displays the current default broadcaster, showing "(none)" when unset.
  - Prefers the flattened `default_broadcaster` key from the merged config, with a fallback to `identity.broadcaster`.
  - Adds a hint to leave the prompt blank to keep the current value.
  - Files: `scripts/setup_wizard.py`

## 2025-09-14 — v0.3.0

- Cleanup — Remove legacy inline color tags and dead code

  - Deleted unused legacy '{@...}' tag stripping and helper functions; all styling now flows through THEME with heuristics for label/value/path lines.
  - Simplified utils logger and added clearer comments; retained symbol accenting (→, :, \*).
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

  - Internal data fallback removed; runtime resolver now uses TRANSITIONS_DIR, repo transitions/, or CWD transitions/.
  - `transitions/static.mp4` is REQUIRED; ensure it exists under your transitions directory.
  - Bundled `ffprobe` alongside `ffmpeg` and `yt-dlp` in the portable output.
  - Updated PyInstaller spec and build scripts to include `_internal`, fonts, transitions, and `ffprobe`.
  - Files: `build/Clippy.spec`, `build/build.ps1`, `build/build.sh`, `_internal/README.md`, `utils.py`

- Changed — Cleaner Ctrl-C output during ffmpeg runs

  - Paired `-progress` with `-nostats` to suppress noisy frame/fps/bitrate spam on interruption.
  - Failure handling detects user interruption and logs concise messages (e.g., "Normalization interrupted by user") instead of large stderr dumps.
  - Retry loops now stop immediately if a shutdown has been requested; transition asset normalization also uses `-nostats`.
  - Files: `pipeline.py`

- Health check & docs
  - Health check messaging updated to focus on transitions directory and static.mp4 requirement.
  - README updated to remove `CLIPPY_USE_INTERNAL` and clarify TRANSITIONS_DIR usage.
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

- Breaking change: `transitions/static.mp4` is required. Place your asset in `transitions/` or provide `--transitions-dir`.
- Project runs from source.
