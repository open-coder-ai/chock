"""Per-vendor runtime goldens: bundle output is frozen bytes until a deliberate regen."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from chock.gate import runtime_bundle

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "runtime_goldens"


def test_every_runtime_matches_its_frozen_fixture() -> None:
    rendered = {f"{agent}.py": runtime_bundle.render(agent) for agent in runtime_bundle.RUNTIME_AGENTS}

    if os.environ.get("CHOCK_REGEN_GOLDENS") == "1":
        if GOLDEN.exists():
            shutil.rmtree(GOLDEN)
        GOLDEN.mkdir(parents=True)
        for name, text in rendered.items():
            (GOLDEN / name).write_text(text, encoding="utf-8")
        pytest.skip(
            "runtime goldens regenerated -- commit the diff; only an agentseam pin bump or a deliberate handler change explains one"
        )

    assert GOLDEN.exists(), "no runtime goldens committed; run with CHOCK_REGEN_GOLDENS=1 once"
    frozen = {p.name: p.read_text(encoding="utf-8") for p in GOLDEN.glob("*.py")}
    assert set(frozen) == set(rendered), (
        f"the runtime set changed (frozen={sorted(frozen)}, rendered={sorted(rendered)}); regenerate deliberately"
    )
    differing = sorted(name for name in rendered if rendered[name] != frozen[name])
    assert not differing, (
        f"runtime bytes moved for {differing}: every adopter's next sync rewrites .chock/bin. "
        "Intentional (pin bump, handler change)? Regenerate with CHOCK_REGEN_GOLDENS=1."
    )
