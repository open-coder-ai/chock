"""Resource-path helpers for wheel and PyInstaller (frozen) builds."""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path


def package_data_dir(package: str, *subdirs: str) -> Path:
    """Return a concrete Path to package data, whether installed or frozen.

    In a PyInstaller one-file build, bundled data is extracted to sys._MEIPASS.
    In a normal wheel/editable install, data lives alongside the package source.
    """
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS) / package.replace(".", "/")
    else:
        root = Path(str(files(package)))
    if subdirs:
        root = root.joinpath(*subdirs)
    return root
