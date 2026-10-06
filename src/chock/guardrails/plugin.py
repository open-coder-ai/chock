"""What every merged plugin carries for its toggle: the hook wrapper, the member list, the skill and self-protection."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from chock.gate.write_gate import STOP_FLAG
from chock.guardrails import toggle
from chock.plugin.store import SCRIPTS_TEMPLATE

_DATA = Path(__file__).resolve().parent / "data"
PROTECT_ID = "chock-guardrails-protect"
SKILL_NAME = "customize-guardrails"
WRAPPER = SCRIPTS_TEMPLATE.format(name="chock_bundle.py")
MEMBERS = SCRIPTS_TEMPLATE.format(name="chock_bundle.json")


class WrapError(ValueError):
    """A member's hook command does not run the client's adapter once, so its toggle cannot be wired."""


def protect_dir() -> Path:
    """The built-in self-protection policy every merged plugin carries; never a catalog member, never toggled."""
    return _DATA / PROTECT_ID


def protect_manifest() -> dict[str, Any]:
    return yaml.safe_load((protect_dir() / "manifest.yaml").read_text(encoding="utf-8"))


def wrap(command: str, agent: str, bundle: str, member: str) -> str:
    """`command` with the toggle wrapper put in front of the client's adapter, so the member checks its own entry first."""
    if not (toggle.NAME_RE.fullmatch(bundle) and toggle.NAME_RE.fullmatch(member)):
        msg = f"bundle {bundle!r} and member {member!r} must match {toggle.NAME_RE.pattern} to sit in a hook command"
        raise WrapError(msg)
    adapter = re.escape(SCRIPTS_TEMPLATE.format(name=f"{agent}.py"))
    pattern = re.compile(rf'"([^"\s]*){adapter}"(?= --(?:guard|gate) )')
    found = pattern.findall(command)
    if len(found) != 1:
        msg = f"hook command for {member} runs the {agent} adapter {len(found)} times, not once: {command!r}"
        raise WrapError(msg)
    return pattern.sub(lambda m: f'"{m.group(1)}{WRAPPER}" --bundle {bundle} --member {member} {m.group(0)}', command)


def wrap_doc(doc: Any, agent: str, bundle: str, member: str) -> Any:
    """A hooks document with every command wrapped for `member`."""
    if isinstance(doc, dict):
        return {
            k: wrap(v, agent, bundle, member)
            if k == "command" and isinstance(v, str)
            else wrap_doc(v, agent, bundle, member)
            for k, v in doc.items()
        }
    return [wrap_doc(v, agent, bundle, member) for v in doc] if isinstance(doc, list) else doc


def verify_at_stop(doc: Any, agent: str) -> Any:
    """The built-in protection's hooks with its Stop gate run as the turn-end check of the toggle files' records.

    The adapter keeps its `--gate ... --stop` arguments, so an unreadable Stop payload is still refused in its grammar.
    """
    adapter = re.escape(SCRIPTS_TEMPLATE.format(name=f"{agent}.py"))
    pattern = re.compile(rf'"([^"\s]*)({adapter}" --gate "[^"]*" {re.escape(STOP_FLAG)})$')

    def swap(command: str) -> str:
        return pattern.sub(lambda m: f'"{m.group(1)}{WRAPPER}" {toggle.VERIFY} "{m.group(1)}{m.group(2)}', command)

    if isinstance(doc, dict):
        return {
            k: swap(v) if k == "command" and isinstance(v, str) else verify_at_stop(v, agent) for k, v in doc.items()
        }
    return [verify_at_stop(v, agent) for v in doc] if isinstance(doc, list) else doc


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def skill(bundle: str, rows: list[tuple[str, str]]) -> str:
    """The bundle's own "customize guardrails" skill, listing each member and its label."""
    table = "\n".join(f"| `{policy_id}` | {_cell(label)} |" for policy_id, label in rows)
    template = (_DATA / SKILL_NAME / "SKILL.md.tmpl").read_text(encoding="utf-8")
    return template.replace("__MEMBERS__", table).replace("__BUNDLE__", bundle)


def files(bundle: str, rows: list[tuple[str, str]], skill_template: str) -> dict[Path, str]:
    """The wrapper, the member list `chock bundle status` reads, and the skill, by path inside the plugin."""
    members = {"bundle": bundle, "members": [{"id": i, "label": label} for i, label in rows]}
    return {
        Path(WRAPPER): Path(toggle.__file__).read_text(encoding="utf-8"),
        Path(MEMBERS): json.dumps(members, indent=2) + "\n",
        Path(skill_template.format(name=SKILL_NAME)): skill(bundle, rows),
    }
