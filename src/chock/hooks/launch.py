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

#: No launcher at git's top level (a nested repo, no repo, not synced) refuses with exit 2:
#: bash-as-sh exits 127 on a missing script, which agents treat as non-blocking.
_MISSING = f"test -f {LAUNCHER_REL} || {{ echo chock: no {LAUNCHER_REL} here, run chock sync --repo . >&2; exit 2; }}"

#: No `$`, no backslash, no single quote: bash, PowerShell and cmd.exe read it identically.
_PREFIX = f'git -c "alias.{ALIAS}=!{_MISSING}; sh {LAUNCHER_REL}" {ALIAS}'

#: A plugin has no repository root to resolve against, so its alias carries nothing but `sh`: git
#: supplies a POSIX sh under bash, PowerShell and cmd.exe alike, and the launcher's path is an
#: argument the client expands in its plugin-root token, as it did for `python3 "<path>"`.
PLUGIN_ALIAS = "chock-sh"

#: The launcher's name beside a plugin's packaged runtime.
PLUGIN_LAUNCHER = "launch.sh"

_TEMPLATE = package_data_dir("chock", "hooks", "data").joinpath("launch.sh").read_text(encoding="utf-8")


def hook_command(runtime: str, *args: str) -> str:
    """The command an agent config carries to run `runtime` (repo-relative) with `args`."""
    words = [f'"{arg}"' if "/" in arg else arg for arg in args]
    return " ".join([_PREFIX, runtime, *words])


#: A plugin launcher that is not there (root unset or wrong) refuses with exit 2 inside git's sh,
#: so the outer shell (bash, PowerShell, cmd.exe) reads nothing but a quoted string.
_PLUGIN_MISSING = "test -f '{path}' || {{ echo chock: the plugin launcher is missing, so this call cannot be checked. Refusing. >&2; exit 2; }}"


def plugin_interpreter(launcher: str) -> str:
    """What stands where a plugin hook said `python3`: git's sh running the shipped launcher at path `launcher`."""
    missing = _PLUGIN_MISSING.format(path=launcher)
    return f'git -c "alias.{PLUGIN_ALIAS}=!{missing}; sh" {PLUGIN_ALIAS} "{launcher}"'


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


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 -- fixed argv: git reading or setting this clone's own config
        ["git", *args],  # noqa: S607 -- git on PATH is the repo route's premise
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def record_interpreter(repo_root: Path) -> bool:
    """Name this interpreter in the clone's own .git/config; never committed. True when set."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        # Only when repo_root is the top level: inside another repo it is that repo's config.
        top = _git(repo_root, "rev-parse", "--show-toplevel").stdout.strip()
        if not top or Path(top).resolve() != Path(repo_root).resolve():
            return False
        return (
            _git(repo_root, "config", "--local", PYTHON_CONFIG_KEY, PurePath(sys.executable).as_posix()).returncode == 0
        )
    return False
