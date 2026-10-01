"""`chock check --history`: both directions, bounds, read-only, refusal of bad refs."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from history_support import BIDI, SECRET, commit, git, make_repo

from chock.history.cli import check_main


def run(repo: Path, *args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    rc = check_main(["--history", "--repo", str(repo), *args])
    out = capsys.readouterr()
    return rc, out.out, out.err


def findings(repo: Path, *args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    rc, out, _ = run(repo, "--json", *args, capsys=capsys)
    return rc, json.loads(out)


def test_secret_in_old_commit_then_removed_is_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"README.md": "hello\n"})
    bad = commit(repo, {"cfg.py": f'x = 1\nKEY = "{SECRET}"\n'}, "add key")
    commit(repo, {}, "drop key", removed=("cfg.py",))
    commit(repo, {"README.md": "hello again\n"})
    rc, doc = findings(repo, capsys=capsys)
    assert rc == 1
    assert [(f["commit"], f["path"], f["line"], f["policy"], f["rule"]) for f in doc["findings"]] == [
        (bad, "cfg.py", 2, "scan-secrets", "content-pattern")
    ]


def test_text_output_never_prints_the_secret(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    sha = commit(repo, {"cfg.py": f'KEY = "{SECRET}"\n'})
    rc, out, err = run(repo, capsys=capsys)
    assert rc == 1
    assert sha[:12] in out and "cfg.py:1" in out and "scan-secrets" in out
    assert SECRET not in out + err and SECRET[:8] not in out + err
    rc, out, err = run(repo, "--json", capsys=capsys)
    assert SECRET not in out + err


def test_invisible_unicode_and_forbidden_path_are_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.py": f"x = 1  # {BIDI}\n", "prod.env": "A=1\n"})
    _, doc = findings(repo, capsys=capsys)
    got = {(f["path"], f["policy"], f["rule"]) for f in doc["findings"]}
    assert got == {
        ("a.py", "block-invisible-unicode", "content-pattern"),
        ("prod.env", "scan-secrets", "forbidden-path"),
    }


def test_clean_history_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.py": "x = 1\n"})
    commit(repo, {"b.py": "y = 2\n"})
    rc, out, _ = run(repo, capsys=capsys)
    assert rc == 0 and "no findings" in out


def test_report_only_exits_zero_but_still_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"cfg.py": f'KEY = "{SECRET}"\n'})
    rc, doc = findings(repo, "--report-only", capsys=capsys)
    assert rc == 0 and len(doc["findings"]) == 1


def test_persisting_secret_reported_once_where_it_entered(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    first = commit(repo, {"cfg.py": f'KEY = "{SECRET}"\n'})
    commit(repo, {"cfg.py": f'KEY = "{SECRET}"\nmore = 1\n'})
    commit(repo, {"cfg.py": f'KEY = "{SECRET}"\nmore = 2\n'})
    _, doc = findings(repo, capsys=capsys)
    assert [f["commit"] for f in doc["findings"]] == [first]


def test_binary_and_oversize_blobs_are_skipped(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"blob.bin": b"\0\0" + SECRET.encode(), "big.txt": SECRET + "\n" + "x" * 5000})
    rc, doc = findings(repo, "--max-blob-bytes", "1000", capsys=capsys)
    assert rc == 0 and doc["findings"] == []
    assert doc["skipped_binary"] == 1 and doc["skipped_oversize"] == 1
    rc, doc = findings(repo, capsys=capsys)
    assert rc == 1 and [f["path"] for f in doc["findings"]] == ["big.txt"]


def test_identical_blobs_read_once_but_every_path_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.py": f'K = "{SECRET}"\n', "b.py": f'K = "{SECRET}"\n'})
    _, doc = findings(repo, capsys=capsys)
    assert doc["blobs_scanned"] == 1
    assert [f["path"] for f in doc["findings"]] == ["a.py", "b.py"]


@pytest.mark.parametrize("ref", ["--output=/x", "-p", "--all", ""])
def test_option_like_ref_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str], ref: str) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.py": "x\n"})
    rc, _, err = run(repo, f"--since={ref}", capsys=capsys)
    assert rc == 2 and "refusing ref" in err
    assert not (tmp_path / "r" / "x").exists()


def test_unknown_ref_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.py": "x\n"})
    rc, _, err = run(repo, "--since=no-such-ref", capsys=capsys)
    assert rc == 2 and "does not name a commit" in err


def test_since_and_max_commits_bound_the_scan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"old.py": f'K = "{SECRET}"\n'})
    mid = commit(repo, {"mid.py": "x = 1\n"})
    new = commit(repo, {"new.py": f'K = "{SECRET}"\n'})
    _, doc = findings(repo, "--since", mid, capsys=capsys)
    assert [f["commit"] for f in doc["findings"]] == [new] and doc["commits_scanned"] == 1
    _, doc = findings(repo, "--max-commits", "2", capsys=capsys)
    assert [f["commit"] for f in doc["findings"]] == [new] and doc["truncated"] is True


def test_waiver_pragma_on_the_line_is_honoured(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"t.py": f'K = "{SECRET}"  # pragma: allowlist secret\n'})
    rc, _ = findings(repo, capsys=capsys)
    assert rc == 0


def test_read_only_never_touches_worktree_head_or_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"cfg.py": f'K = "{SECRET}"\n'})
    marker = tmp_path / "hook-ran"
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)
    commit(repo, {}, "drop", removed=("cfg.py",))
    before = (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain"), git(repo, "reflog"))
    run(repo, capsys=capsys)
    assert before == (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain"), git(repo, "reflog"))
    assert not marker.exists() and not (repo / "cfg.py").exists()


def test_no_installed_gates_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r", gates=())
    commit(repo, {"a.py": "x\n"})
    rc, _, err = run(repo, capsys=capsys)
    assert rc == 2 and "chock sync" in err


def test_empty_repository_is_not_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    rc, _, err = run(repo, capsys=capsys)
    assert rc == 0 and "no commits" in err


def _fast_import_stream(count: int) -> str:
    """`count` commits touching 40 rotating files, then one that adds a secret."""

    def entry(when: int, path: str, body: str) -> str:
        return (
            f"commit refs/heads/main\ncommitter t <t@example.com> {when} +0000\ndata 1\nc\n"
            f"M 100644 inline {path}\ndata {len(body.encode())}\n{body}\n"
        )

    parts = [entry(1_700_000_000 + i, f"f{i % 40}.py", f"v = {i}\n") for i in range(count)]
    parts.append(entry(1_800_000_000, "k.py", f'KEY = "{SECRET}"\n'))
    return "".join(parts)


def test_few_hundred_commits_scan_quickly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    git(repo, "fast-import", "--quiet", stdin=_fast_import_stream(400))
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    started = time.monotonic()
    rc, doc = findings(repo, capsys=capsys)
    assert time.monotonic() - started < 30
    assert rc == 1 and doc["commits_scanned"] == 401 and [f["path"] for f in doc["findings"]] == ["k.py"]
