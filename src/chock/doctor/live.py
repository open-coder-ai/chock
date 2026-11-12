"""`chock doctor --live`: run chock's own installed pre-tool hooks as the client calls them, on a canary and a harmless command."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from chock import vendors
from chock.doctor.checks import FAIL, INFO, PASS, Check, engine, rebuild
from chock.doctor.payloads import DENY_ON_THE_WIRE, EXIT_2, payload
from chock.doctor.targets import ROUTE_SYNC, Target
from chock.gate.guard_runner import bash_candidates
from chock.gate.runner.journal import LOG_LEVEL_ENV, LOG_OFF
from chock.hooks import launch
from chock.hooks.in_agent_install import install_hooks
from chock.plugin import hook_dir, store
from chock.plugin.clients import CLIENTS
from chock.policies import discover_policy_dirs
from chock.vendored import vendored_differences

REFUSES, ALLOWS, LIVE = "live: refuses the canary", "live: allows a harmless command", "live"
#: A command every policy lets through: it reads nothing and writes nothing.
HARMLESS = "echo chock-doctor-live"
#: Seconds one hook command may take; a client's own timeouts are of this order.
TIMEOUT = 60
#: The exit code every client reads as a refusal.
REFUSAL_EXIT = 2
#: The probe logs nothing, so the decision log never holds a refusal no agent asked for.
QUIET = {LOG_LEVEL_ENV: LOG_OFF}
_REFERENCE = re.compile(r'--(guard|multi)\s+"?([^"\s]+)"?')
_TOOL_KEYS = ("tool_name", "toolName")
_ANY = (None, "", "*")
#: The per-shell keys a hook entry may carry in place of `command` (Copilot's `bash` and `powershell`).
BASH, POWERSHELL = "bash", "powershell"
#: The probe's own session: its calls never join a real session's log, and that file is removed afterwards.
PROBE_SESSION = "chock-doctor-live"
_SESSION_KEYS = ("session_id", "sessionId", "conversation_id", "conversationId", "trajectory_id")
_STATE = (".chock", "state")


def _document(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return tomllib.loads(text) if path.suffix == ".toml" else json.loads(text)


def _matches(matcher: Any, tool: str | None) -> bool:
    if matcher in _ANY or tool is None or not isinstance(matcher, str):
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return True


def _entry(node: dict[str, Any]) -> tuple[str, str] | None:
    """(the key it was read from, the command) the client runs for one hook entry on this OS."""
    for key in ("command", POWERSHELL if os.name == "nt" else BASH):
        if isinstance(node.get(key), str):
            return key, node[key]
    return None


def _collect(node: Any, tool: str | None, matcher: Any = None) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        matcher = node.get("matcher", matcher)
        entry = _entry(node)
        if entry is not None and _matches(matcher, tool):
            yield entry
        for value in node.values():
            yield from _collect(value, tool, matcher)
    elif isinstance(node, list):
        for item in node:
            yield from _collect(item, tool, matcher)


def _under(node: Any, event: str) -> Iterator[Any]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == event:
                yield value
            else:
                yield from _under(value, event)
    elif isinstance(node, list):
        for item in node:
            yield from _under(item, event)


def commands(target: Target) -> list[tuple[str, str]]:
    """The pre-tool entries the client runs for its shell tool, read from the very file it reads."""
    doc = _document(target.hooks)
    sample = payload(target.agent, HARMLESS) if target.agent in DENY_ON_THE_WIRE else {}
    tool = next((sample[k] for k in _TOOL_KEYS if isinstance(sample.get(k), str)), None)
    return [c for part in _under(doc, vendors.shell_gate_event(target.agent)) for c in _collect(part, tool)]


def rendered(target: Target) -> set[tuple[str, str]]:
    """Every entry this engine's installer writes for the target, rendered from the repo's policies into a scratch copy."""
    rel = target.hooks.relative_to(target.root)
    with tempfile.TemporaryDirectory(prefix="chock-live-") as tmp:
        shadow = Path(tmp)
        compiled = target.root / ".chock" / "compiled"
        if compiled.is_dir():
            shutil.copytree(compiled, shadow / ".chock" / "compiled")
        for pack in discover_policy_dirs(target.root):
            shutil.copytree(pack, shadow / pack.relative_to(target.root), dirs_exist_ok=True)
        install_hooks(shadow, target.agent)
        written = shadow / rel
        return set(_collect(_document(written), None)) if written.is_file() else set()


def own_runtime(target: Target) -> bool:
    """Whether the launcher and every vendored runtime are byte-equal to what this engine renders."""
    try:
        same_launcher = target.launcher.read_text(encoding="utf-8") == launch.launcher_text()
    except (OSError, UnicodeDecodeError):
        return False
    return same_launcher and engine(target).status == PASS and not vendored_differences(target.root)


def _guards(command: str, root: Path) -> Iterator[Path]:
    for flag, ref in _REFERENCE.findall(command):
        path = Path(ref) if Path(ref).is_absolute() else root / ref
        if flag == "guard":
            yield path
            continue
        try:
            members = json.loads(path.read_text(encoding="utf-8")).get("members") or []
        except (OSError, ValueError, AttributeError):
            continue
        for member in members:
            argv = (member.get("argv") if isinstance(member, dict) else None) or []
            yield from (root / argv[i + 1] for i, word in enumerate(argv[:-1]) if word == "--guard")


def _first_block(suite: Path) -> str | None:
    try:
        cases = (yaml.safe_load(suite.read_text(encoding="utf-8")) or {}).get("suite", {}).get("cases") or []
    except (OSError, yaml.YAMLError, AttributeError):
        return None
    for case in cases:
        run = case.get("execute") if isinstance(case, dict) else None
        if isinstance(run, dict) and run.get("expect") == "block" and isinstance(run.get("command"), str):
            return run["command"]
    return None


def canary(target: Target, repo: Path, found: list[tuple[str, str]]) -> tuple[str, str] | None:
    """(policy id, command): the first installed guard's own first refusing eval case; None when no guard has one."""
    for _key, command in found:
        for guard in _guards(command, target.root):
            policy = guard.parent.parent if guard.parent.name == "implementations" else None
            suites = [policy / "evals" / "suite.yaml"] if policy else []
            suites.append(repo / ".agents" / "policies" / guard.stem / "evals" / "suite.yaml")
            for suite in suites:
                case = _first_block(suite)
                if case is not None:
                    return suite.parent.parent.name, case
    return None


