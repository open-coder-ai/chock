"""One hook process per event decides exactly what one process per policy decides, over this repo's compiled policies.

Runs in CI with the rest of the suite. `CHOCK_EQUIVALENCE_REPO=<repo root> python -m pytest tests/test_multi_equivalence.py` runs it over
another repository's `.agents/policies` and `.chock/compiled` (a catalog clone); a policy without a payload in
`VIOLATING` is then checked on its clean and faulting payloads only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from decision_log_support import hook_env
from runtime_support import write_runtime

from chock.gate.build import vendor_runner
from chock.hooks.in_agent_install import install_hooks
from chock.hooks.multi_wiring import INDEX_DIR, INDEX_SHA_FLAG, MULTI_FLAG, member_files

ROOT = Path(os.environ.get("CHOCK_EQUIVALENCE_REPO") or Path(__file__).resolve().parents[1])
RUNTIME = Path(".chock") / "bin" / "claude_code.py"
CLEAN = "clean"
FAULT = "fault"
VIOLATING_KIND = "violating"

#: Per (policy, flag): a call the policy refuses, as (tool, tool_input). The two content gates whose violating text
#: this repo's own hooks refuse to have written into a file take theirs from the policy's committed eval suite at test time.
VIOLATING = {
    ("block-destructive-commands", "--guard"): ("Bash", {"command": "rm -rf /"}),
    ("block-no-verify", "--guard"): ("Bash", {"command": "git commit --no-verify -m x"}),
    ("protect-agent-config", "--guard"): ("Bash", {"command": "echo x > AGENTS.md"}),
    ("protect-commit-privacy", "--guard"): ("Bash", {"command": 'git commit -m "per the conversation notes"'}),
    ("block-invisible-unicode", "--gate"): ("Write", {"file_path": "a.md", "content": "hi\u202ethere"}),
    ("pin-github-actions", "--gate"): (
        "Write",
        {"file_path": ".github/workflows/x.yml", "content": "jobs:\n a:\n  steps:\n   - uses: actions/checkout@v4\n"},
    ),
    ("protect-agent-config", "--gate"): ("Write", {"file_path": "AGENTS.md", "content": "x"}),
}


def _suite_payload(policy: str) -> tuple[str, dict] | None:
    """The first single-file staged case the policy's own eval suite expects to be blocked, as a Write call."""
    suite = ROOT / ".agents" / "policies" / policy / "evals" / "suite.yaml"
    if not suite.is_file():
        return None
    for case in yaml.safe_load(suite.read_text(encoding="utf-8"))["suite"]["cases"]:
        execute = case.get("execute") or {}
        if execute.get("expect") == "block" and len(execute.get("files") or {}) == 1:
            ((path, content),) = execute["files"].items()
            return "Write", {"file_path": path, "content": content}
    return None


for _policy_id in ("block-wildcard-agent-permissions", "scan-secrets"):
    if (_found := _suite_payload(_policy_id)) is not None:
        VIOLATING[(_policy_id, "--gate")] = _found
CLEAN_INPUT = {"Bash": {"command": "echo hello"}, "Write": {"file_path": "notes.txt", "content": "hello"}}
#: A payload no policy can read: the tool input is not what its tool promises.
FAULT_INPUT = {"Bash": {"command": 123}, "Write": {"file_path": ["a"], "content": None}}
TOOLS = ("Bash", "Write")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """The repo's policies and compiled tree, wired by the real installer: {root, groups: [(matcher, rel, pin, members)]}."""
    root = tmp_path_factory.mktemp("equivalence")
    for rel in (".agents/policies", ".chock/compiled"):
        if (ROOT / rel).is_dir():
            shutil.copytree(ROOT / rel, root / rel)
    (root / ".git").mkdir()
    vendor_runner(root / ".chock")
    install_hooks(root, "claude_code")
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    groups = []
    for entry in settings["hooks"].get("PreToolUse", []):
        command = entry["hooks"][0]["command"]
        if MULTI_FLAG not in command:
            continue
        words = command.split(" ")
        rel, pin = words[words.index(MULTI_FLAG) + 1].strip('"'), words[words.index(INDEX_SHA_FLAG) + 1]
        members = json.loads((root / rel).read_text(encoding="utf-8"))["members"]
        groups.append((entry.get("matcher"), rel, pin, members))
    return {"root": root, "groups": groups}


