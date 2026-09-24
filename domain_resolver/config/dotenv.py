"""Minimal, dependency-free ``.env`` loader.

Reads ``KEY=VALUE`` lines from a ``.env`` file and puts them into the process
environment so secrets/config (DB URL, LLM provider/model/API key) can live in
one gitignored file instead of being re-exported every session. A real
environment variable always wins over the file (``setdefault`` semantics).
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> None:
    """Load ``path`` into ``os.environ`` if present; never overrides real env vars."""
    file_path = Path(path)
    if not file_path.is_file():
        return
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
