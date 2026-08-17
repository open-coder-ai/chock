"""Table-driven executable tests for all default guard implementations."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest
from conftest import baseline_policy, build_test_gate_json


def _framework_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git_bin_dirs() -> list[Path]:
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
    for candidate_dir in _git_bin_dirs():
        candidate = candidate_dir / "bash.exe"
        if candidate.exists():
            return str(candidate)
    return shutil.which("bash")


def _find_powershell() -> str | None:
    for name in ("pwsh", "powershell", "powershell.exe"):
        if (path := shutil.which(name)) is not None:
            return path
    return None


def _run(cmd: list[str], cwd: Path, *, input_text: str = "") -> subprocess.CompletedProcess[str]:
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
        check=False,
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


def _policy_impl(name: str, event_or_script: str, ext: str) -> Path:
    return baseline_policy(name) / "implementations" / f"{event_or_script}.{ext}"


def _run_guard(
    repo_or_cwd: Path,
    script: Path,
    ext: str,
    args: list[str],
    input_text: str = "",
) -> subprocess.CompletedProcess[str]:
    if not script.exists():
        policy_dir = script.parents[1]
        event = script.stem.replace("git-", "")
        gate_json = build_test_gate_json(repo_or_cwd, policy_dir)
        cmd = [
            sys.executable,
            "-m",
            "chock.gate.runner",
            "run",
            "--gate",
            str(gate_json),
            "--event",
            event,
            *args,
        ]
        return _run(cmd, repo_or_cwd, input_text=input_text)

    if ext == "sh":
        interpreter = _find_bash()
        assert interpreter is not None, "No bash on this platform"
        cmd = [interpreter, str(script), *args]
    else:
        interpreter = _find_powershell()
        assert interpreter is not None, "No PowerShell on this platform"
        cmd = [interpreter, "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    return _run(cmd, repo_or_cwd, input_text=input_text)


Case = tuple[str, str, str, list[str], str, int]


def _protect_cases() -> list[Case]:
    return [
        ("protect-main-branch", "git-pre-commit", "sh", [], "main", 1),
        ("protect-main-branch", "git-pre-commit", "sh", [], "feature/x", 0),
        ("protect-main-branch", "git-pre-push", "sh", [], "refs/heads/main abc123 refs/heads/main def456\n", 1),
        (
            "protect-main-branch",
            "git-pre-push",
            "sh",
            [],
            "refs/heads/feature/main-menu abc123 refs/heads/feature/main-menu def456\n",
            0,
        ),
        ("protect-main-branch", "git-pre-push", "sh", [], "refs/heads/master abc123 refs/heads/master def456\n", 1),
    ]


def _destructive_cases() -> list[Case]:
    return [
        ("block-destructive-commands", "block-destructive", "sh", ["rm", "-rf", "/"], "", 1),
        ("block-destructive-commands", "block-destructive", "sh", ["rm", "-fr", "/var"], "", 1),
        ("block-destructive-commands", "block-destructive", "sh", ["rm", "-r", "-f", "/"], "", 1),
        ("block-destructive-commands", "block-destructive", "sh", ["git", "push", "--force"], "", 1),
        ("block-destructive-commands", "block-destructive", "sh", ["git", "reset", "--hard"], "", 1),
        ("block-destructive-commands", "block-destructive", "sh", ["git", "status"], "", 0),
        ("block-destructive-commands", "block-destructive", "sh", ["rm", "-rf", "./build"], "", 0),
        ("block-destructive-commands", "block-destructive", "sh", ["git", "push", "--force-with-lease"], "", 0),
        ("block-destructive-commands", "block-destructive", "sh", ["git", "clean", "-f"], "", 1),
        ("block-destructive-commands", "block-destructive", "sh", ["kubectl", "delete", "pod", "x"], "", 1),
        ("block-destructive-commands", "block-destructive", "sh", ["terraform", "destroy"], "", 1),
    ]


def _no_verify_cases() -> list[Case]:
    return [
        ("block-no-verify", "block-no-verify", "sh", ["git", "commit", "--no-verify"], "", 1),
        ("block-no-verify", "block-no-verify", "sh", ["git", "commit", "-nm", "x"], "", 1),
        ("block-no-verify", "block-no-verify", "sh", ["git", "commit", "-m", "fix -n flag"], "", 0),
        ("block-no-verify", "block-no-verify", "sh", ["git", "commit", "-mn", "x"], "", 1),
        ("block-no-verify", "block-no-verify", "sh", ["git", "push", "-n"], "", 1),
    ]


def _scan_secret_cases() -> list[tuple[str, str, str, Callable[[Path], None], int]]:
    def stage_aws(repo: Path) -> None:
        (repo / "config.py").write_text("AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n")
        _run(["git", "add", "config.py"], repo)

    def stage_env(repo: Path) -> None:
        (repo / ".env").write_text("DATABASE_URL=x\n")
        _run(["git", "add", ".env"], repo)

    def stage_password_word(repo: Path) -> None:
        (repo / "readme.md").write_text("# Ask the user for their password\n")
        _run(["git", "add", "readme.md"], repo)

    def stage_allowlist(repo: Path) -> None:
        (repo / "test_fixture.py").write_text("TEST_KEY = 'AKIAIOSFODNN7EXAMPLE'  # pragma: allowlist secret\n")
        _run(["git", "add", "test_fixture.py"], repo)

    return [
        ("scan-secrets", "git-pre-commit", "sh", stage_aws, 1),
        ("scan-secrets", "git-pre-commit", "sh", stage_env, 1),
        ("scan-secrets", "git-pre-commit", "sh", stage_password_word, 0),
        ("scan-secrets", "git-pre-commit", "sh", stage_allowlist, 0),
    ]


def _prepare_repo(policy: str, ext: str) -> Callable[..., Path]:
    def factory(tmp_path: Path, branch: str = "") -> Path:
        repo = _init_repo(tmp_path)
        if policy == "protect-main-branch" and branch:
            _run(["git", "checkout", "-b", branch], repo)
        return repo

    return factory


@pytest.mark.parametrize(
    "policy, script_name, ext, extra_args, branch_or_input, expected",
    _protect_cases() + _destructive_cases() + _no_verify_cases(),
)
def test_guard_executable(
    tmp_path: Path,
    policy: str,
    script_name: str,
    ext: str,
    extra_args: list[str],
    branch_or_input: str,
    expected: int,
) -> None:
    repo_factory = _prepare_repo(policy, ext)
    if policy == "protect-main-branch" and script_name == "git-pre-commit":
        repo = repo_factory(tmp_path, branch_or_input)
        input_text = ""
    elif policy == "protect-main-branch" and script_name == "git-pre-push":
        repo = repo_factory(tmp_path)
        input_text = branch_or_input
    else:
        repo = tmp_path / "cwd"
        repo.mkdir()
        input_text = branch_or_input

    script = _policy_impl(policy, script_name, ext)
    result = _run_guard(repo, script, ext, extra_args, input_text)
    assert result.returncode == expected, result.stderr


@pytest.mark.parametrize(
    "policy, script_name, ext, stage_fixture, expected",
    _scan_secret_cases(),
)
def test_scan_secrets_executable(
    tmp_path: Path,
    policy: str,
    script_name: str,
    ext: str,
    stage_fixture: Callable[[Path], None],
    expected: int,
) -> None:
    repo = _init_repo(tmp_path)
    stage_fixture(repo)
    script = _policy_impl(policy, script_name, ext)
    result = _run_guard(repo, script, ext, [], "")
    assert result.returncode == expected, result.stderr
