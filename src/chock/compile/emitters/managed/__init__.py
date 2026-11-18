"""Managed emit: a vendor's admin-deployed hook file and the bundle it runs, written only under `--out`."""

from __future__ import annotations

import json
import os
import posixpath
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from agentseam import matrix_terms

from chock import evidence
from chock.compile.levels import Grade, capped, in_agent_level, render_grade
from chock.compile.surface_kinds import Surface
from chock.emit import write_generated
from chock.resources import package_data_dir

CHANNELS: dict[str, Any] = json.loads(
    package_data_dir("chock", "data").joinpath("managed_channels.json").read_text(encoding="utf-8")
)
PLATFORMS = tuple(CHANNELS["system_roots"])
VENDORS = tuple(CHANNELS["vendors"])
#: Every managed label rests on the vendor's own docs until a `managed` witness row says otherwise.
BASIS = matrix_terms.BASIS_DOCS
WINDOWS = "windows"
MACOS = "macos"
_WINDOWS_ROOT = re.compile(r"[A-Za-z]:/[^/].*")
#: `//host/c$/...`, an administrative share of a drive.
_ADMIN_SHARE = re.compile(r"^//[^/]+/([a-z])\$(?=/|$)", re.I)
#: `\\?\` and `\\.\` device prefixes, and their UNC form, in forward-slash spelling.
_DEVICE_UNC = re.compile(r"^//[?.]/unc/", re.I)
_DEVICE = re.compile(r"^//[?.]/")
_DRIVE_ROOT = re.compile(r"[a-z]:/?")
_CONTROL = re.compile(r"[\r\n\0]")
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
    return MACOS if sys.platform == "darwin" else "linux"


def _system_roots(platform: str) -> list[str]:
    roots = list(CHANNELS["system_roots"][platform])
    if platform == WINDOWS:
        roots += [os.environ[name].replace("\\", "/") for name in _WINDOWS_ENV_ROOTS if os.environ.get(name)]
    return roots


def spelled(text: str, platform: str) -> str:
    """`text` in one comparable spelling: Windows device and admin-share prefixes removed, case folded where the OS ignores it."""
    if platform != WINDOWS:
        text = re.sub(r"^/+", "/", text)
        return text.casefold() if platform == MACOS else text
    text = text.replace("\\", "/")
    text = _DEVICE_UNC.sub("//", text)
    text = _DEVICE.sub("", text)
    text = _ADMIN_SHARE.sub(lambda m: f"{m.group(1)}:/", text)
    return re.sub(r"/+", "/", text).casefold()


def _inside(text: str, root: str) -> bool:
    base = root.rstrip("/")
    if not base or _DRIVE_ROOT.fullmatch(base):  # a filesystem root holds everything: refuse it alone
        return text.rstrip("/") == base
    return text == base or text.startswith(f"{base}/")


def root_named(text: str, platform: str) -> str | None:
    """The system path the absolute, resolved `text` names or sits inside, on `platform`, else None."""
    text = spelled(text, platform)
    if platform == WINDOWS and _DRIVE_ROOT.fullmatch(text):
        return text
    return next((root for root in _system_roots(platform) if _inside(text, spelled(root, platform))), None)


def system_root_of(path: Path, platform: str | None = None) -> str | None:
    """The system path `path` resolves inside (symlinks followed), else None."""
    return root_named(Path(path).resolve().as_posix(), platform or host_platform())


def vendor_out(out: Path, vendor: str) -> Path:
    """`<out>/<vendor>`, refused when `out` resolves into a system path, is not a folder, or the folder already exists."""
    root = system_root_of(out)
    if root is not None:
        msg = (
            f"--out {out} resolves to or inside the system path {root}; chock emit writes only to a folder you "
            "deploy from, never to where a client reads it"
        )
        raise EmitRefusedError(msg)
    if os.path.lexists(out) and not Path(out).is_dir():
        msg = f"--out {out} is not a folder"
        raise EmitRefusedError(msg)
    dest = Path(out).resolve() / vendor
    if os.path.lexists(dest):
        msg = f"{dest} already exists; give a new --out or remove that folder first"
        raise EmitRefusedError(msg)
    return dest


def _absolute(text: str, platform: str) -> str | None:
    """`text` as a normalised absolute `platform` path in forward slashes, else None; a line break or NUL is refused."""
    path = (text.replace("\\", "/") if platform == WINDOWS else text).rstrip("/")
    absolute = _WINDOWS_ROOT.fullmatch(path) if platform == WINDOWS else len(path) > 1 and path.startswith("/")
    if not absolute or _CONTROL.search(path):
        return None
    return posixpath.normpath(path) if platform != WINDOWS else path[:2] + posixpath.normpath(path[2:])


def deploy_root(text: str, platform: str) -> str:
    """The absolute folder the admin will copy the bundle to, normalised, in forward-slash form."""
    root = _absolute(text, platform)
    if root is None:
        msg = f"--deploy-root {text!r} must be an absolute {platform} folder with no line break"
        raise EmitRefusedError(msg)
    return root


def interpreter(text: str, platform: str) -> str:
    """The absolute Python the hooks start on `platform`; nothing on PATH or in git config is consulted."""
    path = _absolute(text, platform)
    if path is None:
        msg = (
            f"--python {text!r} must be the absolute path of the Python 3.11+ interpreter on the target {platform} "
            "machines: a managed hook must not take its interpreter from the user's PATH or git config"
        )
        raise EmitRefusedError(msg)
    return path


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
