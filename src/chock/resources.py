"""Resource-path helpers for wheel and PyInstaller (frozen) builds."""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path


def package_data_dir(package: str, *subdirs: str) -> Path:
    """Return a concrete Path to package data, whether installed or frozen."""
    if getattr(sys, "frozen", False):
        root = Path(sys._MEIPASS) / package.replace(".", "/")
    else:
        root = Path(str(files(package)))
    if subdirs:
        root = root.joinpath(*subdirs)
    return root


def template_text(rel: str) -> str:
    """Raw bytes of a packaged emitted-artifact template, tokens unrendered."""
    return (package_data_dir("chock", "data", "templates") / rel).read_text(encoding="utf-8")


def render_template(rel: str, tokens: dict[str, str]) -> str:
    """Render a packaged template by literal __TOKEN__ replacement, never .format()."""
    text = template_text(rel)
    for token, value in tokens.items():
        text = text.replace(token, value)
    return text


def render_template_line(rel: str, tokens: dict[str, str]) -> str:
    """Render a one-line command template, without the file's trailing newline."""
    return render_template(rel, tokens).removesuffix("\n")
