"""The prompt-submit half of `chock doctor --live`: a policy's refusing eval prompt must be refused, `hello` allowed."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from chock.doctor.checks import FAIL, INFO, PASS, Check, rebuild
from chock.doctor.live_exec import call, own_session, said
from chock.doctor.payloads import PROMPT_AGENTS, prompt_payload, prompt_refused
from chock.doctor.targets import Target

PROMPT_REFUSES, PROMPT_ALLOWS = "live: refuses the canary prompt", "live: allows a harmless prompt"
PROMPT_LIVE = "live: prompt submit"
#: A prompt every policy lets through.
HARMLESS_PROMPT = "hello"
PROMPT_EVENT = "prompt_submit"
_PROMPT_GATE = re.compile(r'--prompt-submit\s+"?([^"\s]+)"?')


def prompt_probe(agent: str, asked: str, repo: Path) -> dict[str, Any]:
    return own_session(prompt_payload(agent, asked, repo.as_posix()))


def _first_prompt_block(suite: Path) -> str | None:
    try:
        cases = (yaml.safe_load(suite.read_text(encoding="utf-8")) or {}).get("suite", {}).get("cases") or []
    except (OSError, yaml.YAMLError, AttributeError):
        return None
    for case in cases:
        run = case.get("execute") if isinstance(case, dict) else None
        if isinstance(run, dict) and (run.get("event"), run.get("expect")) == (PROMPT_EVENT, "block"):
            prompt = run.get("prompt")
            if isinstance(prompt, str) and prompt:
                return prompt
    return None


def _prompt_policy(command: str) -> str | None:
    """The policy id a prompt-submit hook command's compiled gate belongs to."""
    named = _PROMPT_GATE.search(command)
    return Path(named.group(1)).parent.parent.name if named else None


def prompt_canary(repo: Path, found: list[tuple[str, str]]) -> tuple[str, str] | None:
    """(policy id, prompt): the first installed prompt-submit policy's own first refusing eval case; None when none has one."""
    for _key, command in found:
        policy = _prompt_policy(command)
        case = _first_prompt_block(repo / ".agents" / "policies" / policy / "evals" / "suite.yaml") if policy else None
        if policy and case is not None:
            return policy, case
    return None


def _prompt_refused(agent: str, done: subprocess.CompletedProcess | str) -> bool:
    return not isinstance(done, str) and prompt_refused(agent, done.returncode, done.stdout)


def _prompt_refuses(target: Target, repo: Path, found: list[tuple[str, str]]) -> Check:
    probe = prompt_canary(repo, found)
    if probe is None:
        return Check(INFO, PROMPT_LIVE, "skipped (no prompt_submit policy has an eval case that must block)")
    policy, case = probe
    sent = prompt_probe(target.agent, case, repo)
    answers = [call(target, repo, c, sent) for c in found if _prompt_policy(c[1]) == policy]
    if any(_prompt_refused(target.agent, done) for done in answers):
        return Check(PASS, PROMPT_REFUSES, f"{policy} refused its eval prompt")
    why = said(answers[0]) if answers else "no hook command runs it"
    return Check(FAIL, PROMPT_REFUSES, f"{policy} did not refuse its eval prompt: {why}", rebuild(target))


def _prompt_allows(target: Target, repo: Path, found: list[tuple[str, str]]) -> Check:
    sent = prompt_probe(target.agent, HARMLESS_PROMPT, repo)
    for done in (call(target, repo, c, sent) for c in found):
        if isinstance(done, str) or done.returncode != 0 or _prompt_refused(target.agent, done):
            return Check(FAIL, PROMPT_ALLOWS, f"`{HARMLESS_PROMPT}` was not allowed: {said(done)}", rebuild(target))
    return Check(PASS, PROMPT_ALLOWS, f"`{HARMLESS_PROMPT}` allowed by {len(found)} hook command(s)")


def rows(target: Target, repo: Path, found: list[tuple[str, str]]) -> list[Check]:
    """The two prompt-submit rows; nothing for a target with no such hook of chock's."""
    if not found:
        return []
    if target.agent not in PROMPT_AGENTS:
        return [Check(INFO, PROMPT_LIVE, f"skipped (no recorded {target.agent} prompt payload)")]
    refuses = _prompt_refuses(target, repo, found)
    return [refuses, _prompt_allows(target, repo, found)]
