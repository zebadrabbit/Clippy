"""Backward-compatible shim. The setup wizard now lives in :mod:`clippy.wizard`.

Prefer ``clippy setup``. This keeps ``python scripts/setup_wizard.py`` working.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from clippy.wizard import main  # noqa: E402

if __name__ == "__main__":
    main()
