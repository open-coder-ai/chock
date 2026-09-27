"""A gate never judges its own policy's shipped or compiled files, and nothing else.

java-security refused its own adoption commit on evals/suite.yaml and skill/setup.html, and every
Stop after it: a policy's evals carry the very content its gate refuses (#32).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from conftest import init_repo, stage

from chock.gate.runner import run

POLICY_ID = "scripted"
MARKER = "FORBIDDEN"
SCRIPT = textwrap.dedent(
    """\
    import json, sys
    hits = sorted(p for p, t in json.load(sys.stdin)["writes"].items() if "FORBIDDEN" in t)
    if hits:
        print("refused: " + ", ".join(hits), file=sys.stderr)
        sys.exit(1)
    """
)


def _gate(repo: Path, spec: dict, policy_id: str = POLICY_ID) -> Path:
    gate = repo / ".chock" / "compiled" / policy_id / "git-hook" / "gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps(spec), encoding="utf-8")
    return gate


def _script_gate(repo: Path) -> Path:
    script = f".agents/policies/{POLICY_ID}/implementations/gate.py"
    (repo / script).parent.mkdir(parents=True)
    (repo / script).write_text(SCRIPT, encoding="utf-8")
    return _gate(repo, {"kind": "script", "on": ["commit", "tool_use"], "params": {"script": script}})


@pytest.mark.parametrize("event", ["pre-commit", "pre-tool-use", "stop"])
def test_a_script_gate_does_not_refuse_its_own_evals_or_compiled_output(tmp_path: Path, event: str) -> None:
    init_repo(tmp_path)
    gate = _script_gate(tmp_path)
    own = {
        f".agents/policies/{POLICY_ID}/evals/suite.yaml": f"payload: {MARKER}\n",
        f".agents/policies/{POLICY_ID}/skill/setup.html": f"<p>{MARKER}</p>\n",
        f".chock/compiled/{POLICY_ID}/stop/gate.json": f'{{"x": "{MARKER}"}}\n',
    }
    if event == "pre-commit":
        for path, text in own.items():
            stage(tmp_path, path, text)
        assert run(gate, event, None, tmp_path) == 0
    else:
        assert run(gate, event, None, tmp_path, writes=own) == 0


def test_another_policys_folder_and_ordinary_files_are_still_judged(tmp_path: Path) -> None:
    init_repo(tmp_path)
    gate = _script_gate(tmp_path)
    assert run(gate, "stop", None, tmp_path, writes={".agents/policies/other/x.yaml": MARKER}) == 1
    assert run(gate, "stop", None, tmp_path, writes={"App.java": MARKER}) == 1


@pytest.mark.parametrize(
    "path", [".chock/bin/notes.txt", ".chock/bin/claude_code.py", ".chock/compiled/other/stop/leak.env"]
)
@pytest.mark.parametrize("event", ["pre-commit", "stop"])
def test_a_file_planted_in_the_generated_tree_is_still_judged(tmp_path: Path, event: str, path: str) -> None:
    """A secret committed under .chock/ must not ride past every content gate."""
    init_repo(tmp_path)
    gate = _script_gate(tmp_path)
    if event == "pre-commit":
        stage(tmp_path, path, MARKER)
        assert run(gate, event, None, tmp_path) == 1
    else:
        assert run(gate, event, None, tmp_path, writes={path: MARKER}) == 1


@pytest.mark.parametrize("path", [".chock/config.yaml", ".chock/dependency-allowlist.txt"])
def test_the_adopters_own_chock_files_are_still_judged(tmp_path: Path, path: str) -> None:
    """Only what sync generates is exempt; config the adopter writes by hand is ordinary text."""
    init_repo(tmp_path)
    gate = _script_gate(tmp_path)
    assert run(gate, "stop", None, tmp_path, writes={path: MARKER}) == 1


def test_a_content_gate_follows_the_same_rule(tmp_path: Path) -> None:
    """Declarative kinds had the same self-trigger; the catalog dodged it per policy with self-safe patterns."""
    init_repo(tmp_path)
    spec = {"kind": "content_regex", "on": ["commit"], "params": {"scan": "added_lines", "content_pattern": MARKER}}
    gate = _gate(tmp_path, spec, "pin")
    stage(tmp_path, ".agents/policies/pin/evals/suite.yaml", f"{MARKER}\n")
    assert run(gate, "pre-commit", None, tmp_path) == 0
    stage(tmp_path, ".agents/policies/other/evals/suite.yaml", f"{MARKER}\n")
    assert run(gate, "pre-commit", None, tmp_path) == 1
