"""A gate whose check is a script the policy ships: the runner's material, the script's verdict.

The declarative kinds answer questions a closed table can hold. A flow model over a method
body cannot be written that way, and until now the only door for a script was the shell
guard, which judges a command and never sees the file being written. `kind: script` hands
the policy's own program the same material every declarative kind reads -- the staged blobs
at commit, the write at tool use and at the turn's end -- and carries back its verdict.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml
from conftest import init_repo, stage

from chock.compile.emitters.advisory import advisory_lines
from chock.compile.emitters.in_agent import GATE_FILE, STOP_FRAGMENT, WRITE_FRAGMENT, emit_pre_tool_use, emit_stop
from chock.eval.execute import run_case
from chock.eval.model import Case
from chock.gate import runner
from chock.gate.build import build_gate_json
from chock.gate.runner import WRITE_PATH_KINDS, run
from chock.validation.checks_gate_shape import _validate_gate
from chock.validation.report import Report

POLICY_ID = "scripted"
SCRIPT = "scripted-gate.py"
MARKER = "FORBIDDEN"

#: Refuses any write carrying MARKER, in its own words. Two other markers make it misbehave,
#: so the runner's answer to a script that gives no verdict can be pinned without a second file.
GATE_SCRIPT = textwrap.dedent(
    """\
    import json, sys, time
    payload = json.load(sys.stdin)
    texts = payload["writes"]
    if any("CRASH" in t for t in texts.values()):
        sys.exit(7)
    if any("HANG" in t for t in texts.values()):
        time.sleep(5)
    hits = sorted(p for p, t in texts.items() if "FORBIDDEN" in t)
    if hits:
        print("scripted: forbidden marker in " + ", ".join(hits), file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
    """
)


def _policy(repo: Path, *, on=("commit", "tool_use"), ship_script: bool = True) -> tuple[Path, dict]:
    policy = repo / ".agents" / "policies" / POLICY_ID
    (policy / "implementations").mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": POLICY_ID,
        "name": "Scripted",
        "version": "0.0.1",
        "description": "d",
        "artifact": "hook",
        "enforcement": "block",
        "hook": {
            "gate": {"kind": "script", "on": list(on), "action": "block", "message": "m", "params": {"script": SCRIPT}}
        },
        "provenance": {"author": "t"},
        "lifecycle": {"status": "draft"},
    }
    (policy / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if ship_script:
        (policy / "implementations" / SCRIPT).write_text(GATE_SCRIPT, encoding="utf-8")
    return policy, manifest


def _gate(repo: Path, **kw) -> Path:
    """The compiled gate.json for a scripted policy in `repo`, where the git hook would find it."""
    policy, _ = _policy(repo, **kw)
    spec = build_gate_json(policy, repo)
    assert spec is not None
    gate = repo / ".chock" / "compiled" / POLICY_ID / "git-hook" / GATE_FILE
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps(spec), encoding="utf-8")
    return gate


# --- the compiled gate ------------------------------------------------------------------------


def test_the_compiled_gate_names_the_script_from_the_repository_root(tmp_path: Path) -> None:
    policy, _ = _policy(tmp_path)
    spec = build_gate_json(policy, tmp_path)
    assert spec is not None
    assert spec["params"]["script"] == f".agents/policies/{POLICY_ID}/implementations/{SCRIPT}"


def test_a_script_can_answer_for_a_write() -> None:
    assert "script" in WRITE_PATH_KINDS


# --- at commit, the staged blobs ------------------------------------------------------------------


def test_a_staged_file_the_script_refuses_blocks_the_commit(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    init_repo(tmp_path)
    gate = _gate(tmp_path)
    stage(tmp_path, "App.java", f"x = {MARKER}\n")
    assert run(gate, "pre-commit", None, tmp_path) == 1
    assert "scripted: forbidden marker in App.java" in capsys.readouterr().err


def test_a_clean_staged_file_passes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    gate = _gate(tmp_path)
    stage(tmp_path, "App.java", "x = 1\n")
    assert run(gate, "pre-commit", None, tmp_path) == 0


def test_nothing_staged_is_nothing_to_refuse(tmp_path: Path) -> None:
    init_repo(tmp_path)
    assert run(_gate(tmp_path), "pre-commit", None, tmp_path) == 0


# --- at tool use and at the turn's end, the write --------------------------------------------------


@pytest.mark.parametrize("event", ["pre-tool-use", "stop"])
def test_a_write_is_judged_by_the_same_script(tmp_path: Path, event: str) -> None:
    init_repo(tmp_path)
    gate = _gate(tmp_path)
    assert run(gate, event, None, tmp_path, writes={"App.java": MARKER}) == 1
    assert run(gate, event, None, tmp_path, writes={"App.java": "clean"}) == 0


def test_the_scripts_own_words_are_the_reason(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The policy's generic message would say less than the script, which knows which rule and where."""
    init_repo(tmp_path)
    gate = _gate(tmp_path)
    run(gate, "pre-tool-use", None, tmp_path, writes={"App.java": MARKER})
    assert "scripted: forbidden marker in App.java" in capsys.readouterr().err


# --- no verdict is a refusal ----------------------------------------------------------------------


def test_a_script_that_crashes_refuses(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    init_repo(tmp_path)
    gate = _gate(tmp_path)
    assert run(gate, "pre-tool-use", None, tmp_path, writes={"App.java": "CRASH"}) == 1
    err = capsys.readouterr().err
    assert "exited 7" in err
    assert "refusing" in err


def test_a_script_that_is_not_installed_refuses(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    init_repo(tmp_path)
    gate = _gate(tmp_path, ship_script=False)
    assert run(gate, "pre-tool-use", None, tmp_path, writes={"App.java": "clean"}) == 1
    assert "not installed" in capsys.readouterr().err


def test_a_script_that_never_answers_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(runner, "_SCRIPT_TIMEOUT_SECONDS", 1)
    init_repo(tmp_path)
    gate = _gate(tmp_path)
    assert run(gate, "pre-tool-use", None, tmp_path, writes={"App.java": "HANG"}) == 1
    assert "no verdict" in capsys.readouterr().err


# --- the emitters wire it where every write-path gate goes ---------------------------------------


def test_a_script_gate_reaches_the_write_path(tmp_path: Path) -> None:
    policy, manifest = _policy(tmp_path)
    out = tmp_path / ".chock" / "compiled" / POLICY_ID / "pre-tool-use"
    out.mkdir(parents=True)
    names = {p.name for p in emit_pre_tool_use(policy, out, manifest)}
    assert {GATE_FILE, WRITE_FRAGMENT} <= names
    spec = json.loads((out / GATE_FILE).read_text(encoding="utf-8"))
    assert spec["kind"] == "script"
    assert spec["params"]["script"].endswith(f"implementations/{SCRIPT}")


def test_a_script_gate_reaches_the_turns_end(tmp_path: Path) -> None:
    policy, manifest = _policy(tmp_path)
    out = tmp_path / ".chock" / "compiled" / POLICY_ID / "stop"
    out.mkdir(parents=True)
    names = {p.name for p in emit_stop(policy, out, manifest)}
    assert {GATE_FILE, STOP_FRAGMENT} <= names


def test_a_commit_only_script_gate_stays_out_of_the_agent(tmp_path: Path) -> None:
    policy, manifest = _policy(tmp_path, on=("commit",))
    pre = tmp_path / ".chock" / "compiled" / POLICY_ID / "pre-tool-use"
    end = tmp_path / ".chock" / "compiled" / POLICY_ID / "stop"
    assert emit_pre_tool_use(policy, pre, manifest) == []
    assert emit_stop(policy, end, manifest) == []


# --- the validator refuses what the runner would ----------------------------------------------------


def _messages(gate: dict, artifact_dir: Path | None = None) -> list[str]:
    report = Report()
    _validate_gate(gate, "manifest", report, tool_use_allowed=True, artifact_dir=artifact_dir)
    return [f.message for f in report.errors]


def _spec(script: str) -> dict:
    return {"kind": "script", "on": ["commit"], "action": "block", "message": "m", "params": {"script": script}}


@pytest.mark.parametrize("name", ["../escape.py", "sub/dir.py", "gate.sh", ""])
def test_the_script_must_be_a_bare_python_file_name(name: str) -> None:
    assert any("script" in m for m in _messages(_spec(name)))


def test_a_declared_script_must_be_shipped(tmp_path: Path) -> None:
    policy, _ = _policy(tmp_path, ship_script=False)
    assert any("not there" in m for m in _messages(_spec(SCRIPT), policy))


def test_a_shipped_script_validates(tmp_path: Path) -> None:
    policy, _ = _policy(tmp_path)
    assert _messages(_spec(SCRIPT), policy) == []


# --- an eval case replays against the script, not against its absence --------------------------


def _case(files: dict[str, str], expect: str) -> Case:
    return Case(
        id="t",
        category="trigger",
        prompt="p",
        expect="e",
        policy_id=POLICY_ID,
        execute={"files": files, "event": "commit", "expect": expect},
    )


@pytest.mark.parametrize(("text", "expect"), [(MARKER, "block"), ("clean", "allow")])
def test_an_eval_case_finds_the_script_in_the_throwaway_repo(tmp_path: Path, text: str, expect: str) -> None:
    """The throwaway repo holds only the case's files; the gate's own program has to be put there."""
    init_repo(tmp_path)
    policy, _ = _policy(tmp_path)
    result = run_case(_case({"App.java": text}, expect), policy, tmp_path, guards=[])
    assert result.outcome == "pass", result.detail


def test_an_eval_case_never_stages_the_script_itself(tmp_path: Path) -> None:
    """A script that refuses its own text must not refuse every case by being in the writes."""
    init_repo(tmp_path)
    policy, _ = _policy(tmp_path)
    (policy / "implementations" / SCRIPT).write_text(GATE_SCRIPT.replace('"FORBIDDEN" in t', '"sys.exit" in t'))
    result = run_case(_case({"App.java": "clean"}, "allow"), policy, tmp_path, guards=[])
    assert result.outcome == "pass", result.detail


# --- the ambient line names the script wherever the policy sits ------------------------------------


def test_the_ambient_line_names_the_script_not_its_address(tmp_path: Path) -> None:
    """One packaged SKILL.md must be right in a catalog tree and in .agents/policies alike."""
    adopted, _ = _policy(tmp_path)
    catalog_root = tmp_path / "catalog"
    (catalog_root / ".chock").mkdir(parents=True)
    catalog = catalog_root / "base" / POLICY_ID
    (catalog / "implementations").mkdir(parents=True)
    (catalog / "manifest.yaml").write_text((adopted / "manifest.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (catalog / "implementations" / SCRIPT).write_text(GATE_SCRIPT, encoding="utf-8")
    assert advisory_lines(adopted, yaml.safe_load((adopted / "manifest.yaml").read_text()), tmp_path) == advisory_lines(
        catalog, yaml.safe_load((catalog / "manifest.yaml").read_text()), catalog_root
    )
    assert (
        f"script={SCRIPT}"
        in advisory_lines(adopted, yaml.safe_load((adopted / "manifest.yaml").read_text()), tmp_path)[0]
    )
