"""Every built plugin hook runs: a benign shell command, write and turn end are allowed, a violating command is refused."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import init_repo
from guard_gate_support import BUILDERS, STORES
from plugin_smoke_support import run_hooks

from chock.compile.emitters.in_agent import _guard_script

REFUSED = "refused: danger"
VIOLATION = "echo danger"
#: One guard per way a policy's program reaches the files beside it, plus the script gate named after its policy.
GUARD_SOURCES = {
    "flat-sibling": ("from flatlib import REFUSED\n", {"flatlib.py": f"REFUSED = {REFUSED!r}\n"}),
    "data-table": (
        "from tbl import WORDS\nREFUSED = 'refused: ' + WORDS[0]\n",
        {
            "tbl/__init__.py": (
                "import json\nfrom pathlib import Path\n"
                "WORDS = json.loads((Path(__file__).resolve().parent.parent / 'data' / 'words.json').read_text())['words']\n"
            ),
            "data/words.json": '{"words": ["danger"]}\n',
        },
    ),
    "both-halves": ("from bothlib import REFUSED\n", {"bothlib.py": f"REFUSED = {REFUSED!r}\n"}),
}
GUARD_BODY = "import sys\n{imports}\nif 'danger' in sys.argv[1:]:\n    print(REFUSED)\n    sys.exit(1)\n"
#: A JSON-in script gate: stdin is the engine's document, never a command line.
GATE_BODY = (
    "import json, sys\n{imports}\n"
    "doc = json.load(sys.stdin)\n"
    "sys.exit(1 if any('FORBIDDEN' in text for text in doc.get('writes', {{}}).values()) else 0)\n"
)
GATE_SCRIPTS = {"script-gate": "script-gate.py", "both-halves": "both-halves_gate.py"}


def _manifest(policy_id: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": policy_id,
        "name": policy_id,
        "version": "0.0.1",
        "description": "A fixture policy.",
        "artifact": "hook",
        "enforcement": "block",
        "provenance": {"author": "t", "license": "Apache-2.0"},
        "lifecycle": {"status": "draft"},
    }
    if policy_id in GATE_SCRIPTS:
        gate = {
            "kind": "script",
            "on": ["tool_use"],
            "action": "block",
            "message": "no",
            "params": {"script": GATE_SCRIPTS[policy_id]},
        }
        data["hook"] = {"gate": gate}
    return data


def _policy(root: Path, policy_id: str) -> tuple[Path, dict[str, Any]]:
    pack = root / policy_id
    impl = pack / "implementations"
    impl.mkdir(parents=True)
    manifest = _manifest(policy_id)
    (pack / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    imports, files = GUARD_SOURCES.get(policy_id, ("", {}))
    if policy_id in GUARD_SOURCES:
        (impl / f"{policy_id}.py").write_text(GUARD_BODY.format(imports=imports), encoding="utf-8")
    if policy_id in GATE_SCRIPTS:
        (impl / GATE_SCRIPTS[policy_id]).write_text(GATE_BODY.format(imports=""), encoding="utf-8")
    for rel, text in files.items():
        (impl / rel).parent.mkdir(parents=True, exist_ok=True)
        (impl / rel).write_text(text, encoding="utf-8")
    return pack, manifest


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "repo").mkdir()
    repo = init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


def _check_policy(client: str, pack: Path, manifest: dict[str, Any], tmp_path: Path, violation: str | None) -> None:
    """Build `pack` in `client`'s format and run every hook it ships; fail on a crash, an ask or a deny."""
    policy_id = str(manifest["id"])
    out = tmp_path / "dist" / client / policy_id
    BUILDERS[client](pack, manifest, pack.parent, out)
    hooks_rel = STORES[client][2]
    if not (out / hooks_rel).is_file():
        return
    repo = _repo(tmp_path)
    bad = [(kind, said, hook[-90:]) for hook, kind, said in run_hooks(client, out, hooks_rel, repo) if said != "allow"]
    assert not bad, f"{client}/{policy_id} hooks did not allow a benign call: {bad}"
    if violation and _guard_script(pack, policy_id):
        refused = [said for _hook, kind, said in run_hooks(client, out, hooks_rel, repo, violation) if kind == "shell"]
        assert refused and all(said in ("deny", "block") for said in refused), f"{client}/{policy_id}: {refused}"


@pytest.mark.parametrize("client", sorted(BUILDERS))
@pytest.mark.parametrize("policy_id", sorted({*GUARD_SOURCES, *GATE_SCRIPTS}))
def test_each_failure_shape_builds_a_hook_that_runs(client: str, policy_id: str, tmp_path: Path) -> None:
    pack, manifest = _policy(tmp_path / "policies", policy_id)
    _check_policy(client, pack, manifest, tmp_path, VIOLATION)


def test_a_script_gate_is_not_wired_as_a_command_guard(tmp_path: Path) -> None:
    pack, _ = _policy(tmp_path / "policies", "script-gate")
    assert _guard_script(pack, "script-gate") is None
    pack, _ = _policy(tmp_path / "policies", "both-halves")
    assert _guard_script(pack, "both-halves") == "both-halves.py"


# --- the real catalog, when a checkout of it is named ------------------------------------------

CATALOG = os.environ.get("CHOCK_CATALOG_DIR")
CATALOG_DIRS = ("base", "agentic-security", "compliance")


def _catalog_policies() -> list[Path]:
    root = Path(CATALOG or ".")
    return sorted(p for d in CATALOG_DIRS for p in (root / d).glob("*/manifest.yaml")) if CATALOG else []


def _first_violation(pack: Path) -> str | None:
    """The first eval case whose command the guard must refuse."""
    suite = pack / "evals" / "suite.yaml"
    cases = (
        (yaml.safe_load(suite.read_text(encoding="utf-8")) or {}).get("suite", {}).get("cases", [])
        if suite.is_file()
        else []
    )
    for case in cases:
        run = case.get("execute") or {}
        if run.get("expect") == "block" and run.get("command"):
            return str(run["command"])
    return None


@pytest.mark.skipif(not CATALOG, reason="set CHOCK_CATALOG_DIR to a chock-catalog checkout")
@pytest.mark.parametrize("client", sorted(BUILDERS))
@pytest.mark.parametrize("manifest_path", _catalog_policies(), ids=lambda p: p.parent.name)
def test_every_catalog_policy_builds_hooks_that_run(client: str, manifest_path: Path, tmp_path: Path) -> None:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    _check_policy(client, manifest_path.parent, manifest, tmp_path, _first_violation(manifest_path.parent))
