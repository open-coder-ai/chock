"""Managed emit: a vendor's admin-deployed hook file and the bundle it runs, written only under `--out`."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from agentseam import matrix_terms

from chock import evidence
from chock.compile.levels import Grade, capped, in_agent_level, render_grade
from chock.compile.surface_kinds import Surface
from chock.emit import write_generated
from chock.hooks.launch import QUOTED_UNSAFE
from chock.resources import package_data_dir

CHANNELS: dict[str, Any] = json.loads(
    package_data_dir("chock", "data").joinpath("managed_channels.json").read_text(encoding="utf-8")
)
PLATFORMS = tuple(CHANNELS["system_roots"])
VENDORS = tuple(CHANNELS["vendors"])
#: Every managed label rests on the vendor's own docs until a `managed` witness row says otherwise.
BASIS = matrix_terms.BASIS_DOCS
WINDOWS = "windows"
_WINDOWS_ROOT = re.compile(r"[A-Za-z]:/[^/].*")
#: Windows system folders that may sit on another drive than C:.
_WINDOWS_ENV_ROOTS = ("ProgramFiles", "ProgramFiles(x86)", "ProgramData", "SystemRoot")

Files = dict[PurePosixPath, str]


class EmitRefusedError(ValueError):
    """The command would write somewhere it must not, or has nothing true to write."""


def facts(vendor: str) -> dict[str, Any]:
    """`vendor`'s managed-channel facts, as read from its docs on the recorded date."""
    return CHANNELS["vendors"][vendor]


def host_platform() -> str:
    """This machine's platform, in the data file's words."""
    if sys.platform == "win32":
        return WINDOWS
    return "macos" if sys.platform == "darwin" else "linux"


def _system_roots(platform: str) -> list[str]:
    roots = list(CHANNELS["system_roots"][platform])
    if platform == WINDOWS:
        roots += [os.environ[name].replace("\\", "/") for name in _WINDOWS_ENV_ROOTS if os.environ.get(name)]
    return roots


def system_root_of(path: Path, platform: str | None = None) -> str | None:
    """The system path `path` resolves inside (symlinks followed), else None."""
    platform = platform or host_platform()
    fold = str.casefold if platform == WINDOWS else str
    text = fold(Path(path).resolve().as_posix())
    for root in _system_roots(platform):
        base = fold(root.rstrip("/"))
        if text == base or text.startswith(f"{base}/"):
            return root
    return None


def vendor_out(out: Path, vendor: str) -> Path:
    """`<out>/<vendor>`, refused when `out` resolves into a system path or the folder already exists."""
    root = system_root_of(out)
    if root is not None:
        msg = (
            f"--out {out} resolves inside the system path {root}; chock emit writes only to a folder you "
            "deploy from, never to where a client reads it"
        )
        raise EmitRefusedError(msg)
    dest = Path(out).resolve() / vendor
    if os.path.lexists(dest):
        msg = f"{dest} already exists; give a new --out or remove that folder first"
        raise EmitRefusedError(msg)
    return dest


def deploy_root(text: str, platform: str) -> str:
    """The absolute folder the admin will copy the bundle to, in forward-slash form; a shell-read character is refused."""
    root = (text.replace("\\", "/") if platform == WINDOWS else text).rstrip("/")
    absolute = _WINDOWS_ROOT.fullmatch(root) if platform == WINDOWS else len(root) > 1 and root.startswith("/")
    if not absolute or QUOTED_UNSAFE.search(root):
        msg = (
            f"--deploy-root {text!r} must be an absolute {platform} folder holding no quote, $, backquote, "
            "backslash or line break: the hook commands name it inside double quotes"
        )
        raise EmitRefusedError(msg)
    return root


def write_tree(dest: Path, files: Files) -> list[Path]:
    """Write `files` under the new folder `dest`, refusing any path that would leave it."""
    dest.mkdir(parents=True)
    top = dest.resolve()
    written = []
    for rel, text in sorted(files.items()):
        path = dest.joinpath(*rel.parts)
        if rel.is_absolute() or ".." in rel.parts:
            msg = f"{rel} is not a path inside {dest}"
            raise EmitRefusedError(msg)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or not path.parent.resolve().is_relative_to(top):
            msg = f"{path} would be written outside {dest}"
            raise EmitRefusedError(msg)
        write_generated(path, text)
        written.append(path)
    return written


def label(policy_id: str, vendor: str, agent: str, halves: list[str]) -> dict[str, Any]:
    """One (policy, vendor) cell: the in-agent word capped by vendor-docs evidence, with chock's own witness."""
    level = capped(in_agent_level(agent), [BASIS])
    grade = Grade(level, BASIS, witnessed=evidence.witness(vendor, evidence.MANAGED) is not None)
    return {
        "policy": policy_id,
        "vendor": vendor,
        "surface": Surface.MANAGED_SETTING.value,
        "halves": halves,
        "level": grade.level,
        "basis": grade.basis,
        "witnessed": grade.witnessed,
        "label": render_grade(grade),
    }


def as_json(data: Any) -> str:
    return json.dumps(data, indent=2) + "\n"