def _argv(agent: str, key: str, command: str) -> list[str] | str:
    """The shell the client runs a hook in on this OS: sh on POSIX; on Windows PowerShell for a `powershell` entry,
    cmd.exe where the store says so, else Git Bash."""
    if os.name != "nt":
        return [shutil.which("sh") or "sh", "-c", command]
    if key == POWERSHELL:
        return [shutil.which("powershell") or "powershell", "-NoProfile", "-Command", command]
    cmd = any(c.agent == agent and store.windows_hook_command(f) == hook_dir.QUOTE_FREE for f, c in CLIENTS.items())
    bash = [] if cmd else bash_candidates()
    return [bash[0], "-c", command] if bash else command


def _probe(agent: str, asked: str, repo: Path) -> dict[str, Any]:
    sent = payload(agent, asked, repo.as_posix())
    named = [key for key in _SESSION_KEYS if key in sent] or [_SESSION_KEYS[0]]
    return {**sent, **dict.fromkeys(named, PROBE_SESSION)}


def _call(target: Target, repo: Path, entry: tuple[str, str], asked: str) -> subprocess.CompletedProcess | str:
    """One hook command's answer to `asked`, or why it gave none."""
    argv = _argv(target.agent, *entry)
    try:
        return subprocess.run(  # noqa: S603 -- a hook command this engine rendered, byte-equal, as the client runs it
            argv,
            shell=isinstance(argv, str),
            cwd=repo,
            env={**os.environ, **QUIET},
            input=json.dumps(_probe(target.agent, asked, repo)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{type(exc).__name__}: {exc}"


def refused(agent: str, done: subprocess.CompletedProcess) -> bool:
    """Whether the answer is a refusal in `agent`'s grammar: its deny word on stdout, or exit 2."""
    word = DENY_ON_THE_WIRE[agent]
    return done.returncode == REFUSAL_EXIT or (word != EXIT_2 and done.returncode == 0 and f'"{word}"' in done.stdout)


def _said(done: subprocess.CompletedProcess | str) -> str:
    if isinstance(done, str):
        return done
    text = (done.stderr.strip() or done.stdout.strip()).splitlines()
    return f"exit {done.returncode}" + (f": {text[0][:160]}" if text else "")


def _refuses(target: Target, repo: Path, found: list[tuple[str, str]], probe: tuple[str, str] | None) -> Check:
    if probe is None:
        return Check(INFO, LIVE, "skipped (no in-agent policy installed on its shell tool)")
    policy, case = probe
    answers = [_call(target, repo, c, case) for c in found]
    for done in answers:
        if not isinstance(done, str) and refused(target.agent, done) and policy in done.stdout + done.stderr:
            return Check(PASS, REFUSES, f"{policy} refused `{case}`")
    return Check(FAIL, REFUSES, f"{policy} did not refuse `{case}`: {_said(answers[0])}", rebuild(target))


def _allows(target: Target, repo: Path, found: list[tuple[str, str]]) -> Check:
    for done in (_call(target, repo, c, HARMLESS) for c in found):
        if isinstance(done, str) or done.returncode != 0 or refused(target.agent, done):
            return Check(FAIL, ALLOWS, f"`{HARMLESS}` was not allowed: {_said(done)}", rebuild(target))
    return Check(PASS, ALLOWS, f"`{HARMLESS}` allowed by {len(found)} hook command(s)")


def _runnable(target: Target) -> tuple[list[tuple[str, str]], list[Check]]:
    """(chock's own pre-tool entries, the rows that say what was not run); no entries when nothing may run."""
    if target.route != ROUTE_SYNC:
        return [], [Check(INFO, LIVE, "skipped (plugin route: chock cannot re-render a plugin's hook commands)")]
    if target.agent not in DENY_ON_THE_WIRE:
        return [], [Check(INFO, LIVE, f"skipped (no recorded {target.agent} pre-tool payload)")]
    if not own_runtime(target):
        return [], [Check(INFO, LIVE, "skipped (runtime is not this engine's)", rebuild(target))]
    try:
        found, ours = commands(target), rendered(target)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return [], [Check(FAIL, LIVE, f"{target.hooks} is unreadable ({exc})", rebuild(target))]
    mine = [entry for entry in found if entry in ours]
    other = len(found) - len(mine)
    rows = [Check(INFO, LIVE, f"{other} other hook command(s) not run (not chock's)")] if other else []
    if not mine:
        rows.append(Check(FAIL, LIVE, f"{target.hooks} holds no pre-tool command chock renders", rebuild(target)))
    return mine, rows


def run(target: Target, repo: Path) -> list[Check]:
    """The two live rows for one target, after a row for anything not run; or the one row that says why nothing ran."""
    found, rows = _runnable(target)
    if not found:
        return rows
    logs = [
        base.joinpath(*_STATE, PROBE_SESSION + suffix) for base in {repo, target.root} for suffix in (".jsonl", ".tmp")
    ]
    fresh = [path for path in logs if not path.exists()]
    try:
        return [*rows, _refuses(target, repo, found, canary(target, repo, found)), _allows(target, repo, found)]
    finally:
        for path in fresh:
            path.unlink(missing_ok=True)
