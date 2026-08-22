"""Tier 1 harness: Chock as an adopter receives it.

`tests/` asks "do the parts work?" and answers from inside, importing the modules it tests.
On 2026-08-04, 281 such tests were green while the wheel shipped without 42 template files,
`init` installed 10 of the 12 policies it bundles, PreToolUse enforced nothing, and a clean
install emitted eleven warnings about the policies it had just installed. Every one of
those is invisible from inside and immediate from outside.

The rules, and why each is load-bearing:

  **Never import chock.** Everything runs through a wheel installed into an isolated
  venv, invoked as a subprocess. A suite that can reach into the source tree stops testing
  what ships. `test_isolation.py` enforces this.

  **Assert only on what an adopter can see** -- exit codes, output, files, and whether git
  actually refused. Not internal state.

  **A fixture policy, not a shipped one.** Tier 1 proves the plumbing. Using `scan-secrets`
  to prove it would mean tightening its regex could fail this suite, and would only ever
  show the framework works for policies we ship -- when the claim is that it works for any
  policy an adopter writes. Shipped-policy correctness is tier 2.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import venv
from dataclasses import dataclass
from pathlib import Path

import pytest
from policy_fixtures import FIXTURE_MANIFEST, FIXTURE_SUITE, FIXTURE_TOKEN, GUARD_POLICIES

FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Result:
    """What an adopter observes from running a command."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def __repr__(self) -> str:  # shown on assertion failure
        return f"exit={self.returncode}\n--- stdout ---\n{self.stdout}\n--- stderr ---\n{self.stderr}"


class Adopter:
    """A throwaway git repo with Chock installed, driven from outside."""

    def __init__(self, repo: Path, python: Path) -> None:
        self.repo = repo
        self.python = python

    def run(self, *args: str, stdin: str | None = None) -> Result:
        proc = subprocess.run(
            list(args),
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            input=stdin,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.repo)},
        )
        return Result(proc.returncode, proc.stdout, proc.stderr)

    def chock(self, *args: str, stdin: str | None = None) -> Result:
        """Invoke the installed CLI -- never the source tree."""
        return self.run(str(self.python), "-m", "chock.cli", *args, stdin=stdin)

    def git(self, *args: str) -> Result:
        return self.run("git", *args)

    def write(self, rel: str, content: str) -> Path:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def read(self, rel: str) -> str:
        return (self.repo / rel).read_text(encoding="utf-8")

    def read_json(self, rel: str) -> dict:
        return json.loads(self.read(rel))

    def exists(self, rel: str) -> bool:
        return (self.repo / rel).exists()

    def commit(self, message: str, *paths: str) -> Result:
        """Stage and commit. Returns the result so a block can be asserted on."""
        self.git("add", *(paths or ("-A",)))
        return self.git("commit", "-m", message)

    def tool_use(self, command: str) -> str:
        """The JSON payload Claude Code sends to a PreToolUse hook."""
        return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})

    def fire_pretooluse(self, command: str) -> bool:
        """Run every installed PreToolUse hook as Claude would. True if any blocks."""
        settings = self.read_json(".claude/settings.json")
        for entry in settings.get("hooks", {}).get("PreToolUse", []):
            for hook in entry.get("hooks", []):
                cmd = hook["command"].replace("${CLAUDE_PROJECT_DIR}", str(self.repo))
                # This harness runs the installed hook COMMAND STRING exactly as the
                # client does, shell interpretation included; an argv list would test
                # a different mechanism than the one adopters get.
                proc = subprocess.run(  # nosemgrep: chock-no-subprocess-shell
                    cmd,
                    cwd=str(self.repo),
                    shell=True,
                    capture_output=True,
                    text=True,
                    input=self.tool_use(command),
                    env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.repo)},
                )
                if proc.returncode == 2:
                    return True
        return False


