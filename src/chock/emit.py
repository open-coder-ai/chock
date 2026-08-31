"""Deterministic writes for generated artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_generated(path: Path, text: str) -> None:
    """Write text with LF line endings on every platform."""
    path.write_text(text, encoding="utf-8", newline="\n")


def write_generated_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Serialise and write JSON with LF line endings on every platform."""
    write_generated(path, json.dumps(data, indent=indent))
