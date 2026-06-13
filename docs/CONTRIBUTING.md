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
- Try a small run:
  - `python main.py --broadcaster <name> --clips 4 --compilations 1 -y`
- Style: keep patches focused and avoid reformatting unrelated files. The commit
  hook runs `black` then `ruff --fix` on staged Python files; bypass once with
  `git commit --no-verify` if needed.

## Pull Requests
- Describe the motivation and changes clearly.
- Add tests when changing behavior (where feasible).
- Ensure builds pass (see GitHub Actions workflow).

## Security / Secrets
- Do not commit secrets. Use `.env` locally.
- Respect Twitch’s terms and rate limits.

## License
- By contributing, you agree your contributions will be licensed under the repository’s license.
