"""Gate outcome logging: the local evidence trail for gates that actually evaluated.

The point of the log is answering "has this gate ever fired, and does it fire wrongly" --
so the allow case matters as much as the block case, and a gate that never fires is itself
the finding. Two properties here are load-bearing rather than cosmetic: logging must never
change a verdict, and no scanned content may reach the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import init_repo, stage

from chock.gate import runner as gate_runner
from chock.gate.runner import GATE_LOG_ENV, run


@pytest.fixture(autouse=True)
def enable_gate_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt back in to the logging the suite-wide `no_gate_log` fixture switches off."""
    monkeypatch.delenv(GATE_LOG_ENV, raising=False)


# The canonical AWS documentation example key, and the fixture the secret tests below scan
# for. Pragma'd because scan-secrets is installed on this repo and correctly blocks the
# literal -- which is how this file first proved the log records a real block.
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret

SECRET_SPEC = {
    "kind": "content_regex",
    "on": ["commit"],
    "action": "block",
    "message": "secret",
    "params": {
        "scan": "added_lines",
        "content_pattern": r"(?i)(AKIA[0-9A-Z]{16})",
        "allowlist_pragma": r"#\s*pragma:\s*allowlist\s+secret",
    },
}


def compiled_gate(repo: Path, policy_id: str, spec: dict, surface: str = "git-hook") -> Path:
    """A gate.json at the compiled path shape, which is what the runner logs against."""
    gate = repo / ".chock" / "compiled" / policy_id / surface / "gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(json.dumps(spec), encoding="utf-8")
    return gate


def log_path(repo: Path) -> Path:
    return repo / ".chock" / "log" / "gate-events.jsonl"


def read_log(repo: Path) -> list[dict]:
    path = log_path(repo)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_block_is_recorded(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "app.py", f'KEY = "{AWS_KEY}"\n')
    gate = compiled_gate(tmp_path, "scan-secrets", SECRET_SPEC)

    assert run(gate, "pre-commit", None, tmp_path) == 1

    records = read_log(tmp_path)
    assert len(records) == 1
    record = records[0]
    assert record["policy_id"] == "scan-secrets"
    assert record["surface"] == "git-hook"
    assert record["event"] == "commit"
    assert record["kind"] == "content_regex"
    assert record["verdict"] == "block"
    assert record["match_count"] == 1
    assert record["matches"] == ["app.py: content pattern"]
    assert record["ts"].endswith("Z")


def test_allow_is_recorded(tmp_path: Path) -> None:
    """A gate that passes still produces evidence -- otherwise 'never fired' is unprovable."""
    init_repo(tmp_path)
    stage(tmp_path, "app.py", "x = 1\n")
    gate = compiled_gate(tmp_path, "scan-secrets", SECRET_SPEC)

    assert run(gate, "pre-commit", None, tmp_path) == 0

    records = read_log(tmp_path)
    assert len(records) == 1
    assert records[0]["verdict"] == "allow"
    assert records[0]["match_count"] == 0
    assert records[0]["matches"] == []


def test_runs_append_rather_than_overwrite(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "app.py", "x = 1\n")
    gate = compiled_gate(tmp_path, "scan-secrets", SECRET_SPEC)

    run(gate, "pre-commit", None, tmp_path)
    run(gate, "pre-commit", None, tmp_path)

    assert len(read_log(tmp_path)) == 2


def test_env_switch_disables_logging(tmp_path: Path, monkeypatch) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "app.py", f'KEY = "{AWS_KEY}"\n')
    gate = compiled_gate(tmp_path, "scan-secrets", SECRET_SPEC)
    monkeypatch.setenv(GATE_LOG_ENV, "0")

    assert run(gate, "pre-commit", None, tmp_path) == 1
    assert not log_path(tmp_path).exists()


def test_uncovered_event_is_not_recorded(tmp_path: Path) -> None:
    """'This gate did not apply' is not an outcome, and logging it would bury the signal."""
    init_repo(tmp_path)
    stage(tmp_path, "app.py", f'KEY = "{AWS_KEY}"\n')
    gate = compiled_gate(tmp_path, "scan-secrets", SECRET_SPEC)

    assert run(gate, "pre-push", "", tmp_path) == 0
    assert not log_path(tmp_path).exists()


def test_missing_gate_is_not_recorded(tmp_path: Path) -> None:
    init_repo(tmp_path)
    absent = tmp_path / ".chock" / "compiled" / "scan-secrets" / "git-hook" / "gate.json"

    assert run(absent, "pre-commit", None, tmp_path) == 0
    assert not log_path(tmp_path).exists()


def test_uncompiled_gate_path_is_not_recorded(tmp_path: Path) -> None:
    """An eval replaying a spec from a temp file is not an enforcement event."""
    init_repo(tmp_path)
    stage(tmp_path, "app.py", f'KEY = "{AWS_KEY}"\n')
    gate = tmp_path / "gate.json"
    gate.write_text(json.dumps(SECRET_SPEC), encoding="utf-8")

    assert run(gate, "pre-commit", None, tmp_path) == 1
    assert not log_path(tmp_path).exists()


def test_secret_value_never_reaches_the_log(tmp_path: Path) -> None:
    """The invariant the whole design rests on: `matches` carries locations, never content.

    If a kind ever starts reporting the text it matched, this log becomes the plaintext
    credential store that scan-secrets exists to prevent.
    """
    init_repo(tmp_path)
    stage(tmp_path, "app.py", f'KEY = "{AWS_KEY}"\n')
    gate = compiled_gate(tmp_path, "scan-secrets", SECRET_SPEC)

    run(gate, "pre-commit", None, tmp_path)

    assert AWS_KEY not in log_path(tmp_path).read_text(encoding="utf-8")


def test_logging_failure_does_not_change_the_verdict(tmp_path: Path, monkeypatch) -> None:
    """Telemetry that can block a commit is worse than no telemetry."""
    init_repo(tmp_path)
    stage(tmp_path, "app.py", f'KEY = "{AWS_KEY}"\n')
    gate = compiled_gate(tmp_path, "scan-secrets", SECRET_SPEC)

    class Exploding:
        @staticmethod
        def now(*args, **kwargs):
            raise OSError("log device on fire")

    monkeypatch.setattr(gate_runner, "datetime", Exploding)

    assert run(gate, "pre-commit", None, tmp_path) == 1
    assert read_log(tmp_path) == []


def test_oversized_log_rotates_once(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "app.py", "x = 1\n")
    gate = compiled_gate(tmp_path, "scan-secrets", SECRET_SPEC)
    path = log_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * (gate_runner._LOG_MAX_BYTES + 1), encoding="utf-8")

    run(gate, "pre-commit", None, tmp_path)

    assert (path.parent / "gate-events.1.jsonl").exists()
    assert len(read_log(tmp_path)) == 1


def test_match_list_is_capped_but_count_is_not(tmp_path: Path) -> None:
    """A truncated sample must never understate how many times the gate hit."""
    init_repo(tmp_path)
    total = gate_runner._LOG_MATCH_CAP + 5
    for i in range(total):
        stage(tmp_path, f"f{i}.py", f'KEY = "{AWS_KEY}"\n')
    gate = compiled_gate(tmp_path, "scan-secrets", SECRET_SPEC)

    run(gate, "pre-commit", None, tmp_path)

    record = read_log(tmp_path)[0]
    assert record["match_count"] == total
    assert len(record["matches"]) == gate_runner._LOG_MATCH_CAP
