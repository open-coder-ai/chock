"""Deterministic execution: replay a case against the mechanism and observe the answer."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterator

from chock.compile.compiler import _load_manifest
from chock.eval.fixture import init_repo, prepare
from chock.eval.model import Case, CaseResult
from chock.eval.replay import (
    AGENT_CASE_EVENTS,
    ALLOW,
    ASK,
    BLOCK,
    ERROR,
    SCRIPT_CASE_EVENTS,
    WARN,
    prepare_agent,
    run_script_event,
)
from chock.gate import runner as gate_runner
from chock.gate.build import build_gate_json
from chock.gate.guard_runner import (
    GUARD_ASK_EXIT,
    GUARD_VIOLATION,
    find_interpreter,
    interpreter_env,
    is_guard_crash,
    split_command,
)
from chock.gate.runner import GATE_LOG_ENV

#: gate_runner.judge()'s process-exit convention: 0 allow, 1 block, 2 spec error, 3 ask, 4 warn.
_GATE_EXIT_SPEC_ERROR = 2
_GATE_EXIT_VERDICT = {gate_runner.EXIT_ASK: ASK, gate_runner.EXIT_WARN: WARN}


def _observed(code: int, judged: str) -> str:
    """The verdict a gate run earns. At a git event ask exits 1 and warn exits 0, so `judged` tells them apart."""
    if code in _GATE_EXIT_VERDICT:
        return _GATE_EXIT_VERDICT[code]
    if judged in (ASK, WARN):
        return judged
    return BLOCK if code == 1 else ALLOW


def _install_script(repo: Path, policy_dir: Path, gate_spec: dict[str, Any]) -> None:
    """Put a script gate's program where the compiled gate names it, as `chock sync` would have.

    A declarative gate is whole in its JSON, so the throwaway repo needs nothing else. A script
    gate names a file under the policy's `implementations/`, and the runner resolves that name
    from the repository root -- a root that, here, holds only the case's own files. Copied, not
    staged: the material a case puts before the gate is the files it lists, never the gate's
    own program.
    """
    if gate_spec.get("kind") != "script":
        return
    named = str((gate_spec.get("params") or {}).get("script", ""))
    source = Path(policy_dir) / "implementations"
    if not named or not source.is_dir():
        return
    shutil.copytree(source, repo / Path(named).parent, dirs_exist_ok=True)


@contextlib.contextmanager
def _person_env() -> Iterator[None]:
    """Judge a case as a person's commit: the agent running the eval must not change its verdict."""
    names = (gate_runner.AGENT_COMMIT_ENV, gate_runner.CLAUDECODE_ENV, gate_runner.AI_AGENT_ENV, gate_runner.ALLOW_ENV)
    saved = {name: os.environ.pop(name) for name in names if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _run_gate(
    repo: Path,
    gate_spec: dict[str, Any],
    spec: dict[str, Any],
    writes: dict[str, str] | None = None,
    added: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return (verdict, detail) by running the compiled gate as a git hook would."""
    gate_path = repo / "gate.json"
    gate_path.write_text(json.dumps(gate_spec), encoding="utf-8", newline="\n")

    case_event = str(spec.get("event", "commit"))
    event = AGENT_CASE_EVENTS.get(case_event) or ("pre-push" if case_event == "push" else "pre-commit")
    push_stdin = None
    if event == "pre-push":
        refs = [str(r) for r in (spec.get("push_refs") or [])]
        push_stdin = "".join(f"refs/heads/local {'0' * 40} {ref} {'0' * 40}\n" for ref in refs)

    captured = io.StringIO()
    prior_log = os.environ.get(GATE_LOG_ENV)
    os.environ[GATE_LOG_ENV] = "0"
    try:
        with contextlib.redirect_stderr(captured), _person_env():
            code, judged = gate_runner.judge(gate_path, event, push_stdin, repo, writes=writes, added=added)
    finally:
        if prior_log is None:
            os.environ.pop(GATE_LOG_ENV, None)
        else:
            os.environ[GATE_LOG_ENV] = prior_log
    reason = " ".join(captured.getvalue().split())

    if code == _GATE_EXIT_SPEC_ERROR:
        return ERROR, f"gate reported a spec error: {reason}".strip()
    return _observed(code, judged), reason or f"gate exit {code}"


def _run_guard(repo: Path, guard: Path, command: str) -> tuple[str, str]:
    """Return (verdict, detail) by invoking a guard script with the argv it guards."""
    bash = find_interpreter(guard)
    if bash is None:
        return ERROR, "no interpreter could resolve the guard path"
    args, _ = split_command(command)

    try:
        env = {**interpreter_env(bash), "CHOCK_RAW_COMMAND": command}
        proc = subprocess.run(  # noqa: S603 -- running the guard under test is the point of this harness
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
        if is_guard_crash((proc.stderr or "") + (proc.stdout or "")):
            return ERROR, f"guard exited 1 without a reason, so nothing was checked: {first}"
        return BLOCK, first
    if proc.returncode == GUARD_ASK_EXIT:
        return ASK, first
    if proc.returncode == 0:
        return ALLOW, first
    return ERROR, f"guard exited {proc.returncode}, so nothing was checked: {first}"


def resolve_gate(policy_dir: Path, repo_root: Path) -> tuple[dict[str, Any] | None, str]:
    """Return (gate spec, where it came from), preferring the artifact that actually enforces."""
    policy_id = _load_manifest(policy_dir).get("id") or policy_dir.name
    compiled = repo_root / ".chock" / "compiled" / policy_id / "git-hook" / "gate.json"
    if compiled.is_file():
        try:
            return json.loads(compiled.read_text(encoding="utf-8")), "compiled"
        except (json.JSONDecodeError, OSError):
            return None, "unreadable"
    return build_gate_json(policy_dir, repo_root), "manifest"


def _replay(case: Case, spec: dict[str, Any], env: tuple[Path, Path, Path, list[Path]]) -> tuple[str, str]:
    """Return (verdict, detail) for one executable case, in the throwaway repo `env` names."""
    repo, policy_dir, repo_root, guards = env
    event = str(spec.get("event", "commit"))
    if "command" in spec:
        if not guards:
            return ERROR, "case declares a command but the policy ships no guard"
        init_repo(repo)
        return _run_guard(repo, guards[0], str(spec["command"]))
    if event in AGENT_CASE_EVENTS and not (spec.get("writes") or spec.get("files")):
        return ERROR, f"case runs at {event} but declares no writes, so the gate would judge nothing"
    if event in SCRIPT_CASE_EVENTS:
        return run_script_event(repo, policy_dir, case.policy_id, spec)

    gate_spec, source = resolve_gate(policy_dir, repo_root)
    if gate_spec is None:
        return ERROR, {
            "unreadable": "the compiled gate exists but could not be parsed; nothing is enforcing this policy",
            "manifest": "case describes a gate but the policy declares none",
        }[source]
    writes, added = prepare_agent(repo, spec) if event in AGENT_CASE_EVENTS else (None, None)
    if writes is None:
        prepare(repo, spec)
    _install_script(repo, policy_dir, gate_spec)
    verdict, detail = _run_gate(repo, gate_spec, spec, writes, added)
    if source == "manifest":
        detail = f"{detail} [gate derived from manifest; policy not compiled]"
    return verdict, detail


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
            verdict, detail = _replay(case, spec, (repo, policy_dir, repo_root, guards))
        except OSError as exc:
            return CaseResult(case, "error", detail=f"{type(exc).__name__}: {exc}")

    if verdict == ERROR:
        return CaseResult(case, "error", detail=detail)
    if verdict == expected:
        return CaseResult(case, "pass", detail=detail)
    hint = f"; the gate {verdict}s rather than {expected}s" if verdict in (ASK, WARN) and expected == BLOCK else ""
    return CaseResult(case, "fail", detail=f"expected {expected}, observed {verdict}{hint} ({detail})")