def _run(root: Path, argv: list[str], tool: str, tool_input: dict) -> tuple:
    """(exit code, decision, reason or context) of one runtime process handed the event on stdin."""
    if isinstance(tool_input.get("file_path"), str):
        tool_input = {**tool_input, "file_path": str(root / tool_input["file_path"])}
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    payload.update(cwd=str(root), session_id="s", tool_use_id="t")
    proc = subprocess.run(
        [sys.executable, str(root / RUNTIME), *argv],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=root,
        env=hook_env(root.parent),
        check=False,
    )
    out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else {}
    said = out.get("permissionDecisionReason", out.get("additionalContext"))
    return proc.returncode, out.get("permissionDecision", "allow"), said


def _multi_argv(root: Path, members: list[dict], name: str) -> list[str]:
    """`--multi` over an index of just `members`, written and pinned beside the real ones."""
    path = root / INDEX_DIR / name
    path.write_text(json.dumps({"members": members}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return [MULTI_FLAG, path.relative_to(root).as_posix(), "--index-sha256", _sha(path)]


def _fold(results: list[tuple]) -> tuple:
    """What the combined hook says given each policy's own answer: any deny, then any ask, joined in index order."""
    for decision in ("deny", "ask"):
        reasons = [reason for _code, found, reason in results if found == decision]
        if reasons:
            return decision, "\n".join(reasons)
    spoken = [(found, reason) for _code, found, reason in results if reason is not None]
    return spoken[0] if len(spoken) == 1 else ("allow", None)


def _policy(member: dict) -> tuple[str, str]:
    flag, target = member["argv"][0], Path(member["argv"][1])
    return target.parts[2], flag


def _tool(member: dict) -> str:
    return "Bash" if member["argv"][0] == "--guard" else "Write"


def _payloads(member: dict, tool: str) -> dict[str, dict]:
    """The inputs worth sending a member that reads `tool`'s calls."""
    found = {CLEAN: CLEAN_INPUT[tool], FAULT: FAULT_INPUT[tool]}
    violating = VIOLATING.get(_policy(member))
    if violating is not None and violating[0] == tool:
        found[VIOLATING_KIND] = violating[1]
    return found


def _members(world: dict) -> list[dict]:
    return [m for _matcher, _rel, _pin, members in world["groups"] for m in members]


def test_every_policy_with_a_hook_is_a_member_and_the_rest_carry_none(world: dict) -> None:
    compiled = {p.name for p in (world["root"] / ".chock" / "compiled").iterdir()}
    members = {_policy(m)[0] for m in _members(world)}
    assert members <= compiled
    assert members, "no compiled policy carries a hook: nothing to compare"


def test_the_two_gates_with_unwritable_payloads_are_measured_from_their_suites(world: dict) -> None:
    """A member whose policy ships an eval suite is sent a call that suite expects blocked, never only clean and fault."""
    members = {_policy(m) for m in _members(world)}
    for policy in ("block-wildcard-agent-permissions", "scan-secrets"):
        if (ROOT / ".agents" / "policies" / policy / "evals" / "suite.yaml").is_file() and (
            policy,
            "--gate",
        ) in members:
            assert (policy, "--gate") in VIOLATING, policy


def test_each_member_decides_alone_what_its_single_policy_entry_decides(world: dict) -> None:
    root = world["root"]
    for n, member in enumerate(_members(world)):
        tool = _tool(member)
        for kind, tool_input in _payloads(member, tool).items():
            old = _run(root, member["argv"], tool, tool_input)
            one = _run(root, _multi_argv(root, [member], f"one-{n}.json"), tool, tool_input)
            assert one[1:] == old[1:], (member["argv"], kind, old, one)
            if kind == VIOLATING_KIND:
                assert old[1] != "allow", (member["argv"], "the payload does not violate the policy")


def test_all_members_together_say_the_fold_of_what_each_says_alone(world: dict) -> None:
    root = world["root"]
    for matcher, rel, pin, members in world["groups"]:
        for tool in (t for t in TOOLS if matcher is None or re.fullmatch(matcher, t)):
            payloads = {CLEAN: CLEAN_INPUT[tool], FAULT: FAULT_INPUT[tool]}
            for member in members:
                payloads.update(
                    {f"{member['argv']}": v for k, v in _payloads(member, tool).items() if k == VIOLATING_KIND}
                )
            for kind, tool_input in payloads.items():
                alone = [_run(root, m["argv"], tool, tool_input) for m in members]
                together = _run(root, [MULTI_FLAG, rel, "--index-sha256", pin], tool, tool_input)
                assert together[1:] == _fold(alone), (matcher, tool, kind, alone, together)


def test_a_member_pins_every_file_its_single_policy_entry_is_verified_by(world: dict) -> None:
    root = world["root"]
    for member in _members(world):
        policy = _policy(member)[0]
        pack = next(p for p in (root / ".agents" / "policies").rglob(policy) if (p / "manifest.yaml").is_file())
        verified = {
            path.relative_to(root).as_posix()
            for folder in (pack, root / ".chock" / "compiled" / policy)
            if folder.is_dir()
            for path in folder.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo")
        }
        assert set(member["files"]) == verified, member["argv"]
        assert member["argv"][1] in member["files"]
        assert all(_sha(root / rel) == digest for rel, digest in member["files"].items())
        assert member_files(root, member["argv"]) == member["files"]


def test_the_combined_answer_is_one_response_on_stdout(world: dict) -> None:
    """Members get no stdin and print nowhere: what the client reads is the one response, and nothing else."""
    root = world["root"]
    _matcher, rel, pin, _members_ = next(g for g in world["groups"] if len(g[3]) > 1)
    violating = VIOLATING[("block-destructive-commands", "--guard")][1]
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": violating, "cwd": str(root)}
    proc = subprocess.run(
        [sys.executable, str(root / RUNTIME), MULTI_FLAG, rel, "--index-sha256", pin],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=root,
        env=hook_env(root.parent),
        check=False,
    )
    assert len(json.loads(proc.stdout)) == 1
    assert proc.stdout.count("\n") <= 1


HANG = "import time\ntime.sleep(60)\n"
CRASH = "raise SystemExit(7)\n"
ASK = "import sys\nprint('please confirm')\nsys.exit(3)\n"
DENY = "import sys\nprint('blocked by deny')\nsys.exit(1)\n"
ALLOW = "import sys\nsys.exit(0)\n"


def _synthetic(tmp_path: Path, scripts: dict[str, str], seconds: dict[str, float]) -> tuple[Path, list[dict]]:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    write_runtime(root / RUNTIME, "claude_code")
    (root / INDEX_DIR).mkdir(parents=True)
    members = []
    for name, text in scripts.items():
        path = root / "guards" / f"{name}.py"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        rel = path.relative_to(root).as_posix()
        members.append({"argv": ["--guard", rel], "files": {rel: _sha(path)}, "timeout": seconds.get(name, 30)})
    return root, members


def test_a_hang_a_crash_and_an_ask_never_change_another_members_answer(tmp_path: Path) -> None:
    scripts = {"allow": ALLOW, "deny": DENY, "ask": ASK, "crash": CRASH, "hang": HANG}
    root, members = _synthetic(tmp_path, scripts, {"hang": 2})
    tool_input = {"command": "echo hello"}
    alone = {
        m["argv"][1]: _run(root, _multi_argv(root, [m], f"alone-{n}.json"), "Bash", tool_input)
        for n, m in enumerate(members)
    }
    assert [alone[f"guards/{name}.py"][1] for name in scripts] == ["allow", "deny", "ask", "ask", "deny"]
    together = _run(root, _multi_argv(root, members, "together.json"), "Bash", tool_input)
    assert together[1] == "deny"
    for name in ("deny", "hang"):  # a crashed guard asks, and a deny outranks an ask
        assert alone[f"guards/{name}.py"][2] in together[2], name
    # Without the denying members the ask still reaches the client: nothing else's fault changes it.
    quiet = _run(root, _multi_argv(root, [members[0], members[2]], "quiet.json"), "Bash", tool_input)
    assert quiet[1:] == alone["guards/ask.py"][1:]
