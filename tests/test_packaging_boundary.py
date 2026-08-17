"""The framework ships mechanism. It ships no policies.

That is an ownership decision, not a packaging detail: bundled policies were reinstalled
over adopter edits on every `init`, silently, and the only way to stop fighting the edit is
to have nothing framework-owned to overwrite. The decision is one commit away from being
undone by a well-meaning `packs/_baseline/` reappearing, so the boundary is asserted here
rather than remembered.

Both halves are checked against the built wheel, not the source tree, because the wheel is
what an adopter installs -- and `package-data` globs are exactly the kind of thing that
starts sweeping up a directory nobody meant to ship.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
BUNDLED_PACKS = FRAMEWORK_ROOT / "src" / "chock" / "packs"


def test_no_policies_are_bundled_in_the_source_tree() -> None:
    """`packs/` holds authoring skills only. A policy tree here is the thing being banned."""
    assert not (BUNDLED_PACKS / "_baseline").exists(), (
        "src/chock/packs/_baseline is back. Policies are content and live in "
        "chock-catalog; the framework ships mechanism."
    )


def test_the_wheel_ships_no_policy_folder(built_wheel: Path) -> None:
    """No file under any `.agents/policies/` path may reach an adopter's install.

    Catches the two ways a policy could travel: a bundled pack tree, and a copy smuggled
    into the `chock-init` template assets -- which is where a third, stale duplicate
    of all twelve policies once lived, read by nothing and kept correct by nobody.
    """
    with zipfile.ZipFile(built_wheel) as whl:
        names = whl.namelist()

    offenders = sorted(n for n in names if ".agents/policies/" in n or "packs/_baseline/" in n)
    assert not offenders, f"the wheel ships {len(offenders)} policy file(s): {offenders[:10]}"


def test_the_wheel_still_ships_the_mechanism(built_wheel: Path) -> None:
    """Guard the guard: a wheel that shipped nothing at all would pass the test above."""
    with zipfile.ZipFile(built_wheel) as whl:
        names = whl.namelist()

    assert any("packs/_skills/" in n for n in names), "authoring skills missing from the wheel"
    assert any("validation/schemas/" in n for n in names), "validation schemas missing from the wheel"
