# Contributing

Thanks for considering a contribution!

## Getting Started
- Fork the repo and create a feature branch.
- Use Python 3.12+.
- Create a venv and install deps:
  - `python -m venv .venv && .venv\\Scripts\\Activate.ps1`
  - `pip install -r requirements.txt`

## Development
- Run the health check: `python health_check.py`
- Try a small run:
  - `python main.py --broadcaster <name> --clips 4 --compilations 1 -y`
- Style: keep patches focused and avoid reformatting unrelated files.

## Pull Requests
- Describe the motivation and changes clearly.
- Add tests when changing behavior (where feasible).
- Ensure builds pass (see GitHub Actions workflow).

## Security / Secrets
- Do not commit secrets. Use `.env` locally.
- Respect Twitch’s terms and rate limits.

## License
- By contributing, you agree your contributions will be licensed under the repository’s license.
