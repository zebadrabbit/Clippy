from __future__ import annotations

import os
from pathlib import Path


def _load_env_if_present():
    """Tiny .env loader: sets env vars from a local .env if they aren't set."""
    try:
        env_path = os.path.join(os.getcwd(), ".env")
        if not os.path.exists(env_path):
            return
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        # best-effort; ignore file-read errors
        pass


def save_env(values: dict[str, str]) -> None:
    """Write or update a .env file with the given key=value pairs.

    Preserves existing comments, ordering, and keys not in *values*.
    """
    env_path = Path(".env")

    existing_lines: list[str] = []
    if env_path.is_file():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    written_keys: set[str] = set()
    new_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                new_lines.append(f"{key}={values[key]}")
                written_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in values.items():
        if key not in written_keys:
            new_lines.append(f"{key}={val}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
