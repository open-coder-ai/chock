"""Selection warnings: rules are data (data/warnings.json); each kind is one predicate over the selection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from chock.resources import package_data_dir


@dataclass(frozen=True)
class Context:
    """What a rule may look at: the chosen ids, each one's grade keyword, the client and its other chock plugins."""

    chosen: list[str]
    grades: dict[str, str]
    cwd: Path
    client: str = ""
    #: (plugin name, folder, policy ids) of every other chock-built plugin for this client.
    others: list[tuple[str, Path, list[str]]] = field(default_factory=list)


Predicate = Callable[[dict[str, Any], Context], list[str]]


def _missing_partner(rule: dict[str, Any], ctx: Context) -> list[str]:
    present = [p for p in rule["policies"] if p in ctx.chosen]
    absent = [p for p in rule["policies"] if p not in ctx.chosen]
    return [_say(rule, present, ABSENT=", ".join(absent))] if present and absent else []


def _all_present(rule: dict[str, Any], ctx: Context) -> list[str]:
    return [_say(rule, rule["policies"])] if all(p in ctx.chosen for p in rule["policies"]) else []


def _file_absent(rule: dict[str, Any], ctx: Context) -> list[str]:
    present = [p for p in rule["policies"] if p in ctx.chosen]
    return [_say(rule, present, FILE=rule["file"])] if present and not (ctx.cwd / rule["file"]).is_file() else []


def _grade(rule: dict[str, Any], ctx: Context) -> list[str]:
    return [_say(rule, [p]) for p in ctx.chosen if ctx.grades.get(p) == rule["grade"]]


def _client(rule: dict[str, Any], ctx: Context) -> list[str]:
    """A fact about the client itself, said once when the selection is built for it."""
    return [_say(rule, [])] if ctx.client in rule["clients"] else []


def _overlap(rule: dict[str, Any], ctx: Context) -> list[str]:
    """A chosen policy another chock plugin for this client already carries: both would fire."""
    out = []
    for name, folder, ids in ctx.others:
        shared = [p for p in ctx.chosen if p in ids]
        if shared:
            out.append(_say(rule, shared, PLUGIN=name, PATH=str(folder)))
    return out


KINDS: dict[str, Predicate] = {
    "missing_partner": _missing_partner,
    "all_present": _all_present,
    "file_absent": _file_absent,
    "grade": _grade,
    "client": _client,
    "overlap": _overlap,
}


def _say(rule: dict[str, Any], present: list[str], **tokens: str) -> str:
    text = rule["says"].replace("__PRESENT__", " and ".join(present))
    for name, value in tokens.items():
        text = text.replace(f"__{name}__", value)
    return text


def load_rules() -> list[dict[str, Any]]:
    """The packaged warning rules."""
    text = package_data_dir("chock.install", "data").joinpath("warnings.json").read_text(encoding="utf-8")
    return json.loads(text)["rules"]


def warnings_for(ctx: Context, rules: list[dict[str, Any]]) -> list[str]:
    """Every warning `rules` raise for the selection in `ctx`; none refuses."""
    return [line for rule in rules for line in KINDS[rule["kind"]](rule, ctx)]
