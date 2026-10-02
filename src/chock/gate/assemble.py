"""Assemble the single-file vendored gate runtime (`.chock/bin/gate.py`) from the runner package."""

from __future__ import annotations

import re

from chock.resources import package_data_dir

RUNNER_PACKAGE = "chock.gate.runner"

#: A module's text after its header is fragments, each opened by this line; fragment numbers set
#: their order in gate.py and run 1..N across the package with no gap and no repeat.
_MARKER_RE = re.compile(r"^# >>> gate\.py (\d+)\n", re.MULTILINE)
#: Two blank lines join consecutive fragments, as between top-level definitions.
_SEPARATOR = "\n\n\n"


def _prelude() -> str:
    return package_data_dir("chock.gate", "data").joinpath("gate_prelude.py.tmpl").read_text(encoding="utf-8")


def _fragments() -> dict[int, str]:
    found: dict[int, str] = {}
    for module in sorted(package_data_dir(RUNNER_PACKAGE).glob("*.py")):
        parts = _MARKER_RE.split(module.read_text(encoding="utf-8"))
        for number, body in zip(parts[1::2], parts[2::2], strict=True):
            if int(number) in found:
                msg = f"gate.py fragment {number} appears twice (again in {module.name})"
                raise ValueError(msg)
            found[int(number)] = body.strip("\n")
    return found


def runner_source() -> str:
    """The vendored gate runner: the prelude, then every fragment in number order. Raises on a gap."""
    found = _fragments()
    if not found:
        msg = f"no gate.py fragments under {package_data_dir(RUNNER_PACKAGE)}; a binary must bundle its .py as data"
        raise FileNotFoundError(msg)
    if sorted(found) != list(range(1, len(found) + 1)):
        msg = f"gate.py fragments must run 1..N without a gap; found {sorted(found)}"
        raise ValueError(msg)
    return _prelude() + _SEPARATOR.join(found[number] for number in sorted(found)) + "\n"
