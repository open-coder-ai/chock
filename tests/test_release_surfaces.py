"""The surfaces a release ships beside the wheel say the version being released.

`action.yml`'s default is what an adopter gets with no `version:`; the installation page's
example is what they copy. Both are literals, so a release that bumps `pyproject.toml`
and forgets either ships an install of an older chock under the new tag.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _released_version() -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert match, "pyproject.toml carries no version"
    return match.group(1)


def test_the_action_installs_the_version_being_released() -> None:
    action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    default = str(action["inputs"]["version"]["default"])
    assert default == _released_version(), (
        f"action.yml installs chock=={default} by default; this release is {_released_version()}"
    )


def test_the_installation_example_pins_the_version_being_released() -> None:
    text = (ROOT / "docs" / "installation.md").read_text(encoding="utf-8")
    version = _released_version()
    assert f"uses: open-coder-ai/chock@v{version}" in text, (
        "docs/installation.md's action example names another release"
    )
    assert f"version: {version}" in text, "docs/installation.md's action example installs another release"


_INSTALL = re.compile(r"\b(?:pipx|pip3?|uv\s+pip|uv\s+tool|python3?\s+-m\s+pip)\s+install\b([^\n`]*)")
_COMMAND_END = re.compile(r"\s#|&&|\|\||;|\|")


def _install_targets(text: str) -> list[str]:
    """Every package argument of every pip/pipx/uv install command in `text`."""
    targets: list[str] = []
    for match in _INSTALL.finditer(text):
        args = _COMMAND_END.split(" " + match.group(1), maxsplit=1)[0]
        targets.extend(arg for arg in shlex.split(args) if not arg.startswith("-"))
    return targets


def _off_version(text: str, version: str) -> list[str]:
    return [target for target in _install_targets(text) if target != f"chock=={version}"]


@pytest.mark.parametrize(
    "line",
    [
        'pip install "chock @ git+https://github.com/open-coder-ai/chock@992711af"',
        "pipx install chock==0.15.2",
        "pip install chock",
        "uv tool install chock>=1.0",
        "pip install --upgrade chock==9.9.9 && chock init .",
    ],
)
def test_the_install_line_check_refuses_anything_but_the_current_pin(line: str) -> None:
    assert _off_version(f"```bash\n{line}\n```\n", "9.9.8"), f"{line!r} slipped past the check"


def test_the_install_line_check_accepts_the_current_pin() -> None:
    assert _install_targets("pip install chock==9.9.8  # pinned\n") == ["chock==9.9.8"]
    assert not _off_version("pipx install --force chock==9.9.8; chock --version\n", "9.9.8")


def test_every_readme_install_line_pins_the_version_being_released() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    version = _released_version()
    assert _install_targets(text), "README.md has no install line; the check below would pass on nothing"
    assert not _off_version(text, version), (
        f"README.md installs {_off_version(text, version)}; every install line must be chock=={version}"
    )
