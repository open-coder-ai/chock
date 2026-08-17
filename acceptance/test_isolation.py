"""The rule that makes this suite worth having, enforced rather than trusted.

If a scenario can import `chock`, it stops testing the wheel an adopter installs and
starts testing the source tree next to it. Every defect this suite exists to catch --
missing template files, half-installed policies, hooks wired to nothing -- is invisible
from inside the source tree. The rule erodes the first time obeying it is inconvenient, so
it is checked here rather than left to discipline.
"""

from __future__ import annotations

import re
from pathlib import Path

ACCEPTANCE_ROOT = Path(__file__).resolve().parent

# conftest reads FRAMEWORK_ROOT to build the wheel; that is a path, not an import.
_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+chock\b", re.MULTILINE)


def _python_files() -> list[Path]:
    return sorted(p for p in ACCEPTANCE_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def test_no_acceptance_file_imports_the_framework() -> None:
    offenders: list[str] = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        for match in _IMPORT_RE.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(ACCEPTANCE_ROOT)}:{line}")
    assert not offenders, (
        f"acceptance tests must drive the installed wheel, never the source tree. Found imports at: {offenders}"
    )


def test_the_suite_actually_has_scenarios() -> None:
    """Guard the guard: a rule about files is vacuous if there is nothing to run.

    Counts Gherkin scenarios rather than test modules. Since the suite moved to pytest-bdd
    the modules stay at two no matter how much coverage is deleted, so counting files would
    pass an empty suite.
    """
    features = sorted((ACCEPTANCE_ROOT / "features").glob("*.feature"))
    assert features, "no feature files found"
    total = sum(
        line.strip().startswith(("Scenario:", "Scenario Outline:"))
        for feature in features
        for line in feature.read_text(encoding="utf-8").splitlines()
    )
    assert total >= 10, f"expected the acceptance scenarios to be present, found {total}"
