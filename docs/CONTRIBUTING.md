# Contributing

Thanks for considering a contribution!

## Getting Started
- Fork the repo and create a feature branch.
- Use Python 3.10+ (CI runs 3.10–3.12).
- Create a venv and install deps:
  - `python -m venv .venv && .venv\\Scripts\\Activate.ps1`
  - `pip install -e ".[dev,tui]"`
- Enable the git hooks (lint + format on commit):
  - PowerShell: `./scripts/install-hooks.ps1`
  - bash: `./scripts/install-hooks.sh`
  - or directly: `git config core.hooksPath .githooks`

## Development
- Run the health check: `python scripts/health_check.py`
- Run the tests: `pytest -q`
- Lint / format manually: `ruff check .` and `black .`
- Exercise the real ffmpeg pipeline without touching Twitch:
  `python scripts/smoke_local.py --overlay -y`
  (this is what CI runs; it builds an actual compilation from `transitions/static.mp4`)
- Try a small run:
  - `clippy --broadcaster <name> --clips 4 --compilations 1 -y`
  - Check your setup anytime with `clippy doctor`
- Style: keep patches focused and avoid reformatting unrelated files. The commit
  hook runs `black` then `ruff --fix` on staged Python files; bypass once with
  `git commit --no-verify` if needed.

## What CI checks
Every push and PR runs two jobs, both of which must pass:
- **Lint & test** on Python 3.10, 3.11 and 3.12 — `ruff check .`, `black --check .`, `pytest -q`.
- **End-to-end pipeline smoke test** — installs ffmpeg on a GPU-less runner and builds a
  real compilation, asserting the processed clip actually lands in the output. Because the
  runner has no NVENC, this also covers the libx264 fallback path.

## Pull Requests
- Describe the motivation and changes clearly.
- Add tests when changing behavior (where feasible).
- Ensure CI passes.

## Releasing
- Bump `__version__` in `clippy/__init__.py` (the single source — `pyproject.toml` reads it).
- Move the changelog's `Unreleased` heading to the new version.
- Tag and push: `git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z`.
- The release workflow verifies the tag matches `clippy.__version__`, then builds and
  attaches the wheel and sdist to the GitHub Release.

## Security / Secrets
- Do not commit secrets. Use `.env` locally.
- Respect Twitch’s terms and rate limits.

## License
- By contributing, you agree your contributions will be licensed under the repository’s license.