@pytest.fixture(scope="session")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build once, from a clean copy.

    Building in place reuses build/lib, which can hold files the current packaging config
    no longer selects -- that is how a packaging bug stayed hidden.
    """
    # Deliberately not `importorskip`. This is the suite that catches what the unit tests
    # structurally cannot, and a missing dependency used to skip all 19 scenarios while the
    # run still reported success -- a tier-1 gate that no-ops green is the exact failure
    # mode this directory exists to prevent. Opting out has to be a choice someone made.
    if importlib.util.find_spec("build") is None:
        if os.environ.get("CHOCK_ACCEPTANCE_OPTIONAL") == "1":
            pytest.skip("build is not installed and CHOCK_ACCEPTANCE_OPTIONAL=1")
        pytest.fail(
            "the acceptance suite needs the `build` package to produce the wheel it tests "
            "(pip install build). Set CHOCK_ACCEPTANCE_OPTIONAL=1 to skip instead.",
            pytrace=False,
        )
    src = tmp_path_factory.mktemp("src") / "chock"
    shutil.copytree(
        FRAMEWORK_ROOT,
        src,
        ignore=shutil.ignore_patterns(
            "build", "dist", "*.egg-info", ".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache"
        ),
    )
    out = tmp_path_factory.mktemp("dist")
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "-o", str(out)], cwd=src, capture_output=True, text=True
    )
    assert proc.returncode == 0, f"wheel build failed:\n{proc.stdout}\n{proc.stderr}"
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


@pytest.fixture(scope="session")
def installed_python(wheel: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A venv with only the wheel installed. Shared: per-test installs cost ~10s each."""
    venv_dir = tmp_path_factory.mktemp("venv") / "v"
    venv.create(venv_dir, with_pip=True, clear=True)
    bindir = "Scripts" if sys.platform == "win32" else "bin"
    python = venv_dir / bindir / ("python.exe" if sys.platform == "win32" else "python")
    proc = subprocess.run([str(python), "-m", "pip", "install", "--quiet", str(wheel)], capture_output=True, text=True)
    assert proc.returncode == 0, f"wheel install failed:\n{proc.stdout}\n{proc.stderr}"
    return python


@pytest.fixture
def adopter(installed_python: Path, tmp_path: Path) -> Adopter:
    """A fresh git repo per test. Git config is pinned so failures are never environmental."""
    repo = tmp_path / "project"
    repo.mkdir()
    for args in (
        ("git", "init", "--quiet", "."),
        ("git", "config", "user.email", "adopter@example.com"),
        ("git", "config", "user.name", "Adopter"),
        ("git", "config", "commit.gpgsign", "false"),
    ):
        subprocess.run(args, cwd=str(repo), check=True, capture_output=True)
    return Adopter(repo, installed_python)


@pytest.fixture
def onboarded(adopter: Adopter) -> Adopter:
    """An adopter who has run `init` -- the normal starting point."""
    result = adopter.chock("init", ".")
    assert result.ok, f"init failed:\n{result!r}"
    return adopter


@pytest.fixture
def copy_guard_policies():
    """Install this repo's guard policies into an adopter repo and compile them."""

    def _install(repo: Adopter) -> Adopter:
        # Copy the folder, then recompile. Deliberately nothing else: this is the documented
        # install, and the fixture must not paper over gaps in it. It used to also run
        # `refresh` and `registry scan`, which hid the fact that `recompile` alone left the
        # repo unable to commit -- a workaround in a fixture is a defect report nobody filed.
        for policy_id in GUARD_POLICIES:
            shutil.copytree(
                FRAMEWORK_ROOT / ".agents" / "policies" / policy_id,
                repo.repo / ".agents" / "policies" / policy_id,
            )
        assert repo.chock("recompile", "--repo", ".", "--skip-hooks").ok
        return repo

    return _install


@pytest.fixture
def fixture_policy_for():
    """Install a synthetic gate policy the suite owns into a given repo, compiled and wired.

    Deliberately not a shipped policy: this proves the framework works for *any* policy,
    and cannot be broken by someone tightening a baseline regex.

    The repo is passed in rather than closed over, because a step definition receives its
    repo from the scenario's Background, not from a fixture this one could depend on.
    """

    def _install(repo: Adopter, token: str = FIXTURE_TOKEN, policy_id: str = "acceptance-guard") -> Adopter:
        repo.write(
            f".agents/policies/{policy_id}/manifest.yaml",
            FIXTURE_MANIFEST.format(id=policy_id, pattern=token),
        )
        repo.write(f".agents/policies/{policy_id}/evals/suite.yaml", FIXTURE_SUITE.format(id=policy_id))
        # --skip-hooks: compiling and installing are separate steps, and the difference
        # is the whole coverage model. Scenarios opt into installation explicitly.
        result = repo.chock("recompile", "--repo", ".", "--skip-hooks")
        assert result.ok, f"recompile failed:\n{result!r}"
        # `recompile` alone, as an adopter would run it. This used to be followed by
        # `refresh` and `registry scan` because without them the installed validate hook
        # blocked every commit -- described at the time as "the sequence an adopter runs".
        # It was not a sequence, it was a defect: `recompile` now reconciles both itself.
        return repo

    return _install
