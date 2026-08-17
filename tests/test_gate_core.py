"""Core gate runner tests for the three v2 kinds."""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import init_repo, stage, write_gate

from chock.gate.runner import run

SECRET_PARAMS = {
    "scan": "added_lines",
    "forbidden_path_regex": r"\.(env|pem|key)$",
    "allowlist_pragma": r"#\s*pragma:\s*allowlist\s+secret",
    "content_pattern": r"(?i)(AKIA[0-9A-Z]{16})",
}


def _secret_gate(tmp_path: Path) -> Path:
    return write_gate(
        tmp_path,
        {
            "kind": "content_regex",
            "on": ["commit"],
            "action": "block",
            "message": "secret",
            "params": SECRET_PARAMS,
        },
    )


def test_blocks_aws_key(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "app.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    assert run(_secret_gate(tmp_path), "pre-commit", None, tmp_path) == 1


def test_allows_clean_file(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "app.py", "x = 1\n")
    assert run(_secret_gate(tmp_path), "pre-commit", None, tmp_path) == 0


def test_pragma_exempts_line(tmp_path: Path) -> None:
    init_repo(tmp_path)
    stage(tmp_path, "t.py", 'KEY = "AKIAIOSFODNN7EXAMPLE"  # pragma: allowlist secret\n')
    assert run(_secret_gate(tmp_path), "pre-commit", None, tmp_path) == 0


def test_forbidden_path_blocked(tmp_path: Path) -> None:
    init_repo(tmp_path)
    gate = write_gate(
        tmp_path,
        {
            "kind": "content_regex",
            "on": ["commit"],
            "action": "block",
            "message": "forbidden",
            "params": {
                "scan": "added_lines",
                "content_pattern": "NEVER_MATCH",
                "forbidden_path_regex": r"\.env$",
                "allowlist_pragma": r"#\s*pragma:\s*allowlist\s+secret",
            },
        },
    )
    stage(tmp_path, ".env", "x=1\n")
    assert run(gate, "pre-commit", None, tmp_path) == 1


def test_forbidden_path_allowed_when_pragma_in_blob(tmp_path: Path) -> None:
    init_repo(tmp_path)
    gate = write_gate(
        tmp_path,
        {
            "kind": "content_regex",
            "on": ["commit"],
            "action": "block",
            "message": "forbidden",
            "params": {
                "scan": "added_lines",
                "content_pattern": "NEVER_MATCH",
                "forbidden_path_regex": r"\.env$",
                "allowlist_pragma": r"#\s*pragma:\s*allowlist\s+secret",
            },
        },
    )
    stage(tmp_path, ".env", "# pragma: allowlist secret\nx=1\n")
    assert run(gate, "pre-commit", None, tmp_path) == 0


def test_forbidden_ref_commit_blocks_main(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    gate = write_gate(
        tmp_path,
        {
            "kind": "forbidden_ref",
            "on": ["commit"],
            "action": "block",
            "message": "no",
            "params": {"refs": ["main", "master"]},
        },
    )
    subprocess.run(["git", "checkout", "-b", "main"], cwd=repo, check=True)
    stage(repo, "a.txt", "ok\n")
    assert run(gate, "pre-commit", None, repo) == 1


def test_forbidden_ref_commit_allows_feature(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    gate = write_gate(
        tmp_path,
        {
            "kind": "forbidden_ref",
            "on": ["commit"],
            "action": "block",
            "message": "no",
            "params": {"refs": ["main", "master"]},
        },
    )
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
    stage(repo, "a.txt", "ok\n")
    assert run(gate, "pre-commit", None, repo) == 0


def test_forbidden_ref_push_blocks_main(tmp_path: Path) -> None:
    gate = write_gate(
        tmp_path,
        {
            "kind": "forbidden_ref",
            "on": ["push"],
            "action": "block",
            "message": "no",
            "params": {"refs": ["main", "master"]},
        },
    )
    stdin = "refs/heads/main abc refs/heads/main def\n"
    assert run(gate, "pre-push", stdin, tmp_path) == 1


def test_forbidden_ref_push_allows_feature(tmp_path: Path) -> None:
    gate = write_gate(
        tmp_path,
        {
            "kind": "forbidden_ref",
            "on": ["push"],
            "action": "block",
            "message": "no",
            "params": {"refs": ["main", "master"]},
        },
    )
    stdin = "refs/heads/feature abc refs/heads/feature def\n"
    assert run(gate, "pre-push", stdin, tmp_path) == 0


def test_forbidden_ref_detached_head_allows(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    gate = write_gate(
        tmp_path,
        {
            "kind": "forbidden_ref",
            "on": ["commit"],
            "action": "block",
            "message": "no",
            "params": {"refs": ["main", "master"]},
        },
    )
    subprocess.run(["git", "checkout", "-b", "tmp"], cwd=repo, check=True)
    stage(repo, "a.txt", "ok\n")
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(["git", "checkout", sha], cwd=repo, check=True)
    stage(repo, "b.txt", "ok\n")
    assert run(gate, "pre-commit", None, repo) == 0


def test_dependency_allowlist_blocks_unknown(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "allow.txt").write_text("requests\n", encoding="utf-8")
    gate = write_gate(
        tmp_path,
        {
            "kind": "dependency_allowlist",
            "on": ["commit"],
            "action": "block",
            "message": "dep",
            "params": {"manifests": ["requirements.txt"], "allowlist_file": "allow.txt"},
        },
    )
    stage(repo, "requirements.txt", "numpy\n")
    assert run(gate, "pre-commit", None, repo) == 1


def test_dependency_allowlist_allows_known(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "allow.txt").write_text("requests\n", encoding="utf-8")
    gate = write_gate(
        tmp_path,
        {
            "kind": "dependency_allowlist",
            "on": ["commit"],
            "action": "block",
            "message": "dep",
            "params": {"manifests": ["requirements.txt"], "allowlist_file": "allow.txt"},
        },
    )
    stage(repo, "requirements.txt", "requests\n")
    assert run(gate, "pre-commit", None, repo) == 0


def test_dependency_allowlist_no_crash_on_unparseable(tmp_path: Path) -> None:
    repo = init_repo(tmp_path)
    (repo / "allow.txt").write_text("requests\n", encoding="utf-8")
    gate = write_gate(
        tmp_path,
        {
            "kind": "dependency_allowlist",
            "on": ["commit"],
            "action": "block",
            "message": "dep",
            "params": {"manifests": ["requirements.txt"], "allowlist_file": "allow.txt"},
        },
    )
    stage(repo, "requirements.txt", "%%%\n")
    assert run(gate, "pre-commit", None, repo) == 0


def test_run_missing_gate(tmp_path: Path) -> None:
    missing = tmp_path / "no.json"
    assert run(missing, "pre-commit", None, tmp_path) == 0


def test_run_event_not_covered(tmp_path: Path) -> None:
    gate = write_gate(
        tmp_path,
        {
            "kind": "content_regex",
            "on": ["push"],
            "action": "block",
            "message": "",
            "params": {"content_pattern": "x"},
        },
    )
    assert run(gate, "pre-commit", None, tmp_path) == 0


def test_run_unknown_kind(tmp_path: Path) -> None:
    gate = write_gate(
        tmp_path,
        {
            "kind": "nope",
            "on": ["commit"],
            "action": "block",
            "message": "",
            "params": {},
        },
    )
    assert run(gate, "pre-commit", None, tmp_path) == 2
