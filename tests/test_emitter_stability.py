"""Patch releases must compile byte-identical output: the adopter contract.

Every adopter commits compiled artifacts, and every engine bump makes their drift
checks compare those bytes against what the new engine produces. The versioning
policy therefore promises: a PATCH release never changes emitter output, so a patch
bump never requires `chock sync`. This suite is that promise, tested.

Two frozen fixture policies compile against a committed golden tree. If an emitter
change is intentional, regenerate the goldens (CHOCK_REGEN_GOLDENS=1 pytest
tests/test_emitter_stability.py) and land the diff in the same PR -- reviewers then
see exactly what every adopter's next `chock sync` will rewrite, and the version
bump must be MINOR, not patch.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from chock.compile.compiler import _load_manifest, compile_policy
from chock.config import policy_status

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "emitter_stability"
POLICIES = FIXTURES / "policies"
GOLDEN = FIXTURES / "golden"

#: Frozen agent list: golden bytes must not depend on which agents a dev machine
#: configures. Two agents with different surface sets keeps coverage honest.
AGENTS = ["claude", "cursor"]


def _compile_fixtures(output_root: Path) -> None:
    for pack_dir in sorted(p for p in POLICIES.iterdir() if p.is_dir()):
        manifest = _load_manifest(pack_dir)
        status = policy_status({}, manifest.get("id") or pack_dir.name, manifest)
        compile_policy(
            pack_dir,
            targets=status["targets"],
            output_root=output_root,
            agents=AGENTS,
            repo_root=FIXTURES,
        )


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_emitters_compile_the_goldens_byte_identically(tmp_path: Path) -> None:
    out = tmp_path / "compiled"
    out.mkdir()
    _compile_fixtures(out)

    if os.environ.get("CHOCK_REGEN_GOLDENS") == "1":
        if GOLDEN.exists():
            shutil.rmtree(GOLDEN)
        shutil.copytree(out, GOLDEN)
        pytest.skip("goldens regenerated -- commit the diff and bump MINOR, not patch")

    assert GOLDEN.exists(), "no golden tree committed; run with CHOCK_REGEN_GOLDENS=1 once"

    expected = _tree(GOLDEN)
    actual = _tree(out)

    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    assert not missing and not extra, (
        f"emitter output shape changed (missing={missing}, extra={extra}). "
        "Intentional? Regenerate goldens and bump MINOR."
    )

    differing = sorted(rel for rel in expected if expected[rel] != actual[rel])
    assert not differing, (
        f"emitter output changed for: {differing}. Every adopter's next `chock sync` "
        "rewrites these files. Intentional? Regenerate goldens (CHOCK_REGEN_GOLDENS=1) "
        "and bump MINOR, not patch."
    )


def test_golden_tree_covers_every_surface_worth_freezing() -> None:
    """The guarantee is only as wide as the fixtures. If a golden tree exists but no
    longer contains a gate, shim, or ambient file, the stability test is passing on
    an empty promise."""
    if not GOLDEN.exists():
        pytest.skip("goldens not generated yet")
    names = {p.name for p in GOLDEN.rglob("*") if p.is_file()}
    # pretooluse.json/cursor-hooks.json joined the contract with the #49 K1 fix: the
    # session-enforcement emitters were the one surface the byte-stability promise
    # skipped, exactly where a silent output change hurts the most installed clients.
    for required in ("gate.json", "ambient.md", "pretooluse.json", "cursor-hooks.json", "agent-hooks.json"):
        assert any(required in n for n in names), f"golden tree lost its {required} coverage"
