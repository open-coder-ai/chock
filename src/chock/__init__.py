"""Chock: agent-neutral policy-engineering framework."""

import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    __version__ = version("chock")
except PackageNotFoundError:
    if getattr(sys, "frozen", False):
        pyproject = Path(sys._MEIPASS) / "pyproject.toml"
        if pyproject.exists():
            match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
            __version__ = match.group(1) if match else "0.0.1"
        else:
            __version__ = "0.0.1"
    else:
        __version__ = "0.0.1"
