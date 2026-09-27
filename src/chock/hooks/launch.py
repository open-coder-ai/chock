"""The portable hook command: git runs chock's committed launcher from the repository root."""

from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path, PurePath

from chock.emit import write_generated
from chock.resources import package_data_dir

#: Where the launcher lives in a consumer repo, beside the vendored runtimes it starts.
LAUNCHER_REL = ".chock/bin/launch.sh"

#: Local-only git config key naming the interpreter `chock sync` ran under on this machine.
PYTHON_CONFIG_KEY = "chock.python"

#: The oldest Python the vendored runtime runs on (chock's own `requires-python`).
MIN_PYTHON = (3, 11)

ALIAS = "chock-hook"

#: No `$`, no backslash, no single quote: bash, PowerShell and cmd.exe read it identically.
_PREFIX = f'git -c "alias.{ALIAS}=!sh {LAUNCHER_REL}" {ALIAS}'

_TEMPLATE = package_data_dir("chock", "hooks", "data").joinpath("launch.sh").read_text(encoding="utf-8")


def hook_command(runtime: str, *args: str) -> str:
    """The command an agent config carries to run `runtime` (repo-relative) with `args`."""
    words = [f'"{arg}"' if "/" in arg else arg for arg in args]
    return " ".join([_PREFIX, runtime, *words])


def launcher_text() -> str:
    """The launcher script, with this chock's minimum Python filled in."""
    return _TEMPLATE.replace("__MIN_PYTHON_TEXT__", ".".join(map(str, MIN_PYTHON))).replace(
        "__MIN_PYTHON__", ", ".join(map(str, MIN_PYTHON))
    )


def write_launcher(repo_root: Path) -> Path:
    """Write the launcher into the consumer repo (LF, so git's sh reads it on Windows too)."""
    dest = Path(repo_root) / LAUNCHER_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_generated(dest, launcher_text())
    with contextlib.suppress(OSError):
        dest.chmod(0o755)
    return dest


def record_interpreter(repo_root: Path) -> bool:
    """Name this interpreter in the clone's own .git/config; never committed. True when set."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        proc = subprocess.run(  # noqa: S603 -- fixed argv: git config with this process's own interpreter path
            ["git", "config", "--local", PYTHON_CONFIG_KEY, PurePath(sys.executable).as_posix()],  # noqa: S607 -- git on PATH is the repo route's premise
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=30,
        )
        return proc.returncode == 0
    return False
