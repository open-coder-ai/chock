"""Review 4: abnormal paths (L3, L4, item 5). None may end as 0; SARIF and text must agree."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

from floor_support import base_repo, commit, git, run_floor, write
from floor_support4 import rebase_main

from chock.validation import checks_floor

W = Path(__file__).resolve().parents[1] / "floor-review"


def _obj(repo: Path, oid: str) -> Path:
    return repo / ".git/objects" / oid[:2] / oid[2:]


def _corrupt(repo: Path, oid: str, how: str) -> None:
    path = _obj(repo, oid)
    os.chmod(path, 0o644)
    raw = zlib.decompress(path.read_bytes())
    if how == "garbage":
        path.write_bytes(b"not zlib at all")
    elif how == "truncated":
        path.write_bytes(zlib.compress(raw)[:-6])
    elif how == "wrong-type":
        body = raw.split(b"\0", 1)[1]
        path.write_bytes(zlib.compress(b"tree %d\0" % len(body) + body))
    elif how == "wrong-size":
        body = raw.split(b"\0", 1)[1]
        path.write_bytes(zlib.compress(b"blob %d\0" % (len(body) + 50) + body))


def _script_only(tmp_path: Path) -> Path:
    repo = base_repo(tmp_path)

    def base(r):
        for policy in ("floor-token", "test-integrity"):
            shutil.rmtree(r / ".chock/compiled" / policy)

    rebase_main(repo, base)
    return repo


def test_corrupt_head_blob_every_way(tmp_path, capsys):
    for how in ("garbage", "truncated", "wrong-type"):  # wrong-size: git returns the true bytes (rc 0); not a finding
        for shape in ("content", "script"):
            repo = (base_repo if shape == "content" else _script_only)(tmp_path / f"{how}-{shape}")
            write(repo, "src/new.py", "print('x')\n")
            commit(repo, "pr")
            _corrupt(repo, git(repo, "rev-parse", "HEAD:src/new.py"), how)
            code, out = run_floor(repo, capsys)
            assert code == 2, (how, shape, out)


def test_corrupt_head_tree(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/new.py", "print('x')\n")
    commit(repo, "pr")
    _corrupt(repo, git(repo, "rev-parse", "HEAD:src"), "garbage")
    code, out = run_floor(repo, capsys)
    assert code == 2, out


def test_corrupt_base_config_blob(tmp_path, capsys):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: write(r, ".chock/config.yaml", "floor:\n  control_plane: listed\n"))
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    _corrupt(repo, git(repo, "rev-parse", "main:.chock/config.yaml"), "garbage")
    code, out = run_floor(repo, capsys)
    assert code == 2, out


def test_invalid_json_gate_at_base(tmp_path, capsys):
    repo = base_repo(tmp_path)
    rebase_main(repo, lambda r: write(r, ".chock/compiled/floor-token/ci-gate/gate.json", "{not json"))
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    code, out = run_floor(repo, capsys)
    assert code == 2, out


def test_git_missing_from_path(tmp_path):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    env = {"PATH": str(tmp_path / "empty"), "HOME": os.environ["HOME"], "PYTHONPATH": os.environ.get("PYTHONPATH", "")}
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from chock.validation.checks_floor import main; sys.exit(main(sys.argv[1:]))",
            "--repo",
            str(repo),
            "--base",
            "main",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_temp_dir_full(tmp_path, capsys, monkeypatch):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")

    def full(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", full)
    code, out = run_floor(repo, capsys)
    assert code == 2, out


def test_unusable_tmpdir_env(tmp_path):
    repo = base_repo(tmp_path)
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    commit(repo, "pr")
    bad = tmp_path / "ro"
    bad.mkdir()
    bad.chmod(0o500)
    env = {**os.environ, "TMPDIR": str(bad / "missing")}
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from chock.validation.checks_floor import main; sys.exit(main(sys.argv[1:]))",
            "--repo",
            str(repo),
            "--base",
            "main",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode in (1, 2), proc.stdout + proc.stderr


def test_sarif_unwritable_targets(tmp_path, capsys):
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    (tmp_path / "adir").mkdir()
    for target in (tmp_path / "missing/x.sarif", tmp_path / "adir"):
        code, out = run_floor(repo, capsys, "--sarif", str(target))
        assert code == 2, (target, out)


def test_sarif_agrees_with_exit_on_every_outcome(tmp_path, capsys):
    """refuse+listed -> error results; listed -> note results and exit 0; undecided -> executionSuccessful false."""
    repo = base_repo(tmp_path)
    write(repo, ".claude/settings.json", "{}\n")
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    commit(repo, "pr")
    sarif = tmp_path / "o.sarif"
    code, _ = run_floor(repo, capsys, "--sarif", str(sarif))
    doc = json.loads(sarif.read_text())
    levels = {r["level"] for r in doc["runs"][0]["results"]}
    assert code == 1 and levels == {"error"}, (code, levels)


def test_an_undecided_run_replaces_a_stale_sarif(tmp_path, capsys):
    """S6: the output path holds a clean SARIF (as a head checkout could); an undecided run overwrites it."""
    repo = base_repo(tmp_path)
    write(repo, "src/app.py", "VALUE = 2\n")
    commit(repo, "pr")
    sarif = tmp_path / "o.sarif"
    sarif.write_text(json.dumps({"version": "2.1.0", "runs": [{"results": []}]}))
    code = checks_floor.main(["--repo", str(repo), "--base", "no-such-ref", "--sarif", str(sarif)])
    capsys.readouterr()
    assert code == 2
    doc = json.loads(sarif.read_text())
    invocation = doc["runs"][0]["invocations"][0]
    assert invocation["executionSuccessful"] is False, doc
    assert "does not resolve" in invocation["toolExecutionNotifications"][0]["message"]["text"], doc


def test_repo_forms(tmp_path, capsys):
    repo = base_repo(tmp_path / "with space")
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    commit(repo, "pr")
    link = tmp_path / "link"
    os.symlink(repo, link)
    wt = tmp_path / "wt dir"
    git(repo, "worktree", "add", "-q", "--detach", str(wt), "pr")
    (repo / "src/deep/er").mkdir(parents=True)
    for form in (repo, link, link / "src", wt, wt / "tests", repo / "src/deep/er"):
        code = checks_floor.main(["--repo", str(form), "--base", "main", "--head", "pr"])
        out = capsys.readouterr()
        assert code == 1, (form, out.out + out.err)
    bare = tmp_path / "bare.git"
    git(repo, "clone", "-q", "--bare", str(repo), str(bare))
    code = checks_floor.main(["--repo", str(bare), "--base", "main", "--head", "pr"])
    out = capsys.readouterr()
    assert code in (1, 2), out.out + out.err


def test_ref_forms(tmp_path, capsys):
    repo = base_repo(tmp_path)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@e", "tag", "-a", "-m", "t", "v1", "main")
    git(repo, "tag", "light", "main")
    write(repo, "tests/test_core.py", "def test_a():\n    pass\n")
    commit(repo, "pr")
    short = git(repo, "rev-parse", "--short=7", "main")
    git(repo, "branch", "we/ird-n@me", "main")
    for base in ("v1", "light", short, "HEAD~1", "pr~1", "we/ird-n@me", "refs/heads/main", "main^{commit}"):
        code = checks_floor.main(["--repo", str(repo), "--base", base])
        out = capsys.readouterr()
        assert code == 1, (base, out.out + out.err)
    for base in ("--all", "-h", "main..pr", "main...pr", "", "@{-1}", ":/base"):
        try:
            code = checks_floor.main(["--repo", str(repo), f"--base={base}"])
        except SystemExit as exc:
            code = exc.code
        out = capsys.readouterr()
        assert code in (1, 2), (base, code, out.out + out.err)


def test_head_equal_to_base_is_clean(tmp_path, capsys):
    repo = base_repo(tmp_path)
    code = checks_floor.main(["--repo", str(repo), "--base", "main", "--head", "main"])
    out = capsys.readouterr()
    assert code == 0, out.out
