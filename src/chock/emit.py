"""Deterministic writes for generated artifacts.

Every file Chock regenerates into a repository must be byte-identical across
platforms. `Path.write_text()` without `newline=` translates "\\n" to "\\r\\n" on Windows,
so a recompile there rewrote ~20 tracked files with CRLF. Git normalises them back to LF
on commit, so nothing wrong ever landed -- but `git status` reported 20 modified files
while `git diff` reported zero changes.

That gap is the hazard: it trains whoever sees it to run `git checkout --` reflexively
over generated output, and eventually that reflex discards a real change. It also makes
byte-identity checks on compiled gates unreliable, which is the evidence we depend on to
prove an enforcement change did not alter enforcement.

Use `write_generated()` for anything the tool regenerates. Files scaffolded once into a
new repo and then owned by the adopter are not generated artifacts and are out of scope.
"""

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
