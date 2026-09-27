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


_OLD_HEADER = (
    "from __future__ import annotations\n\nimport json\n_json = json\nimport sys\nimport traceback\n\n# body\n"
)
_REORDERED = (
    "from __future__ import annotations\n\nimport contextlib\nimport io\nimport json\n_json = json\n"
    "import os\nimport sys\nimport traceback\n\n# body\n"
)


@pytest.mark.parametrize("header", [_OLD_HEADER, _REORDERED], ids=["agentseam-0.3.3", "hoisted-around-sys"])
def test_chock_imports_land_after_import_sys_however_agentseam_orders_its_block(header: str) -> None:
    """agentseam 0.3.4 hoists contextlib/io/os; an exact-block anchor then matched nothing."""
    at = runtime_bundle._hoist_point(header)
    assert header[:at].endswith("import sys\n")
    assert "# body" not in header[:at]


def test_a_bundle_without_the_import_block_is_refused() -> None:
    assert runtime_bundle._hoist_point("from __future__ import annotations\n\nimport json\n\nimport sys\n") == -1
    assert runtime_bundle._hoist_point("import sys\n") == -1
