"""`chock check --history` fails closed: a scan that cannot decide exits 2, never 0."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from history_support import SECRET, commit, git, install_gates, make_repo

from chock.history import cli as history_cli
from chock.history import gitlog, scan
from chock.history.cli import check_main


def run(repo: Path, *args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    rc = check_main(["--history", "--repo", str(repo), *args])
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_not_a_git_repository_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "plain").mkdir()
    assert run(tmp_path / "plain", capsys=capsys)[0] == 2
    assert run(tmp_path / "nonexistent", capsys=capsys)[0] == 2


def test_git_missing_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.py": "x\n"})
    monkeypatch.setattr(gitlog, "_BASE", ("/nonexistent/git",))
    rc, _, err = run(repo, capsys=capsys)
    assert rc == 2 and "cannot run git" in err


def test_missing_blob_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.py": f'K = "{SECRET}"\n'})
    oid = git(repo, "rev-parse", "HEAD:a.py")
    (repo / ".git" / "objects" / oid[:2] / oid[2:]).unlink()
    rc, _, err = run(repo, capsys=capsys)
    assert rc == 2 and "missing" in err


def _shallow_clone(tmp_path: Path) -> Path:
    src = make_repo(tmp_path / "src")
    commit(src, {"a.py": "x = 1\n"})
    commit(src, {"b.py": "y = 2\n"})
    dest = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--depth", "1", src.as_uri(), str(dest))
    install_gates(dest)
    return dest


def test_shallow_clone_exits_2_unless_allowed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clone = _shallow_clone(tmp_path)
    rc, _, err = run(clone, capsys=capsys)
    assert rc == 2 and "shallow" in err
    rc, out, err = run(clone, "--allow-shallow", capsys=capsys)
    assert rc == 0 and "WARNING shallow" in err and "no findings" in out


def test_signature_check_and_gpg_program_in_repo_config_never_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.py": "x = 1\n"})
    marker = tmp_path / "gpg-ran"
    program = tmp_path / "evil-gpg.sh"
    program.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
    program.chmod(0o755)
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    sig = "gpgsig -----BEGIN PGP SIGNATURE-----\n \n abc\n -----END PGP SIGNATURE-----\n"
    raw = f"tree {tree}\nauthor t <t@e.com> 1700000000 +0000\ncommitter t <t@e.com> 1700000000 +0000\n{sig}\nsigned\n"
    signed = git(repo, "hash-object", "-t", "commit", "-w", "--stdin", stdin=raw)
    git(repo, "update-ref", "HEAD", signed)
    git(repo, "config", "log.showSignature", "true")
    git(repo, "config", "gpg.program", str(program))
    rc, _, _ = run(repo, capsys=capsys)
    assert rc == 0 and not marker.exists()
    git(repo, "log", "-1", "--show-signature")  # the repo config really does name the program
    assert marker.exists()


def _custom_gate(repo: Path, name: str, body: str) -> None:
    dest = repo / ".chock" / "compiled" / name / "git-hook"
    dest.mkdir(parents=True)
    (dest / "gate.json").write_text(body, encoding="utf-8")


def test_catastrophic_gate_pattern_times_out_naming_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path / "r", gates=())
    gate = {"kind": "content_regex", "on": ["commit"], "params": {"content_pattern": r"^(a+)+$"}}
    _custom_gate(repo, "redos-gate", json.dumps(gate))
    commit(repo, {"a.txt": "a" * 60 + "!\n"})
    monkeypatch.setattr(scan, "BLOB_SECONDS", 1)
    rc, _, err = run(repo, capsys=capsys)
    assert rc == 2 and "redos-gate" in err


def test_non_dict_gate_document_exits_2_naming_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    _custom_gate(repo, "odd-gate", "[]")
    commit(repo, {"a.py": "x\n"})
    rc, _, err = run(repo, capsys=capsys)
    assert rc == 2 and "odd-gate" in err


def test_unexpected_exception_exits_2_not_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"a.py": f'K = "{SECRET}"\n'})

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(SECRET)

    monkeypatch.setattr(history_cli, "scan", boom)
    rc, out, err = run(repo, capsys=capsys)
    assert rc == 2 and SECRET not in out + err and "RuntimeError" in err


def test_symlink_target_is_scanned_submodule_pointer_is_not(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    os.symlink(SECRET, repo / "link")
    git(repo, "add", "link")
    git(repo, "update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},sub")
    commit(repo, {"a.py": "x\n"})
    rc, out, err = run(repo, "--json", capsys=capsys)
    doc = json.loads(out)
    assert rc == 1 and [f["path"] for f in doc["findings"]] == ["link"]
    assert doc["skipped_submodules"] == 1 and "1 submodule" in err


def test_non_utf8_path_is_judged_on_its_raw_form(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    name = os.fsdecode(b"x\xffprod.env")
    commit(repo, {name: "A=1\n"})
    rc, out, _ = run(repo, "--json", capsys=capsys)
    assert rc == 1 and [f["rule"] for f in json.loads(out)["findings"]] == ["forbidden-path"]
    rc, out, _ = run(repo, capsys=capsys)
    assert rc == 1 and "?" in out


def test_skip_counts_are_noted_on_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path / "r")
    commit(repo, {"blob.bin": b"\0\0abc"})
    rc, _, err = run(repo, capsys=capsys)
    assert rc == 0 and "skipped 1 binary" in err


def test_check_help_mentions_history(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        check_main(["-h"])
    assert "--history" in capsys.readouterr().out
