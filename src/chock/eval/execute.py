"""Deterministic execution: replay a case against the mechanism and observe the answer.

The design rule this file exists to honour is **prefer observation over judgment**. For
"the gate blocks a commit on main", do not ask a model whether that sounds right -- build a
throwaway repo, stage the commit, run the gate, and read the exit code. The objective
signal is available, so nothing here is subject to an opinion.

Two mechanisms, chosen by the case rather than configured:

  `files` / `branch` / `event`  -> a declarative `hook.gate`, replayed against a git repo
  `command`                     -> a guard script, invoked with the argv it guards

Every case gets its own repository. Sharing one would let a case that stages a file change
what the next case observes, and a suite whose results depend on order is not a measurement.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from chock.compile.compiler import _load_manifest
from chock.eval.model import Case, CaseResult
from chock.gate import runner as gate_runner
from chock.gate.build import build_gate_json
from chock.gate.pretooluse import GUARD_VIOLATION, find_bash
from chock.gate.runner import GATE_LOG_ENV

BLOCK = "block"
ALLOW = "allow"
ERROR = "error"


def _git(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin,
        check=False,
    )


def _init_repo(repo: Path) -> None:
    """A repo with one commit, so HEAD resolves and added lines diff against something."""
    _git(repo, "init", "--quiet", "--initial-branch=main", ".")
    _git(repo, "config", "user.email", "eval@chock.invalid")
    _git(repo, "config", "user.name", "Chock Eval")
    _git(repo, "config", "commit.gpgsign", "false")


def _write(repo: Path, files: dict[str, Any]) -> list[str]:
    written: list[str] = []
    for rel, content in (files or {}).items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8", newline="\n")
        written.append(rel)
    return written


def _prepare(repo: Path, spec: dict[str, Any]) -> None:
    """Build the repository state the case describes, up to but not including the gate run."""
    _init_repo(repo)

    # A baseline commit. `head_files` lets a case express "this manifest already existed",
    # which is what distinguishes a dependency this commit ADDS from one merely present.
    head_files = spec.get("head_files") or {}
    if head_files:
        _write(repo, head_files)
        _git(repo, "add", *sorted(head_files))
    _git(repo, "commit", "--allow-empty", "-m", "baseline")

    branch = spec.get("branch")
    if branch and branch != "main":
        _git(repo, "checkout", "-q", "-b", str(branch))

    # Untracked repo state the gate reads but the commit does not contain, e.g. an allowlist.
    _write(repo, spec.get("repo_files") or {})

    staged = _write(repo, spec.get("files") or {})
    if staged:
        # Named paths only. `git add -A` would stage the allowlist and any other scaffolding,
        # letting a gate fire on the fixture rather than on the case.
        _git(repo, "add", *sorted(staged))


def _run_gate(repo: Path, gate_spec: dict[str, Any], spec: dict[str, Any]) -> tuple[str, str]:
    """Return (verdict, detail) by running the compiled gate as a git hook would."""
    gate_path = repo / "gate.json"
    gate_path.write_text(json.dumps(gate_spec), encoding="utf-8", newline="\n")

    event = "pre-push" if str(spec.get("event", "commit")) == "push" else "pre-commit"
    push_stdin = None
    if event == "pre-push":
        refs = [str(r) for r in (spec.get("push_refs") or [])]
        # <local_ref> <local_sha> <remote_ref> <remote_sha>, which is what git feeds pre-push.
        push_stdin = "".join(f"refs/heads/local {'0' * 40} {ref} {'0' * 40}\n" for ref in refs)

    # The runner prints the block reason to stderr, because at git-hook time that is the
    # only channel the adopter reads. Here it is the most useful detail we have, so capture
    # it rather than letting a hundred block messages interleave with the results table.
    captured = io.StringIO()
    # Replay is deterministic and side-effect free by contract. The gate path here is a bare
    # temp file rather than a compiled tree, so the runner already declines to log it, but
    # saying so explicitly keeps that a stated property of eval rather than a coincidence of
    # where the fixture happens to live.
    prior_log = os.environ.get(GATE_LOG_ENV)
    os.environ[GATE_LOG_ENV] = "0"
    try:
        with contextlib.redirect_stderr(captured):
            code = gate_runner.run(gate_path, event, push_stdin, repo)
    finally:
        if prior_log is None:
            os.environ.pop(GATE_LOG_ENV, None)
        else:
            os.environ[GATE_LOG_ENV] = prior_log
    reason = " ".join(captured.getvalue().split())

    if code == 2:
        return ERROR, f"gate reported a spec error: {reason}".strip()
    return (BLOCK if code == 1 else ALLOW), reason or f"gate exit {code}"


def _run_guard(repo: Path, guard: Path, command: str) -> tuple[str, str]:
    """Return (verdict, detail) by invoking a guard script with the argv it guards.

    At runtime a guard that cannot run fails open, because turning a best-effort guard into
    a total outage is worse than missing a check. Here the opposite is required: a guard
    that did not run has produced no evidence, so it is an `error`, never a pass. Reading
    "could not launch" as "blocked" is what made every allow-case fail on Windows, where
    `bash` on PATH is WSL's and cannot see a Windows path.
    """
    bash = find_bash(guard)
    if bash is None:
        return ERROR, "no bash could resolve the guard path"
    try:
        args = shlex.split(command)
    except ValueError:
        return ERROR, f"case command has unbalanced quotes: {command}"

    try:
        # Mirror the runtime adapter (gate/pretooluse.py): pass the untokenized command so
        # a guard that reads CHOCK_RAW_COMMAND to recognise PowerShell/Windows syntax is
        # tested the same way it runs. Without this, a PowerShell eval case would exercise
        # only the mangled argv and never reach the raw-text branch.
        env = {**os.environ, "CHOCK_RAW_COMMAND": command}
        proc = subprocess.run(
            [bash, str(guard), *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
        )
    except OSError as exc:
        return ERROR, f"guard could not run: {exc}"

    detail = (proc.stderr or proc.stdout).strip().splitlines()
    first = detail[0] if detail else f"guard exit {proc.returncode}"
    if proc.returncode == GUARD_VIOLATION:
        return BLOCK, first
    if proc.returncode == 0:
        return ALLOW, first
    return ERROR, f"guard exited {proc.returncode}, so nothing was checked: {first}"


def resolve_gate(policy_dir: Path, repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    """Return (gate spec, where it came from), preferring the artifact that actually enforces.

    This built the gate from the manifest unconditionally, which made the suite argue about
    the wrong thing. The catalog's claim is "evals are the argument", and `_run_gate` below
    says it runs "the compiled gate" -- but a gate derived fresh from the manifest is not the
    one in `.chock/compiled/`, and it is the installed one that decides whether a
    commit is blocked.

    Drift between the two is now caught by `validate`, `verify` and `recompile --check`, so
    this is no longer the only thing standing between an adopter and a silently disabled
    policy. It is still the difference between a suite that vouches for what runs and one
    that vouches for what was written down.

    Falls back to the manifest when nothing is compiled: `chock new` scaffolds a
    policy and its eval suite before any compile, and refusing to run those cases would make
    the suite unusable exactly when an author most wants it.
    """
    policy_id = _load_manifest(policy_dir).get("id") or policy_dir.name
    compiled = repo_root / ".chock" / "compiled" / policy_id / "git-hook" / "gate.json"
    if compiled.is_file():
        try:
            return json.loads(compiled.read_text(encoding="utf-8")), "compiled"
        except (json.JSONDecodeError, OSError):
            # Reported, never silently replaced by the manifest: an unreadable compiled gate
            # is a broken installed control, and evaluating the manifest instead would turn
            # that into a passing suite -- the exact substitution this function removes.
            return None, "unreadable"
    return build_gate_json(policy_dir, repo_root), "manifest"


def run_case(case: Case, policy_dir: Path, repo_root: Path, guards: list[Path]) -> CaseResult:
    """Execute one case and report what was observed, never what was expected."""
    if case.status == "pending":
        return CaseResult(case, "pending", detail="case is a placeholder; no expectation stated")
    spec = case.execute
    if not spec:
        return CaseResult(case, "skipped", detail="no executable form; behavioural case for agent mode")

    expected = str(spec.get("expect", BLOCK))

    with tempfile.TemporaryDirectory(prefix="chock-eval-") as tmp:
        repo = Path(tmp) / "repo"
        repo.mkdir()
        try:
            if "command" in spec:
                if not guards:
                    return CaseResult(case, "error", detail="case declares a command but the policy ships no guard")
                _init_repo(repo)
                verdict, detail = _run_guard(repo, guards[0], str(spec["command"]))
            else:
                gate_spec, source = resolve_gate(policy_dir, repo_root)
                if gate_spec is None:
                    reason = {
                        "unreadable": "the compiled gate exists but could not be parsed; "
                        "nothing is enforcing this policy",
                        "manifest": "case describes a gate but the policy declares none",
                    }[source]
                    return CaseResult(case, "error", detail=reason)
                _prepare(repo, spec)
                verdict, detail = _run_gate(repo, gate_spec, spec)
                # Named in the result, because "which gate was replayed" is the difference
                # between evidence about the installed control and evidence about the intent.
                if source == "manifest":
                    detail = f"{detail} [gate derived from manifest; policy not compiled]"
        except OSError as exc:
            return CaseResult(case, "error", detail=f"{type(exc).__name__}: {exc}")

    if verdict == ERROR:
        return CaseResult(case, "error", detail=detail)
    if verdict == expected:
        return CaseResult(case, "pass", detail=detail)
    return CaseResult(case, "fail", detail=f"expected {expected}, observed {verdict} ({detail})")
