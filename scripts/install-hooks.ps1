# Enable Clippy's native git hooks (lint + format on commit).
# Run from the repo root:  ./scripts/install-hooks.ps1
$ErrorActionPreference = "Stop"
git config core.hooksPath .githooks
Write-Host "Enabled git hooks from .githooks (core.hooksPath)." -ForegroundColor Green
Write-Host "Commits will now run ruff + black on staged Python files." -ForegroundColor Green
Write-Host "Bypass a single commit with: git commit --no-verify"
