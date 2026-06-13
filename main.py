"""Backward-compatible entry point.

The orchestration now lives in :mod:`clippy.run` so it can ship inside the
installed package and back the ``clippy`` console command. This shim keeps
``python main.py ...`` working exactly as before.
"""

from __future__ import annotations

from clippy.run import console_main, main  # noqa: F401  (re-exported for compatibility)

if __name__ == "__main__":
    console_main()
