"""Executable table tests for the default Chock git policy hooks."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import baseline_policy, build_test_gate_json

SKIP_REASON = "bash not available on this platform"


def _git_bin_dirs() -> list[Path]:
    """Return candidate Git for Windows bin directories for PATH augmentation."""
    git_exe = shutil.which("git")
    if not git_exe:
        return []
    base = Path(git_exe).parent.parent
    return [
        base / "usr" / "bin",
        base / "bin",
        base / "mingw64" / "bin",
    ]


def _find_bash() -> str | None:
    """Return a usable bash path."""
    for candidate_dir in _git_bin_dirs():
        candidate = candidate_dir / "bash.exe"
        if candidate.exists():
            return str(candidate)
    return shutil.which("bash")


def _framework_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run(cmd: list[str], cwd: Path, *, input_text: str = "", check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(subprocess.os.environ)
    if sys.platform == "win32":
        extra = ";".join(str(d) for d in _git_bin_dirs() if d.exists())
        if extra:
            env["PATH"] = f"{extra};{env.get('PATH', '')}"
    env["PYTHONPATH"] = str(_framework_root() / "src")
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
        env=env,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "consumer"
    repo.mkdir()
    _run(["git", "init", "--quiet"], repo)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Test User"], repo)
    (repo / "initial.txt").write_text("initial\n")
    _run(["git", "add", "initial.txt"], repo)
    _run(["git", "commit", "-m", "initial", "--quiet"], repo)
    return repo


def _policy_dir(name: str) -> Path:
    return baseline_policy(name)


def _gate_cmd(name: str, event: str, tmp_path: Path) -> list[str]:
    """Return a command that runs the vendored runner against the source gate."""
    gate_json = build_test_gate_json(tmp_path, _policy_dir(name))
    return [sys.executable, "-m", "chock.gate.runner", "run", "--gate", str(gate_json), "--event", event]


@pytest.mark.skipif(not _find_bash(), reason=SKIP_REASON)
def test_protect_main_branch_pre_commit_blocks_commit_on_main(tmp_path: Path) -> None:
    """pre-commit rejects commits when the current branch is main."""
    repo = _init_repo(tmp_path)

    _run(["git", "checkout", "-b", "main"], repo)
    (repo / "file.txt").write_text("x")
    _run(["git", "add", "file.txt"], repo)

    result = _run(_gate_cmd("protect-main-branch", "pre-commit", tmp_path), repo, check=False)
    assert result.returncode == 1
    assert "main" in result.stderr


@pytest.mark.skipif(not _find_bash(), reason=SKIP_REASON)
def test_protect_main_branch_pre_commit_allows_feature_branch(tmp_path: Path) -> None:
    """pre-commit allows commits on feature branches."""
    repo = _init_repo(tmp_path)

    _run(["git", "checkout", "-b", "feature/main-menu"], repo)
    (repo / "file.txt").write_text("x")
    _run(["git", "add", "file.txt"], repo)

    result = _run(_gate_cmd("protect-main-branch", "pre-commit", tmp_path), repo)
    assert result.returncode == 0


@pytest.mark.skipif(not _find_bash(), reason=SKIP_REASON)
def test_protect_main_branch_pre_push_blocks_main_ref(tmp_path: Path) -> None:
    """pre-push rejects pushes of refs/heads/main."""
    repo = _init_repo(tmp_path)

    stdin = "refs/heads/main abc123 refs/heads/main def456\n"
    result = _run(_gate_cmd("protect-main-branch", "pre-push", tmp_path), repo, input_text=stdin, check=False)
    assert result.returncode == 1
    assert "refs/heads/main" in result.stderr


@pytest.mark.skipif(not _find_bash(), reason=SKIP_REASON)
def test_protect_main_branch_pre_push_allows_feature_main_substring(tmp_path: Path) -> None:
    """pre-push allows feature/main-menu because the remote ref is not main/master."""
    repo = _init_repo(tmp_path)

    stdin = "refs/heads/feature/main-menu abc123 refs/heads/feature/main-menu def456\n"
    result = _run(_gate_cmd("protect-main-branch", "pre-push", tmp_path), repo, input_text=stdin)
    assert result.returncode == 0


@pytest.mark.skipif(not _find_bash(), reason=SKIP_REASON)
def test_scan_secrets_blocks_aws_key(tmp_path: Path) -> None:
    """scan-secrets blocks commits containing an AWS access key ID."""
    repo = _init_repo(tmp_path)

    (repo / "config.py").write_text("AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n")
    _run(["git", "add", "config.py"], repo)

    result = _run(_gate_cmd("scan-secrets", "pre-commit", tmp_path), repo, check=False)
    assert result.returncode == 1
    assert "secret" in result.stderr.lower()


@pytest.mark.skipif(not _find_bash(), reason=SKIP_REASON)
def test_scan_secrets_blocks_env_file(tmp_path: Path) -> None:
    """scan-secrets blocks commits adding a .env file."""
    repo = _init_repo(tmp_path)

    (repo / ".env").write_text("DATABASE_URL=x\n")
    _run(["git", "add", ".env"], repo)

    result = _run(_gate_cmd("scan-secrets", "pre-commit", tmp_path), repo, check=False)
    assert result.returncode == 1
    assert ".env: forbidden path" in result.stderr


@pytest.mark.skipif(not _find_bash(), reason=SKIP_REASON)
def test_scan_secrets_allows_benign_password_word(tmp_path: Path) -> None:
    """scan-secrets allows comments that contain the word 'password' without a secret value."""
    repo = _init_repo(tmp_path)

    (repo / "readme.md").write_text("# Ask the user for their password\n")
    _run(["git", "add", "readme.md"], repo)

    result = _run(_gate_cmd("scan-secrets", "pre-commit", tmp_path), repo)
    assert result.returncode == 0


@pytest.mark.skipif(not _find_bash(), reason=SKIP_REASON)
def test_scan_secrets_respects_allowlist(tmp_path: Path) -> None:
    """scan-secrets allows test fixtures annotated with the allowlist pragma."""
    repo = _init_repo(tmp_path)

    (repo / "test_fixture.py").write_text("TEST_KEY = 'AKIAIOSFODNN7EXAMPLE'  # pragma: allowlist secret\n")
    _run(["git", "add", "test_fixture.py"], repo)

    result = _run(_gate_cmd("scan-secrets", "pre-commit", tmp_path), repo)
    assert result.returncode == 0
