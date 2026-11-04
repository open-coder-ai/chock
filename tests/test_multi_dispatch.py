"""One hook process, many policies: the rendered runtime run with `--multi` denies what any member denies."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from decision_log_support import hook_env
from runtime_support import write_runtime

from chock.gatelog_chain import verify

WORDS = ("alpha", "bravo", "charlie", "delta")
GUARD = "import sys\nif {word!r} in sys.argv[1:]:\n    print('blocked by {word}')\n    sys.exit(1)\n"
LOG = ("log", "gate-events.jsonl")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo(tmp_path: Path, words: tuple[str, ...]) -> tuple[Path, str]:
    """A repository with one guard per word and the hook command that runs them all in one process."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    write_runtime(repo / ".chock" / "bin" / "claude_code.py", "claude_code")
    members = []
    for word in words:
        guard = repo / "guards" / f"{word}.py"
        guard.parent.mkdir(exist_ok=True)
        guard.write_text(GUARD.format(word=word), encoding="utf-8")
        members.append(
            {"argv": ["--guard", f"guards/{word}.py"], "timeout": 30, "files": {f"guards/{word}.py": _sha(guard)}}
        )
    index = repo / "index.json"
    index.write_text(json.dumps({"members": members}), encoding="utf-8")
    return repo, f"{sys.executable} .chock/bin/claude_code.py --multi index.json --index-sha256 {_sha(index)}"


def _run(repo: Path, command: str, bash_command: str) -> subprocess.CompletedProcess:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": bash_command}}
    payload.update(cwd=str(repo), session_id="s", tool_use_id="t")
    env = hook_env(repo.parent)
    return subprocess.run(
        command.split(), cwd=repo, env=env, input=json.dumps(payload), capture_output=True, text=True, check=False
    )


def _denied(proc: subprocess.CompletedProcess) -> bool:
    return proc.returncode == 2 or '"permissionDecision": "deny"' in proc.stdout


def _lines(repo: Path) -> list[dict]:
    log = repo.joinpath(".chock", *LOG)
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def test_a_clean_call_is_allowed_through_every_member(tmp_path: Path) -> None:
    repo, command = _repo(tmp_path, WORDS)
    proc = _run(repo, command, "echo hello")
    assert proc.returncode == 0, proc.stderr
    assert not _denied(proc)


@pytest.mark.parametrize("word", WORDS)
def test_a_violating_payload_is_denied_through_one_member(tmp_path: Path, word: str) -> None:
    """The member that objects is any one of the index: the empty stdin it was run with never turns into an allow."""
    repo, command = _repo(tmp_path, WORDS)
    proc = _run(repo, command, f"echo {word}")
    assert _denied(proc), (proc.returncode, proc.stdout, proc.stderr)
    assert f"blocked by {word}" in proc.stdout + proc.stderr


def test_a_violating_payload_is_denied_with_a_single_member_index(tmp_path: Path) -> None:
    repo, command = _repo(tmp_path, ("alpha",))
    proc = _run(repo, command, "echo alpha")
    assert _denied(proc), (proc.returncode, proc.stdout, proc.stderr)
    assert not _denied(_run(repo, command, "echo other"))


def test_every_member_denies_and_the_reasons_are_all_named_in_index_order(tmp_path: Path) -> None:
    repo, command = _repo(tmp_path, WORDS)
    proc = _run(repo, command, "echo " + " ".join(WORDS))
    assert _denied(proc), (proc.returncode, proc.stdout, proc.stderr)
    said = proc.stdout + proc.stderr
    assert [said.index(f"blocked by {word}") for word in WORDS] == sorted(
        said.index(f"blocked by {word}") for word in WORDS
    )


def test_all_members_deny_fifty_times_and_the_decision_log_chain_verifies(tmp_path: Path) -> None:
    repo, command = _repo(tmp_path, WORDS)
    for _ in range(50):
        proc = _run(repo, command, "echo " + " ".join(WORDS))
        assert _denied(proc), (proc.returncode, proc.stdout, proc.stderr)
    lines = _lines(repo)
    blocked = [line["policy_id"] for line in lines if line["verdict"] == "block"]
    assert blocked == list(WORDS) * 50
    chain = verify("claude_code", [repo.joinpath(".chock", *LOG)])
    assert chain.breaks is None
    assert chain.records == len(lines)


def test_an_index_that_does_not_match_its_pin_refuses(tmp_path: Path) -> None:
    repo, command = _repo(tmp_path, WORDS)
    repo.joinpath("index.json").write_text('{"members": []}', encoding="utf-8")
    proc = _run(repo, command, "echo hello")
    assert _denied(proc), (proc.returncode, proc.stdout, proc.stderr)


def test_a_member_file_that_drifted_refuses_the_call(tmp_path: Path) -> None:
    repo, command = _repo(tmp_path, WORDS)
    repo.joinpath("guards", "alpha.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    proc = _run(repo, command, "echo hello")
    assert _denied(proc), (proc.returncode, proc.stdout, proc.stderr)
