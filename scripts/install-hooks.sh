#!/usr/bin/env bash
# Enable Clippy's native git hooks (lint + format on commit).
# Run from the repo root:  ./scripts/install-hooks.sh
set -euo pipefail
git config core.hooksPath .githooks
echo "Enabled git hooks from .githooks (core.hooksPath)."
echo "Commits will now run ruff + black on staged Python files."
echo "Bypass a single commit with: git commit --no-verify"
