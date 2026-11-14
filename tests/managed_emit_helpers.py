"""Shared fixture and helpers for the `chock emit --managed claude_code` tests."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import baseline_policy

from chock import cli
from chock.doctor.payloads import payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "managed_emit"
POLICIES = ("block-no-verify", "scan-secrets")
DEPLOY_ROOT = "/srv/chock-managed"
DROP_IN = Path("managed-settings.d") / "50-chock.json"
PERMISSION_RULE = re.compile(r"^[A-Za-z]+\(.*\)$")
OVERRIDE_CLAIM = re.compile(r"(cannot|can't|can not|unable to) (be )?overrid", re.IGNORECASE)


def make_repo(tmp_path: Path) -> Path:
    """A repository holding the two golden policies and one advisory policy with nothing to run."""
    root = tmp_path / "repo"
    for policy_id in (*POLICIES, "yagni"):
        shutil.copytree(baseline_policy(policy_id), root / ".agents" / "policies" / policy_id)
    return root


PYTHON = "/usr/bin/python3"
ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
FAIL_CLOSED = re.compile(r"fail(s|ing|ed)?[- ]closed|cannot be (bypassed|disabled)|\benforced\b", re.IGNORECASE)


def emit(repo: Path, out: Path, *extra: str, python: str = PYTHON, on_failure: str = "block") -> int:
    return cli.main(
        [
            "emit",
            "--managed",
            "claude_code",
            "--out",
            str(out),
            "--repo",
            str(repo),
            "--python",
            python,
            "--on-failure",
            on_failure,
            *extra,
        ]
    )


def linux(repo: Path, out: Path, *extra: str, on_failure: str = "block") -> int:
    return emit(repo, out, "--platform", "linux", "--deploy-root", DEPLOY_ROOT, *extra, on_failure=on_failure)


def drop_in(out: Path) -> dict:
    return json.loads((out / "claude_code" / DROP_IN).read_text(encoding="utf-8"))


def handlers(doc: dict) -> list[tuple[str, dict]]:
    return [(event, hook) for event, groups in doc["hooks"].items() for group in groups for hook in group["hooks"]]


def tree(root: Path, skip: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and skip not in p.parents and "__pycache__" not in p.parts
    }


def bundle_hook(repo: Path, tmp_path: Path, on_failure: str = "block") -> tuple[Path, dict]:
    """The block-no-verify guard's handler, emitted with this test's Python and rooted at the bundle itself."""
    out = tmp_path / "out"
    bundle = (out / "claude_code" / "bundle").as_posix()
    assert (
        emit(
            repo,
            out,
            "--policies",
            "block-no-verify",
            "--deploy-root",
            bundle,
            python=sys.executable,
            on_failure=on_failure,
        )
        == 0
    )
    [(_, hook), *_] = handlers(drop_in(out))
    return out / "claude_code" / "bundle", hook


def env_for(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "AI_AGENT", "CHOCK_AGENT_COMMIT")}
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env["HOME"] = env["USERPROFILE"] = str(home)
    return {**env, **extra}


def run_hook(hook: dict, command: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run `hook` the way the client runs exec form: `command` spawned with `args`, no shell."""
    return subprocess.run(
        [hook["command"], *hook["args"]],
        input=json.dumps(payload("claude_code", command, cwd.as_posix())),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
        timeout=60,
    )


def one_line_refusal(capsys: pytest.CaptureFixture[str]) -> str:
    err = capsys.readouterr().err
    assert "Traceback" not in err and len(err.strip().splitlines()) == 1, err
    return err


def plan_of(out: Path) -> dict:
    return json.loads((out / "claude_code" / "deploy.json").read_text(encoding="utf-8"))
